const fs = require('fs');
const jsQR = require('/home/henry/node_modules/jsqr/dist/jsQR.js');

const rawBuf = fs.readFileSync('tests/real_phone_screenshot.raw');
const width = 501;
const height = 1024;

console.log("==========================================");
console.log("BENCHMARK: jsQR Full vs Cropped ROI Speed");
console.log("==========================================");

// Full frame benchmark
const fullData = new Uint8ClampedArray(rawBuf);
const t0 = performance.now();
for (let i = 0; i < 10; i++) {
    jsQR(fullData, width, height);
}
const fullTime = (performance.now() - t0) / 10;
console.log(`Full Frame (${width}x${height}): ${fullTime.toFixed(2)} ms / frame (${(1000/fullTime).toFixed(1)} FPS)`);

// Cropped ROI (e.g. 350x350)
const cropW = 350;
const cropH = 350;
const startX = 50;
const startY = 200;
const croppedData = new Uint8ClampedArray(cropW * cropH * 4);

for (let y = 0; y < cropH; y++) {
    for (let x = 0; x < cropW; x++) {
        const srcIdx = ((startY + y) * width + (startX + x)) * 4;
        const dstIdx = (y * cropW + x) * 4;
        croppedData[dstIdx] = fullData[srcIdx];
        croppedData[dstIdx + 1] = fullData[srcIdx + 1];
        croppedData[dstIdx + 2] = fullData[srcIdx + 2];
        croppedData[dstIdx + 3] = fullData[srcIdx + 3];
    }
}

const t1 = performance.now();
for (let i = 0; i < 10; i++) {
    jsQR(croppedData, cropW, cropH);
}
const cropTime = (performance.now() - t1) / 10;
console.log(`Cropped ROI (${cropW}x${cropH}): ${cropTime.toFixed(2)} ms / frame (${(1000/cropTime).toFixed(1)} FPS)`);
console.log(`🚀 Speedup: ${(fullTime / cropTime).toFixed(1)}x FASTER!`);
