"""
Adversarial Stress Test: Perspective Homography & Tilt Limits (45°+)
Tests 3D projective perspective distortion across extreme pitch, yaw, roll, and compound angles.
"""

import sys
import os
import time
import math
import numpy as np
import cv2

# Add project root to sys.path
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


def generate_perspective_warped_frame(
    bgr_matrix: np.ndarray,
    tilt_angle_deg: float,
    tilt_axis: str = 'pitch', # pitch, yaw, compound
    canvas_size: int = 720,
    margin: int = 60
) -> np.ndarray:
    """
    Simulates a camera viewing the screen at an arbitrary tilt angle theta (in degrees).
    Uses a true 3D camera projection model with focal length.
    """
    h_m, w_m = bgr_matrix.shape[:2]
    # Center matrix on a canvas
    canvas = np.zeros((canvas_size, canvas_size, 3), dtype=np.uint8) + 40
    cx = (canvas_size - w_m) // 2
    cy = (canvas_size - h_m) // 2
    canvas[cy:cy + h_m, cx:cx + w_m] = bgr_matrix

    rad = math.radians(tilt_angle_deg)
    f = float(canvas_size) # focal length
    w = float(canvas_size)
    h = float(canvas_size)

    # 3D rotation matrix
    cos_t = math.cos(rad)
    sin_t = math.sin(rad)

    if tilt_axis == 'pitch': # Tilt along X axis (top tilts away or towards)
        R = np.array([
            [1, 0, 0],
            [0, cos_t, -sin_t],
            [0, sin_t, cos_t]
        ], dtype=np.float64)
    elif tilt_axis == 'yaw': # Tilt along Y axis (left tilts away)
        R = np.array([
            [cos_t, 0, sin_t],
            [0, 1, 0],
            [-sin_t, 0, cos_t]
        ], dtype=np.float64)
    elif tilt_axis == 'compound': # Tilt along diagonal axis (pitch + yaw)
        rad_half = rad / math.sqrt(2.0)
        c, s = math.cos(rad_half), math.sin(rad_half)
        Rx = np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)
        Ry = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64)
        R = Rx @ Ry
    else:
        R = np.eye(3, dtype=np.float64)

    # Intrinsic camera matrix K
    K = np.array([
        [f, 0, w / 2.0],
        [0, f, h / 2.0],
        [0, 0, 1]
    ], dtype=np.float64)
    K_inv = np.linalg.inv(K)

    # Translation: distance camera from plane
    # Ensure plane stays in front of camera
    dist = f
    T = np.array([0, 0, dist], dtype=np.float64)

    # 4 corners in 3D object plane coordinates (z = 0)
    pts_src = np.array([
        [0.0, 0.0],
        [w, 0.0],
        [w, h],
        [0.0, h]
    ], dtype=np.float32)

    # Compute homography via 3D plane projection
    # Normal of object plane: n = [0, 0, 1]^T
    # H_plane = K * (R - (T * n^T) / d) * K_inv
    # Direct corner projection:
    corners_3d = np.array([
        [-w/2.0, -h/2.0, 0.0],
        [ w/2.0, -h/2.0, 0.0],
        [ w/2.0,  h/2.0, 0.0],
        [-w/2.0,  h/2.0, 0.0]
    ], dtype=np.float64)

    transformed_corners_3d = (R @ corners_3d.T).T + T
    # Project to 2D
    projected = []
    for pt in transformed_corners_3d:
        z = pt[2]
        if z <= 0.1:
            z = 0.1
        px = f * (pt[0] / z) + w / 2.0
        py = f * (pt[1] / z) + h / 2.0
        projected.append([px, py])

    pts_dst = np.array(projected, dtype=np.float32)
    H = cv2.getPerspectiveTransform(pts_src, pts_dst)

    warped_frame = cv2.warpPerspective(
        canvas, H, (canvas_size, canvas_size),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(40, 40, 40)
    )
    return warped_frame


def run_perspective_stress_tests():
    print("=" * 70)
    print("STRESS TEST 1: High Aspect Ratio Perspective Warping (45°+ Tilt)")
    print("=" * 70)

    angles = [0, 15, 30, 40, 45, 50, 55, 60, 65, 70]
    axes = ['pitch', 'yaw', 'compound']
    modes = [
        (MODE_1BIT_BW, "1-bit Potato", 32),
        (MODE_2BIT_4COLOR, "2-bit Balanced", 48),
        (MODE_3BIT_8COLOR, "3-bit Turbo", 48),
    ]

    results = []
    tracker = OpticalTracker(target_grid_dim=512)

    for mode, mode_name, grid_size in modes:
        layout = ColorMatrixLayout(grid_size=grid_size, color_mode=mode)
        payload = b"ChromaBeam-StressPayload-" + mode_name.encode() + b"-CRC32Test"
        pkt = pack_packet(file_id=777, total_blocks=1, block_size=len(payload), seed=777, payload=payload)
        grid = bytes_to_color_grid(pkt, layout)

        matrix_img = cv2.resize(grid, (400, 400), interpolation=cv2.INTER_NEAREST)
        matrix_bgr = cv2.cvtColor(matrix_img, cv2.COLOR_RGB2BGR)

        for axis in axes:
            for angle in angles:
                frame = generate_perspective_warped_frame(matrix_bgr, angle, tilt_axis=axis)
                
                # Check for tracker crash or hang
                start_t = time.perf_counter()
                try:
                    anchors = tracker.find_anchors(frame)
                    detection_time_ms = (time.perf_counter() - start_t) * 1000.0
                    detected = (anchors is not None)
                except Exception as e:
                    print(f"CRASH in find_anchors! Mode={mode_name}, Axis={axis}, Angle={angle}°: {e}")
                    results.append({
                        "mode": mode_name, "axis": axis, "angle": angle,
                        "detected": False, "decoded": False, "time_ms": 0, "crash": str(e)
                    })
                    continue

                decoded = False
                payload_match = False
                if detected:
                    try:
                        warped = tracker.warp_matrix(frame, anchors, grid_size=grid_size)
                        sampled = tracker.sample_grid_cells(warped, grid_size=grid_size)
                        
                        # Test 4-way rotation search for decode
                        for rot_k in [0, 1, 2, 3]:
                            rot_sampled = np.rot90(sampled, k=rot_k)
                            raw = color_grid_to_bytes(rot_sampled, layout)
                            res = unpack_packet(raw)
                            if res is not None:
                                hdr, rec_payload = res
                                if rec_payload == payload:
                                    decoded = True
                                    payload_match = True
                                    break
                    except Exception as e:
                        print(f"CRASH in warp/sample/decode! Mode={mode_name}, Axis={axis}, Angle={angle}°: {e}")
                        results.append({
                            "mode": mode_name, "axis": axis, "angle": angle,
                            "detected": True, "decoded": False, "time_ms": detection_time_ms, "crash": str(e)
                        })
                        continue

                results.append({
                    "mode": mode_name, "axis": axis, "angle": angle,
                    "detected": detected, "decoded": decoded,
                    "time_ms": detection_time_ms, "crash": None
                })

                status = "DECODED" if decoded else ("DETECTED" if detected else "LOST")
                print(f"[{mode_name:14s}] Axis: {axis:8s} | Tilt: {angle:2d}° | {status:8s} | Time: {detection_time_ms:5.1f} ms")

    # Analyze results
    print("\n--- Summary of Perspective Stress Tests ---")
    crashes = [r for r in results if r["crash"] is not None]
    print(f"Total test cases: {len(results)}")
    print(f"Crashes / Unhandled Exceptions: {len(crashes)}")

    for mode_name in ["1-bit Potato", "2-bit Balanced", "3-bit Turbo"]:
        mode_res = [r for r in results if r["mode"] == mode_name]
        detected_angles = [r["angle"] for r in mode_res if r["detected"]]
        decoded_angles = [r["angle"] for r in mode_res if r["decoded"]]
        max_detected = max(detected_angles) if detected_angles else 0
        max_decoded = max(decoded_angles) if decoded_angles else 0
        print(f"[{mode_name}] Max Detection Tilt: {max_detected}° | Max Decode Tilt: {max_decoded}°")

    return results


if __name__ == "__main__":
    run_perspective_stress_tests()
