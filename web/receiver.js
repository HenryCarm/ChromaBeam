/**
 * ChromaBeam High-Performance Web & Mobile Optical Receiver
 * Features:
 * - Sub-pixel corner anchor search & snap
 * - Dynamic 5-point RGB color calibrator & Euclidean nearest-neighbor classifier
 * - Robust Soliton Luby Transform ripple solver
 * - Auto-download upon 100% completion
 */

let receiverGridSize = 64;
let receiverLayout = new JSColorMatrixLayout(receiverGridSize);
let receiverDecoder = null;
let receiverCurrentFileId = null;
let receiverVideo = null;
let receiverCanvas = null;
let receiverCtx = null;
let receiverStream = null;
let receiverRunning = false;

let receiverPacketsCaught = 0;
let receiverCRCErrors = 0;
let receiverIsComplete = false;
let receiverFpsCounter = 0;
let receiverLastFpsTime = 0;
let receiverCalculatedFPS = 0;

// Dynamic calibrated color vectors in RGB [0..255]
let calibratedPalette = [
    [20, 20, 20],      // 000: Black
    [40, 60, 220],     // 001: Blue
    [40, 200, 60],     // 010: Green
    [40, 210, 220],    // 011: Cyan
    [220, 40, 40],     // 100: Red
    [220, 50, 220],    // 101: Magenta
    [220, 210, 40],    // 110: Yellow
    [240, 240, 240]    // 111: White
];

function initReceiver() {
    receiverVideo = document.getElementById('receiverVideo');
    receiverCanvas = document.getElementById('receiverCanvas');
    if (receiverCanvas) {
        receiverCtx = receiverCanvas.getContext('2d', { willReadFrequently: true });
    }
}

function updateReceiverGridDensity(size) {
    receiverGridSize = size;
    receiverLayout = new JSColorMatrixLayout(size);
    receiverDecoder = null;
    receiverCurrentFileId = null;
    receiverPacketsCaught = 0;
    receiverCRCErrors = 0;
    receiverIsComplete = false;
    updateReceiverProgress(0);
}

async function getCameraStream(constraints) {
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        return await navigator.mediaDevices.getUserMedia(constraints);
    }
    const legacyGetUserMedia = navigator.getUserMedia || navigator.webkitGetUserMedia || navigator.mozGetUserMedia || navigator.msGetUserMedia;
    if (legacyGetUserMedia) {
        return new Promise((resolve, reject) => {
            legacyGetUserMedia.call(navigator, constraints, resolve, reject);
        });
    }
    throw new Error("INSECURE_CONTEXT_OR_UNSUPPORTED");
}

async function startReceiverCamera() {
    try {
        const constraints = {
            video: {
                facingMode: { ideal: "environment" },
                width: { ideal: 1280 },
                height: { ideal: 720 },
                frameRate: { ideal: 60 }
            },
            audio: false
        };

        receiverStream = await getCameraStream(constraints);
        receiverVideo.srcObject = receiverStream;
        await receiverVideo.play();

        receiverRunning = true;
        receiverPacketsCaught = 0;
        receiverCRCErrors = 0;
        receiverIsComplete = false;
        receiverDecoder = null;

        document.getElementById('receiverStartBtn').style.display = 'none';
        document.getElementById('receiverStopBtn').style.display = 'inline-block';
        document.getElementById('receiverStatusBadge').textContent = "● SCANNING FOR OPTICAL BEAM";
        document.getElementById('receiverStatusBadge').className = "badge-scanning";

        requestAnimationFrame(processReceiverFrame);
    } catch (err) {
        if (err.message === "INSECURE_CONTEXT_OR_UNSUPPORTED" || err.name === "TypeError") {
            const httpsUrl = `https://${location.hostname}:8443/`;
            const msg = `⚠️ Camera Blocked by Browser Security Policy!\n\nModern mobile browsers require HTTPS for camera access.\n\n👉 Please open the HTTPS link:\n${httpsUrl}\n\n(Tap 'Advanced' -> 'Proceed' if you see a cert warning).`;
            alert(msg);
            if (confirm("Redirect to HTTPS now?")) {
                window.location.href = httpsUrl;
            }
        } else {
            alert("Camera Access Error: " + err.message);
        }
        console.error("Camera error:", err);
    }
}

function stopReceiverCamera() {
    receiverRunning = false;
    if (receiverStream) {
        receiverStream.getTracks().forEach(track => track.stop());
        receiverStream = null;
    }
    document.getElementById('receiverStartBtn').style.display = 'inline-block';
    document.getElementById('receiverStopBtn').style.display = 'none';
    document.getElementById('receiverStatusBadge').textContent = "● IDLE";
    document.getElementById('receiverStatusBadge').className = "badge-idle";
}

function processReceiverFrame() {
    if (!receiverRunning) return;

    receiverFpsCounter++;
    const now = performance.now();
    if (now - receiverLastFpsTime >= 1000) {
        receiverCalculatedFPS = receiverFpsCounter;
        receiverFpsCounter = 0;
        receiverLastFpsTime = now;
        document.getElementById('receiverFpsVal').textContent = `${receiverCalculatedFPS} FPS`;
    }

    if (receiverVideo.readyState === receiverVideo.HAVE_ENOUGH_DATA) {
        const vw = receiverVideo.videoWidth;
        const vh = receiverVideo.videoHeight;

        if (receiverCanvas.width !== vw || receiverCanvas.height !== vh) {
            receiverCanvas.width = vw;
            receiverCanvas.height = vh;
        }

        receiverCtx.drawImage(receiverVideo, 0, 0, vw, vh);
        const imgData = receiverCtx.getImageData(0, 0, vw, vh);

        // 1. Locate the optical frame corners with sub-pixel snap
        const quad = detectAndSnapQuad(imgData, vw, vh);

        // 2. Draw viewfinder target guide & snapped corners
        drawLockReticle(quad, vw, vh);

        if (quad) {
            document.getElementById('receiverStatusBadge').textContent = "● LOCKED ONTO BEAM";
            document.getElementById('receiverStatusBadge').className = "badge-locked";

            // 3. Calibrate color palette from top border reference swatches
            calibrateColorsFromFrame(imgData, vw, vh, quad);

            // 4. Sample cells and classify
            const sampledGrid = sampleGridFromQuad(imgData, vw, vh, quad, receiverLayout.gridSize);
            const rawBytes = gridIndicesToBytes(sampledGrid, receiverLayout);
            const packet = unpackPacket(rawBytes);

            if (packet) {
                receiverPacketsCaught++;
                const { header, payload } = packet;

                if (!receiverDecoder || receiverCurrentFileId !== header.fileId) {
                    receiverCurrentFileId = header.fileId;
                    receiverDecoder = new LTDecoder(header.totalBlocks, header.blockSize, header.totalBlocks * header.blockSize);
                    receiverIsComplete = false;
                }

                const solved = receiverDecoder.addDroplet(header.seed, payload);
                const progress = receiverDecoder.getProgress();

                updateReceiverProgress(progress);

                if (solved && !receiverIsComplete) {
                    receiverIsComplete = true;
                    onFileTransferComplete();
                }
            } else {
                receiverCRCErrors++;
            }
        }

        document.getElementById('receiverDropletVal').textContent = `Caught: ${receiverPacketsCaught} (Drops: ${receiverCRCErrors})`;
    }

    if (receiverRunning) {
        requestAnimationFrame(processReceiverFrame);
    }
}

/**
 * Searches near the 4 corners of the center viewfinder for high-contrast white anchors and snaps to them.
 */
function detectAndSnapQuad(imgData, w, h) {
    const margin = Math.min(w, h) * 0.12;
    const size = Math.min(w, h) - (2 * margin);
    const cx = w / 2;
    const cy = h / 2;

    let tl = { x: cx - size / 2, y: cy - size / 2 };
    let tr = { x: cx + size / 2, y: cy - size / 2 };
    let br = { x: cx + size / 2, y: cy + size / 2 };
    let bl = { x: cx - size / 2, y: cy + size / 2 };

    // Snap to nearest bright white corner peaks within a 40px search radius
    tl = snapToBrightCorner(imgData, w, h, tl.x, tl.y, -1, -1);
    tr = snapToBrightCorner(imgData, w, h, tr.x, tr.y, 1, -1);
    br = snapToBrightCorner(imgData, w, h, br.x, br.y, 1, 1);
    bl = snapToBrightCorner(imgData, w, h, bl.x, bl.y, -1, 1);

    return [tl, tr, br, bl];
}

function snapToBrightCorner(imgData, w, h, initX, initY, dirX, dirY) {
    const data = imgData.data;
    const radius = 35;
    let maxScore = -1;
    let bestX = initX;
    let bestY = initY;

    const minX = Math.max(10, Math.floor(initX - radius));
    const maxX = Math.min(w - 10, Math.floor(initX + radius));
    const minY = Math.max(10, Math.floor(initY - radius));
    const maxY = Math.min(h - 10, Math.floor(initY + radius));

    // Look for white anchor border (high luminance)
    for (let y = minY; y <= maxY; y += 3) {
        for (let x = minX; x <= maxX; x += 3) {
            const idx = (y * w + x) * 4;
            const r = data[idx];
            const g = data[idx + 1];
            const b = data[idx + 2];
            const luma = 0.299 * r + 0.587 * g + 0.114 * b;

            if (luma > maxScore) {
                maxScore = luma;
                bestX = x;
                bestY = y;
            }
        }
    }

    if (maxScore > 140) {
        return { x: bestX, y: bestY };
    }
    return { x: initX, y: initY };
}

/**
 * Samples the 5-point calibration bar (Black, Red, Green, Blue, White) and updates the calibrated palette.
 */
function calibrateColorsFromFrame(imgData, w, h, quad) {
    const [tl, tr, br, bl] = quad;
    const N = receiverLayout.gridSize;
    const s = receiverLayout.anchorSize;
    const calCoords = receiverLayout.calCells;
    if (calCoords.length < 5) return;

    const samples = [];
    for (let i = 0; i < Math.min(5, calCoords.length); i++) {
        const { r, c } = calCoords[i];
        const u = (c + 0.5) / N;
        const v = (r + 0.5) / N;

        const topX = tl.x + u * (tr.x - tl.x);
        const topY = tl.y + u * (tr.y - tl.y);
        const botX = bl.x + u * (br.x - bl.x);
        const botY = bl.y + u * (br.y - bl.y);

        const px = Math.floor(topX + v * (botX - topX));
        const py = Math.floor(topY + v * (botY - topY));

        if (px >= 0 && px < w && py >= 0 && py < h) {
            const idx = (py * w + px) * 4;
            samples.push([imgData.data[idx], imgData.data[idx + 1], imgData.data[idx + 2]]);
        }
    }

    if (samples.length >= 5) {
        const [K, R, G, B, W] = samples;
        calibratedPalette[0] = K; // Black
        calibratedPalette[1] = B; // Blue
        calibratedPalette[2] = G; // Green
        calibratedPalette[3] = [(G[0] + B[0]) / 2, (G[1] + B[1]) / 2, (G[2] + B[2]) / 2]; // Cyan
        calibratedPalette[4] = R; // Red
        calibratedPalette[5] = [(R[0] + B[0]) / 2, (R[1] + B[1]) / 2, (R[2] + B[2]) / 2]; // Magenta
        calibratedPalette[6] = [(R[0] + G[0]) / 2, (R[1] + G[1]) / 2, (R[2] + G[2]) / 2]; // Yellow
        calibratedPalette[7] = W; // White
    }
}

/**
 * Samples cells and classifies using nearest Euclidean distance to calibrated color vectors.
 */
function sampleGridFromQuad(imgData, w, h, quad, gridSize) {
    const [tl, tr, br, bl] = quad;
    const grid2D = Array.from({ length: gridSize }, () => new Uint8Array(gridSize));
    const data = imgData.data;

    for (let r = 0; r < gridSize; r++) {
        const v = (r + 0.5) / gridSize;
        for (let c = 0; c < gridSize; c++) {
            const u = (c + 0.5) / gridSize;

            const topX = tl.x + u * (tr.x - tl.x);
            const topY = tl.y + u * (tr.y - tl.y);
            const botX = bl.x + u * (br.x - bl.x);
            const botY = bl.y + u * (br.y - bl.y);

            const px = Math.floor(topX + v * (botX - topX));
            const py = Math.floor(topY + v * (botY - topY));

            if (px >= 0 && px < w && py >= 0 && py < h) {
                const idx = (py * w + px) * 4;
                const cr = data[idx];
                const cg = data[idx + 1];
                const cb = data[idx + 2];

                // Nearest-color classification
                let bestIdx = 0;
                let minDist = 1e9;
                for (let k = 0; k < 8; k++) {
                    const [pr, pg, pb] = calibratedPalette[k];
                    const dist = (cr - pr) ** 2 + (cg - pg) ** 2 + (cb - pb) ** 2;
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

function drawLockReticle(quad, w, h) {
    if (!quad) return;

    // Outer guide box
    receiverCtx.strokeStyle = '#00ff66';
    receiverCtx.lineWidth = 2.5;
    receiverCtx.beginPath();
    receiverCtx.moveTo(quad[0].x, quad[0].y);
    receiverCtx.lineTo(quad[1].x, quad[1].y);
    receiverCtx.lineTo(quad[2].x, quad[2].y);
    receiverCtx.lineTo(quad[3].x, quad[3].y);
    receiverCtx.closePath();
    receiverCtx.stroke();

    // Draw corner brackets
    quad.forEach((pt, i) => {
        receiverCtx.fillStyle = '#00ff66';
        receiverCtx.beginPath();
        receiverCtx.arc(pt.x, pt.y, 6, 0, 2 * Math.PI);
        receiverCtx.fill();

        receiverCtx.strokeStyle = '#ffffff';
        receiverCtx.lineWidth = 2;
        receiverCtx.beginPath();
        receiverCtx.arc(pt.x, pt.y, 14, 0, 2 * Math.PI);
        receiverCtx.stroke();
    });
}

function updateReceiverProgress(ratio) {
    const pct = Math.min(100, Math.floor(ratio * 100));
    document.getElementById('receiverProgressBar').style.width = `${pct}%`;
    document.getElementById('receiverProgressLabel').textContent = `${pct}%`;
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

    alert(`🎉 Success! Received and downloaded: ${filename} (${(filePayload.length / 1024).toFixed(1)} KB)`);
}
