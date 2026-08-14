/**
 * ChromaBeam High-Performance Optical Receiver v4
 * 
 * KEY FIX: Within the viewfinder guide, automatically detect the actual matrix
 * bounding box by scanning for the bright white anchor borders. This means the
 * user doesn't need to perfectly fill the guide — just get the matrix roughly
 * inside it and we'll find the exact edges.
 * 
 * Features:
 * - Auto-crop to actual matrix edges within guide region
 * - 3x3 multi-pixel cell sampling with averaging
 * - Otsu adaptive threshold for B&W
 * - Nearest-neighbor for color modes
 * - Auto-density sweep with config locking
 * - Pre-cached layouts (zero GC per frame)
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
let receiverLockedConfig = null;

// Pre-cache ALL candidate layouts at startup
const CANDIDATE_CONFIGS = [
    { grid: 32, mode: 0, label: '32×32 B&W' },
    { grid: 48, mode: 0, label: '48×48 B&W' },
    { grid: 64, mode: 0, label: '64×64 B&W' },
    { grid: 32, mode: 1, label: '32×32 4-Color' },
    { grid: 48, mode: 1, label: '48×48 4-Color' },
    { grid: 48, mode: 2, label: '48×48 8-Color' },
    { grid: 64, mode: 2, label: '64×64 8-Color' },
];

const CACHED_LAYOUTS = {};
for (const cfg of CANDIDATE_CONFIGS) {
    CACHED_LAYOUTS[`${cfg.grid}_${cfg.mode}`] = new JSColorMatrixLayout(cfg.grid, cfg.mode);
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

async function startReceiverCamera() {
    try {
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
        document.getElementById('receiverStatusBadge').textContent = "● SCANNING";
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

// ===================== MAIN FRAME LOOP =====================

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

        receiverCtx.drawImage(receiverVideo, 0, 0, vw, vh);
        const fullImgData = receiverCtx.getImageData(0, 0, vw, vh);

        // Step 1: Define a generous guide region (center 85%)
        const guideSide = Math.min(vw, vh) * 0.85;
        const gx = Math.floor((vw - guideSide) / 2);
        const gy = Math.floor((vh - guideSide) / 2);
        const gw = Math.floor(guideSide);
        const gh = Math.floor(guideSide);

        // Step 2: Within the guide, auto-detect the actual matrix bounding box
        const matrixRect = detectMatrixBounds(fullImgData, vw, vh, gx, gy, gw, gh);

        // Step 3: Draw viewfinder and detected bounds
        drawViewfinder(gx, gy, gw, gh, matrixRect, vw, vh);

        // Step 4: Sample and decode from the detected matrix region
        let decodedPacket = null;
        let matchedLabel = '';

        if (matrixRect && matrixRect.w > 30 && matrixRect.h > 30) {
            const mImgData = receiverCtx.getImageData(matrixRect.x, matrixRect.y, matrixRect.w, matrixRect.h);

            if (receiverLockedConfig) {
                const key = `${receiverLockedConfig.grid}_${receiverLockedConfig.mode}`;
                const layout = CACHED_LAYOUTS[key];
                const grid = sampleGrid(mImgData, matrixRect.w, matrixRect.h, layout);
                const bytes = gridIndicesToBytes(grid, layout);
                decodedPacket = unpackPacket(bytes);
                if (decodedPacket) {
                    matchedLabel = receiverLockedConfig.label;
                } else {
                    receiverLockedConfig = null; // lost lock
                }
            }

            if (!decodedPacket) {
                for (const cfg of CANDIDATE_CONFIGS) {
                    const key = `${cfg.grid}_${cfg.mode}`;
                    const layout = CACHED_LAYOUTS[key];
                    const grid = sampleGrid(mImgData, matrixRect.w, matrixRect.h, layout);
                    const bytes = gridIndicesToBytes(grid, layout);
                    const pkt = unpackPacket(bytes);
                    if (pkt) {
                        decodedPacket = pkt;
                        matchedLabel = cfg.label;
                        receiverLockedConfig = cfg;
                        break;
                    }
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
            document.getElementById('receiverStatusBadge').textContent = "● SCANNING (point at matrix)";
            document.getElementById('receiverStatusBadge').className = "badge-scanning";
        }

        document.getElementById('receiverDropletVal').textContent =
            `Caught: ${receiverPacketsCaught} (Drops: ${receiverCRCErrors})`;
    }

    requestAnimationFrame(processReceiverFrame);
}

// ===================== MATRIX BOUNDARY DETECTION =====================

/**
 * Within the guide region, finds the actual matrix bounding box by scanning
 * for rows and columns containing bright pixels (the white anchor borders).
 * 
 * This is WAY simpler and more robust than trying to find individual corners.
 * The matrix has bright white borders on all 4 sides (the anchor patterns),
 * so we just need to find where the bright stuff starts and ends.
 */
function detectMatrixBounds(imgData, imgW, imgH, gx, gy, gw, gh) {
    const data = imgData.data;
    const BRIGHT_THRESHOLD = 160; // Pixel is considered "bright" if luma > this
    const MIN_BRIGHT_PIXELS = 3;  // Minimum bright pixels in a row/col to count

    let topEdge = -1, bottomEdge = -1, leftEdge = -1, rightEdge = -1;

    // Scan rows top→bottom to find top edge
    for (let y = gy; y < gy + gh; y++) {
        let brightCount = 0;
        for (let x = gx; x < gx + gw; x += 3) { // sparse scan for speed
            const idx = (y * imgW + x) * 4;
            const luma = 0.299 * data[idx] + 0.587 * data[idx + 1] + 0.114 * data[idx + 2];
            if (luma > BRIGHT_THRESHOLD) brightCount++;
        }
        if (brightCount >= MIN_BRIGHT_PIXELS) {
            topEdge = y;
            break;
        }
    }

    // Scan rows bottom→top to find bottom edge
    for (let y = gy + gh - 1; y >= gy; y--) {
        let brightCount = 0;
        for (let x = gx; x < gx + gw; x += 3) {
            const idx = (y * imgW + x) * 4;
            const luma = 0.299 * data[idx] + 0.587 * data[idx + 1] + 0.114 * data[idx + 2];
            if (luma > BRIGHT_THRESHOLD) brightCount++;
        }
        if (brightCount >= MIN_BRIGHT_PIXELS) {
            bottomEdge = y;
            break;
        }
    }

    // Scan columns left→right to find left edge
    for (let x = gx; x < gx + gw; x++) {
        let brightCount = 0;
        for (let y = gy; y < gy + gh; y += 3) {
            const idx = (y * imgW + x) * 4;
            const luma = 0.299 * data[idx] + 0.587 * data[idx + 1] + 0.114 * data[idx + 2];
            if (luma > BRIGHT_THRESHOLD) brightCount++;
        }
        if (brightCount >= MIN_BRIGHT_PIXELS) {
            leftEdge = x;
            break;
        }
    }

    // Scan columns right→left to find right edge
    for (let x = gx + gw - 1; x >= gx; x--) {
        let brightCount = 0;
        for (let y = gy; y < gy + gh; y += 3) {
            const idx = (y * imgW + x) * 4;
            const luma = 0.299 * data[idx] + 0.587 * data[idx + 1] + 0.114 * data[idx + 2];
            if (luma > BRIGHT_THRESHOLD) brightCount++;
        }
        if (brightCount >= MIN_BRIGHT_PIXELS) {
            rightEdge = x;
            break;
        }
    }

    if (topEdge < 0 || bottomEdge < 0 || leftEdge < 0 || rightEdge < 0) return null;
    if (rightEdge <= leftEdge || bottomEdge <= topEdge) return null;

    // Make it square (the matrix is always square)
    let w = rightEdge - leftEdge;
    let h = bottomEdge - topEdge;
    const side = Math.min(w, h);

    // Center the square within the detected bounds
    const cx = leftEdge + w / 2;
    const cy = topEdge + h / 2;

    return {
        x: Math.floor(cx - side / 2),
        y: Math.floor(cy - side / 2),
        w: Math.floor(side),
        h: Math.floor(side)
    };
}

// ===================== GRID SAMPLING =====================

/**
 * Samples the grid from a cropped matrix region.
 * Uses 3x3 multi-pixel averaging and Otsu threshold for B&W.
 */
function sampleGrid(imgData, regionW, regionH, layout) {
    const N = layout.gridSize;
    const grid2D = Array.from({ length: N }, () => new Uint8Array(N));
    const data = imgData.data;
    const colorMode = layout.colorMode;
    const cellW = regionW / N;
    const cellH = regionH / N;
    const palette = layout.palette;

    // Otsu threshold for B&W
    let lumaThreshold = 128;
    if (colorMode === 0) {
        lumaThreshold = computeOtsuThreshold(data, regionW, regionH);
    }

    for (let r = 0; r < N; r++) {
        for (let c = 0; c < N; c++) {
            const centerX = (c + 0.5) * cellW;
            const centerY = (r + 0.5) * cellH;

            // 3x3 kernel sampling at cell center ± 20% of cell size
            let avgR = 0, avgG = 0, avgB = 0, count = 0;
            const offsets = [-0.2, 0, 0.2];

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
                avgR /= count;
                avgG /= count;
                avgB /= count;
            }

            if (colorMode === 0) {
                const luma = 0.299 * avgR + 0.587 * avgG + 0.114 * avgB;
                grid2D[r][c] = (luma > lumaThreshold) ? 1 : 0;
            } else {
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

function computeOtsuThreshold(data, w, h) {
    const step = Math.max(1, Math.floor((w * h) / 400));
    const histogram = new Uint32Array(256);
    let sampleCount = 0;

    for (let i = 0; i < w * h; i += step) {
        const idx = i * 4;
        if (idx + 2 < data.length) {
            const luma = Math.floor(0.299 * data[idx] + 0.587 * data[idx + 1] + 0.114 * data[idx + 2]);
            histogram[Math.min(255, luma)]++;
            sampleCount++;
        }
    }

    let sumTotal = 0;
    for (let i = 0; i < 256; i++) sumTotal += i * histogram[i];

    let sumBg = 0, weightBg = 0, maxVariance = 0, threshold = 128;

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

function drawViewfinder(gx, gy, gw, gh, matrixRect, vw, vh) {
    const ctx = receiverCtx;
    const bracketLen = Math.min(gw, gh) * 0.06;

    // Dim overlay outside guide
    ctx.fillStyle = 'rgba(0, 0, 0, 0.4)';
    ctx.fillRect(0, 0, vw, gy);
    ctx.fillRect(0, gy + gh, vw, vh - gy - gh);
    ctx.fillRect(0, gy, gx, gh);
    ctx.fillRect(gx + gw, gy, vw - gx - gw, gh);

    // Guide corner brackets (green)
    ctx.strokeStyle = '#00ff66';
    ctx.lineWidth = 2;
    ctx.lineCap = 'round';

    // TL
    ctx.beginPath();
    ctx.moveTo(gx, gy + bracketLen); ctx.lineTo(gx, gy); ctx.lineTo(gx + bracketLen, gy);
    ctx.stroke();
    // TR
    ctx.beginPath();
    ctx.moveTo(gx + gw - bracketLen, gy); ctx.lineTo(gx + gw, gy); ctx.lineTo(gx + gw, gy + bracketLen);
    ctx.stroke();
    // BR
    ctx.beginPath();
    ctx.moveTo(gx + gw, gy + gh - bracketLen); ctx.lineTo(gx + gw, gy + gh); ctx.lineTo(gx + gw - bracketLen, gy + gh);
    ctx.stroke();
    // BL
    ctx.beginPath();
    ctx.moveTo(gx + bracketLen, gy + gh); ctx.lineTo(gx, gy + gh); ctx.lineTo(gx, gy + gh - bracketLen);
    ctx.stroke();

    // If matrix detected, draw tight blue rect around it
    if (matrixRect) {
        ctx.strokeStyle = '#58a6ff';
        ctx.lineWidth = 2;
        ctx.strokeRect(matrixRect.x, matrixRect.y, matrixRect.w, matrixRect.h);

        // Fill percentage indicator
        const fillPct = Math.floor((matrixRect.w * matrixRect.h) / (gw * gh) * 100);
        ctx.fillStyle = '#58a6ff';
        ctx.font = 'bold 13px sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(`Matrix: ${matrixRect.w}×${matrixRect.h}px (${fillPct}% fill)`, matrixRect.x, matrixRect.y - 6);
    }

    // Top label
    ctx.fillStyle = '#00ff66';
    ctx.font = '11px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Point camera at the flashing matrix', gx + gw / 2, gy - 6);
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
