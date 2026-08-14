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


if __name__ == '__main__':
    unittest.main()
