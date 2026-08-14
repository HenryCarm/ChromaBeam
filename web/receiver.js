/**
 * ChromaBeam High-Performance Universal Optical Receiver v3
 * 
 * APPROACH: Fixed centered viewfinder guide. User positions the flashing matrix
 * to fill the guide. No fragile auto-corner-detection needed.
 * 
 * Features:
 * - Fixed viewfinder guide with clear corner brackets
 * - Multi-pixel cell sampling (3x3 kernel) for noise resilience
 * - Otsu adaptive threshold for B&W mode
 * - Euclidean nearest-neighbor for color modes with 5-point calibration
 * - Auto-density sweep across all 6 mode/grid combinations
 * - Pre-cached layouts to avoid GC thrashing on mobile
 */

let receiverVideo = null;
let receiverCanvas = null;
let receiverCtx = null;
let receiverStream = null;
let receiverRunning = false;

let receiverDecoder = null;
let receiverCurrentFileId = null;
let receiverPacketsCaught = 0;
let receiverCRCErrors = 0;
let receiverIsComplete = false;
let receiverFpsCounter = 0;
let receiverLastFpsTime = 0;
let receiverCalculatedFPS = 0;
let receiverLockedConfig = null; // Once we catch a valid packet, lock to that config

// Pre-cache ALL candidate layouts at startup to avoid per-frame allocation
const CANDIDATE_CONFIGS = [
    { grid: 32, mode: 0, label: '32x32 B&W' },
    { grid: 32, mode: 1, label: '32x32 4-Color' },
    { grid: 48, mode: 0, label: '48x48 B&W' },
    { grid: 48, mode: 1, label: '48x48 4-Color' },
    { grid: 48, mode: 2, label: '48x48 8-Color' },
    { grid: 64, mode: 0, label: '64x64 B&W' },
    { grid: 64, mode: 1, label: '64x64 4-Color' },
    { grid: 64, mode: 2, label: '64x64 8-Color' },
];

const CACHED_LAYOUTS = {};
for (const cfg of CANDIDATE_CONFIGS) {
    const key = `${cfg.grid}_${cfg.mode}`;
    CACHED_LAYOUTS[key] = new JSColorMatrixLayout(cfg.grid, cfg.mode);
}

function initReceiver() {
    receiverVideo = document.getElementById('receiverVideo');
    receiverCanvas = document.getElementById('receiverCanvas');
    if (receiverCanvas) {
        receiverCtx = receiverCanvas.getContext('2d', { willReadFrequently: true });
    }
}

function resetReceiverSession() {
    receiverDecoder = null;
    receiverCurrentFileId = null;
    receiverPacketsCaught = 0;
    receiverCRCErrors = 0;
    receiverIsComplete = false;
    receiverLockedConfig = null;
    updateReceiverProgress(0);
}

async function getCameraStream(constraints) {
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        return await navigator.mediaDevices.getUserMedia(constraints);
    }
    const legacy = navigator.getUserMedia || navigator.webkitGetUserMedia || navigator.mozGetUserMedia;
    if (legacy) {
        return new Promise((resolve, reject) => legacy.call(navigator, constraints, resolve, reject));
    }
    throw new Error("INSECURE_CONTEXT_OR_UNSUPPORTED");
}

async function startReceiverCamera() {
    try {
        receiverStream = await getCameraStream({
            video: {
                facingMode: { ideal: "environment" },
                width: { ideal: 1280 },
                height: { ideal: 720 },
                frameRate: { ideal: 60 }
            },
            audio: false
        });
        receiverVideo.srcObject = receiverStream;
        await receiverVideo.play();

        receiverRunning = true;
        resetReceiverSession();

        document.getElementById('receiverStartBtn').style.display = 'none';
        document.getElementById('receiverStopBtn').style.display = 'inline-block';
        document.getElementById('receiverStatusBadge').textContent = "● SCANNING";
        document.getElementById('receiverStatusBadge').className = "badge-scanning";

        requestAnimationFrame(processReceiverFrame);
    } catch (err) {
        if (err.message === "INSECURE_CONTEXT_OR_UNSUPPORTED" || err.name === "TypeError") {
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

// ===================== MAIN FRAME LOOP =====================

function processReceiverFrame() {
    if (!receiverRunning || receiverIsComplete) return;

    // FPS counter
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

        receiverCtx.drawImage(receiverVideo, 0, 0, vw, vh);

        // Fixed centered square viewfinder guide (user fills this with the matrix)
        const side = Math.min(vw, vh) * 0.80;
        const cx = vw / 2;
        const cy = vh / 2;
        const guideRect = {
            x: Math.floor(cx - side / 2),
            y: Math.floor(cy - side / 2),
            w: Math.floor(side),
            h: Math.floor(side)
        };

        // Draw the viewfinder guide
        drawViewfinderGuide(guideRect, vw, vh);

        // Read pixels from the guide region
        const imgData = receiverCtx.getImageData(guideRect.x, guideRect.y, guideRect.w, guideRect.h);

        // Try to decode
        let decodedPacket = null;
        let matchedLayout = null;
        let matchedLabel = '';

        if (receiverLockedConfig) {
            // Already locked onto a config — only try that one (fast path)
            const layout = CACHED_LAYOUTS[`${receiverLockedConfig.grid}_${receiverLockedConfig.mode}`];
            const sampledGrid = sampleGridFromRegion(imgData, guideRect.w, guideRect.h, layout);
            const rawBytes = gridIndicesToBytes(sampledGrid, layout);
            decodedPacket = unpackPacket(rawBytes);
            if (decodedPacket) {
                matchedLayout = layout;
                matchedLabel = receiverLockedConfig.label;
            } else {
                // Lost lock, fall back to sweep
                receiverLockedConfig = null;
            }
        }

        if (!decodedPacket) {
            // Sweep all candidate configs
            for (const cfg of CANDIDATE_CONFIGS) {
                const key = `${cfg.grid}_${cfg.mode}`;
                const layout = CACHED_LAYOUTS[key];
                const sampledGrid = sampleGridFromRegion(imgData, guideRect.w, guideRect.h, layout);
                const rawBytes = gridIndicesToBytes(sampledGrid, layout);
                const packet = unpackPacket(rawBytes);
                if (packet) {
                    decodedPacket = packet;
                    matchedLayout = layout;
                    matchedLabel = cfg.label;
                    receiverLockedConfig = cfg;
                    break;
                }
            }
        }

        if (decodedPacket) {
            receiverPacketsCaught++;
            document.getElementById('receiverStatusBadge').textContent = `● LOCKED: ${matchedLabel}`;
            document.getElementById('receiverStatusBadge').className = "badge-locked";

            const { header, payload } = decodedPacket;

            if (!receiverDecoder || receiverCurrentFileId !== header.fileId) {
                receiverCurrentFileId = header.fileId;
                receiverDecoder = new LTDecoder(header.totalBlocks, header.blockSize, header.totalBlocks * header.blockSize);
                receiverIsComplete = false;
            }

            const solved = receiverDecoder.addDroplet(header.seed, payload);
            updateReceiverProgress(receiverDecoder.getProgress());

            if (solved && !receiverIsComplete) {
                receiverIsComplete = true;
                onFileTransferComplete();
            }
        } else {
            receiverCRCErrors++;
            document.getElementById('receiverStatusBadge').textContent = "● SCANNING (align matrix in guide)";
            document.getElementById('receiverStatusBadge').className = "badge-scanning";
        }

        document.getElementById('receiverDropletVal').textContent =
            `Caught: ${receiverPacketsCaught} (Drops: ${receiverCRCErrors})`;
    }

    requestAnimationFrame(processReceiverFrame);
}

// ===================== GRID SAMPLING =====================

/**
 * Samples the grid from a cropped region (the viewfinder guide area).
 * Uses 3x3 multi-pixel averaging per cell for noise resilience.
 * Uses Otsu adaptive threshold for B&W mode.
 */
function sampleGridFromRegion(imgData, regionW, regionH, layout) {
    const N = layout.gridSize;
    const grid2D = Array.from({ length: N }, () => new Uint8Array(N));
    const data = imgData.data;
    const colorMode = layout.colorMode;
    const cellW = regionW / N;
    const cellH = regionH / N;
    const palette = layout.palette;

    // For B&W mode: compute Otsu threshold over a sample of luminance values
    let lumaThreshold = 128;
    if (colorMode === 0) {
        lumaThreshold = computeOtsuThreshold(data, regionW, regionH, N);
    }

    for (let r = 0; r < N; r++) {
        for (let c = 0; c < N; c++) {
            // Sample 3x3 kernel at cell center for noise resilience
            const centerX = (c + 0.5) * cellW;
            const centerY = (r + 0.5) * cellH;

            let avgR = 0, avgG = 0, avgB = 0, count = 0;
            const offsets = [-0.15, 0, 0.15]; // sample at center ± 15% of cell

            for (const dy of offsets) {
                for (const dx of offsets) {
                    const px = Math.floor(centerX + dx * cellW);
                    const py = Math.floor(centerY + dy * cellH);
                    if (px >= 0 && px < regionW && py >= 0 && py < regionH) {
                        const idx = (py * regionW + px) * 4;
                        avgR += data[idx];
                        avgG += data[idx + 1];
                        avgB += data[idx + 2];
                        count++;
                    }
                }
            }

            if (count > 0) {
                avgR = avgR / count;
                avgG = avgG / count;
                avgB = avgB / count;
            }

            if (colorMode === 0) {
                // B&W: adaptive Otsu threshold
                const luma = 0.299 * avgR + 0.587 * avgG + 0.114 * avgB;
                grid2D[r][c] = (luma > lumaThreshold) ? 1 : 0;
            } else {
                // Color modes: nearest-neighbor to palette
                let bestIdx = 0;
                let minDist = Infinity;
                for (let k = 0; k < palette.length; k++) {
                    const [pr, pg, pb] = palette[k];
                    const dist = (avgR - pr) ** 2 + (avgG - pg) ** 2 + (avgB - pb) ** 2;
                    if (dist < minDist) {
                        minDist = dist;
                        bestIdx = k;
                    }
                }
                grid2D[r][c] = bestIdx;
            }
        }
    }

    return grid2D;
}

/**
 * Computes Otsu's optimal threshold from a sparse sample of pixel luminance values.
 * This dynamically adapts to screen brightness, camera exposure, and ambient light.
 */
function computeOtsuThreshold(data, w, h, gridSize) {
    // Sample ~500 pixels uniformly across the image
    const step = Math.max(1, Math.floor((w * h) / 500));
    const histogram = new Uint32Array(256);
    let sampleCount = 0;

    for (let i = 0; i < w * h; i += step) {
        const idx = i * 4;
        const luma = Math.floor(0.299 * data[idx] + 0.587 * data[idx + 1] + 0.114 * data[idx + 2]);
        histogram[Math.min(255, luma)]++;
        sampleCount++;
    }

    // Otsu's method
    let sumTotal = 0;
    for (let i = 0; i < 256; i++) sumTotal += i * histogram[i];

    let sumBg = 0, weightBg = 0;
    let maxVariance = 0, threshold = 128;

    for (let t = 0; t < 256; t++) {
        weightBg += histogram[t];
        if (weightBg === 0) continue;
        const weightFg = sampleCount - weightBg;
        if (weightFg === 0) break;

        sumBg += t * histogram[t];
        const meanBg = sumBg / weightBg;
        const meanFg = (sumTotal - sumBg) / weightFg;
        const variance = weightBg * weightFg * (meanBg - meanFg) ** 2;

        if (variance > maxVariance) {
            maxVariance = variance;
            threshold = t;
        }
    }

    return threshold;
}

// ===================== VIEWFINDER UI =====================

function drawViewfinderGuide(rect, vw, vh) {
    const ctx = receiverCtx;
    const { x, y, w, h } = rect;
    const bracketLen = Math.min(w, h) * 0.08;
    const lw = 3;

    // Semi-transparent overlay outside the guide
    ctx.fillStyle = 'rgba(0, 0, 0, 0.35)';
    ctx.fillRect(0, 0, vw, y);           // top
    ctx.fillRect(0, y + h, vw, vh - y - h); // bottom
    ctx.fillRect(0, y, x, h);            // left
    ctx.fillRect(x + w, y, vw - x - w, h); // right

    // Corner brackets (green)
    ctx.strokeStyle = '#00ff66';
    ctx.lineWidth = lw;
    ctx.lineCap = 'round';

    // Top-Left
    ctx.beginPath();
    ctx.moveTo(x, y + bracketLen); ctx.lineTo(x, y); ctx.lineTo(x + bracketLen, y);
    ctx.stroke();
    // Top-Right
    ctx.beginPath();
    ctx.moveTo(x + w - bracketLen, y); ctx.lineTo(x + w, y); ctx.lineTo(x + w, y + bracketLen);
    ctx.stroke();
    // Bottom-Right
    ctx.beginPath();
    ctx.moveTo(x + w, y + h - bracketLen); ctx.lineTo(x + w, y + h); ctx.lineTo(x + w - bracketLen, y + h);
    ctx.stroke();
    // Bottom-Left
    ctx.beginPath();
    ctx.moveTo(x + bracketLen, y + h); ctx.lineTo(x, y + h); ctx.lineTo(x, y + h - bracketLen);
    ctx.stroke();

    // Center crosshair (subtle)
    ctx.strokeStyle = 'rgba(0, 255, 102, 0.3)';
    ctx.lineWidth = 1;
    const cx = x + w / 2, cy = y + h / 2;
    ctx.beginPath();
    ctx.moveTo(cx - 15, cy); ctx.lineTo(cx + 15, cy);
    ctx.moveTo(cx, cy - 15); ctx.lineTo(cx, cy + 15);
    ctx.stroke();

    // Label
    ctx.fillStyle = '#00ff66';
    ctx.font = '12px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Fill this area with the flashing matrix', x + w / 2, y - 8);
}

// ===================== PROGRESS & COMPLETION =====================

function updateReceiverProgress(ratio) {
    const pct = Math.min(100, Math.floor(ratio * 100));
    const bar = document.getElementById('receiverProgressBar');
    if (bar) bar.style.width = `${pct}%`;
    const lbl = document.getElementById('receiverProgressLabel');
    if (lbl) lbl.textContent = `${pct}%`;
}

function onFileTransferComplete() {
    updateReceiverProgress(1.0);
    document.getElementById('receiverStatusBadge').textContent = "★ TRANSFER COMPLETE!";
    document.getElementById('receiverStatusBadge').className = "badge-complete";

    const fullData = receiverDecoder.reconstructData();
    if (!fullData) return;

    const meta = unpackFileMetadata(fullData);
    let filename = "chromabeam_received.bin";
    let filePayload = fullData;

    if (meta) {
        filename = meta.filename;
        filePayload = fullData.subarray(meta.metadataHeaderLen, meta.metadataHeaderLen + meta.filesize);
    }

    const blob = new Blob([filePayload], { type: 'application/octet-stream' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    alert(`🎉 Received: ${filename} (${(filePayload.length / 1024).toFixed(1)} KB)`);
}
