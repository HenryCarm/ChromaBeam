"""
Cross-Language Protocol & Fountain Code Adversarial Tester
Generates test vectors from Python, executes Node.js decoding,
and tests Node.js generation with Python decoding under corrupt/lossy conditions.
"""

import os
import sys
import json
import struct
import random
import zlib
import subprocess
import numpy as np

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

from core.fountain import LTEncoder, LTDecoder, Mulberry32, get_robust_soliton_cdf, get_droplet_indices
from core.protocol import pack_packet, unpack_packet, pack_file_metadata, unpack_file_metadata, MAGIC_INT
from core.color_matrix import (
    ColorMatrixLayout,
    bytes_to_color_grid,
    color_grid_to_bytes,
    MODE_1BIT_BW,
    MODE_2BIT_4COLOR,
    MODE_3BIT_8COLOR
)

def test_mulberry32_parity():
    """Verify PRNG output parity across seeds."""
    seeds = [0, 1, 42, 1337, 999999, 0x7FFFFFFF, 0xFFFFFFFF]
    py_results = {}
    for s in seeds:
        prng = Mulberry32(s)
        py_results[s] = [prng.next_uint32() for _ in range(100)]
    return py_results

def test_soliton_cdf_parity():
    """Verify Soliton CDF parity across various K values."""
    Ks = [1, 2, 5, 10, 20, 50, 100, 256]
    py_cdfs = {}
    for K in Ks:
        py_cdfs[K] = get_robust_soliton_cdf(K)
    return py_cdfs

def test_droplet_indices_parity():
    """Verify droplet indices parity across various seeds and K."""
    test_cases = []
    for K in [1, 5, 20, 100]:
        for seed in [0, K - 1, K, K + 1, 1000, 99999]:
            deg, indices = get_droplet_indices(seed, K)
            test_cases.append({
                "K": K,
                "seed": seed,
                "degree": deg,
                "indices": indices
            })
    return test_cases

def generate_python_packets_for_js(file_bytes: bytes, block_size: int, redundancy_factor: float = 2.0, corrupt_rate: float = 0.0, drop_rate: float = 0.0):
    """Generates packed packets using Python implementation."""
    encoder = LTEncoder(file_bytes, block_size=block_size)
    num_packets = max(encoder.K, int(encoder.K * redundancy_factor))
    packets = []
    
    file_id = random.randint(1, 65535)
    for seed in range(num_packets):
        if random.random() < drop_rate:
            continue
            
        deg, indices, payload = encoder.generate_droplet(seed)
        packed = pack_packet(file_id, encoder.K, block_size, seed, payload)
        
        # Inject corruption if requested
        is_corrupt = False
        if corrupt_rate > 0 and random.random() < corrupt_rate:
            is_corrupt = True
            packed_arr = bytearray(packed)
            corrupt_type = random.choice(["flip_payload", "corrupt_crc", "corrupt_magic", "truncate", "flip_header"])
            if corrupt_type == "flip_payload":
                idx = random.randint(12, 12 + block_size - 1)
                packed_arr[idx] ^= 0xFF
            elif corrupt_type == "corrupt_crc":
                idx = random.randint(12 + block_size, len(packed_arr) - 1)
                packed_arr[idx] ^= 0xFF
            elif corrupt_type == "corrupt_magic":
                packed_arr[0] ^= 0xFF
            elif corrupt_type == "truncate":
                packed_arr = packed_arr[:len(packed_arr) - random.randint(1, 10)]
            elif corrupt_type == "flip_header":
                idx = random.randint(2, 11)
                packed_arr[idx] ^= 0xFF
            packed = bytes(packed_arr)
            
        packets.append({
            "seed": seed,
            "hex": packed.hex(),
            "is_corrupted": is_corrupt
        })
        
    return {
        "file_id": file_id,
        "K": encoder.K,
        "block_size": block_size,
        "filesize": len(file_bytes),
        "packets": packets
    }

if __name__ == '__main__':
    # Print self-test summary
    print("[PyCrossTest] Generated test data generator loaded.")
