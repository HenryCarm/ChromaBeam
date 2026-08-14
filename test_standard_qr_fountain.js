const qrcode = require('/home/henry/node_modules/qrcode-generator/dist/qrcode.js');
const jsQR = require('/home/henry/node_modules/jsqr/dist/jsQR.js');
const { packPacket, unpackPacket } = require('./web/protocol.js');
const { LTEncoder, LTDecoder } = require('./web/fountain.js');

console.log("==================================================");
console.log("TEST: Standard QR Code Stream + LT Fountain Code");
console.log("==================================================");

// 1. Create a 10KB test file
const testSize = 10 * 1024;
const fileData = new Uint8Array(testSize);
for (let i = 0; i < testSize; i++) fileData[i] = (i * 37) & 0xFF;

const blockSize = 200; // 200 bytes per QR frame
const encoder = new LTEncoder(fileData, blockSize);
const decoder = new LTDecoder(encoder.K, blockSize, testSize);

console.log(`Payload: ${testSize} bytes, K=${encoder.K} blocks, blockSize=${blockSize} bytes`);

let seed = 0;
let caught = 0;

const t0 = performance.now();

while (!decoder.isComplete && seed < encoder.K * 3) {
    const s = seed++;
    const { degree, indices, payload } = encoder.generateDroplet(s);
    const packetBytes = packPacket(12345, encoder.K, blockSize, s, payload);

    // Encode packetBytes to base64 or latin1 string for QR code
    let binaryStr = "";
    for (let i = 0; i < packetBytes.length; i++) binaryStr += String.fromCharCode(packetBytes[i]);
    const b64 = Buffer.from(packetBytes).toString('base64');

    // Generate Standard QR Code (Version 10 to 14, Error Correction L)
    const qr = qrcode(0, 'L');
    qr.addData(b64);
    qr.make();

    const moduleCount = qr.getModuleCount();
    // Render to 256x256 RGBA image buffer
    const cellSize = 6;
    const imgSize = moduleCount * cellSize;
    const imgData = new Uint8ClampedArray(imgSize * imgSize * 4);

    for (let r = 0; r < moduleCount; r++) {
        for (let c = 0; c < moduleCount; c++) {
            const isDark = qr.isDark(r, c);
            const val = isDark ? 0 : 255;
            for (let dy = 0; dy < cellSize; dy++) {
                for (let dx = 0; dx < cellSize; dx++) {
                    const py = r * cellSize + dy;
                    const px = c * cellSize + dx;
                    const idx = (py * imgSize + px) * 4;
                    imgData[idx] = val;
                    imgData[idx + 1] = val;
                    imgData[idx + 2] = val;
                    imgData[idx + 3] = 255;
                }
            }
        }
    }

    // Decode with jsQR
    const scanRes = jsQR(imgData, imgSize, imgSize);
    if (scanRes) {
        const decodedB64 = scanRes.data;
        const decodedBytes = Buffer.from(decodedB64, 'base64');
        const unpacked = unpackPacket(decodedBytes);

        if (unpacked) {
            caught++;
            decoder.addDroplet(unpacked.header.seed, unpacked.payload);
        }
    }
}

const elapsed = (performance.now() - t0).toFixed(2);
console.log(`\nResults:`);
console.log(`  Elapsed: ${elapsed} ms for ${seed} frames (${(seed / (elapsed/1000)).toFixed(1)} FPS)`);
console.log(`  Frames Sent: ${seed}`);
console.log(`  Frames Caught: ${caught} (${(caught / seed * 100).toFixed(1)}%)`);
console.log(`  Progress: ${(decoder.getProgress() * 100).toFixed(4)}%`);
console.log(`  Solved: ${decoder.solvedBlocks.size} / ${decoder.K} blocks`);
console.log(`  Complete: ${decoder.isComplete ? '✅ YES' : '❌ NO'}`);

if (decoder.isComplete) {
    const recovered = decoder.reconstructData();
    let matches = true;
    for (let i = 0; i < testSize; i++) {
        if (recovered[i] !== fileData[i]) { matches = false; break; }
    }
    console.log(`  Data Integrity: ${matches ? '✅ 100% BIT-FOR-BIT MATCH' : '❌ CORRUPTED'}`);
}
