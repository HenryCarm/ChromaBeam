"""
ChromaBeam Protocol Unit Tests
"""
import unittest
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.protocol import (
    pack_packet,
    unpack_packet,
    pack_file_metadata,
    unpack_file_metadata,
    MAGIC_INT
)


class TestChromaBeamProtocol(unittest.TestCase):
    def test_pack_and_unpack_packet_valid(self):
        file_id = 42
        total_blocks = 120
        block_size = 256
        seed = 987654321
        payload = os.urandom(block_size)

        packed = pack_packet(file_id, total_blocks, block_size, seed, payload)
        self.assertGreater(len(packed), block_size)

        result = unpack_packet(packed)
        self.assertIsNotNone(result)
        header, unpacked_payload = result

        self.assertEqual(header.file_id, file_id)
        self.assertEqual(header.total_blocks, total_blocks)
        self.assertEqual(header.block_size, block_size)
        self.assertEqual(header.seed, seed)
        self.assertEqual(unpacked_payload, payload)

    def test_unpack_corrupt_crc(self):
        file_id = 1
        total_blocks = 10
        block_size = 64
        seed = 123
        payload = b"A" * block_size

        packed = bytearray(pack_packet(file_id, total_blocks, block_size, seed, payload))
        # Corrupt one byte in payload
        packed[15] ^= 0xFF

        result = unpack_packet(bytes(packed))
        self.assertIsNone(result, "Corrupt payload CRC must be rejected")

    def test_pack_unpack_metadata(self):
        filename = "secret_dataset.zip"
        filesize = 1048576
        mime_type = "application/zip"

        meta_bytes = pack_file_metadata(filename, filesize, mime_type)
        result = unpack_file_metadata(meta_bytes)
        self.assertIsNotNone(result)
        un_name, un_size, un_mime = result

        self.assertEqual(un_name, filename)
        self.assertEqual(un_size, filesize)
        self.assertEqual(un_mime, mime_type)


if __name__ == '__main__':
    unittest.main()
