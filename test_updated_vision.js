const fs = require('fs');
const { detectOpticalQuad, sampleQuadGrid, decodeGridMultiOrientation } = require('./web/vision_engine.js');
const { JSColorMatrixLayout, gridIndicesToBytes } = require('./web/matrix.js');

const rawBuf = fs.readFileSync('tests/real_phone_screenshot.raw');
const width = 501;
const height = 1024;

const imgData = {
    data: new Uint8ClampedArray(rawBuf),
    width,
    height
};

const t0 = performance.now();
const res = detectOpticalQuad(imgData, width, height, { x: 50, y: 50, w: 400, h: 400 });
const elapsed = (performance.now() - t0).toFixed(1);

console.log(`⏱️ detectOpticalQuad executed in ${elapsed} ms`);
console.log(`Method: ${res.method}, Confidence: ${res.confidence}`);
if (res.quad) {
    console.log("Quad corners:");
    res.quad.forEach((pt, i) => console.log(`  ${['TL','TR','BR','BL'][i]}: (${pt.x.toFixed(1)}, ${pt.y.toFixed(1)})`));
}
