"""
ChromaBeam Luby Transform (LT) Fountain Code Tests
Verifies 100% lossless reconstruction with out-of-order arrival and high packet drop rates.
"""
import unittest
import os
import sys
import random

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.fountain import LTEncoder, LTDecoder, Mulberry32, get_droplet_indices


class TestFountainCodes(unittest.TestCase):
    def test_mulberry32_prng_determinism(self):
        prng1 = Mulberry32(1337)
        prng2 = Mulberry32(1337)

        vals1 = [prng1.next_uint32() for _ in range(50)]
        vals2 = [prng2.next_uint32() for _ in range(50)]
        self.assertEqual(vals1, vals2)

    def test_systematic_decoding_instant(self):
        """Under perfect zero-loss transmission, systematic frames decode in exactly K packets."""
        original_data = b"Hello, Henny! Ultra-fast optical streaming is working flawlessly! \xf0\x9f\x9a\x80\xe2\x9c\xa8" * 10
        block_size = 64

        encoder = LTEncoder(original_data, block_size=block_size)
        decoder = LTDecoder(encoder.K, block_size=block_size, total_filesize=len(original_data))

        # Send exact systematic sequence [0, K-1]
        for seed in range(encoder.K):
            degree, indices, payload = encoder.generate_droplet(seed)
            self.assertEqual(degree, 1)
            self.assertEqual(indices, [seed])
            decoder.add_droplet(seed, payload)

        self.assertTrue(decoder.is_complete)
        rebuilt = decoder.reconstruct_data()
        self.assertEqual(rebuilt, original_data)

    def test_lossy_fountain_channel_reconstruction(self):
        """Simulate severe channel loss (40% packet drops + random arrival order)."""
        original_data = os.urandom(128 * 1024)  # 128 KB test file
        block_size = 256

        encoder = LTEncoder(original_data, block_size=block_size)
        decoder = LTDecoder(encoder.K, block_size=block_size, total_filesize=len(original_data))

        # Generate stream of droplets
        droplet_pool = []
        # Generate up to 2.0x packets
        for seed in range(int(encoder.K * 2.0)):
            _, _, payload = encoder.generate_droplet(seed)
            droplet_pool.append((seed, payload))

        # Simulate harsh optical conditions: 40% packet drop + shuffle
        random.seed(42)
        random.shuffle(droplet_pool)
        # Drop 40%
        received_droplets = droplet_pool[:int(len(droplet_pool) * 0.6)]

        for seed, payload in received_droplets:
            if decoder.add_droplet(seed, payload):
                break

        self.assertTrue(decoder.is_complete, f"Solver should complete. Progress: {decoder.get_progress():.1%}")
        rebuilt = decoder.reconstruct_data()
        self.assertEqual(rebuilt, original_data, "Reconstructed file must match 100% byte-for-byte!")


if __name__ == '__main__':
    unittest.main()
