"""
ChromaBeam Offline HTML Bundler & Web Worker Inlining Tests
Validates M3 deliverables:
1. Offline HTML single-file compilation with zero external dependencies
2. Inlined background Web Worker script embedding
3. Dynamic Worker blob instantiation and processFrameInline fallback decoding
4. Multi-mode and multi-orientation inline decoding
"""

import unittest
import os
import sys
import subprocess
import json
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import build_offline_html


class TestOfflineBundlerAndWorkerInlining(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure fresh build of offline HTML
        build_offline_html.bundle()
        cls.html_path = os.path.join(os.path.dirname(__file__), '..', 'chromabeam_offline.html')

    def test_offline_html_structure_and_dependencies(self):
        """Verifies chromabeam_offline.html is 100% self-contained with no external css/js links."""
        self.assertTrue(os.path.exists(self.html_path), "chromabeam_offline.html does not exist")
        file_size = os.path.getsize(self.html_path)
        self.assertGreater(file_size, 50000, f"Bundled file is suspiciously small: {file_size} bytes")

        with open(self.html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # No external script or stylesheet links
        self.assertNotIn('<script src="', content, "Offline HTML contains external <script src>")
        self.assertNotIn('<link rel="stylesheet"', content, "Offline HTML contains external <link rel='stylesheet'>")

        # Must have inline <style> and <script id="scanner-worker-src" type="text/plain">
        self.assertIn('<style>', content, "Offline HTML missing inline <style>")
        self.assertIn('id="scanner-worker-src"', content, "Offline HTML missing scanner-worker-src script element")
        self.assertIn('type="text/plain"', content, "scanner-worker-src must have type='text/plain'")

    def test_bundled_worker_script_completeness_and_syntax(self):
        """Verifies embedded worker code contains all required dependencies and is valid JS."""
        with open(self.html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Extract worker source from <script id="scanner-worker-src" ...>
        soup = BeautifulSoup(content, 'html.parser')
        worker_elem = soup.find('script', {'id': 'scanner-worker-src'})
        self.assertIsNotNone(worker_elem, "Could not find script#scanner-worker-src in DOM")
        worker_code = worker_elem.string

        self.assertIn('class LTDecoder', worker_code, "Worker script bundle missing LTDecoder")
        self.assertIn('class JSColorMatrixLayout', worker_code, "Worker script bundle missing JSColorMatrixLayout")
        self.assertIn('function detectOpticalQuad', worker_code, "Worker script bundle missing detectOpticalQuad")
        self.assertIn('function sampleQuadGrid', worker_code, "Worker script bundle missing sampleQuadGrid")
        self.assertIn('function decodeGridMultiOrientation', worker_code, "Worker script bundle missing decodeGridMultiOrientation")

        # Verify worker code parses cleanly in Node.js
        test_script = f"""
        const vm = require('vm');
        const code = {json.dumps(worker_code)};
        const sandbox = {{
            console,
            performance,
            self: {{
                postMessage: () => {{}},
                onmessage: null
            }},
            Uint8Array,
            Uint32Array,
            Uint8ClampedArray,
            Math,
            Array
        }};
        vm.createContext(sandbox);
        vm.runInContext(code + "\\nthis.hasOnMessage = (typeof self.onmessage === 'function'); this.hasDecoder = (typeof LTDecoder !== 'undefined'); this.hasLayout = (typeof JSColorMatrixLayout !== 'undefined');", sandbox);
        console.log(JSON.stringify({{
            hasOnMessage: sandbox.hasOnMessage,
            hasDecoder: sandbox.hasDecoder,
            hasLayout: sandbox.hasLayout
        }}));
        """
        res = subprocess.run(["node", "-"], input=test_script, capture_output=True, text=True, check=True)
        out = json.loads(res.stdout.strip().split("\n")[-1])
        self.assertTrue(out["hasOnMessage"], "Worker failed to register self.onmessage")
        self.assertTrue(out["hasDecoder"], "Worker did not define LTDecoder in scope")
        self.assertTrue(out["hasLayout"], "Worker did not define JSColorMatrixLayout in scope")

    def test_inline_processing_fallback_decoding(self):
        """Verifies receiver.js processFrameInline functions properly without Web Workers."""
        test_script = """
        const fs = require('fs');
        const path = require('path');
        const vm = require('vm');

        // Load dependencies into global sandbox
        const fountainCode = fs.readFileSync(path.join(__dirname, '..', 'web', 'fountain.js'), 'utf8');
        const protocolCode = fs.readFileSync(path.join(__dirname, '..', 'web', 'protocol.js'), 'utf8');
        const matrixCode = fs.readFileSync(path.join(__dirname, '..', 'web', 'matrix.js'), 'utf8');
        const visionCode = fs.readFileSync(path.join(__dirname, '..', 'web', 'vision_engine.js'), 'utf8');
        const receiverCode = fs.readFileSync(path.join(__dirname, '..', 'web', 'receiver.js'), 'utf8');

        const sandbox = {
            console,
            performance,
            Math,
            Uint8Array,
            Uint32Array,
            Uint8ClampedArray,
            Array,
            window: {},
            document: {
                getElementById: () => null
            }
        };
        vm.createContext(sandbox);
        vm.runInContext(
            fountainCode + '\\n' +
            protocolCode + '\\n' +
            matrixCode + '\\n' +
            visionCode + '\\n' +
            receiverCode + '\\n' +
            'this.packPacket = packPacket; this.JSColorMatrixLayout = JSColorMatrixLayout; this.bytesToGridIndices = bytesToGridIndices; this.processFrameInline = processFrameInline; this.setReceiverRunning = (v) => { receiverRunning = v; }; this.getPacketsCaught = () => receiverPacketsCaught; this.getIsLocked = () => receiverIsLocked; this.getLastQuad = () => receiverLastQuad;',
            sandbox
        );

        sandbox.setReceiverRunning(true);

        // Generate a synthetic test packet and 32x32 Potato (B&W) grid
        const payload = new Uint8Array([10, 20, 30, 40, 50, 60, 70, 80]);
        const packet = sandbox.packPacket(101, 1, payload.length, 1, payload);
        const layout = new sandbox.JSColorMatrixLayout(32, 0);
        const gridIndices = sandbox.bytesToGridIndices(packet, layout);

        // Render synthetic image buffer
        const ox = 20, oy = 20, cell = 4;
        const matrixSize = 32 * cell; // 128px
        const width = matrixSize + 40;
        const height = matrixSize + 40;
        const imgData = {
            data: new Uint8ClampedArray(width * height * 4),
            width,
            height
        };
        imgData.data.fill(0); // Dark background

        for (let r = 0; r < 32; r++) {
            for (let c = 0; c < 32; c++) {
                const colorVal = (gridIndices[r][c] === 1) ? 255 : 0;
                for (let dy = 0; dy < cell; dy++) {
                    for (let dx = 0; dx < cell; dx++) {
                        const px = ox + c * cell + dx;
                        const py = oy + r * cell + dy;
                        const idx = (py * width + px) * 4;
                        imgData.data[idx] = colorVal;
                        imgData.data[idx + 1] = colorVal;
                        imgData.data[idx + 2] = colorVal;
                        imgData.data[idx + 3] = 255;
                    }
                }
            }
        }

        // Test processFrameInline with framing guideRect
        sandbox.processFrameInline(imgData, width, height, { x: ox, y: oy, w: matrixSize, h: matrixSize });

        console.log(JSON.stringify({
            locked: sandbox.getIsLocked(),
            caught: sandbox.getPacketsCaught(),
            hasQuad: sandbox.getLastQuad() !== null
        }));
        """;

        res = subprocess.run(["node", "-e", test_script, "--", ""], cwd=os.path.dirname(__file__),
                             capture_output=True, text=True, check=True)
        out = json.loads(res.stdout.strip().split("\n")[-1])
        self.assertTrue(out["locked"], "processFrameInline failed to lock and decode valid synthetic grid")
        self.assertEqual(out["caught"], 1, "Expected caught packets to be 1")
        self.assertTrue(out["hasQuad"], "Expected detected quadrilateral to be stored")

    def test_inline_processing_multi_mode_and_rotation(self):
        """Verifies processFrameInline decodes across 4-color mode and 90° rotation."""
        test_script = """
        const fs = require('fs');
        const path = require('path');
        const vm = require('vm');

        const fountainCode = fs.readFileSync(path.join(__dirname, '..', 'web', 'fountain.js'), 'utf8');
        const protocolCode = fs.readFileSync(path.join(__dirname, '..', 'web', 'protocol.js'), 'utf8');
        const matrixCode = fs.readFileSync(path.join(__dirname, '..', 'web', 'matrix.js'), 'utf8');
        const visionCode = fs.readFileSync(path.join(__dirname, '..', 'web', 'vision_engine.js'), 'utf8');
        const receiverCode = fs.readFileSync(path.join(__dirname, '..', 'web', 'receiver.js'), 'utf8');

        const sandbox = {
            console,
            performance,
            Math,
            Uint8Array,
            Uint32Array,
            Uint8ClampedArray,
            Array,
            window: {},
            document: {
                getElementById: () => null
            }
        };
        vm.createContext(sandbox);
        vm.runInContext(
            fountainCode + '\\n' +
            protocolCode + '\\n' +
            matrixCode + '\\n' +
            visionCode + '\\n' +
            receiverCode + '\\n' +
            'this.packPacket = packPacket; this.JSColorMatrixLayout = JSColorMatrixLayout; this.bytesToGridIndices = bytesToGridIndices; this.processFrameInline = processFrameInline; this.setReceiverRunning = (v) => { receiverRunning = v; }; this.getPacketsCaught = () => receiverPacketsCaught; this.getIsLocked = () => receiverIsLocked; this.getLastConfigLabel = () => receiverLastConfigLabel;',
            sandbox
        );

        sandbox.setReceiverRunning(true);

        // Test Mode 1 (4-Color, 32x32) rotated 90 degrees clockwise
        const payload = new Uint8Array([99, 88, 77, 66, 55, 44, 33, 22]);
        const packet = sandbox.packPacket(202, 1, payload.length, 1, payload);
        const layout = new sandbox.JSColorMatrixLayout(32, 1);
        const origGrid = sandbox.bytesToGridIndices(packet, layout);

        // Rotate grid 90 deg clockwise
        const N = 32;
        const rotGrid = Array.from({ length: N }, () => new Uint8Array(N));
        for (let r = 0; r < N; r++) {
            for (let c = 0; c < N; c++) {
                rotGrid[c][N - 1 - r] = origGrid[r][c];
            }
        }

        // Render RGB image buffer
        const ox = 16, oy = 16, cell = 4;
        const matrixSize = N * cell;
        const width = matrixSize + 32;
        const height = matrixSize + 32;
        const imgData = {
            data: new Uint8ClampedArray(width * height * 4),
            width,
            height
        };
        imgData.data.fill(0);

        const palette = layout.palette;
        for (let r = 0; r < N; r++) {
            for (let c = 0; c < N; c++) {
                const colorIdx = rotGrid[r][c];
                const [red, green, blue] = palette[colorIdx];
                for (let dy = 0; dy < cell; dy++) {
                    for (let dx = 0; dx < cell; dx++) {
                        const px = ox + c * cell + dx;
                        const py = oy + r * cell + dy;
                        const idx = (py * width + px) * 4;
                        imgData.data[idx] = red;
                        imgData.data[idx + 1] = green;
                        imgData.data[idx + 2] = blue;
                        imgData.data[idx + 3] = 255;
                    }
                }
            }
        }

        sandbox.processFrameInline(imgData, width, height, { x: ox, y: oy, w: matrixSize, h: matrixSize });

        console.log(JSON.stringify({
            locked: sandbox.getIsLocked(),
            caught: sandbox.getPacketsCaught(),
            configLabel: sandbox.getLastConfigLabel()
        }));
        """;

        res = subprocess.run(["node", "-e", test_script, "--", ""], cwd=os.path.dirname(__file__),
                             capture_output=True, text=True, check=True)
        out = json.loads(res.stdout.strip().split("\n")[-1])
        self.assertTrue(out["locked"], "Failed to lock 4-color rotated matrix")
        self.assertEqual(out["caught"], 1, "Expected caught packets to be 1")
        self.assertIn("270° rot", out["configLabel"], "Expected 270° un-rotation to be detected for 90° rotated grid")


if __name__ == '__main__':
    unittest.main()
