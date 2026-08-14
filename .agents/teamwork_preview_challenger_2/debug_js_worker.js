const fs = require('fs');
const path = require('path');
const vm = require('vm');

const PROJECT_ROOT = path.join(__dirname, '..', '..');
const fountainCode = fs.readFileSync(path.join(PROJECT_ROOT, "web", "fountain.js"), 'utf8');
const protocolCode = fs.readFileSync(path.join(PROJECT_ROOT, "web", "protocol.js"), 'utf8');
const matrixCode = fs.readFileSync(path.join(PROJECT_ROOT, "web", "matrix.js"), 'utf8');
const visionCode = fs.readFileSync(path.join(PROJECT_ROOT, "web", "vision_engine.js"), 'utf8');
const workerCode = fs.readFileSync(path.join(PROJECT_ROOT, "web", "scanner_worker.js"), 'utf8');

const postedMessages = [];
const sandbox = {
    console,
    performance,
    Math,
    Uint8Array,
    Uint32Array,
    Uint8ClampedArray,
    Float64Array,
    DataView,
    TextEncoder,
    TextDecoder,
    Array,
    Set,
    Map,
    postedMessages,
    self: {
        postMessage: (msg, transfer) => {
            postedMessages.push(msg);
        },
        onmessage: null
    }
};

vm.createContext(sandbox);
vm.runInContext(fountainCode + '\n' + protocolCode + '\n' + matrixCode + '\n' + visionCode + '\n' + workerCode, sandbox);

const testRunner = `
const onmessage = self.onmessage;
onmessage({ data: { type: 'reset' } });
postedMessages.shift(); // resetAck

function renderFrame(gridSize, colorMode, rotDeg, packetBytes) {
    const layout = new JSColorMatrixLayout(gridSize, colorMode);
    let gridIndices = bytesToGridIndices(packetBytes, layout);

    if (rotDeg === 90) {
        const rot = Array.from({ length: gridSize }, () => new Uint8Array(gridSize));
        for (let r = 0; r < gridSize; r++) for (let c = 0; c < gridSize; c++) rot[c][gridSize - 1 - r] = gridIndices[r][c];
        gridIndices = rot;
    } else if (rotDeg === 180) {
        const rot = Array.from({ length: gridSize }, () => new Uint8Array(gridSize));
        for (let r = 0; r < gridSize; r++) for (let c = 0; c < gridSize; c++) rot[gridSize - 1 - r][gridSize - 1 - c] = gridIndices[r][c];
        gridIndices = rot;
    }

    const cell = 6;
    const ox = 32, oy = 32;
    const matrixDim = gridSize * cell;
    const width = matrixDim + 64;
    const height = matrixDim + 64;
    const imgBuffer = new ArrayBuffer(width * height * 4);
    const imgData = new Uint8ClampedArray(imgBuffer);
    imgData.fill(0);

    const palette = layout.palette;
    for (let r = 0; r < gridSize; r++) {
        for (let c = 0; c < gridSize; c++) {
            const colorIdx = gridIndices[r][c];
            const [red, green, blue] = palette[colorIdx];
            for (let dy = 0; dy < cell; dy++) {
                for (let dx = 0; dx < cell; dx++) {
                    const px = ox + c * cell + dx;
                    const py = oy + r * cell + dy;
                    const idx = (py * width + px) * 4;
                    imgData[idx] = red;
                    imgData[idx + 1] = green;
                    imgData[idx + 2] = blue;
                    imgData[idx + 3] = 255;
                }
            }
        }
    }

    return { imgBuffer, width, height, ox, oy, matrixDim };
}

// Frame 1: 32x32 Potato (Mode 0, 0°)
const payload1 = new Uint8Array([1, 2, 3, 4]);
const pkt1 = packPacket(77, 3, 4, 0, payload1);
const f1 = renderFrame(32, 0, 0, pkt1);
onmessage({ data: { type: 'processFrame', buffer: f1.imgBuffer, width: f1.width, height: f1.height, guideRect: { x: f1.ox, y: f1.oy, w: f1.matrixDim, h: f1.matrixDim } } });
const res1 = postedMessages.shift();

// Frame 2: 48x48 Balanced (Mode 1, 90°)
const payload2 = new Uint8Array([5, 6, 7, 8]);
const pkt2 = packPacket(77, 3, 4, 1, payload2);
const f2 = renderFrame(48, 1, 90, pkt2);
onmessage({ data: { type: 'processFrame', buffer: f2.imgBuffer, width: f2.width, height: f2.height, guideRect: { x: f2.ox, y: f2.oy, w: f2.matrixDim, h: f2.matrixDim } } });
const res2 = postedMessages.shift();

// Frame 3: 48x48 Turbo (Mode 2, 180°)
const payload3 = new Uint8Array([9, 10, 11, 12]);
const pkt3 = packPacket(77, 3, 4, 2, payload3);
const f3 = renderFrame(48, 2, 180, pkt3);
onmessage({ data: { type: 'processFrame', buffer: f3.imgBuffer, width: f3.width, height: f3.height, guideRect: { x: f3.ox, y: f3.oy, w: f3.matrixDim, h: f3.matrixDim } } });
const res3 = postedMessages.shift();

({ res1, res2, res3 });
`;

const results = vm.runInContext(testRunner, sandbox);
console.log(JSON.stringify(results, null, 2));
