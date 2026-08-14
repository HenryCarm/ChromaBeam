#!/usr/bin/env python3
"""
ChromaBeam CRITICAL DEBUG: Why does the mobile phone scanner always show caught=0?

This script simulates EXACTLY what happens in the real scenario:
1. PC web sender (sender.js) renders a matrix to an HTML canvas
2. Phone camera sees the screen and captures the frame
3. Phone scanner (vision_engine.js + scanner_worker.js) tries to decode

We test each stage independently to find exactly where it breaks.
"""
import sys, os, struct, hashlib
import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.color_matrix import ColorMatrixLayout, bytes_to_color_grid, color_grid_to_bytes
from core.protocol import pack_packet, unpack_packet, pack_file_metadata
from core.fountain import LTEncoder


def simulate_js_canvas_rendering(grid_img_rgb, canvas_size=480):
    """
    Simulate what sender.js drawGridToCanvas() does:
    It draws each cell as a filled rectangle on a 480x480 canvas.
    This is NOT cv2.resize INTER_NEAREST — it uses Math.floor/Math.ceil.
    """
    N = grid_img_rgb.shape[0]
    canvas = np.zeros((canvas_size, canvas_size, 3), dtype=np.uint8)
    cell_size = canvas_size / N

    for r in range(N):
        for c in range(N):
            x1 = int(np.floor(c * cell_size))
            y1 = int(np.floor(r * cell_size))
            x2 = int(np.ceil((c + 1) * cell_size))
            y2 = int(np.ceil((r + 1) * cell_size))
            color = grid_img_rgb[r, c]
            canvas[y1:y2, x1:x2] = color

    return canvas


def simulate_camera_capture(screen_image_rgb, noise_sigma=5):
    """
    Simulate what a phone camera sees when pointed at a PC screen.
    Adds slight gaussian noise and possible slight blur.
    """
    frame = screen_image_rgb.copy().astype(np.float32)
    if noise_sigma > 0:
        noise = np.random.randn(*frame.shape) * noise_sigma
        frame = np.clip(frame + noise, 0, 255)
    return frame.astype(np.uint8)


def simulate_js_quad_sampling(camera_frame_rgb, quad, N, mode, palette):
    """
    Simulate EXACTLY what sampleQuadGrid() in vision_engine.js does.
    quad = [TL, TR, BR, BL] as {x,y} dicts
    """
    h, w = camera_frame_rgb.shape[:2]

    # Build the projective transform (simplified — for axis-aligned quad, it's just bilinear)
    p0, p1, p2, p3 = quad  # TL, TR, BR, BL

    grid2D = np.zeros((N, N), dtype=np.uint8)
    luma_samples = []

    for r in range(N):
        v = (r + 0.5) / N
        for c in range(N):
            u = (c + 0.5) / N

            # Bilinear interpolation of quad corners
            top_x = p0[0] * (1 - u) + p1[0] * u
            top_y = p0[1] * (1 - u) + p1[1] * u
            bot_x = p3[0] * (1 - u) + p2[0] * u
            bot_y = p3[1] * (1 - u) + p2[1] * u

            px = int(top_x * (1 - v) + bot_x * v)
            py = int(top_y * (1 - v) + bot_y * v)

            px = max(0, min(px, w - 1))
            py = max(0, min(py, h - 1))

            pixel = camera_frame_rgb[py, px]
            r_val, g_val, b_val = int(pixel[0]), int(pixel[1]), int(pixel[2])

            if mode == 0:
                luma = 0.299 * r_val + 0.587 * g_val + 0.114 * b_val
                luma_samples.append(luma)
            else:
                best_idx = 0
                min_dist = float('inf')
                for k, pal in enumerate(palette):
                    dist = (r_val - pal[0])**2 + (g_val - pal[1])**2 + (b_val - pal[2])**2
                    if dist < min_dist:
                        min_dist = dist
                        best_idx = k
                grid2D[r][c] = best_idx

    if mode == 0:
        # Otsu threshold
        luma_arr = np.array(luma_samples)
        threshold = otsu_threshold(luma_arr)
        idx = 0
        for r in range(N):
            for c in range(N):
                grid2D[r][c] = 1 if luma_samples[idx] > threshold else 0
                idx += 1

    return grid2D


def otsu_threshold(samples):
    histogram = np.zeros(256, dtype=np.int32)
    for s in samples:
        histogram[max(0, min(255, int(s)))] += 1

    total = len(samples)
    sum_total = np.sum(np.arange(256) * histogram)

    sum_bg = 0
    weight_bg = 0
    max_variance = 0
    threshold = 128

    for t in range(256):
        weight_bg += histogram[t]
        if weight_bg == 0:
            continue
        weight_fg = total - weight_bg
        if weight_fg == 0:
            break

        sum_bg += t * histogram[t]
        mean_bg = sum_bg / weight_bg
        mean_fg = (sum_total - sum_bg) / weight_fg
        variance = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2

        if variance > max_variance:
            max_variance = variance
            threshold = t

    return threshold


def grid_indices_to_bytes(grid2D, layout):
    """Exact equivalent of gridIndicesToBytes() in matrix.js"""
    bits = []
    bpc = layout.bits_per_cell

    for r, c in layout.data_coords:
        idx = int(grid2D[r][c])
        if bpc == 1:
            bits.append(idx & 1)
        elif bpc == 2:
            bits.append((idx >> 1) & 1)
            bits.append(idx & 1)
        else:
            bits.append((idx >> 2) & 1)
            bits.append((idx >> 1) & 1)
            bits.append(idx & 1)

    num_bytes = len(bits) // 8
    out = bytearray(num_bytes)
    for i in range(num_bytes):
        b = 0
        for k in range(8):
            b = (b << 1) | bits[i * 8 + k]
        out[i] = b

    return bytes(out)


def run_full_diagnostic():
    print("=" * 70)
    print("CHROMABEAM CRITICAL DIAGNOSTIC: Why caught=0 on mobile?")
    print("=" * 70)

    test_data = os.urandom(200)
    meta = pack_file_metadata("test.bin", len(test_data))
    full_payload = meta + test_data

    for mode in [0, 1, 2]:
        mode_name = ["1-bit B&W", "2-bit 4-Color", "3-bit 8-Color"][mode]
        for grid_size in [32, 48, 64]:
            layout = ColorMatrixLayout(grid_size=grid_size, color_mode=mode)
            block_size = max(24, layout.max_payload_bytes - 16)
            encoder = LTEncoder(full_payload, block_size=block_size)

            seed = 0
            degree, indices, droplet_payload = encoder.generate_droplet(seed)
            packet_bytes = pack_packet(
                file_id=999,
                total_blocks=encoder.K,
                block_size=block_size,
                seed=seed,
                payload=droplet_payload
            )

            print(f"\n--- {mode_name} @ {grid_size}x{grid_size} ---")
            print(f"  Packet: {len(packet_bytes)} bytes, K={encoder.K}, blockSize={block_size}")

            # Step 1: Render to NxN RGB grid
            grid_img = bytes_to_color_grid(packet_bytes, layout)

            # Step 2: Simulate JS canvas rendering (480x480)
            canvas = simulate_js_canvas_rendering(grid_img, canvas_size=480)

            # Step 3: Simulate camera capture (clean, no noise first)
            camera_frame = simulate_camera_capture(canvas, noise_sigma=0)

            # Step 4: Define quad (perfect alignment - the whole image IS the matrix)
            h, w = camera_frame.shape[:2]
            quad = [(0, 0), (w, 0), (w, h), (0, h)]

            # Step 5: Sample grid (simulating sampleQuadGrid)
            sampled_grid = simulate_js_quad_sampling(
                camera_frame, quad, grid_size, mode, 
                layout.palette.tolist()
            )

            # Step 6: Convert sampled grid indices to bytes
            recovered_bytes = grid_indices_to_bytes(sampled_grid, layout)

            # Step 7: Try unpack
            result = unpack_packet(recovered_bytes)
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"  Clean decode (no noise): {status}")

            if result is None:
                # Deep debug
                print(f"  Original[0:16]: {packet_bytes[:16].hex()}")
                print(f"  Recovered[0:16]: {recovered_bytes[:16].hex()}")
                
                # Check magic
                if len(recovered_bytes) >= 2:
                    magic = struct.unpack(">H", recovered_bytes[:2])[0]
                    print(f"  Magic: 0x{magic:04x} (expected 0x4342 = 'CB')")

                # Bit-level comparison of grid
                orig_grid_flat = []
                recv_grid_flat = []
                for r, c in layout.data_coords:
                    orig_grid_flat.append(int(grid_img[r, c, 0] > 128) if mode == 0 else -1)
                    recv_grid_flat.append(int(sampled_grid[r][c]))

                mismatches = 0
                for i in range(len(orig_grid_flat)):
                    if mode == 0:
                        orig_idx = orig_grid_flat[i]
                        recv_idx = recv_grid_flat[i]
                        if orig_idx != recv_idx:
                            mismatches += 1
                    # For color modes we'd need to compare differently

                if mode == 0:
                    print(f"  Cell-level mismatches (B&W): {mismatches} / {len(orig_grid_flat)}")

                # Byte-level diff
                min_len = min(len(packet_bytes), len(recovered_bytes))
                byte_mismatches = sum(1 for i in range(min_len) if packet_bytes[i] != recovered_bytes[i])
                print(f"  Byte-level mismatches: {byte_mismatches} / {min_len}")

                for i in range(min(min_len, 20)):
                    if packet_bytes[i] != recovered_bytes[i]:
                        print(f"    Byte {i}: orig=0x{packet_bytes[i]:02x} recv=0x{recovered_bytes[i]:02x}")
            else:
                print(f"  Decoded header: fileId={result[0].file_id}, K={result[0].total_blocks}, seed={result[0].seed}")

            # Now test with noise
            camera_noisy = simulate_camera_capture(canvas, noise_sigma=10)
            sampled_noisy = simulate_js_quad_sampling(
                camera_noisy, quad, grid_size, mode,
                layout.palette.tolist()
            )
            recovered_noisy = grid_indices_to_bytes(sampled_noisy, layout)
            result_noisy = unpack_packet(recovered_noisy)
            status_noisy = "✅ PASS" if result_noisy else "❌ FAIL"
            print(f"  Noisy decode (σ=10): {status_noisy}")


    # ========== CRITICAL TEST: What the JS scanner_worker ACTUALLY receives ==========
    print("\n" + "=" * 70)
    print("CRITICAL: Testing what detectOpticalQuad actually detects")
    print("=" * 70)

    # Simulate what the camera actually sees: the matrix on a screen surrounded by desktop
    layout = ColorMatrixLayout(grid_size=32, color_mode=0)
    block_size = max(24, layout.max_payload_bytes - 16)
    encoder = LTEncoder(full_payload, block_size=block_size)
    seed = 0
    _, _, droplet_payload = encoder.generate_droplet(seed)
    packet_bytes = pack_packet(999, encoder.K, block_size, seed, droplet_payload)
    grid_img = bytes_to_color_grid(packet_bytes, layout)
    canvas = simulate_js_canvas_rendering(grid_img, canvas_size=480)

    # Place the matrix in the center of a larger frame (simulating phone camera view)
    full_frame = np.full((720, 1280, 3), 40, dtype=np.uint8)  # Dark background (like browser)
    # Center the 480x480 matrix
    y_off = (720 - 480) // 2
    x_off = (1280 - 480) // 2
    full_frame[y_off:y_off+480, x_off:x_off+480] = canvas

    # Now test anchor detection
    # First, check if the 1:1:1:1:1 pattern is actually visible
    print(f"\n  Matrix placed at ({x_off},{y_off}) to ({x_off+480},{y_off+480}) in 1280x720 frame")

    # Check what the scanline sees at the anchor rows
    anchor_center_y = y_off + int(2.5 / 32 * 480)
    print(f"  Top anchor row in frame: y={anchor_center_y}")
    
    scanline = full_frame[anchor_center_y, :, :]
    luma_scanline = 0.299 * scanline[:, 0] + 0.587 * scanline[:, 1] + 0.114 * scanline[:, 2]

    mid_luma = (luma_scanline.min() + luma_scanline.max()) / 2
    binary_scanline = (luma_scanline > mid_luma).astype(int)

    # Find 1:1:1:1:1 patterns
    print(f"  Scanline luma range: [{luma_scanline.min():.0f}, {luma_scanline.max():.0f}], mid={mid_luma:.0f}")

    # Show the binary pattern around the TL anchor
    tl_x = x_off + int(2.5 / 32 * 480)
    region_start = max(0, tl_x - 50)
    region_end = min(1280, tl_x + 50)
    print(f"  Binary around TL anchor (x≈{tl_x}): ...{''.join(map(str, binary_scanline[region_start:region_end]))}...")

    # Check the actual anchor pattern
    anchor_px = 480 / 32  # pixels per cell
    print(f"  Pixels per cell: {anchor_px:.1f}")
    print(f"  Expected 1:1:1:1:1 pattern width: {anchor_px * 5:.0f} pixels")

    # Show what the anchor ACTUALLY looks like in the rendered image
    print(f"\n  TL Anchor (cells 0-4, rows 0-4) colors in grid_img:")
    for r in range(5):
        row_str = ""
        for c in range(5):
            pixel = grid_img[r, c]
            luma = 0.299 * pixel[0] + 0.587 * pixel[1] + 0.114 * pixel[2]
            row_str += f"{'W' if luma > 128 else 'B'} "
        print(f"    Row {r}: {row_str}")


if __name__ == "__main__":
    run_full_diagnostic()
