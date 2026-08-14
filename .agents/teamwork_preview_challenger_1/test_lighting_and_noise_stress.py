"""
Adversarial Stress Test: Dynamic Lighting Contrast Shifts, Extreme Noise & Color Classification
Tests robustness against extreme lighting perturbations, sensor noise, optical blur, glare, and color casts.
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
from desktop_receiver.color_classifier import AdaptiveColorClassifier


def apply_brightness_contrast(frame: np.ndarray, alpha: float, beta: int) -> np.ndarray:
    """Applies contrast multiplier (alpha) and brightness offset (beta): out = alpha * in + beta."""
    return np.clip(frame.astype(np.float32) * alpha + beta, 0, 255).astype(np.uint8)


def apply_extreme_gaussian_noise(frame: np.ndarray, sigma: float, seed: int = 1234) -> np.ndarray:
    """Applies Gaussian sensor noise."""
    rng = np.random.RandomState(seed)
    noise = rng.normal(0, sigma, frame.shape)
    return np.clip(frame.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def apply_salt_and_pepper_noise(frame: np.ndarray, amount: float, seed: int = 1234) -> np.ndarray:
    """Applies salt and pepper impulse noise."""
    rng = np.random.RandomState(seed)
    out = frame.copy()
    num_salt = int(amount * frame.size * 0.5)
    num_pepper = int(amount * frame.size * 0.5)
    
    # Salt
    coords = [rng.randint(0, i - 1, num_salt) for i in frame.shape[:2]]
    out[tuple(coords)] = 255
    # Pepper
    coords = [rng.randint(0, i - 1, num_pepper) for i in frame.shape[:2]]
    out[tuple(coords)] = 0
    return out


def apply_harsh_lighting_gradient(frame: np.ndarray, max_glare: int = 60) -> np.ndarray:
    """Applies strong non-linear diagonal glare gradient across the frame."""
    h, w = frame.shape[:2]
    x = np.linspace(0, 1, w, dtype=np.float32)
    y = np.linspace(0, 1, h, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)
    grad = (xx**2 + yy**2) / 2.0
    glare = (grad[:, :, np.newaxis] * max_glare)
    return np.clip(frame.astype(np.float32) + glare, 0, 255).astype(np.uint8)


def apply_color_temperature_cast(frame: np.ndarray, cast_type: str = 'warm') -> np.ndarray:
    """Applies realistic display color casts (warm amber, cool blue, fluorescent green)."""
    out = frame.astype(np.float32)
    if cast_type == 'warm': # Amber / Night Light (more red, less blue)
        out[:, :, 2] = np.clip(out[:, :, 2] * 1.25, 0, 255) # R
        out[:, :, 1] = np.clip(out[:, :, 1] * 1.05, 0, 255) # G
        out[:, :, 0] = np.clip(out[:, :, 0] * 0.70, 0, 255) # B
    elif cast_type == 'cool': # Cold Blue
        out[:, :, 0] = np.clip(out[:, :, 0] * 1.30, 0, 255) # B
        out[:, :, 2] = np.clip(out[:, :, 2] * 0.75, 0, 255) # R
    elif cast_type == 'green': # Fluorescent Tint
        out[:, :, 1] = np.clip(out[:, :, 1] * 1.25, 0, 255) # G
        out[:, :, 0] = np.clip(out[:, :, 0] * 0.85, 0, 255) # B
    return out.astype(np.uint8)


def run_lighting_and_noise_stress_tests():
    print("=" * 70)
    print("STRESS TEST 3: Dynamic Lighting Contrast, Extreme Noise & Color Classification")
    print("=" * 70)

    tracker = OpticalTracker(target_grid_dim=512)
    modes = [
        (MODE_1BIT_BW, "1-bit Potato", 32),
        (MODE_2BIT_4COLOR, "2-bit Balanced", 48),
        (MODE_3BIT_8COLOR, "3-bit Turbo", 48),
    ]

    all_test_records = []

    # 1. Brightness Offset Sweep (-80 to +80)
    print("\n--- 1. Brightness Sweep (Exposure Shifts) ---")
    brightness_levels = [-80, -60, -40, -20, 0, +20, +40, +60, +80]
    for mode, mode_name, grid_size in modes:
        layout = ColorMatrixLayout(grid_size=grid_size, color_mode=mode)
        payload = b"ChromaBeam-BrightnessTest-" + mode_name.encode()
        pkt = pack_packet(file_id=901, total_blocks=1, block_size=len(payload), seed=901, payload=payload)
        grid = bytes_to_color_grid(pkt, layout)
        matrix_img = cv2.resize(grid, (400, 400), interpolation=cv2.INTER_NEAREST)
        matrix_bgr = cv2.cvtColor(matrix_img, cv2.COLOR_RGB2BGR)

        # Base frame on canvas
        canvas = np.zeros((600, 600, 3), dtype=np.uint8) + 40
        canvas[100:500, 100:500] = matrix_bgr

        for beta in brightness_levels:
            frame = apply_brightness_contrast(canvas, alpha=1.0, beta=beta)
            anchors = tracker.find_anchors(frame)
            det = (anchors is not None)
            dec = False
            if det:
                warped = tracker.warp_matrix(frame, anchors, grid_size=grid_size)
                sampled = tracker.sample_grid_cells(warped, grid_size=grid_size)
                for rot_k in [0, 1, 2, 3]:
                    raw = color_grid_to_bytes(np.rot90(sampled, k=rot_k), layout)
                    res = unpack_packet(raw)
                    if res and res[1] == payload:
                        dec = True
                        break
            status = "DECODED" if dec else ("DETECTED" if det else "FAIL")
            print(f"[{mode_name:14s}] Brightness: {beta:+3d} | Result: {status}")
            all_test_records.append({"test": "brightness", "mode": mode_name, "param": beta, "det": det, "dec": dec})

    # 2. Contrast Scaling Sweep (0.3x to 2.5x)
    print("\n--- 2. Contrast Scaling Sweep (Low to High Dynamic Range) ---")
    contrast_levels = [0.35, 0.5, 0.7, 1.0, 1.3, 1.6, 2.0, 2.5]
    for mode, mode_name, grid_size in modes:
        layout = ColorMatrixLayout(grid_size=grid_size, color_mode=mode)
        payload = b"ChromaBeam-ContrastTest-" + mode_name.encode()
        pkt = pack_packet(file_id=902, total_blocks=1, block_size=len(payload), seed=902, payload=payload)
        grid = bytes_to_color_grid(pkt, layout)
        matrix_img = cv2.resize(grid, (400, 400), interpolation=cv2.INTER_NEAREST)
        matrix_bgr = cv2.cvtColor(matrix_img, cv2.COLOR_RGB2BGR)

        canvas = np.zeros((600, 600, 3), dtype=np.uint8) + 40
        canvas[100:500, 100:500] = matrix_bgr

        for alpha in contrast_levels:
            frame = apply_brightness_contrast(canvas, alpha=alpha, beta=0)
            anchors = tracker.find_anchors(frame)
            det = (anchors is not None)
            dec = False
            if det:
                warped = tracker.warp_matrix(frame, anchors, grid_size=grid_size)
                sampled = tracker.sample_grid_cells(warped, grid_size=grid_size)
                for rot_k in [0, 1, 2, 3]:
                    raw = color_grid_to_bytes(np.rot90(sampled, k=rot_k), layout)
                    res = unpack_packet(raw)
                    if res and res[1] == payload:
                        dec = True
                        break
            status = "DECODED" if dec else ("DETECTED" if det else "FAIL")
            print(f"[{mode_name:14s}] Contrast: {alpha:4.2f}x | Result: {status}")
            all_test_records.append({"test": "contrast", "mode": mode_name, "param": alpha, "det": det, "dec": dec})

    # 3. Gaussian Sensor Noise Sweep (sigma = 5 to 60)
    print("\n--- 3. Extreme Gaussian Sensor Noise Sweep ---")
    noise_sigmas = [5, 10, 15, 20, 25, 30, 40, 50, 60]
    for mode, mode_name, grid_size in modes:
        layout = ColorMatrixLayout(grid_size=grid_size, color_mode=mode)
        payload = b"ChromaBeam-NoiseTest-" + mode_name.encode()
        pkt = pack_packet(file_id=903, total_blocks=1, block_size=len(payload), seed=903, payload=payload)
        grid = bytes_to_color_grid(pkt, layout)
        matrix_img = cv2.resize(grid, (400, 400), interpolation=cv2.INTER_NEAREST)
        matrix_bgr = cv2.cvtColor(matrix_img, cv2.COLOR_RGB2BGR)

        canvas = np.zeros((600, 600, 3), dtype=np.uint8) + 40
        canvas[100:500, 100:500] = matrix_bgr

        for sigma in noise_sigmas:
            frame = apply_extreme_gaussian_noise(canvas, sigma=sigma, seed=42)
            anchors = tracker.find_anchors(frame)
            det = (anchors is not None)
            dec = False
            if det:
                warped = tracker.warp_matrix(frame, anchors, grid_size=grid_size)
                sampled = tracker.sample_grid_cells(warped, grid_size=grid_size)
                for rot_k in [0, 1, 2, 3]:
                    raw = color_grid_to_bytes(np.rot90(sampled, k=rot_k), layout)
                    res = unpack_packet(raw)
                    if res and res[1] == payload:
                        dec = True
                        break
            status = "DECODED" if dec else ("DETECTED" if det else "FAIL")
            print(f"[{mode_name:14s}] Noise Sigma: {sigma:2d} | Result: {status}")
            all_test_records.append({"test": "noise", "mode": mode_name, "param": sigma, "det": det, "dec": dec})

    # 4. Color Cast / Temperature Shifts (Warm, Cool, Green)
    print("\n--- 4. Color Temperature Cast Shifts ---")
    casts = ['warm', 'cool', 'green']
    for mode, mode_name, grid_size in modes:
        layout = ColorMatrixLayout(grid_size=grid_size, color_mode=mode)
        payload = b"ChromaBeam-ColorCastTest-" + mode_name.encode()
        pkt = pack_packet(file_id=904, total_blocks=1, block_size=len(payload), seed=904, payload=payload)
        grid = bytes_to_color_grid(pkt, layout)
        matrix_img = cv2.resize(grid, (400, 400), interpolation=cv2.INTER_NEAREST)
        matrix_bgr = cv2.cvtColor(matrix_img, cv2.COLOR_RGB2BGR)

        canvas = np.zeros((600, 600, 3), dtype=np.uint8) + 40
        canvas[100:500, 100:500] = matrix_bgr

        for cast in casts:
            frame = apply_color_temperature_cast(canvas, cast_type=cast)
            anchors = tracker.find_anchors(frame)
            det = (anchors is not None)
            dec = False
            if det:
                warped = tracker.warp_matrix(frame, anchors, grid_size=grid_size)
                sampled = tracker.sample_grid_cells(warped, grid_size=grid_size)
                for rot_k in [0, 1, 2, 3]:
                    raw = color_grid_to_bytes(np.rot90(sampled, k=rot_k), layout)
                    res = unpack_packet(raw)
                    if res and res[1] == payload:
                        dec = True
                        break
            status = "DECODED" if dec else ("DETECTED" if det else "FAIL")
            print(f"[{mode_name:14s}] Cast: {cast:6s} | Result: {status}")
            all_test_records.append({"test": "color_cast", "mode": mode_name, "param": cast, "det": det, "dec": dec})

    # 5. Pathological Corner Cases (Solid Black, Solid White, Random Noise Frame)
    print("\n--- 5. Pathological Frame Invariant Rejection ---")
    pathological_frames = [
        ("Solid Black (0)", np.zeros((600, 600, 3), dtype=np.uint8)),
        ("Solid White (255)", np.full((600, 600, 3), 255, dtype=np.uint8)),
        ("Pure Uniform Noise", np.random.randint(0, 256, (600, 600, 3), dtype=np.uint8)),
        ("Single Random Square", cv2.rectangle(np.zeros((600, 600, 3), dtype=np.uint8), (100, 100), (300, 300), (255, 255, 255), -1)),
        ("Three Circles (Fake Anchors)", cv2.circle(cv2.circle(cv2.circle(np.zeros((600, 600, 3), dtype=np.uint8), (100, 100), 40, (255, 255, 255), -1), (400, 100), 40, (255, 255, 255), -1), (100, 400), 40, (255, 255, 255), -1))
    ]

    for label, bad_frame in pathological_frames:
        try:
            anchors = tracker.find_anchors(bad_frame)
            if anchors is None:
                print(f"[REJECTION OK] {label:30s} -> Correctly returned None (No false positive)")
            else:
                print(f"[FALSE POSITIVE] {label:30s} -> Detected false anchors: {anchors}")
        except Exception as e:
            print(f"[CRASH] {label:30s} -> Unhandled Exception: {e}")

    return all_test_records


if __name__ == "__main__":
    run_lighting_and_noise_stress_tests()
