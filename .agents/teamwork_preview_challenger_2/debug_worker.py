import subprocess
import json
from bs4 import BeautifulSoup

with open('../../chromabeam_offline.html', 'r') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')
worker_src = soup.find('script', {'id': 'scanner-worker-src'}).string

test_script = f"""
const vm = require('vm');
const code = {json.dumps(worker_src)};

const postedMessages = [];
const workerSandbox = {{
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
    self: {{
        postMessage: (msg, transfer) => {{
            postedMessages.push(msg);
        }},
        onmessage: null
    }}
}};

vm.createContext(workerSandbox);
vm.runInContext(code, workerSandbox);

const onmessage = workerSandbox.self.onmessage;
onmessage({{ data: {{ type: 'reset' }} }});
console.log("Reset ack received:", postedMessages.length);

// Generate packet
const testFilePayload = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]);
const meta = workerSandbox.packFileMetadata("test_offline.txt", testFilePayload.length, "text/plain");
const fullTransferData = new Uint8Array(meta.length + testFilePayload.length);
fullTransferData.set(meta, 0);
fullTransferData.set(testFilePayload, meta.length);

const blockSize = 64;
const encoder = new workerSandbox.LTEncoder(fullTransferData, blockSize);
const K = encoder.K;

const {{ payload }} = encoder.generateDroplet(0);
const packet = workerSandbox.packPacket(555, K, blockSize, 0, payload);

const layout = new workerSandbox.JSColorMatrixLayout(32, 0);
const gridIndices = workerSandbox.bytesToGridIndices(packet, layout);

const cell = 6;
const ox = 32, oy = 32;
const matrixDim = 32 * cell;
const width = matrixDim + 64;
const height = matrixDim + 64;
const imgBuffer = new ArrayBuffer(width * height * 4);
const imgData = new Uint8ClampedArray(imgBuffer);
imgData.fill(0);

for (let r = 0; r < 32; r++) {{
    for (let c = 0; c < 32; c++) {{
        const val = (gridIndices[r][c] === 1) ? 255 : 0;
        for (let dy = 0; dy < cell; dy++) {{
            for (let dx = 0; dx < cell; dx++) {{
                const px = ox + c * cell + dx;
                const py = oy + r * cell + dy;
                const idx = (py * width + px) * 4;
                imgData[idx] = val;
                imgData[idx + 1] = val;
                imgData[idx + 2] = val;
                imgData[idx + 3] = 255;
            }}
        }}
    }}
}}

onmessage({{
    data: {{
        type: 'processFrame',
        buffer: imgBuffer,
        width,
        height,
        guideRect: {{ x: ox, y: oy, w: matrixDim, h: matrixDim }}
    }}
}});

console.log("Posted messages after frame:", postedMessages.length);
console.log("Last message:", JSON.stringify(postedMessages[postedMessages.length - 1]));
"""

proc = subprocess.run(["node", "-e", test_script], capture_output=True, text=True)
print("Returncode:", proc.returncode)
print("STDOUT:", proc.stdout)
print("STDERR:", proc.stderr)
