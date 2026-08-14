/**
 * ChromaBeam High-Performance Universal Optical Receiver v5
 * 
 * Features:
 * - Full 3D Perspective Homography Tracking
 * - 360° 4-Way Rotation Invariance (0°, 90°, 180° upside-down, 270° sideways)
 * - Multi-Threaded Web Worker Pipeline (60 FPS Butter UI on Main Thread)
 * - Transferable ArrayBuffers for zero-copy memory transfer
 * - Adaptive Quad Locking & Telemetry Reticles
 * - Automatic Offline Fallback
 */

let receiverVideo = null;
let receiverCanvas = null;
let receiverCtx = null;
let receiverStream = null;
let receiverRunning = false;

let scannerWorker = null;
let workerIsBusy = false;

let receiverPacketsCaught = 0;
let receiverCRCErrors = 0;
let receiverIsComplete = false;
let receiverFpsCounter = 0;
let receiverLastFpsTime = 0;
let receiverCalculatedFPS = 0;
let receiverLastQuad = null;
let receiverLastConfigLabel = '';
let receiverIsLocked = false;

function initReceiver() {
    receiverVideo = document.getElementById('receiverVideo');
    receiverCanvas = document.getElementById('receiverCanvas');
    if (receiverCanvas) {
        receiverCtx = receiverCanvas.getContext('2d', { willReadFrequently: true });
    }
    setupScannerWorker();
}

function setupScannerWorker() {
    if (window.Worker) {
        try {
            scannerWorker = new Worker('scanner_worker.js');
            scannerWorker.onmessage = handleWorkerMessage;
            scannerWorker.onerror = function(err) {
                console.warn("[Receiver] Worker error, fallback to inline:", err);
                scannerWorker = null;
            };
        } catch (e) {
            console.warn("[Receiver] Could not start Worker, using inline mode:", e);
            scannerWorker = null;
        }
    }
}

function resetReceiverSession() {
    receiverPacketsCaught = 0;
    receiverCRCErrors = 0;
    receiverIsComplete = false;
    receiverLastQuad = null;
    receiverIsLocked = false;
    receiverLastConfigLabel = '';
    workerIsBusy = false;
    updateReceiverProgress(0);

    if (scannerWorker) {
        scannerWorker.postMessage({ type: 'reset' });
    }
}

async function startReceiverCamera() {
    try {
        if (!scannerWorker) setupScannerWorker();

        const stream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: { ideal: "environment" },
                width: { ideal: 1280 },
                height: { ideal: 720 },
                frameRate: { ideal: 60 }
            },
            audio: false
        });
        receiverStream = stream;
        receiverVideo.srcObject = stream;
        await receiverVideo.play();

        receiverRunning = true;
        resetReceiverSession();

        document.getElementById('receiverStartBtn').style.display = 'none';
        document.getElementById('receiverStopBtn').style.display = 'inline-block';
        document.getElementById('receiverStatusBadge').textContent = "● SCANNING (360° 3D Active)";
        document.getElementById('receiverStatusBadge').className = "badge-scanning";

        requestAnimationFrame(processReceiverFrame);
    } catch (err) {
        if (err.name === "NotAllowedError" || err.name === "TypeError" || err.name === "NotFoundError") {
            const httpsUrl = `https://${location.hostname}:8443/`;
            alert(`⚠️ Camera requires HTTPS!\n\nOpen: ${httpsUrl}\n(Tap Advanced → Proceed if prompted)`);
            if (confirm("Redirect to HTTPS?")) window.location.href = httpsUrl;
        } else {
            alert("Camera error: " + err.message);
        }
    }
}

function stopReceiverCamera() {
    receiverRunning = false;
    if (receiverStream) {
        receiverStream.getTracks().forEach(t => t.stop());
        receiverStream = null;
    }
    document.getElementById('receiverStartBtn').style.display = 'inline-block';
    document.getElementById('receiverStopBtn').style.display = 'none';
    document.getElementById('receiverStatusBadge').textContent = "● IDLE";
    document.getElementById('receiverStatusBadge').className = "badge-idle";
}

// ===================== MAIN UI 60 FPS LOOP =====================

function processReceiverFrame() {
    if (!receiverRunning || receiverIsComplete) return;

    receiverFpsCounter++;
    const now = performance.now();
    if (now - receiverLastFpsTime >= 1000) {
        receiverCalculatedFPS = receiverFpsCounter;
        receiverFpsCounter = 0;
        receiverLastFpsTime = now;
        document.getElementById('receiverFpsVal').textContent = `${receiverCalculatedFPS} FPS`;
    }

    if (receiverVideo.readyState >= receiverVideo.HAVE_ENOUGH_DATA) {
        const vw = receiverVideo.videoWidth;
        const vh = receiverVideo.videoHeight;

        if (receiverCanvas.width !== vw || receiverCanvas.height !== vh) {
            receiverCanvas.width = vw;
            receiverCanvas.height = vh;
        }

        // Draw camera frame directly to canvas
        receiverCtx.drawImage(receiverVideo, 0, 0, vw, vh);

        // Guide bounds
        const guideSide = Math.min(vw, vh) * 0.85;
        const gx = Math.floor((vw - guideSide) / 2);
        const gy = Math.floor((vh - guideSide) / 2);
        const gw = Math.floor(guideSide);
        const gh = Math.floor(guideSide);
        const guideRect = { x: gx, y: gy, w: gw, h: gh };

        // Draw augmented reality viewfinder guide & 3D quad reticles
        drawViewfinderOverlay(guideRect, receiverLastQuad, receiverIsLocked, receiverLastConfigLabel, vw, vh);

        // Dispatch frame to Background Web Worker if idle
        if (!workerIsBusy && !receiverIsComplete) {
            const imgData = receiverCtx.getImageData(0, 0, vw, vh);
            const buffer = imgData.data.buffer; // Transferable

            if (scannerWorker) {
                workerIsBusy = true;
                scannerWorker.postMessage({
                    type: 'processFrame',
                    buffer,
                    width: vw,
                    height: vh,
                    guideRect
                }, [buffer]);
            } else {
                // Inline synchronous fallback if worker unavailable
                processFrameInline(imgData, vw, vh, guideRect);
            }
        }
    }

    requestAnimationFrame(processReceiverFrame);
}

// ===================== WORKER MESSAGE HANDLER =====================

function handleWorkerMessage(e) {
    workerIsBusy = false;
    const res = e.data;
    if (!res || !receiverRunning) return;

    receiverPacketsCaught = res.caught || 0;
    receiverCRCErrors = res.drops || 0;
    receiverIsLocked = res.locked;
    if (res.quad) receiverLastQuad = res.quad;
    if (res.configLabel) receiverLastConfigLabel = res.configLabel;

    updateReceiverProgress(res.progress || 0);

    const badge = document.getElementById('receiverStatusBadge');
    if (res.locked) {
        badge.textContent = `● LOCKED: ${receiverLastConfigLabel}`;
        badge.className = "badge-locked";
    } else {
        badge.textContent = "● SCANNING (360° 3D Active)";
        badge.className = "badge-scanning";
    }

    document.getElementById('receiverDropletVal').textContent =
        `Caught: ${receiverPacketsCaught} (Drops: ${receiverCRCErrors})`;

    if (res.isComplete && res.fileResult && !receiverIsComplete) {
        receiverIsComplete = true;
        downloadReceivedFile(res.fileResult);
    }
}

function downloadReceivedFile(fileResult) {
    updateReceiverProgress(1.0);
    document.getElementById('receiverStatusBadge').textContent = "★ TRANSFER COMPLETE!";
    document.getElementById('receiverStatusBadge').className = "badge-complete";

    const { filename, payloadBuffer } = fileResult;
    const blob = new Blob([payloadBuffer], { type: 'application/octet-stream' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    alert(`🎉 Success! Received file: ${filename} (${(payloadBuffer.byteLength / 1024).toFixed(1)} KB)`);
}

// ===================== INLINE FALLBACK ENGINE =====================

let inlineDecoder = null;
let inlineCurrentFileId = null;
let inlineLockedConfig = null;

function processFrameInline(imgData, vw, vh, guideRect) {
    const quad = detectOpticalQuad(imgData, vw, vh, guideRect);
    if (!quad) return;

    receiverLastQuad = quad;
    let decodedResult = null;
    let matchedConfig = null;

    const candidateConfigs = [
        { grid: 32, mode: 0, label: '32×32 B&W (Potato)' },
        { grid: 48, mode: 0, label: '48×48 B&W' },
        { grid: 64, mode: 0, label: '64×64 B&W' },
        { grid: 32, mode: 1, label: '32×32 4-Color' },
        { grid: 48, mode: 1, label: '48×48 4-Color' },
        { grid: 48, mode: 2, label: '48×48 8-Color' },
        { grid: 64, mode: 2, label: '64×64 8-Color' },
    ];

    for (const cfg of candidateConfigs) {
        const layout = new JSColorMatrixLayout(cfg.grid, cfg.mode);
        const sampledGrid = sampleQuadGrid(imgData, vw, vh, quad, layout);
        const res = decodeGridMultiOrientation(sampledGrid, layout);
        if (res) {
            decodedResult = res;
            matchedConfig = cfg;
            break;
        }
    }

    if (decodedResult) {
        receiverPacketsCaught++;
        receiverIsLocked = true;
        receiverLastConfigLabel = `${matchedConfig.label} (${decodedResult.rotationDeg}° rot)`;
        const { packet } = decodedResult;
        const { header, payload } = packet;

        if (!inlineDecoder || inlineCurrentFileId !== header.fileId) {
            inlineCurrentFileId = header.fileId;
            inlineDecoder = new LTDecoder(header.totalBlocks, header.blockSize, header.totalBlocks * header.blockSize);
            receiverIsComplete = false;
        }

        const solved = inlineDecoder.addDroplet(header.seed, payload);
        updateReceiverProgress(inlineDecoder.getProgress());

        if (solved && !receiverIsComplete) {
            receiverIsComplete = true;
            const fullData = inlineDecoder.reconstructData();
            if (fullData) {
                const meta = unpackFileMetadata(fullData);
                let filename = "chromabeam_received.bin";
                let filePayload = fullData;
                if (meta) {
                    filename = meta.filename;
                    filePayload = fullData.subarray(meta.metadataHeaderLen, meta.metadataHeaderLen + meta.filesize);
                }
                downloadReceivedFile({ filename, payloadBuffer: filePayload.buffer });
            }
        }
    } else {
        receiverIsLocked = false;
        receiverCRCErrors++;
    }

    document.getElementById('receiverDropletVal').textContent =
        `Caught: ${receiverPacketsCaught} (Drops: ${receiverCRCErrors})`;
}

// ===================== AR VIEWFINDER & 3D RETICLES =====================

function drawViewfinderOverlay(guideRect, quad, isLocked, configLabel, vw, vh) {
    const ctx = receiverCtx;
    const { x, y, w, h } = guideRect;
    const bracketLen = Math.min(w, h) * 0.08;

    // Semi-transparent outer mask
    ctx.fillStyle = 'rgba(0, 0, 0, 0.35)';
    ctx.fillRect(0, 0, vw, y);
    ctx.fillRect(0, y + h, vw, vh - y - h);
    ctx.fillRect(0, y, x, h);
    ctx.fillRect(x + w, y, vw - x - w, h);

    // Guide brackets
    ctx.strokeStyle = isLocked ? '#00ff66' : 'rgba(0, 255, 102, 0.5)';
    ctx.lineWidth = 2.5;
    ctx.lineCap = 'round';

    // 4 Corner brackets
    ctx.beginPath();
    ctx.moveTo(x, y + bracketLen); ctx.lineTo(x, y); ctx.lineTo(x + bracketLen, y);
    ctx.moveTo(x + w - bracketLen, y); ctx.lineTo(x + w, y); ctx.lineTo(x + w, y + bracketLen);
    ctx.moveTo(x + w, y + h - bracketLen); ctx.lineTo(x + w, y + h); ctx.lineTo(x + w - bracketLen, y + h);
    ctx.moveTo(x + bracketLen, y + h); ctx.lineTo(x, y + h); ctx.lineTo(x, y + h - bracketLen);
    ctx.stroke();

    // Draw full 3D perspective quad if detected
    if (quad && quad.length === 4) {
        ctx.strokeStyle = isLocked ? '#00ff66' : '#58a6ff';
        ctx.lineWidth = isLocked ? 3.0 : 2.0;

        ctx.beginPath();
        ctx.moveTo(quad[0].x, quad[0].y);
        ctx.lineTo(quad[1].x, quad[1].y);
        ctx.lineTo(quad[2].x, quad[2].y);
        ctx.lineTo(quad[3].x, quad[3].y);
        ctx.closePath();
        ctx.stroke();

        // Corner circles & crosshairs
        quad.forEach((pt, i) => {
            ctx.fillStyle = (i === 0) ? '#ff4444' : (isLocked ? '#00ff66' : '#58a6ff'); // TL anchor red dot
            ctx.beginPath();
            ctx.arc(pt.x, pt.y, 5, 0, 2 * Math.PI);
            ctx.fill();

            ctx.strokeStyle = '#ffffff';
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.arc(pt.x, pt.y, 10, 0, 2 * Math.PI);
            ctx.stroke();
        });

        // Label above quad
        if (configLabel) {
            ctx.fillStyle = isLocked ? '#00ff66' : '#58a6ff';
            ctx.font = 'bold 12px sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText(`⚡ ${configLabel}`, quad[0].x, Math.max(16, quad[0].y - 12));
        }
    }

    // Top instruction label
    ctx.fillStyle = isLocked ? '#00ff66' : '#ffffff';
    ctx.font = '12px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(isLocked ? '● OPTICAL LOCK ENGAGED (3D PERSPECTIVE ACTIVE)' : 'Point camera at flashing matrix (Any angle / 360° rotation)', x + w / 2, y - 10);
}

function updateReceiverProgress(ratio) {
    const pct = Math.min(100, Math.floor(ratio * 100));
    const bar = document.getElementById('receiverProgressBar');
    if (bar) bar.style.width = `${pct}%`;
    const lbl = document.getElementById('receiverProgressLabel');
    if (lbl) lbl.textContent = `${pct}%`;
}
