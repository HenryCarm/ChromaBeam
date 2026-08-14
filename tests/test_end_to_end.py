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
    upscale_grid_for_display
)
from core.protocol import pack_packet, unpack_packet


class TestColorMatrixAndEndToEnd(unittest.TestCase):
    def test_color_matrix_pack_unpack_lossless(self):
        layout = ColorMatrixLayout(grid_size=48)
        payload = os.urandom(layout.max_payload_bytes - 20)
        packet = pack_packet(file_id=101, total_blocks=50, block_size=len(payload), seed=777, payload=payload)

        # Synthesize RGB frame
        grid = bytes_to_color_grid(packet, layout)
        self.assertEqual(grid.shape, (48, 48, 3))
        self.assertEqual(grid.dtype, np.uint8)

        # Decode directly from grid
        recovered_bytes = color_grid_to_bytes(grid, layout)
        result = unpack_packet(recovered_bytes)
        self.assertIsNotNone(result)

        header, unpacked_payload = result
        self.assertEqual(header.file_id, 101)
        self.assertEqual(header.total_blocks, 50)
        self.assertEqual(header.seed, 777)
        self.assertEqual(unpacked_payload, payload)

    def test_upscaling(self):
        layout = ColorMatrixLayout(grid_size=48)
        grid = np.zeros((48, 48, 3), dtype=np.uint8)
        upscaled = upscale_grid_for_display(grid, target_resolution=480)
        self.assertEqual(upscaled.shape, (480, 480, 3))


if __name__ == '__main__':
    unittest.main()
