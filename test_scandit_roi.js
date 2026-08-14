const fs = require('fs');
const jsQR = require('/home/henry/node_modules/jsqr/dist/jsQR.js');
const qrcode = require('/home/henry/node_modules/qrcode-generator/dist/qrcode.js');
const { packPacket, unpackPacket } = require('./web/protocol.js');
const { LTEncoder, LTDecoder } = require('./web/fountain.js');

console.log("==================================================");
console.log("TEST: Scandit-style Fast ROI Tracking Simulator");
console.log("==================================================");

// Generate a sample frame with QR code placed inside a 720x1280 canvas
const canvasW = 720;
const canvasH = 1280;
const fullCanvas = new Uint8ClampedArray(canvasW * canvasH * 4);
// Fill canvas with gray noise
fullCanvas.fill(80);

const testPayload = new Uint8Array(200);
for (let i = 0; i < 200; i++) testPayload[i] = (i * 17) & 0xFF;
const packet = packPacket(555, 10, 200, 1, testPayload);

let binary = '';
for (let i = 0; i < packet.length; i++) binary += String.fromCharCode(packet[i]);
const b64 = Buffer.from(packet).toString('base64');

const qr = qrcode(0, 'L');
qr.addData(b64);
qr.make();

const moduleCount = qr.getModuleCount();
const qrPixelSize = 360;
const cellSize = qrPixelSize / (moduleCount + 8);
const qrOffsetX = 180;
const qrOffsetY = 460;

// Draw white quiet zone box
for (let y = 0; y < qrPixelSize; y++) {
    for (let x = 0; x < qrPixelSize; x++) {
        const py = qrOffsetY + y;
        const px = qrOffsetX + x;
        if (py < canvasH && px < canvasW) {
            const idx = (py * canvasW + px) * 4;
            fullCanvas[idx] = 255;
            fullCanvas[idx + 1] = 255;
            fullCanvas[idx + 2] = 255;
            fullCanvas[idx + 3] = 255;
        }
    }
}

// Draw QR code modules
for (let r = 0; r < moduleCount; r++) {
    for (let c = 0; c < moduleCount; c++) {
        const val = qr.isDark(r, c) ? 0 : 255;
        for (let dy = 0; dy < Math.ceil(cellSize); dy++) {
            for (let dx = 0; dx < Math.ceil(cellSize); dx++) {
                const py = Math.floor(qrOffsetY + (r + 4) * cellSize + dy);
                const px = Math.floor(qrOffsetX + (c + 4) * cellSize + dx);
                if (py < canvasH && px < canvasW) {
                    const idx = (py * canvasW + px) * 4;
                    fullCanvas[idx] = val;
                    fullCanvas[idx + 1] = val;
                    fullCanvas[idx + 2] = val;
                    fullCanvas[idx + 3] = 255;
                }
            }
        }
    }
}

// Function to crop and scan ROI
function scanCroppedROI(buffer, imgW, imgH, rx, ry, rw, rh) {
    rx = Math.max(0, Math.floor(rx));
    ry = Math.max(0, Math.floor(ry));
    rw = Math.min(imgW - rx, Math.floor(rw));
    rh = Math.min(imgH - ry, Math.floor(rh));
    if (rw < 50 || rh < 50) return null;

    const cropBuf = new Uint8ClampedArray(rw * rh * 4);
    for (let y = 0; y < rh; y++) {
        const srcOffset = ((ry + y) * imgW + rx) * 4;
        const dstOffset = (y * rw) * 4;
        cropBuf.set(buffer.subarray(srcOffset, srcOffset + rw * 4), dstOffset);
    }

    const res = jsQR(cropBuf, rw, rh, { inversionAttempts: "attemptBoth" });
    if (res && res.data) {
        return {
            data: res.data,
            location: {
                topLeftCorner: { x: res.location.topLeftCorner.x + rx, y: res.location.topLeftCorner.y + ry },
                topRightCorner: { x: res.location.topRightCorner.x + rx, y: res.location.topRightCorner.y + ry },
                bottomRightCorner: { x: res.location.bottomRightCorner.x + rx, y: res.location.bottomRightCorner.y + ry },
                bottomLeftCorner: { x: res.location.bottomLeftCorner.x + rx, y: res.location.bottomLeftCorner.y + ry }
            }
        };
    }
    return null;
}

// Benchmark 1: Full Frame
const t0 = performance.now();
const fullRes = jsQR(fullCanvas, canvasW, canvasH);
const tFull = performance.now() - t0;
console.log(`1. Full Frame Search (${canvasW}x${canvasH}): ${tFull.toFixed(2)} ms -> Found: ${fullRes ? 'YES' : 'NO'}`);

// Benchmark 2: Viewfinder ROI (500x500 at center)
const t1 = performance.now();
const vfRes = scanCroppedROI(fullCanvas, canvasW, canvasH, 110, 390, 500, 500);
const tVF = performance.now() - t1;
console.log(`2. Viewfinder ROI (500x500): ${tVF.toFixed(2)} ms -> Found: ${vfRes ? 'YES' : 'NO'}`);

// Benchmark 3: Locked Tracking ROI (400x400 tight bound)
const t2 = performance.now();
const trackRes = scanCroppedROI(fullCanvas, canvasW, canvasH, 160, 440, 400, 400);
const tTrack = performance.now() - t2;
console.log(`3. Locked Tracking ROI (400x400): ${tTrack.toFixed(2)} ms -> Found: ${trackRes ? 'YES' : 'NO'}`);

console.log(`\n🚀 Tracking ROI is ${(tFull / tTrack).toFixed(1)}x FASTER than full frame!`);
