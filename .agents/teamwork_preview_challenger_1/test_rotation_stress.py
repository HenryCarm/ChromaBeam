"""
Adversarial Stress Test: Rotation Invariance at Fine Angular Increments
Tests rotations across fine angular steps (0° to 360° at 5° and 15° increments)
combined with scaling and translations.
"""

import sys
import os
import time
import numpy as np
import cv2

PROJECT_ROOT = "/home/henry/Documents/Projects/Python/QR ChromaBeam"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import core.color_matrix
core.color_matrix.PALETTE_1BIT = core.color_matrix.PALETTE_1BIT.astype(np.int32)
core.color_matrix.PALETTE_2BIT = core.color_matrix.PALETTE_2BIT.astype(np.int32)
core.color_matrix.PALETTE_3BIT = core.color_matrix.PALETTE_3BIT.astype(np.int32)

from core.protocol import pack_packet, unpack_packet
from core.color_matrix import (
    ColorMatrixLayout,
    bytes_to_color_grid,
    color_grid_to_bytes,
    MODE_1BIT_BW,
    MODE_2BIT_4COLOR,
    MODE_3BIT_8COLOR
)
from desktop_receiver.tracker import OpticalTracker


def apply_arbitrary_rotation(
    bgr_matrix: np.ndarray,
    angle_deg: float,
    scale: float = 1.0,
    tx: float = 0.0,
    ty: float = 0.0,
    canvas_size: int = 720
) -> np.ndarray:
    """
    Renders matrix on canvas and applies arbitrary 2D affine transformation (rotation, scale, shift).
    """
    h_m, w_m = bgr_matrix.shape[:2]
    canvas = np.zeros((canvas_size, canvas_size, 3), dtype=np.uint8) + 40
    cx = (canvas_size - w_m) // 2
    cy = (canvas_size - h_m) // 2
    canvas[cy:cy + h_m, cx:cx + w_m] = bgr_matrix

    center = (canvas_size / 2.0 + tx, canvas_size / 2.0 + ty)
    M = cv2.getRotationMatrix2D(center, angle_deg, scale)
    rotated = cv2.warpAffine(
        canvas, M, (canvas_size, canvas_size),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(40, 40, 40)
    )
    return rotated


def run_rotation_stress_tests():
    print("=" * 70)
    print("STRESS TEST 2: Rotations at Fine Angular Increments (0° to 360°)")
    print("=" * 70)

    # 24 discrete fine angular steps covering full 360 degrees
    angles = list(range(0, 360, 15))  # 0, 15, 30, 45, 60, 75, 90, 105, ..., 345
    # Add key intermediate micro-angles (e.g. 5, 23, 44, 89, 137, 269)
    micro_angles = [5, 23, 44, 89, 137, 269, 315]
    all_angles = sorted(list(set(angles + micro_angles)))

    modes = [
        (MODE_1BIT_BW, "1-bit Potato", 32),
        (MODE_2BIT_4COLOR, "2-bit Balanced", 48),
        (MODE_3BIT_8COLOR, "3-bit Turbo", 48),
    ]

    tracker = OpticalTracker(target_grid_dim=512)
    results = []

    for mode, mode_name, grid_size in modes:
        layout = ColorMatrixLayout(grid_size=grid_size, color_mode=mode)
        payload = b"ChromaBeam-RotationStress-" + mode_name.encode() + b"-CRC32Validation"
        pkt = pack_packet(file_id=888, total_blocks=1, block_size=len(payload), seed=888, payload=payload)
        grid = bytes_to_color_grid(pkt, layout)

        matrix_img = cv2.resize(grid, (380, 380), interpolation=cv2.INTER_NEAREST)
        matrix_bgr = cv2.cvtColor(matrix_img, cv2.COLOR_RGB2BGR)

        mode_detected = 0
        mode_decoded = 0

        for angle in all_angles:
            frame = apply_arbitrary_rotation(matrix_bgr, angle_deg=angle, scale=1.0)
            
            start_t = time.perf_counter()
            try:
                anchors = tracker.find_anchors(frame)
                detection_time_ms = (time.perf_counter() - start_t) * 1000.0
                detected = (anchors is not None)
            except Exception as e:
                print(f"CRASH in find_anchors! Mode={mode_name}, Angle={angle}°: {e}")
                results.append({
                    "mode": mode_name, "angle": angle, "scale": 1.0,
                    "detected": False, "decoded": False, "time_ms": 0, "crash": str(e)
                })
                continue

            decoded = False
            matched_rot = None
            if detected:
                mode_detected += 1
                try:
                    warped = tracker.warp_matrix(frame, anchors, grid_size=grid_size)
                    sampled = tracker.sample_grid_cells(warped, grid_size=grid_size)

                    # Verify 4-way rotation search
                    for rot_k in [0, 1, 2, 3]:
                        rot_sampled = np.rot90(sampled, k=rot_k)
                        raw = color_grid_to_bytes(rot_sampled, layout)
                        res = unpack_packet(raw)
                        if res is not None:
                            hdr, rec_payload = res
                            if rec_payload == payload:
                                decoded = True
                                matched_rot = rot_k * 90
                                break
                except Exception as e:
                    print(f"CRASH in warp/sample/decode! Mode={mode_name}, Angle={angle}°: {e}")
                    results.append({
                        "mode": mode_name, "angle": angle, "scale": 1.0,
                        "detected": True, "decoded": False, "time_ms": detection_time_ms, "crash": str(e)
                    })
                    continue

            if decoded:
                mode_decoded += 1

            results.append({
                "mode": mode_name, "angle": angle, "scale": 1.0,
                "detected": detected, "decoded": decoded,
                "matched_rot": matched_rot, "time_ms": detection_time_ms, "crash": None
            })

            status = f"DECODED (k={matched_rot}°)" if decoded else ("DETECTED" if detected else "LOST")
            print(f"[{mode_name:14s}] Angle: {angle:3d}° | {status:20s} | Time: {detection_time_ms:5.1f} ms")

        print(f"\n--- Mode Summary [{mode_name}] ---")
        print(f"Total Angles Tested: {len(all_angles)}")
        print(f"Anchors Detected: {mode_detected} / {len(all_angles)} ({mode_detected/len(all_angles)*100:.1f}%)")
        print(f"CRC Decoded: {mode_decoded} / {len(all_angles)} ({mode_decoded/len(all_angles)*100:.1f}%)\n")

    # Additional Scale + Rotation Compound Test
    print("Testing Scale + Rotation Compound Variations (Scale 0.7x to 1.3x, Angle 37°, 128°, 245°):")
    scale_tests = [(0.7, 37), (0.85, 128), (1.15, 245), (1.3, 310)]
    for scale, angle in scale_tests:
        layout = ColorMatrixLayout(grid_size=48, color_mode=MODE_2BIT_4COLOR)
        payload = b"CompoundScaleRotationTestPayload"
        pkt = pack_packet(file_id=889, total_blocks=1, block_size=len(payload), seed=889, payload=payload)
        grid = bytes_to_color_grid(pkt, layout)
        matrix_img = cv2.resize(grid, (380, 380), interpolation=cv2.INTER_NEAREST)
        matrix_bgr = cv2.cvtColor(matrix_img, cv2.COLOR_RGB2BGR)

        frame = apply_arbitrary_rotation(matrix_bgr, angle_deg=angle, scale=scale)
        anchors = tracker.find_anchors(frame)
        det = (anchors is not None)
        dec = False
        if det:
            warped = tracker.warp_matrix(frame, anchors, grid_size=48)
            sampled = tracker.sample_grid_cells(warped, grid_size=48)
            for rot_k in [0, 1, 2, 3]:
                raw = color_grid_to_bytes(np.rot90(sampled, k=rot_k), layout)
                res = unpack_packet(raw)
                if res and res[1] == payload:
                    dec = True
                    break
        status = "DECODED" if dec else ("DETECTED" if det else "LOST")
        print(f"[Scale={scale:4.2f}, Angle={angle:3d}°] -> {status}")

    return results


if __name__ == "__main__":
    run_rotation_stress_tests()
