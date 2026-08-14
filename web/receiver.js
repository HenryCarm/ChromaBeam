/**
 * ChromaBeam High-Performance Universal Optical Receiver v6
 * 
 * Features:
 * - Real-Time Diagnostic Terminal Logger on-screen
 * - Pi-Accurate Progress Reporting (0.0000% + Block Counts)
 * - Live Vision Binarizer / Debug Overlay Toggle
 * - 360° 4-Way Rotation Invariance (0°, 90°, 180°, 270°)
 * - Multi-Threaded Web Worker Pipeline (60 FPS Main UI)
 * - Transferable Zero-Copy Buffer Streaming
 * - Full Dynamic Lighting & Contrast Telemetry
 */

let receiverVideo = null;
let receiverCanvas = null;
let receiverCtx = null;
let receiverStream = null;
let receiverRunning = false;

let scannerWorker = null;
let workerIsBusy = false;
let showBinarizerView = false;

let receiverPacketsCaught = 0;
let receiverCRCErrors = 0;
let receiverIsComplete = false;
let receiverFpsCounter = 0;
let receiverLastFpsTime = 0;
let receiverCalculatedFPS = 0;
let receiverLastQuad = null;
let receiverLastConfigLabel = '';
let receiverIsLocked = false;
let receiverLastLumaMetrics = null;
let receiverWorkerLatency = 0;

const MAX_LOG_ENTRIES = 120;
let receiverLogLines = [];

function initReceiver() {
    receiverVideo = document.getElementById('receiverVideo');
    receiverCanvas = document.getElementById('receiverCanvas');
    if (receiverCanvas) {
        receiverCtx = receiverCanvas.getContext('2d', { willReadFrequently: true });
    }
    setupScannerWorker();
    appendReceiverLog("[SYSTEM] ChromaBeam 3D Optical Scanner initialized.", "info");
}

function setupScannerWorker() {
    if (window.Worker) {
        try {
            scannerWorker = new Worker('scanner_worker.js');
            scannerWorker.onmessage = handleWorkerMessage;
            scannerWorker.onerror = function(err) {
                appendReceiverLog(`[WORKER ERROR] ${err.message || 'Worker thread failure'}`, "error");
                console.warn("[Receiver] Worker error, fallback to inline:", err);
                scannerWorker = null;
            };
            appendReceiverLog("[SYSTEM] Multi-threaded Web Worker background engine active.", "info");
        } catch (e) {
            appendReceiverLog(`[SYSTEM] Web Worker unavailable (${e.message}), using inline fallback.`, "warn");
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
    updateReceiverProgress(0, "0.0000%", 0, 0);

    if (scannerWorker) {
        scannerWorker.postMessage({ type: 'reset' });
    }
    appendReceiverLog("[SESSION] Reception session reset. Ready for beam.", "info");
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

        appendReceiverLog("[CAMERA] 60 FPS stream acquired. Auto-density & 360° search running.", "vision");
        requestAnimationFrame(processReceiverFrame);
    } catch (err) {
        if (err.name === "NotAllowedError" || err.name === "TypeError" || err.name === "NotFoundError") {
            const httpsUrl = `https://${location.hostname}:8443/`;
            alert(`⚠️ Camera requires HTTPS!\n\nOpen: ${httpsUrl}\n(Tap Advanced → Proceed if prompted)`);
            if (confirm("Redirect to HTTPS?")) window.location.href = httpsUrl;
        } else {
            alert("Camera error: " + err.message);
        }
        appendReceiverLog(`[CAMERA ERROR] ${err.message}`, "error");
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
    appendReceiverLog("[CAMERA] Camera stopped. Scanner idle.", "info");
}

function toggleBinarizerView() {
    showBinarizerView = !showBinarizerView;
    const btn = document.getElementById('receiverDebugToggleBtn');
    if (btn) {
        btn.textContent = showBinarizerView ? "👁️ Normal View" : "👁️ Vision View";
        btn.classList.toggle('btn-primary', showBinarizerView);
    }
    appendReceiverLog(`[UI] Vision Binarizer View: ${showBinarizerView ? 'ON' : 'OFF'}`, "info");
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
        const fpsLabel = `${receiverCalculatedFPS} FPS (Worker: ${receiverWorkerLatency}ms)`;
        document.getElementById('receiverFpsVal').textContent = fpsLabel;
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

        // Optional: Render binarized vision mask if toggled
        if (showBinarizerView && receiverLastLumaMetrics) {
            applyBinarizerFilterToCanvas(vw, vh, receiverLastLumaMetrics.lumaThreshold || 128);
        }

        // Guide bounds (center 85%)
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
            const buffer = imgData.data.buffer; // Transferable zero-copy

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
                processFrameInline(imgData, vw, vh, guideRect);
            }
        }
    }

    requestAnimationFrame(processReceiverFrame);
}

function applyBinarizerFilterToCanvas(w, h, threshold) {
    const imgData = receiverCtx.getImageData(0, 0, w, h);
    const data = imgData.data;
    for (let i = 0; i < data.length; i += 4) {
        const luma = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
        const val = (luma > threshold) ? 255 : 0;
        data[i] = val;
        data[i + 1] = val;
        data[i + 2] = val;
    }
    receiverCtx.putImageData(imgData, 0, 0);
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
    if (res.lumaMetrics) receiverLastLumaMetrics = res.lumaMetrics;
    if (res.latencyMs) receiverWorkerLatency = res.latencyMs;

    // Update Pi-accurate progress
    updateReceiverProgress(
        res.progress || 0,
        res.progressPctFormatted || "0.0000%",
        res.solvedBlocks || 0,
        res.totalBlocks || 0
    );

    // Update Telemetry HUD
    if (res.detectMethod) {
        document.getElementById('receiverDetectorVal').textContent = `${res.detectMethod} ${res.locked ? '★' : '○'}`;
    }
    if (res.lumaMetrics) {
        const lm = res.lumaMetrics;
        document.getElementById('receiverLumaVal').textContent = `Thresh: ${lm.lumaThreshold} (Contr: ${lm.contrast})`;
    }

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

    // Append log line if present
    if (res.logMsg) {
        appendReceiverLog(res.logMsg, res.locked ? "decode" : "info");
    }

    if (res.isComplete && res.fileResult && !receiverIsComplete) {
        receiverIsComplete = true;
        downloadReceivedFile(res.fileResult);
    }
}

function downloadReceivedFile(fileResult) {
    updateReceiverProgress(1.0, "100.0000%", fileResult.filesize, fileResult.filesize);
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

    appendReceiverLog(`[SUCCESS] Assembly complete! Downloaded ${filename} (${(payloadBuffer.byteLength / 1024).toFixed(1)} KB)`, "decode");
    alert(`🎉 Success! Received and assembled file: ${filename} (${(payloadBuffer.byteLength / 1024).toFixed(1)} KB)`);
}

// ===================== LOGGING CONSOLE =====================

function appendReceiverLog(msg, type = "info") {
    const timestamp = new Date().toTimeString().split(' ')[0];
    const entry = `[${timestamp}] ${msg}`;
    receiverLogLines.push({ text: entry, type });
    if (receiverLogLines.length > MAX_LOG_ENTRIES) receiverLogLines.shift();

    const logBox = document.getElementById('receiverDebugLog');
    if (logBox) {
        const lineElem = document.createElement('div');
        lineElem.className = `log-entry log-${type}`;
        lineElem.textContent = entry;
        logBox.appendChild(lineElem);
        logBox.scrollTop = logBox.scrollHeight;
    }
}

function clearReceiverLogs() {
    receiverLogLines = [];
    const logBox = document.getElementById('receiverDebugLog');
    if (logBox) logBox.innerHTML = '<div class="log-entry log-info">[SYSTEM] Logs cleared.</div>';
}

function copyReceiverLogs() {
    const text = receiverLogLines.map(l => l.text).join('\n');
    navigator.clipboard.writeText(text).then(() => {
        alert("📋 Diagnostic logs copied to clipboard!");
    }).catch(() => {
        prompt("Copy logs manually:", text);
    });
}

function updateReceiverProgress(ratio, formattedPct, solved, total) {
    const pct = Math.min(100, Math.max(0, ratio * 100));
    const bar = document.getElementById('receiverProgressBar');
    if (bar) bar.style.width = `${pct}%`;

    const lbl = document.getElementById('receiverProgressLabel');
    if (lbl) lbl.textContent = formattedPct || `${pct.toFixed(4)}%`;

    const blockLbl = document.getElementById('receiverBlockCountLabel');
    if (blockLbl) {
        blockLbl.textContent = (total > 0) ? `Solved: ${solved} / ${total} Blocks (${formattedPct})` : "Waiting for first packet...";
    }
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

        quad.forEach((pt, i) => {
            ctx.fillStyle = (i === 0) ? '#ff4444' : (isLocked ? '#00ff66' : '#58a6ff');
            ctx.beginPath();
            ctx.arc(pt.x, pt.y, 5, 0, 2 * Math.PI);
            ctx.fill();

            ctx.strokeStyle = '#ffffff';
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.arc(pt.x, pt.y, 10, 0, 2 * Math.PI);
            ctx.stroke();
        });

        if (configLabel) {
            ctx.fillStyle = isLocked ? '#00ff66' : '#58a6ff';
            ctx.font = 'bold 12px sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText(`⚡ ${configLabel}`, quad[0].x, Math.max(16, quad[0].y - 12));
        }
    }

    ctx.fillStyle = isLocked ? '#00ff66' : '#ffffff';
    ctx.font = '12px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(isLocked ? '● OPTICAL LOCK ENGAGED (3D PERSPECTIVE ACTIVE)' : 'Point camera at flashing matrix (Any angle / 360° rotation)', x + w / 2, y - 10);
}
