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

const MAX_LOG_ENTRIES = 2000;
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

// ===================== INLINE VISION & DECODER ENGINE FALLBACK =====================

const INLINE_CANDIDATE_CONFIGS = [
    { grid: 32, mode: 0, label: '32×32 B&W (Potato)' },
    { grid: 48, mode: 0, label: '48×48 B&W' },
    { grid: 64, mode: 0, label: '64×64 B&W' },
    { grid: 32, mode: 1, label: '32×32 4-Color' },
    { grid: 48, mode: 1, label: '48×48 4-Color' },
    { grid: 48, mode: 2, label: '48×48 8-Color' },
    { grid: 64, mode: 2, label: '64×64 8-Color' },
];

const INLINE_CACHED_LAYOUTS = {};
function getInlineLayout(grid, mode) {
    const key = `${grid}_${mode}`;
    if (!INLINE_CACHED_LAYOUTS[key] && typeof JSColorMatrixLayout === 'function') {
        INLINE_CACHED_LAYOUTS[key] = new JSColorMatrixLayout(grid, mode);
    }
    return INLINE_CACHED_LAYOUTS[key] || null;
}

let inlineDecoder = null;
let inlineCurrentFileId = null;
let inlineLockedConfig = null;

function resetInlineDecoderSession() {
    inlineDecoder = null;
    inlineCurrentFileId = null;
    inlineLockedConfig = null;
}

function setupScannerWorker() {
    // 1. Check for inlined worker source in offline bundled HTML
    const workerSrcElem = typeof document !== 'undefined' ? document.getElementById('scanner-worker-src') : null;
    if (workerSrcElem && workerSrcElem.textContent && workerSrcElem.textContent.trim().length > 0 &&
        typeof window !== 'undefined' && typeof window.Worker !== 'undefined' &&
        typeof window.Blob !== 'undefined' && typeof window.URL !== 'undefined' &&
        typeof window.URL.createObjectURL === 'function') {
        try {
            const workerCode = workerSrcElem.textContent;
            const blob = new Blob([workerCode], { type: 'application/javascript' });
            const blobUrl = URL.createObjectURL(blob);
            scannerWorker = new Worker(blobUrl);
            scannerWorker.onmessage = handleWorkerMessage;
            scannerWorker.onerror = function(err) {
                appendReceiverLog(`[WORKER ERROR] ${err.message || 'Worker thread failure'}`, "error");
                console.warn("[Receiver] Worker error, falling back to inline decoding:", err);
                try { scannerWorker.terminate(); } catch (_) {}
                scannerWorker = null;
                workerIsBusy = false;
            };
            appendReceiverLog("[SYSTEM] Multi-threaded Web Worker active (Offline Blob Engine).", "info");
            return;
        } catch (e) {
            appendReceiverLog(`[SYSTEM] Blob Worker unavailable (${e.message}), attempting server worker or inline fallback.`, "warn");
            console.warn("[Receiver] Blob Worker creation failed:", e);
            scannerWorker = null;
        }
    }

    // 2. Check for server-hosted scanner_worker.js
    if (typeof window !== 'undefined' && typeof window.Worker !== 'undefined') {
        try {
            scannerWorker = new Worker('scanner_worker.js?v=5');
            scannerWorker.onmessage = handleWorkerMessage;
            scannerWorker.onerror = function(err) {
                appendReceiverLog(`[WORKER ERROR] ${err.message || 'Worker thread failure'}`, "error");
                console.warn("[Receiver] Worker error, falling back to inline decoding:", err);
                try { scannerWorker.terminate(); } catch (_) {}
                scannerWorker = null;
                workerIsBusy = false;
            };
            appendReceiverLog("[SYSTEM] Multi-threaded Web Worker background engine active.", "info");
            return;
        } catch (e) {
            appendReceiverLog(`[SYSTEM] Web Worker unavailable (${e.message}), using inline fallback.`, "warn");
            console.warn("[Receiver] Worker creation failed:", e);
            scannerWorker = null;
        }
    } else {
        appendReceiverLog("[SYSTEM] Web Worker not supported, using inline fallback.", "warn");
        scannerWorker = null;
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
    resetInlineDecoderSession();
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

        // Guide bounds (center 85%)
        const guideSide = Math.min(vw, vh) * 0.85;
        const gx = Math.floor((vw - guideSide) / 2);
        const gy = Math.floor((vh - guideSide) / 2);
        const gw = Math.floor(guideSide);
        const gh = Math.floor(guideSide);
        const guideRect = { x: gx, y: gy, w: gw, h: gh };

        // *** CRITICAL: Capture PRISTINE frame data BEFORE drawing any UI overlays ***
        // The viewfinder mask, brackets, and binarizer filter MUST NOT contaminate
        // the pixel data sent to the scanner worker for decoding!
        if (!workerIsBusy && !receiverIsComplete) {
            const imgData = receiverCtx.getImageData(0, 0, vw, vh);

            if (scannerWorker) {
                const buffer = imgData.data.buffer; // Transferable zero-copy
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

        // NOW draw visual overlays on top (these are for display only, not for decoding)

        // Optional: Render binarized vision mask if toggled
        if (showBinarizerView && receiverLastLumaMetrics) {
            applyBinarizerFilterToCanvas(vw, vh, receiverLastLumaMetrics.lumaThreshold || 128);
        }

        // Draw augmented reality viewfinder guide & 3D quad reticles
        drawViewfinderOverlay(guideRect, receiverLastQuad, receiverIsLocked, receiverLastConfigLabel, vw, vh);
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

// ===================== INLINE FRAME PROCESSING FALLBACK =====================

function processFrameInline(imgData, vw, vh, guideRect) {
    const startTime = performance.now();
    const w = vw || (imgData ? imgData.width : 0);
    const h = vh || (imgData ? imgData.height : 0);

    if (receiverIsComplete) {
        handleWorkerMessage({
            data: {
                type: 'frameResult',
                locked: false,
                caught: receiverPacketsCaught,
                drops: receiverCRCErrors,
                progress: 1.0,
                progressPctFormatted: "100.0000%",
                isComplete: true,
                latencyMs: (performance.now() - startTime).toFixed(1)
            }
        });
        return;
    }

    try {
        // 1. Detect 4-point quadrilateral in 3D camera space
        const detectRes = (typeof detectOpticalQuad === 'function')
            ? detectOpticalQuad(imgData, w, h, guideRect)
            : { quad: null, method: 'None' };
        const quad = detectRes.quad;
        const detectMethod = detectRes.method;

        let decodedResult = null;
        let matchedConfig = null;
        let lastLumaMetrics = null;

        if (quad && typeof sampleQuadGrid === 'function' && typeof decodeGridMultiOrientation === 'function') {
            const configsToTest = inlineLockedConfig ? [inlineLockedConfig] : INLINE_CANDIDATE_CONFIGS;

            for (const cfg of configsToTest) {
                const layout = getInlineLayout(cfg.grid, cfg.mode);
                if (!layout) continue;

                // Primary sample pass
                const sampleRes = sampleQuadGrid(imgData, w, h, quad, layout);
                lastLumaMetrics = {
                    lumaThreshold: sampleRes.lumaThreshold,
                    minLuma: sampleRes.minLuma,
                    maxLuma: sampleRes.maxLuma,
                    contrast: sampleRes.contrast
                };

                let res = decodeGridMultiOrientation(sampleRes.grid2D, layout);

                // Multi-threshold fallback for B&W mode (glare compensation)
                if (!res && cfg.mode === 0 && sampleRes.contrast > 30) {
                    const altThresholds = [sampleRes.lumaThreshold - 15, sampleRes.lumaThreshold + 15];
                    for (const altT of altThresholds) {
                        if (altT > 20 && altT < 240) {
                            const altSample = sampleQuadGrid(imgData, w, h, quad, layout, altT);
                            res = decodeGridMultiOrientation(altSample.grid2D, layout);
                            if (res) break;
                        }
                    }
                }

                if (res) {
                    decodedResult = res;
                    matchedConfig = cfg;
                    inlineLockedConfig = cfg;
                    break;
                }
            }

            if (!decodedResult && inlineLockedConfig) {
                inlineLockedConfig = null; // Lost lock, resume sweep next frame
            }
        }

        let fileResult = null;
        const latencyMs = (performance.now() - startTime).toFixed(1);

        if (decodedResult) {
            const { packet, rotationDeg } = decodedResult;
            const { header, payload } = packet;

            if (!inlineDecoder || inlineCurrentFileId !== header.fileId) {
                inlineCurrentFileId = header.fileId;
                if (typeof LTDecoder === 'function') {
                    inlineDecoder = new LTDecoder(header.totalBlocks, header.blockSize, header.totalBlocks * header.blockSize);
                }
            }

            let solved = false;
            let progressRatio = 0;
            let solvedCount = 0;
            let totalCount = header.totalBlocks || 0;

            if (inlineDecoder) {
                solved = inlineDecoder.addDroplet(header.seed, payload);
                progressRatio = inlineDecoder.getProgress();
                solvedCount = inlineDecoder.solvedBlocks ? inlineDecoder.solvedBlocks.size : 0;
                totalCount = inlineDecoder.K;
            }

            const progressPct = (progressRatio * 100).toFixed(4) + "%";

            if (solved && !receiverIsComplete && inlineDecoder) {
                const fullData = inlineDecoder.reconstructData();
                if (fullData) {
                    const meta = (typeof unpackFileMetadata === 'function') ? unpackFileMetadata(fullData) : null;
                    let filename = "chromabeam_received.bin";
                    let filePayload = fullData;
                    if (meta) {
                        filename = meta.filename;
                        filePayload = fullData.subarray(meta.metadataHeaderLen, meta.metadataHeaderLen + meta.filesize);
                    }
                    fileResult = {
                        filename,
                        filesize: filePayload.length,
                        payloadBuffer: filePayload.buffer
                    };
                }
            }

            handleWorkerMessage({
                data: {
                    type: 'frameResult',
                    locked: true,
                    quad,
                    detectMethod,
                    caught: receiverPacketsCaught + 1,
                    drops: receiverCRCErrors,
                    progress: progressRatio,
                    progressPctFormatted: progressPct,
                    solvedBlocks: solvedCount,
                    totalBlocks: totalCount,
                    configLabel: `${matchedConfig.label} (${rotationDeg}° rot)`,
                    rotationDeg,
                    lumaMetrics: lastLumaMetrics,
                    latencyMs,
                    isComplete: (solved && !receiverIsComplete) ? true : receiverIsComplete,
                    fileResult,
                    logMsg: `[DECODE:INLINE] Droplet seed #${header.seed} (K=${totalCount}) solved: ${solvedCount}/${totalCount} (${progressPct})`
                }
            });

        } else {
            const progressRatio = inlineDecoder ? inlineDecoder.getProgress() : 0;
            const progressPct = (progressRatio * 100).toFixed(4) + "%";

            handleWorkerMessage({
                data: {
                    type: 'frameResult',
                    locked: false,
                    quad,
                    detectMethod,
                    caught: receiverPacketsCaught,
                    drops: quad ? (receiverCRCErrors + 1) : receiverCRCErrors,
                    progress: progressRatio,
                    progressPctFormatted: progressPct,
                    solvedBlocks: (inlineDecoder && inlineDecoder.solvedBlocks) ? inlineDecoder.solvedBlocks.size : 0,
                    totalBlocks: inlineDecoder ? inlineDecoder.K : 0,
                    lumaMetrics: lastLumaMetrics,
                    latencyMs,
                    isComplete: receiverIsComplete,
                    fileResult: null,
                    logMsg: null
                }
            });
        }
    } catch (err) {
        console.error("[Receiver] Inline processing exception:", err);
        handleWorkerMessage({
            data: {
                type: 'frameResult',
                locked: false,
                caught: receiverPacketsCaught,
                drops: receiverCRCErrors + 1,
                progress: 0,
                progressPctFormatted: "0.0000%",
                error: err.message,
                logMsg: `[ERROR:INLINE] ${err.message}`
            }
        });
    }
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
        const detElem = document.getElementById('receiverDetectorVal');
        if (detElem) detElem.textContent = `${res.detectMethod} ${res.locked ? '★' : '○'}`;
    }
    if (res.lumaMetrics) {
        const lm = res.lumaMetrics;
        const lumaElem = document.getElementById('receiverLumaVal');
        if (lumaElem) lumaElem.textContent = `Thresh: ${lm.lumaThreshold} (Contr: ${lm.contrast})`;
    }

    const badge = document.getElementById('receiverStatusBadge');
    if (badge) {
        if (res.locked) {
            badge.textContent = `● LOCKED: ${receiverLastConfigLabel}`;
            badge.className = "badge-locked";
        } else {
            badge.textContent = "● SCANNING (360° 3D Active)";
            badge.className = "badge-scanning";
        }
    }

    const dropElem = document.getElementById('receiverDropletVal');
    if (dropElem) {
        dropElem.textContent = `Caught: ${receiverPacketsCaught} (Drops: ${receiverCRCErrors})`;
    }

    // Append log lines if present (worker may send multi-line logs)
    if (res.logMsg) {
        const lines = res.logMsg.split('\n');
        for (const line of lines) {
            if (line.trim().length > 0) {
                appendReceiverLog(line, res.locked ? "decode" : "info");
            }
        }
    }

    if (res.isComplete && res.fileResult && !receiverIsComplete) {
        receiverIsComplete = true;
        downloadReceivedFile(res.fileResult);
    }
}

let lastReceivedBlobUrl = null;
let lastReceivedFilename = null;

function downloadReceivedFile(fileResult) {
    updateReceiverProgress(1.0, "100.0000%", fileResult.filesize, fileResult.filesize);
    const badge = document.getElementById('receiverStatusBadge');
    if (badge) {
        badge.textContent = "★ TRANSFER COMPLETE!";
        badge.className = "badge-complete";
    }

    const { filename, payloadBuffer } = fileResult;
    lastReceivedFilename = filename;

    if (typeof Blob !== 'undefined' && typeof URL !== 'undefined' && typeof document !== 'undefined') {
        try {
            const blob = new Blob([payloadBuffer], { type: 'application/octet-stream' });
            if (lastReceivedBlobUrl) {
                try { URL.revokeObjectURL(lastReceivedBlobUrl); } catch (_) {}
            }
            lastReceivedBlobUrl = URL.createObjectURL(blob);

            // Show persistent download card in UI
            const dlCard = document.getElementById('receiverDownloadCard');
            const dlLink = document.getElementById('receiverDownloadLink');
            if (dlCard && dlLink) {
                dlLink.href = lastReceivedBlobUrl;
                dlLink.download = filename;
                dlLink.textContent = `📥 SAVE ${filename} (${(payloadBuffer.byteLength / 1024).toFixed(1)} KB)`;
                dlCard.style.display = 'block';
            }

            // Auto-trigger download (do NOT revoke object URL immediately so mobile download managers can stream it)
            const a = document.createElement('a');
            a.href = lastReceivedBlobUrl;
            a.download = filename;
            a.target = '_blank';
            if (document.body) document.body.appendChild(a);
            a.click();
            setTimeout(() => {
                try { if (document.body && a.parentNode) document.body.removeChild(a); } catch (_) {}
            }, 2000);
        } catch (e) {
            console.warn("[Receiver] Download file trigger error:", e);
        }
    }

    appendReceiverLog(`[SUCCESS] Assembly complete! Received ${filename} (${(payloadBuffer.byteLength / 1024).toFixed(1)} KB)`, "decode");
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

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        setupScannerWorker,
        processFrameInline,
        resetReceiverSession,
        resetInlineDecoderSession,
        handleWorkerMessage,
        INLINE_CANDIDATE_CONFIGS,
        getInlineLayout
    };
}

