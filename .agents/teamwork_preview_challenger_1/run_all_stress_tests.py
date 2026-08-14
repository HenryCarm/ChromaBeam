"""
ChromaBeam Challenger 1 - Master Adversarial Stress Harness
Executes all stress tests across perspective warp, fine rotations, lighting/noise, and fountain erasures.
Outputs formatted metrics and summaries.
"""

import sys
import os
import time

PROJECT_ROOT = "/home/henry/Documents/Projects/Python/QR ChromaBeam"
AGENT_DIR = "/home/henry/Documents/Projects/Python/QR ChromaBeam/.agents/teamwork_preview_challenger_1"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

from test_perspective_stress import run_perspective_stress_tests
from test_rotation_stress import run_rotation_stress_tests
from test_lighting_and_noise_stress import run_lighting_and_noise_stress_tests
from test_fountain_erasure_stress import run_fountain_erasure_stress_tests


def main():
    print("=" * 80)
    print("CHROMABEAM FINAL ACCEPTANCE GATE - CHALLENGER 1 EMPIRICAL AUDIT")
    print("=" * 80)
    start_total = time.perf_counter()

    t1 = time.perf_counter()
    persp_results = run_perspective_stress_tests()
    t1_el = time.perf_counter() - t1

    t2 = time.perf_counter()
    rot_results = run_rotation_stress_tests()
    t2_el = time.perf_counter() - t2

    t3 = time.perf_counter()
    light_results = run_lighting_and_noise_stress_tests()
    t3_el = time.perf_counter() - t3

    t4 = time.perf_counter()
    run_fountain_erasure_stress_tests()
    t4_el = time.perf_counter() - t4

    total_el = time.perf_counter() - start_total
    print("\n" + "=" * 80)
    print(f"ALL STRESS TESTS COMPLETED IN {total_el:.2f}s")
    print(f"  Perspective Suite: {t1_el:.2f}s")
    print(f"  Rotation Suite:    {t2_el:.2f}s")
    print(f"  Lighting Suite:    {t3_el:.2f}s")
    print(f"  Fountain Suite:    {t4_el:.2f}s")
    print("=" * 80)


if __name__ == "__main__":
    main()
