"""
Empirical Adversarial Test Suite 3: Auto-Density Sweep Under Rapid Mode & Density Switching
Author: Challenger 2 (Milestone 5 Acceptance Gate)
"""

import os
import sys
import json
import random
import subprocess
import unittest
import numpy as np
import cv2

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

from core.protocol import pack_packet, unpack_packet, pack_file_metadata
from core.color_matrix import (
    ColorMatrixLayout,
    bytes_to_color_grid,
    MODE_1BIT_BW,
    MODE_2BIT_4COLOR,
    MODE_3BIT_8COLOR
)
from core.fountain import LTEncoder
from desktop_receiver.receiver_gui import ChromaBeamReceiver


class TestAutoDensityRapidModeSwitching(unittest.TestCase):
    def _create_frame(self, file_id: int, K: int, block_size: int, seed: int,
                      payload: bytes, size: int, mode: int, rot_deg: int = 0) -> np.ndarray:
        layout = ColorMatrixLayout(grid_size=size, color_mode=mode)
        pkt = pack_packet(file_id, K, block_size, seed, payload)
        grid = bytes_to_color_grid(pkt, layout)

        upscaled = cv2.resize(grid, (512, 512), interpolation=cv2.INTER_NEAREST)
        bgr = cv2.cvtColor(upscaled, cv2.COLOR_RGB2BGR)

        # Margin canvas
        canvas = np.zeros((640, 640, 3), dtype=np.uint8) + 40
        canvas[64:576, 64:576] = bgr

        if rot_deg == 90:
            canvas = cv2.rotate(canvas, cv2.ROTATE_90_CLOCKWISE)
        elif rot_deg == 180:
            canvas = cv2.rotate(canvas, cv2.ROTATE_180)
        elif rot_deg == 270:
            canvas = cv2.rotate(canvas, cv2.ROTATE_90_COUNTERCLOCKWISE)

        return canvas

    def test_python_receiver_rapid_mode_switching_and_stream_abort(self):
        """
        Adversarial Test: Desktop Receiver Auto-Density Sweep
        Scenario:
        1. Sender streams partial File A (File ID 10) in 32x32 Potato (1-bit).
        2. Sender suddenly changes mid-stream to 64x64 Turbo (3-bit) rotated 90° for File A.
        3. Sender aborts File A and transmits full File B (File ID 20) in 48x48 Balanced (2-bit) with rapid random mode hopping per packet!
        """
        receiver = ChromaBeamReceiver(grid_size=None, auto_density=True)

        # 1. Partial File A (32x32, Mode 0)
        file_a_data = b"Incomplete File A stream before mode switch"
        meta_a = pack_file_metadata("file_a.txt", len(file_a_data), "text/plain")
        stream_a = meta_a + file_a_data
        enc_a = LTEncoder(stream_a, block_size=32)

        # Process 1 droplet of File A in 32x32 Potato
        _, _, p0 = enc_a.generate_droplet(0)
        frame_a0 = self._create_frame(10, enc_a.K, 32, 0, p0, size=32, mode=MODE_1BIT_BW, rot_deg=0)
        _, stats_a0 = receiver.process_frame(frame_a0)
        self.assertTrue(stats_a0["locked"])
        self.assertEqual(stats_a0["density"], 32)
        self.assertEqual(stats_a0["mode"], MODE_1BIT_BW)
        self.assertEqual(stats_a0["packets"], 1)

        # 2. Next droplet of File A in 64x64 Turbo (3-bit) rotated 90°
        _, _, p1 = enc_a.generate_droplet(1)
        frame_a1 = self._create_frame(10, enc_a.K, 32, 1, p1, size=64, mode=MODE_3BIT_8COLOR, rot_deg=90)
        _, stats_a1 = receiver.process_frame(frame_a1)
        self.assertTrue(stats_a1["locked"], "Receiver failed to adapt when transmitter changed density 32->64 and mode 0->2 mid-stream")
        self.assertEqual(stats_a1["density"], 64)
        self.assertEqual(stats_a1["mode"], MODE_3BIT_8COLOR)
        self.assertEqual(stats_a1["packets"], 2)

        # 3. Sender ABORTS and switches to File B (File ID 20, 48x48 Balanced, 2-bit)
        file_b_data = b"Secret File B transmission that MUST succeed 100% losslessly under rapid mode switching!"
        meta_b = pack_file_metadata("file_b.txt", len(file_b_data), "text/plain")
        stream_b = meta_b + file_b_data
        enc_b = LTEncoder(stream_b, block_size=24)
        K_b = enc_b.K

        # Stream File B with RAPID RANDOM MODE & DENSITY SWITCHING on every single droplet!
        modes_and_densities = [
            (32, MODE_1BIT_BW, 0),
            (48, MODE_2BIT_4COLOR, 90),
            (64, MODE_3BIT_8COLOR, 180),
            (48, MODE_1BIT_BW, 270),
            (32, MODE_2BIT_4COLOR, 0),
            (64, MODE_1BIT_BW, 90),
            (48, MODE_3BIT_8COLOR, 180)
        ]

        received_packets_b = 0
        for seed in range(K_b * 3):
            cfg = modes_and_densities[seed % len(modes_and_densities)]
            grid_size, color_mode, rot = cfg
            _, _, p_b = enc_b.generate_droplet(seed)
            frame_b = self._create_frame(20, K_b, 24, seed, p_b, size=grid_size, mode=color_mode, rot_deg=rot)
            _, stats_b = receiver.process_frame(frame_b)

            self.assertTrue(stats_b["locked"], f"Receiver lost lock during rapid mode hopping at seed {seed}, cfg={cfg}")
            if stats_b["complete"]:
                break

        self.assertTrue(receiver.complete, f"Receiver failed to complete File B under rapid mode hopping! Progress: {receiver.decoder.get_progress():.1%}")
        reconstructed = receiver.decoder.reconstruct_data()
        self.assertIsNotNone(reconstructed)
        self.assertEqual(reconstructed, stream_b)

    def test_js_worker_rapid_mode_switching_adversarial(self):
        """
        Adversarial Test: JavaScript Web Worker (scanner_worker.js) under rapid mode switching
        Verifies that workerLockedConfig unlocks immediately when format changes without stalling the decoder.
        """
        js_fountain_path = os.path.join(PROJECT_ROOT, "web", "fountain.js")
        js_protocol_path = os.path.join(PROJECT_ROOT, "web", "protocol.js")
        js_matrix_path = os.path.join(PROJECT_ROOT, "web", "matrix.js")
        js_vision_path = os.path.join(PROJECT_ROOT, "web", "vision_engine.js")
        js_worker_path = os.path.join(PROJECT_ROOT, "web", "scanner_worker.js")

        test_script = f"""
        const fs = require('fs');
        const path = require('path');
        const vm = require('vm');

        const fountainCode = fs.readFileSync({json.dumps(js_fountain_path)}, 'utf8');
        const protocolCode = fs.readFileSync({json.dumps(js_protocol_path)}, 'utf8');
        const matrixCode = fs.readFileSync({json.dumps(js_matrix_path)}, 'utf8');
        const visionCode = fs.readFileSync({json.dumps(js_vision_path)}, 'utf8');
        const workerCode = fs.readFileSync({json.dumps(js_worker_path)}, 'utf8');

        const postedMessages = [];
        const sandbox = {{
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

        vm.createContext(sandbox);
        vm.runInContext(fountainCode + '\\n' + protocolCode + '\\n' + matrixCode + '\\n' + visionCode + '\\n' + workerCode, sandbox);

        const onmessage = sandbox.self.onmessage;

        // Reset session
        onmessage({{ data: {{ type: 'reset' }} }});
        postedMessages.shift(); // resetAck

        // Helper to render synthetic frame
        function renderFrame(gridSize, colorMode, rotDeg, packetBytes) {{
            const layout = new sandbox.JSColorMatrixLayout(gridSize, colorMode);
            let gridIndices = sandbox.bytesToGridIndices(packetBytes, layout);

            // Rotate grid if needed
            if (rotDeg === 90) {{
                const rot = Array.from({{ length: gridSize }}, () => new Uint8Array(gridSize));
                for (let r = 0; r < gridSize; r++) for (let c = 0; c < gridSize; c++) rot[c][gridSize - 1 - r] = gridIndices[r][c];
                gridIndices = rot;
            }} else if (rotDeg === 180) {{
                const rot = Array.from({{ length: gridSize }}, () => new Uint8Array(gridSize));
                for (let r = 0; r < gridSize; r++) for (let c = 0; c < gridSize; c++) rot[gridSize - 1 - r][gridSize - 1 - c] = gridIndices[r][c];
                gridIndices = rot;
            }}

            const cell = 6;
            const ox = 32, oy = 32;
            const matrixDim = gridSize * cell;
            const width = matrixDim + 64;
            const height = matrixDim + 64;
            const imgBuffer = new ArrayBuffer(width * height * 4);
            const imgData = new Uint8ClampedArray(imgBuffer);
            imgData.fill(0);

            const palette = layout.palette;
            for (let r = 0; r < gridSize; r++) {{
                for (let c = 0; c < gridSize; c++) {{
                    const colorIdx = gridIndices[r][c];
                    const [red, green, blue] = palette[colorIdx];
                    for (let dy = 0; dy < cell; dy++) {{
                        for (let dx = 0; dx < cell; dx++) {{
                            const px = ox + c * cell + dx;
                            const py = oy + r * cell + dy;
                            const idx = (py * width + px) * 4;
                            imgData[idx] = red;
                            imgData[idx + 1] = green;
                            imgData[idx + 2] = blue;
                            imgData[idx + 3] = 255;
                        }}
                    }}
                }}
            }}

            return {{ imgBuffer, width, height, ox, oy, matrixDim }};
        }}

        // Send 3 frames with switching modes:
        // Frame 1: 32x32 Potato (Mode 0, 0°)
        const payload1 = new Uint8Array([1, 2, 3, 4]);
        const pkt1 = sandbox.packPacket(77, 3, 4, 0, payload1);
        const f1 = renderFrame(32, 0, 0, pkt1);
        onmessage({{ data: {{ type: 'processFrame', buffer: f1.imgBuffer, width: f1.width, height: f1.height, guideRect: {{ x: f1.ox, y: f1.oy, w: f1.matrixDim, h: f1.matrixDim }} }} }});
        const res1 = postedMessages.shift();

        // Frame 2: 48x48 Balanced (Mode 1, 90°)
        const payload2 = new Uint8Array([5, 6, 7, 8]);
        const pkt2 = sandbox.packPacket(77, 3, 4, 1, payload2);
        const f2 = renderFrame(48, 1, 90, pkt2);
        onmessage({{ data: {{ type: 'processFrame', buffer: f2.imgBuffer, width: f2.width, height: f2.height, guideRect: {{ x: f2.ox, y: f2.oy, w: f2.matrixDim, h: f2.matrixDim }} }} }});
        const res2 = postedMessages.shift();

        // Frame 3: 48x48 Turbo (Mode 2, 180°)
        const payload3 = new Uint8Array([9, 10, 11, 12]);
        const pkt3 = sandbox.packPacket(77, 3, 4, 2, payload3);
        const f3 = renderFrame(48, 2, 180, pkt3);
        onmessage({{ data: {{ type: 'processFrame', buffer: f3.imgBuffer, width: f3.width, height: f3.height, guideRect: {{ x: f3.ox, y: f3.oy, w: f3.matrixDim, h: f3.matrixDim }} }} }});
        const res3 = postedMessages.shift();

        console.log(JSON.stringify({{
            frame1: {{ locked: res1.locked, caught: res1.caught, configLabel: res1.configLabel }},
            frame2: {{ locked: res2.locked, caught: res2.caught, configLabel: res2.configLabel }},
            frame3: {{ locked: res3.locked, caught: res3.caught, configLabel: res3.configLabel, isComplete: res3.isComplete }}
        }}));
        """

        proc = subprocess.run(["node", "-e", test_script], capture_output=True, text=True, check=True)
        res = json.loads(proc.stdout.strip().split("\n")[-1])

        self.assertTrue(res["frame1"]["locked"], f"Worker failed on frame 1 (32 Potato): {res['frame1']}")
        self.assertEqual(res["frame1"]["caught"], 1)

        self.assertTrue(res["frame2"]["locked"], f"Worker failed on frame 2 (48 Balanced 90°): {res['frame2']}")
        self.assertEqual(res["frame2"]["caught"], 2)

        self.assertTrue(res["frame3"]["locked"], f"Worker failed on frame 3 (48 Turbo 180°): {res['frame3']}")
        self.assertEqual(res["frame3"]["caught"], 3)
        self.assertTrue(res["frame3"]["isComplete"], "3 systematic packets should solve 3-block file in worker")


if __name__ == '__main__':
    unittest.main()
