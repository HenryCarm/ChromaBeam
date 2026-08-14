"""
ChromaBeam End-to-End Optical & Color Matrix Tests
"""
import unittest
import os
import sys
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.color_matrix import (
    ColorMatrixLayout,
    bytes_to_color_grid,
    color_grid_to_bytes,
    upscale_grid_for_display,
    MODE_1BIT_BW,
    MODE_2BIT_4COLOR,
    MODE_3BIT_8COLOR
)
from core.protocol import pack_packet, unpack_packet


class TestColorMatrixAndEndToEnd(unittest.TestCase):
    def test_mode0_bw_lossless(self):
        layout = ColorMatrixLayout(grid_size=32, color_mode=MODE_1BIT_BW)
        payload = os.urandom(layout.max_payload_bytes - 20)
        packet = pack_packet(file_id=1, total_blocks=10, block_size=len(payload), seed=1, payload=payload)

        grid = bytes_to_color_grid(packet, layout)
        self.assertEqual(grid.shape, (32, 32, 3))

        recovered_bytes = color_grid_to_bytes(grid, layout)
        result = unpack_packet(recovered_bytes)
        self.assertIsNotNone(result)
        header, unpacked_payload = result
        self.assertEqual(unpacked_payload, payload)

    def test_mode1_4color_lossless(self):
        layout = ColorMatrixLayout(grid_size=48, color_mode=MODE_2BIT_4COLOR)
        payload = os.urandom(layout.max_payload_bytes - 20)
        packet = pack_packet(file_id=2, total_blocks=20, block_size=len(payload), seed=2, payload=payload)

        grid = bytes_to_color_grid(packet, layout)
        recovered_bytes = color_grid_to_bytes(grid, layout)
        result = unpack_packet(recovered_bytes)
        self.assertIsNotNone(result)
        header, unpacked_payload = result
        self.assertEqual(unpacked_payload, payload)

    def test_mode2_8color_lossless(self):
        layout = ColorMatrixLayout(grid_size=64, color_mode=MODE_3BIT_8COLOR)
        payload = os.urandom(layout.max_payload_bytes - 20)
        packet = pack_packet(file_id=3, total_blocks=30, block_size=len(payload), seed=3, payload=payload)

        grid = bytes_to_color_grid(packet, layout)
        recovered_bytes = color_grid_to_bytes(grid, layout)
        result = unpack_packet(recovered_bytes)
        self.assertIsNotNone(result)
        header, unpacked_payload = result
        self.assertEqual(unpacked_payload, payload)


    def test_anchor_standard_and_calibration_swatches(self):
        """Verifies 1:1:1:1:1 anchor concentric ratio, standardized White centers, and top calibration swatches."""
        for mode in [MODE_1BIT_BW, MODE_2BIT_4COLOR, MODE_3BIT_8COLOR]:
            for size in [32, 48, 64]:
                layout = ColorMatrixLayout(grid_size=size, color_mode=mode)
                grid = np.zeros((size, size, 3), dtype=np.uint8)
                layout.render_anchors(grid)

                s = 5
                white = np.array([255, 255, 255], dtype=np.uint8)
                black = np.array([0, 0, 0], dtype=np.uint8)

                # 1. Verify 4 anchor centers are all standardized White
                center_coords = [(2, 2), (2, size - 3), (size - 3, size - 3), (size - 3, 2)]
                for r, c in center_coords:
                    np.testing.assert_array_equal(grid[r, c], white, f"Center at ({r}, {c}) must be White for mode {mode}")

                # 2. Verify 1:1:1:1:1 nested concentric structure for each corner anchor
                corners = [
                    (0, 0),                 # TL
                    (0, size - s),          # TR
                    (size - s, size - s),   # BR
                    (size - s, 0)           # BL
                ]
                for r0, c0 in corners:
                    sub = grid[r0:r0+s, c0:c0+s]
                    # Outer border ring must be White
                    for r in range(s):
                        for c in range(s):
                            if r == 0 or r == s - 1 or c == 0 or c == s - 1:
                                np.testing.assert_array_equal(sub[r, c], white)
                    # 3x3 ring must be Black
                    for r in range(1, s - 1):
                        for c in range(1, s - 1):
                            if r == 1 or r == s - 2 or c == 1 or c == s - 2:
                                np.testing.assert_array_equal(sub[r, c], black)
                    # Centroid (2, 2) must be White
                    np.testing.assert_array_equal(sub[2, 2], white)

                    # Check 1:1:1:1:1 cross-section horizontally and vertically
                    h_cross = [np.array_equal(sub[2, c], white) for c in range(s)]
                    v_cross = [np.array_equal(sub[r, 2], white) for r in range(s)]
                    self.assertEqual(h_cross, [True, False, True, False, True], "Horizontal 1:1:1:1:1 ratio mismatch")
                    self.assertEqual(v_cross, [True, False, True, False, True], "Vertical 1:1:1:1:1 ratio mismatch")

                # 3. Verify top calibration swatches
                if mode == MODE_3BIT_8COLOR:
                    expected_swatches = [
                        [0, 0, 0],        # K (Black)
                        [255, 0, 0],      # R (Red)
                        [0, 255, 0],      # G (Green)
                        [0, 0, 255],      # B (Blue)
                        [255, 255, 255]   # W (White)
                    ]
                    for i, exp in enumerate(expected_swatches):
                        np.testing.assert_array_equal(grid[0, 5 + i], np.array(exp, dtype=np.uint8),
                                                      f"Swatch {i} mismatch in 3-bit mode")
                elif mode == MODE_2BIT_4COLOR:
                    expected_swatches = [
                        [0, 0, 0],        # K
                        [255, 50, 50],    # R
                        [50, 255, 50],    # G
                        [255, 255, 255]   # W
                    ]
                    for i, exp in enumerate(expected_swatches):
                        np.testing.assert_array_equal(grid[0, 5 + i], np.array(exp, dtype=np.uint8),
                                                      f"Swatch {i} mismatch in 2-bit mode")
                elif mode == MODE_1BIT_BW:
                    expected_swatches = [
                        [0, 0, 0],
                        [255, 255, 255],
                        [0, 0, 0],
                        [255, 255, 255]
                    ]
                    for i, exp in enumerate(expected_swatches):
                        np.testing.assert_array_equal(grid[0, 5 + i], np.array(exp, dtype=np.uint8),
                                                      f"Swatch {i} mismatch in 1-bit mode")

                # 4. Verify canonical anchor_centers property
                c_norm = 2.5 / float(size)
                expected_centers = [
                    (c_norm, c_norm),
                    (1.0 - c_norm, c_norm),
                    (1.0 - c_norm, 1.0 - c_norm),
                    (c_norm, 1.0 - c_norm)
                ]
                self.assertEqual(layout.anchor_centers, expected_centers)

    def test_python_js_cross_compatibility(self):
        """Validates 100% bit-for-bit equivalence between Python and JS matrix layouts across modes and sizes."""
        import json
        import subprocess

        for mode in [MODE_1BIT_BW, MODE_2BIT_4COLOR, MODE_3BIT_8COLOR]:
            for size in [32, 48, 64]:
                py_layout = ColorMatrixLayout(size, mode)
                test_payload = os.urandom(py_layout.max_payload_bytes)
                py_grid_rgb = bytes_to_color_grid(test_payload, py_layout)

                dists = np.sum((py_grid_rgb[:, :, np.newaxis, :] - py_layout.palette[np.newaxis, np.newaxis, :, :]) ** 2, axis=3)
                py_indices = np.argmin(dists, axis=2)

                js_code = f"""
                const {{ JSColorMatrixLayout, bytesToGridIndices, gridIndicesToBytes }} = require("./web/matrix.js");
                const layout = new JSColorMatrixLayout({size}, {mode});
                const inputBytes = new Uint8Array({list(test_payload)});
                const jsGrid = bytesToGridIndices(inputBytes, layout);
                const jsDecoded = gridIndicesToBytes(jsGrid, layout);
                const pyGrid = {json.dumps(py_indices.tolist())};
                
                let gridsMatch = true;
                for (let r = 0; r < {size}; r++) {{
                    for (let c = 0; c < {size}; c++) {{
                        if (jsGrid[r][c] !== pyGrid[r][c]) {{
                            gridsMatch = false;
                            break;
                        }}
                    }}
                    if (!gridsMatch) break;
                }}
                
                let bytesMatch = (jsDecoded.length === inputBytes.length);
                if (bytesMatch) {{
                    for (let i = 0; i < inputBytes.length; i++) {{
                        if (jsDecoded[i] !== inputBytes[i]) {{
                            bytesMatch = false;
                            break;
                        }}
                    }}
                }}
                console.log(JSON.stringify({{ gridsMatch, bytesMatch }}));
                """

                res = subprocess.run(["node", "-e", js_code], capture_output=True, text=True, check=True)
                out = json.loads(res.stdout.strip().split("\n")[-1])
                self.assertTrue(out["gridsMatch"], f"Grids mismatch for mode={mode}, size={size}")
                self.assertTrue(out["bytesMatch"], f"Bytes mismatch for mode={mode}, size={size}")

                py_recovered = color_grid_to_bytes(py_grid_rgb, py_layout)
                self.assertEqual(py_recovered, test_payload, f"Python self-recovery failed for mode={mode}, size={size}")


if __name__ == '__main__':
    unittest.main()
