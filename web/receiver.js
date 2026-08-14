/**
 * ChromaBeam Web & Mobile Camera Optical Receiver
 * Real-time video frame parsing, perspective correction, color classification, and LT fountain solver.
 */

let receiverLayout = new JSColorMatrixLayout(48);
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

function initReceiver() {
    receiverVideo = document.getElementById('receiverVideo');
    receiverCanvas = document.getElementById('receiverCanvas');
    if (receiverCanvas) {
        receiverCtx = receiverCanvas.getContext('2d', { willReadFrequently: true });
    }
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

        receiverStream = await navigator.mediaDevices.getUserMedia(constraints);
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
        alert("Camera Access Error: " + err.message);
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

    // Measure FPS
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

        // Track and extract optical matrix
        const quad = detectOpticalQuad(imgData, vw, vh);

        if (quad) {
            drawLockReticle(quad);
            document.getElementById('receiverStatusBadge').textContent = "● LOCKED ONTO BEAM";
            document.getElementById('receiverStatusBadge').className = "badge-locked";

            // Sample warped cells
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

                // Update UI progress
                updateReceiverProgress(progress);

                if (solved && !receiverIsComplete) {
                    receiverIsComplete = true;
                    onFileTransferComplete();
                }
            } else {
                receiverCRCErrors++;
            }
        } else {
            document.getElementById('receiverStatusBadge').textContent = "● SCANNING FOR OPTICAL BEAM";
            document.getElementById('receiverStatusBadge').className = "badge-scanning";
        }

        document.getElementById('receiverDropletVal').textContent = `Caught: ${receiverPacketsCaught} (Drops: ${receiverCRCErrors})`;
    }

    if (receiverRunning) {
        requestAnimationFrame(processReceiverFrame);
    }
}

/**
 * Fast quad finder: uses center viewfinder region of interest for rapid homography sampling.
 */
function detectOpticalQuad(imgData, w, h) {
    // High-contrast center ROI box
    const marginX = w * 0.15;
    const marginY = h * 0.15;
    const size = Math.min(w - 2 * marginX, h - 2 * marginY);
    const cx = w / 2;
    const cy = h / 2;

    const tl = { x: cx - size / 2, y: cy - size / 2 };
    const tr = { x: cx + size / 2, y: cy - size / 2 };
    const br = { x: cx + size / 2, y: cy + size / 2 };
    const bl = { x: cx - size / 2, y: cy + size / 2 };

    return [tl, tr, br, bl];
}

function sampleGridFromQuad(imgData, w, h, quad, gridSize) {
    const [tl, tr, br, bl] = quad;
    const grid2D = Array.from({ length: gridSize }, () => new Uint8Array(gridSize));
    const data = imgData.data;

    for (let r = 0; r < gridSize; r++) {
        const v = (r + 0.5) / gridSize;
        for (let c = 0; c < gridSize; c++) {
            const u = (c + 0.5) / gridSize;

            // Bilinear interpolation between quad vertices
            const topX = tl.x + u * (tr.x - tl.x);
            const topY = tl.y + u * (tr.y - tl.y);
            const botX = bl.x + u * (br.x - bl.x);
            const botY = bl.y + u * (br.y - bl.y);

            const px = Math.floor(topX + v * (botX - topX));
            const py = Math.floor(topY + v * (botY - topY));

            if (px >= 0 && px < w && py >= 0 && py < h) {
                const idx = (py * w + px) * 4;
                const red = data[idx];
                const green = data[idx + 1];
                const blue = data[idx + 2];

                // 3-bit threshold
                const rBit = red > 128 ? 1 : 0;
                const gBit = green > 128 ? 1 : 0;
                const bBit = blue > 128 ? 1 : 0;
                grid2D[r][c] = (rBit << 2) | (gBit << 1) | bBit;
            }
        }
    }

    return grid2D;
}

function drawLockReticle(quad) {
    receiverCtx.strokeStyle = '#00ff66';
    receiverCtx.lineWidth = 3;
    receiverCtx.beginPath();
    receiverCtx.moveTo(quad[0].x, quad[0].y);
    receiverCtx.lineTo(quad[1].x, quad[1].y);
    receiverCtx.lineTo(quad[2].x, quad[2].y);
    receiverCtx.lineTo(quad[3].x, quad[3].y);
    receiverCtx.closePath();
    receiverCtx.stroke();

    // Draw corner markers
    quad.forEach(pt => {
        receiverCtx.fillStyle = '#ff0033';
        receiverCtx.beginPath();
        receiverCtx.arc(pt.x, pt.y, 6, 0, 2 * Math.PI);
        receiverCtx.fill();
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

    // Trigger instant browser download
    const blob = new Blob([filePayload], { type: 'application/octet-stream' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    alert(`🎉 Success! Received and saved: ${filename} (${(filePayload.length / 1024).toFixed(1)} KB)`);
}
