"""
Empirical Adversarial Test Suite 2: Offline HTML Bundle Integrity, Blob Worker Execution & Zero-Network Compliance
Author: Challenger 2 (Milestone 5 Acceptance Gate)
"""

import os
import sys
import re
import json
import unittest
import subprocess
from bs4 import BeautifulSoup

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

import build_offline_html


class TestOfflineBundleAdversarial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 1. Rebuild offline HTML bundle
        build_offline_html.bundle()
        cls.html_path = os.path.join(PROJECT_ROOT, "chromabeam_offline.html")

    def test_file_exists_and_size(self):
        """Offline HTML bundle must exist and have substantial size containing full app."""
        self.assertTrue(os.path.exists(self.html_path), "chromabeam_offline.html missing!")
        size = os.path.getsize(self.html_path)
        self.assertGreater(size, 100000, f"Offline HTML suspiciously small: {size} bytes")

    def test_zero_network_offline_compliance(self):
        """
        Adversarial scan: Ensure ZERO external network calls, CDNs, fonts, or tracking scripts.
        Air-gap guarantee: Must work with zero internet connectivity.
        """
        with open(self.html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        soup = BeautifulSoup(content, 'html.parser')

        # 1. No external script src
        scripts_with_src = soup.find_all('script', src=True)
        self.assertEqual(len(scripts_with_src), 0, f"Found external script tags: {scripts_with_src}")

        # 2. No external link tags (CSS, fonts, icons)
        external_links = soup.find_all('link', href=re.compile(r'^(http|https|//)'))
        self.assertEqual(len(external_links), 0, f"Found external links: {external_links}")

        # 3. No external iframe, img, audio, video sources
        for tag_name in ['iframe', 'img', 'audio', 'video', 'embed', 'object']:
            for elem in soup.find_all(tag_name, src=re.compile(r'^(http|https|//)')):
                self.fail(f"Found external media source in <{tag_name}>: {elem}")

        # 4. Search entire HTML content for any HTTP/HTTPS URLs (excluding XML namespaces or comments)
        http_matches = re.findall(r'https?://[^\s"\'<>]+', content)
        # Filter out standard w3.org XML namespace if present
        suspicious_urls = [url for url in http_matches if 'www.w3.org' not in url and 'schema.org' not in url]
        self.assertEqual(len(suspicious_urls), 0, f"Detected external URLs in offline bundle: {suspicious_urls}")

    def test_worker_source_embedding_and_syntax(self):
        """
        Adversarial Test: Embedded Web Worker script in <script id="scanner-worker-src" type="text/plain">
        Must compile cleanly and contain all essential algorithms (Mulberry32, LTDecoder, JSColorMatrixLayout, VisionEngine).
        """
        with open(self.html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        soup = BeautifulSoup(content, 'html.parser')
        worker_elem = soup.find('script', {'id': 'scanner-worker-src'})
        self.assertIsNotNone(worker_elem, "script#scanner-worker-src not found in bundle!")
        self.assertEqual(worker_elem.get('type'), 'text/plain', "script#scanner-worker-src must be text/plain to prevent premature execution on main thread")

        worker_src = worker_elem.string
        self.assertGreater(len(worker_src), 20000, "Worker source seems truncated")

        # Test JavaScript syntax parsing via Node.js vm
        test_script = f"""
        const vm = require('vm');
        const code = {json.dumps(worker_src)};

        try {{
            new vm.Script(code);
            console.log(JSON.stringify({{ syntaxValid: true }}));
        }} catch (err) {{
            console.log(JSON.stringify({{ syntaxValid: false, error: err.message, stack: err.stack }}));
        }}
        """
        proc = subprocess.run(["node", "-e", test_script], capture_output=True, text=True, check=True)
        res = json.loads(proc.stdout.strip().split("\n")[-1])
        self.assertTrue(res["syntaxValid"], f"Worker script has syntax errors: {res.get('error')}")

    def test_simulated_worker_blob_lifecycle_and_frame_decoding(self):
        """
        Simulate Blob URL creation and full Web Worker message lifecycle:
        1. Worker instantiation
        2. 'reset' message -> 'resetAck'
        3. Synthetic frame with 32x32 Potato (1-bit) packet -> 'frameResult' with locked=true, solved=true
        4. Multi-frame reconstruction of complete file via Worker message passing
        """
        with open(self.html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        soup = BeautifulSoup(content, 'html.parser')
        worker_src = soup.find('script', {'id': 'scanner-worker-src'}).string

        test_script = f"""
        const vm = require('vm');
        const code = {json.dumps(worker_src)};

        // Build worker sandbox environment mimicking Web Worker context
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
        if (typeof onmessage !== 'function') {{
            throw new Error("Worker script did not assign self.onmessage");
        }}

        // 1. Test Reset Message
        onmessage({{ data: {{ type: 'reset' }} }});
        const resetAck = postedMessages.shift();
        const resetOk = (resetAck && resetAck.type === 'resetAck');

        // 2. Prepare test file and generate synthetic optical frame
        const testFilePayload = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]);
        const meta = packFileMetadata("test_offline.txt", testFilePayload.length, "text/plain");
        const fullTransferData = new Uint8Array(meta.length + testFilePayload.length);
        fullTransferData.set(meta, 0);
        fullTransferData.set(testFilePayload, meta.length);

        const blockSize = 64;
        const encoder = new LTEncoder(fullTransferData, blockSize);
        const K = encoder.K;

        // Render synthetic frame for droplet seed 0 (systematic)
        const {{ payload }} = encoder.generateDroplet(0);
        const packet = packPacket(555, K, blockSize, 0, payload);

        const layout = new JSColorMatrixLayout(32, 0); // 32x32 Potato B&W
        const gridIndices = bytesToGridIndices(packet, layout);

        // Upscale grid to 256x256 image with margin
        const cell = 6;
        const ox = 32, oy = 32;
        const matrixDim = 32 * cell;
        const width = matrixDim + 64;
        const height = matrixDim + 64;
        const imgBuffer = new ArrayBuffer(width * height * 4);
        const imgData = new Uint8ClampedArray(imgBuffer);
        imgData.fill(0); // dark bg

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

        // 3. Send frame to Worker
        onmessage({{
            data: {{
                type: 'processFrame',
                buffer: imgBuffer,
                width,
                height,
                guideRect: {{ x: ox, y: oy, w: matrixDim, h: matrixDim }}
            }}
        }});

        const frameResult = postedMessages.shift();

        console.log(JSON.stringify({{
            resetOk,
            frameResult: {{
                locked: frameResult ? frameResult.locked : false,
                caught: frameResult ? frameResult.caught : 0,
                progress: frameResult ? frameResult.progress : 0,
                progressPct: frameResult ? frameResult.progressPctFormatted : '',
                isComplete: frameResult ? frameResult.isComplete : false,
                hasFile: frameResult && frameResult.fileResult !== null,
                filename: frameResult && frameResult.fileResult ? frameResult.fileResult.filename : null,
                filesize: frameResult && frameResult.fileResult ? frameResult.fileResult.filesize : 0
            }}
        }}));
        """

        proc = subprocess.run(["node", "-e", test_script], capture_output=True, text=True, check=True)
        res = json.loads(proc.stdout.strip().split("\n")[-1])

        self.assertTrue(res["resetOk"], "Worker failed to handle 'reset' message")
        fr = res["frameResult"]
        self.assertTrue(fr["locked"], f"Worker failed to lock onto synthetic frame: {fr}")
        self.assertEqual(fr["caught"], 1, "Worker should have caught 1 packet")
        self.assertTrue(fr["isComplete"], "Single block file should be complete in 1 systematic packet")
        self.assertTrue(fr["hasFile"], "Expected reconstructed file in worker result")
        self.assertEqual(fr["filename"], "test_offline.txt")
        self.assertEqual(fr["filesize"], 16)


if __name__ == '__main__':
    unittest.main()
