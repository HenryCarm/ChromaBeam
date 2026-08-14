"""
Verification of Burst Erasure Recovery
"""
import sys
import os
import random

PROJECT_ROOT = "/home/henry/Documents/Projects/Python/QR ChromaBeam"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.fountain import LTEncoder, LTDecoder

def test_burst_recovery():
    fsize = 8192
    raw_data = os.urandom(fsize)
    encoder = LTEncoder(raw_data, block_size=256)
    K = encoder.K

    decoder = LTDecoder(K=K, block_size=256, total_filesize=fsize)
    seed = 0
    packets_sent = 0
    packets_received = 0

    # Pattern: 10 packets received, 40 packets dropped, 10 received, 40 dropped...
    while not decoder.is_complete and packets_sent < 5000:
        degree, indices, payload = encoder.generate_droplet(seed)
        packets_sent += 1
        
        # Periodic 10 received / 40 dropped
        if (packets_sent % 50) < 10:
            decoder.add_droplet(seed, payload)
            packets_received += 1
        
        seed += 1

    reconstructed = decoder.reconstruct_data()
    print(f"Periodic Burst Recovery (10 on / 40 off, 80% loss):")
    print(f"  K = {K}")
    print(f"  Packets Sent: {packets_sent}")
    print(f"  Packets Received: {packets_received} (Overhead: {packets_received/K:.2f}x)")
    print(f"  Is Complete: {decoder.is_complete}")
    print(f"  Data Match: {reconstructed == raw_data}")
    assert reconstructed == raw_data

if __name__ == "__main__":
    test_burst_recovery()
