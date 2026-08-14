"""
Adversarial Stress Test: Luby Transform (LT) Fountain Code & High Packet Erasure
Tests decoder performance under severe packet loss (50% to 95%), burst dropouts,
out-of-order delivery, corrupted packets, and pure non-systematic fountain droplets.
"""

import sys
import os
import time
import math
import random
import numpy as np

PROJECT_ROOT = "/home/henry/Documents/Projects/Python/QR ChromaBeam"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.fountain import LTEncoder, LTDecoder, Mulberry32, get_droplet_indices
from core.protocol import pack_packet, unpack_packet


def run_fountain_erasure_stress_tests():
    print("=" * 70)
    print("STRESS TEST 4: Fountain Code Packet Erasure & GF(2) Incremental Solver")
    print("=" * 70)

    # 1. Packet Loss Rate Sweep (50%, 60%, 70%, 80%, 90%, 95%)
    print("\n--- 1. Packet Loss Sweep (Streaming Droplets) ---")
    loss_rates = [0.50, 0.60, 0.70, 0.80, 0.90, 0.95]
    file_sizes = [512, 4096, 16384, 65536] # 512B, 4KB, 16KB, 64KB
    block_size = 256

    for fsize in file_sizes:
        raw_data = os.urandom(fsize)
        encoder = LTEncoder(raw_data, block_size=block_size)
        K = encoder.K
        print(f"\n[Testing File Size: {fsize} bytes | K = {K} blocks | Block Size = {block_size} B]")

        for loss_rate in loss_rates:
            decoder = LTDecoder(K=K, block_size=block_size, total_filesize=fsize)
            seed = 0
            packets_sent = 0
            packets_received = 0
            rng = random.Random(42 + int(loss_rate * 100) + fsize)

            start_t = time.perf_counter()
            max_stream = K * 100 # safety limit
            while not decoder.is_complete and packets_sent < max_stream:
                degree, indices, payload = encoder.generate_droplet(seed)
                packets_sent += 1
                
                # Apply random packet loss
                if rng.random() >= loss_rate:
                    decoder.add_droplet(seed, payload)
                    packets_received += 1

                seed += 1

            solve_time_ms = (time.perf_counter() - start_t) * 1000.0
            reconstructed = decoder.reconstruct_data()
            success = (reconstructed == raw_data)
            overhead_ratio = packets_received / K if K > 0 else 1.0

            status = "PASSED" if success else "FAILED"
            print(f"  Loss: {loss_rate*100:2.0f}% | Sent: {packets_sent:5d} | Received: {packets_received:4d} (Overhead: {overhead_ratio:4.2f}x) | Time: {solve_time_ms:6.1f} ms | Status: {status}")

    # 2. Pure Non-Systematic Stream (0% Systematic Droplets Received)
    print("\n--- 2. Pure Non-Systematic Stream (100% of Systematic Packets Lost) ---")
    fsize = 8192
    raw_data = os.urandom(fsize)
    encoder = LTEncoder(raw_data, block_size=256)
    K = encoder.K

    decoder = LTDecoder(K=K, block_size=256, total_filesize=fsize)
    seed = K # Skip all seeds 0..K-1 (only send non-systematic fountain droplets)
    packets_received = 0
    start_t = time.perf_counter()

    while not decoder.is_complete and seed < K + 500:
        degree, indices, payload = encoder.generate_droplet(seed)
        decoder.add_droplet(seed, payload)
        packets_received += 1
        seed += 1

    solve_time_ms = (time.perf_counter() - start_t) * 1000.0
    reconstructed = decoder.reconstruct_data()
    success = (reconstructed == raw_data)
    overhead_ratio = packets_received / K
    print(f"Non-Systematic Recovery: Received={packets_received} droplets (K={K}, Overhead={overhead_ratio:.2f}x) | Time={solve_time_ms:.1f} ms | Success={success}")

    # 3. Burst Erasure Pattern (Harsh camera occlusion / blackout: 10 packets on / 40 packets dropped = 80% loss)
    print("\n--- 3. Burst Occlusion Stress (Periodic 10 on / 40 off bursts = 80% loss) ---")
    decoder = LTDecoder(K=K, block_size=256, total_filesize=fsize)
    seed = 0
    packets_sent = 0
    packets_received = 0

    while not decoder.is_complete and packets_sent < 5000:
        degree, indices, payload = encoder.generate_droplet(seed)
        packets_sent += 1

        if (packets_sent % 50) < 10:
            decoder.add_droplet(seed, payload)
            packets_received += 1

        seed += 1

    reconstructed = decoder.reconstruct_data()
    print(f"Burst Drop Recovery: Sent={packets_sent}, Received={packets_received} (Overhead={packets_received/K:.2f}x), Solved={reconstructed == raw_data}")

    # 4. Out-of-Order & Duplicate Droplets
    print("\n--- 4. Out-of-Order Delivery & Heavy Duplication (5x Duplicates) ---")
    decoder = LTDecoder(K=K, block_size=256, total_filesize=fsize)
    droplets = []
    for s in range(K + 15):
        _, _, p = encoder.generate_droplet(s)
        # Duplicate each droplet 5 times
        for _ in range(5):
            droplets.append((s, p))

    # Shuffle entirely randomly
    random.seed(999)
    random.shuffle(droplets)

    for s, p in droplets:
        decoder.add_droplet(s, p)

    reconstructed = decoder.reconstruct_data()
    print(f"Shuffled Duplicates Recovery: Total Droplets Fed={len(droplets)}, Solved={reconstructed == raw_data}")

    # 5. Robustness to Corrupted Droplets (Malformed payload length & corrupted data)
    print("\n--- 5. Malformed Payload Injection Robustness ---")
    decoder = LTDecoder(K=K, block_size=256, total_filesize=fsize)
    try:
        # Feed wrong size
        res1 = decoder.add_droplet(0, b"SHORT")
        print(f"Wrong Size Rejection: {res1 == False} (Handled gracefully)")
        # Feed None or invalid seed
        res2 = decoder.add_droplet(-1, b"\x00" * 256)
        print(f"Negative Seed Handled: {type(res2) is bool}")
    except Exception as e:
        print(f"CRASH on malformed injection: {e}")

    # 6. Monte Carlo Overhead Distribution (100 runs)
    print("\n--- 6. Monte Carlo Overhead Distribution Analysis (100 trials, K=32) ---")
    overheads = []
    for trial in range(100):
        test_data = os.urandom(8192)
        enc = LTEncoder(test_data, block_size=256)
        dec = LTDecoder(K=enc.K, block_size=256, total_filesize=8192)
        
        # Simulate 70% packet erasure
        s = 0
        rec = 0
        rng_trial = random.Random(trial * 1000 + 777)
        while not dec.is_complete:
            _, _, pay = enc.generate_droplet(s)
            if rng_trial.random() >= 0.70:
                dec.add_droplet(s, pay)
                rec += 1
            s += 1
        overheads.append(rec / enc.K)

    print(f"Mean Overhead Ratio: {np.mean(overheads):.3f}x")
    print(f"Min Overhead Ratio:  {np.min(overheads):.3f}x")
    print(f"Max Overhead Ratio:  {np.max(overheads):.3f}x")
    print(f"Std Dev Overhead:    {np.std(overheads):.3f}")


if __name__ == "__main__":
    run_fountain_erasure_stress_tests()
