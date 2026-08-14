"""
ChromaBeam Milestone 2 Unit Tests: Python CV Tracker, Hierarchical 1:1:1:1:1 Anchors,
Direct Canonical Homography (H), 360° 4-Way Rotation Invariance, and Auto-Density Sweeping.
"""

import unittest
import os
import sys
import numpy as np
import cv2

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.protocol import pack_packet, unpack_packet
from core.color_matrix import (
    ColorMatrixLayout,
    bytes_to_color_grid,
    color_grid_to_bytes,
    upscale_grid_for_display,
    MODE_1BIT_BW,
    MODE_2BIT_4COLOR,
    MODE_3BIT_8COLOR
)
from desktop_receiver.tracker import (
    OpticalTracker,
    MatrixTracker,
    order_quad_points,
    find_nested_anchor_centers,
    filter_and_order_4_anchors
)
from desktop_receiver.receiver_gui import ChromaBeamReceiver


class TestTrackerAndRotationInvariance(unittest.TestCase):
    def test_order_quad_points(self):
        """Tests that quad points are consistently ordered [TL, TR, BR, BL] (clockwise)."""
        pts = np.array([
            [100.0, 10.0],   # TR
            [10.0, 10.0],    # TL
            [10.0, 100.0],   # BL
            [100.0, 100.0]   # BR
        ], dtype=np.float32)

        ordered = order_quad_points(pts)
        np.testing.assert_allclose(ordered[0], [10.0, 10.0], err_msg="TL mismatch")
        np.testing.assert_allclose(ordered[1], [100.0, 10.0], err_msg="TR mismatch")
        np.testing.assert_allclose(ordered[2], [100.0, 100.0], err_msg="BR mismatch")
        np.testing.assert_allclose(ordered[3], [10.0, 100.0], err_msg="BL mismatch")

        # Permuted test with perspective tilt
        pts_tilted = np.array([
            [480.0, 470.0],  # BR
            [50.0, 490.0],   # BL
            [460.0, 40.0],   # TR
            [30.0, 20.0],    # TL
        ], dtype=np.float32)
        ordered_tilted = order_quad_points(pts_tilted)
        np.testing.assert_allclose(ordered_tilted[0], [30.0, 20.0], err_msg="TL mismatch")
        np.testing.assert_allclose(ordered_tilted[1], [460.0, 40.0], err_msg="TR mismatch")
        np.testing.assert_allclose(ordered_tilted[2], [480.0, 470.0], err_msg="BR mismatch")
        np.testing.assert_allclose(ordered_tilted[3], [50.0, 490.0], err_msg="BL mismatch")

    def test_hierarchical_1_1_1_1_1_anchor_detection(self):
        """
        Verifies mathematical cv2.RETR_TREE nested contour detection of 1:1:1:1:1 anchors
        with centroid matching delta < 2.5px and area ratio in [0.035, 0.160].
        """
        tracker = OpticalTracker(target_grid_dim=512)
        for size in [32, 48, 64]:
            for mode in [MODE_1BIT_BW, MODE_2BIT_4COLOR, MODE_3BIT_8COLOR]:
                layout = ColorMatrixLayout(grid_size=size, color_mode=mode)
                raw_payload = os.urandom(layout.max_payload_bytes - 10)
                pkt = pack_packet(file_id=10, total_blocks=5, block_size=len(raw_payload), seed=0, payload=raw_payload)
                grid = bytes_to_color_grid(pkt, layout)

                # Upscale to standard display frame (e.g. 512x512) inside a camera frame canvas (640x640)
                upscaled = cv2.resize(grid, (512, 512), interpolation=cv2.INTER_NEAREST)
                upscaled_bgr = cv2.cvtColor(upscaled, cv2.COLOR_RGB2BGR)

                canvas = np.zeros((640, 640, 3), dtype=np.uint8) + 40  # dark gray background
                offset_x, offset_y = 64, 64
                canvas[offset_y:offset_y+512, offset_x:offset_x+512] = upscaled_bgr

                # Detect anchors via hierarchical tree
                anchors = tracker.find_anchors(canvas)
                self.assertIsNotNone(anchors, f"Failed to detect anchors for size={size}, mode={mode}")
                self.assertEqual(anchors.shape, (4, 2))

                # Verify expected canonical anchor positions in canvas coordinates
                # Center of 5x5 anchor at (2.5/size * 512) + offset
                c = 2.5 / float(size)
                expected_tl = np.array([offset_x + c * 512.0, offset_y + c * 512.0])
                expected_tr = np.array([offset_x + (1.0 - c) * 512.0, offset_y + c * 512.0])
                expected_br = np.array([offset_x + (1.0 - c) * 512.0, offset_y + (1.0 - c) * 512.0])
                expected_bl = np.array([offset_x + c * 512.0, offset_y + (1.0 - c) * 512.0])

                # Centroids must match within 2.5 pixels
                np.testing.assert_allclose(anchors[0], expected_tl, atol=2.5, err_msg=f"TL anchor centroid error at size {size}")
                np.testing.assert_allclose(anchors[1], expected_tr, atol=2.5, err_msg=f"TR anchor centroid error at size {size}")
                np.testing.assert_allclose(anchors[2], expected_br, atol=2.5, err_msg=f"BR anchor centroid error at size {size}")
                np.testing.assert_allclose(anchors[3], expected_bl, atol=2.5, err_msg=f"BL anchor centroid error at size {size}")

    def test_anchor_detection_with_ui_clutter_and_text(self):
        """
        Ensures the anchor detector isolates the 4 true ChromaBeam matrix anchors from surrounding
        desktop UI text, taskbars, windows, and icons.
        """
        tracker = OpticalTracker(target_grid_dim=512)
        layout = ColorMatrixLayout(grid_size=48, color_mode=MODE_3BIT_8COLOR)
        payload = b"UI-Clutter-Test-Data"
        pkt = pack_packet(file_id=42, total_blocks=1, block_size=len(payload), seed=1, payload=payload)
        grid = bytes_to_color_grid(pkt, layout)

        upscaled = cv2.resize(grid, (480, 480), interpolation=cv2.INTER_NEAREST)
        upscaled_bgr = cv2.cvtColor(upscaled, cv2.COLOR_RGB2BGR)

        # Create large desktop canvas (720x960)
        canvas = np.zeros((720, 960, 3), dtype=np.uint8) + 30

        # Place ChromaBeam matrix in center
        ox, oy = 240, 120
        canvas[oy:oy+480, ox:ox+480] = upscaled_bgr

        # Add heavy desktop UI clutter around the matrix:
        # 1. Desktop Taskbar along bottom
        cv2.rectangle(canvas, (0, 670), (960, 720), (50, 50, 50), -1)
        for tx in range(20, 900, 80):
            cv2.rectangle(canvas, (tx, 675), (tx + 60, 715), (120, 120, 120), -1)
            cv2.putText(canvas, "App", (tx + 5, 700), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

        # 2. Window Titlebar with buttons along top
        cv2.rectangle(canvas, (ox - 20, oy - 40), (ox + 500, oy), (70, 70, 70), -1)
        cv2.putText(canvas, "ChromaBeam Pro Receiver v2.0 - Active Beam", (ox, oy - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.circle(canvas, (ox + 460, oy - 20), 8, (0, 0, 255), -1)
        cv2.circle(canvas, (ox + 480, oy - 20), 8, (0, 255, 0), -1)

        # 3. Dense paragraphs of surrounding text & random small squares
        for ty in range(50, 600, 30):
            cv2.putText(canvas, "Lorem ipsum dolor sit amet nested text", (20, ty),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
            cv2.putText(canvas, "System Diagnostic 0xDEADBEEF 100%", (750, ty),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 180), 1)

        # Detect anchors
        anchors = tracker.find_anchors(canvas)
        self.assertIsNotNone(anchors, "Anchor detector failed to reject UI clutter and isolate matrix")

        # Verify detected anchors are within 2.5px of true positions
        c = 2.5 / 48.0
        expected_tl = np.array([ox + c * 480.0, oy + c * 480.0])
        np.testing.assert_allclose(anchors[0], expected_tl, atol=2.5)

    def test_direct_canonical_homography_warp(self):
        """
        Verifies that tracker.warp_matrix maps the 4 anchor centers directly to
        canonical coordinates (2.5/N, 2.5/N) without extrapolation drift.
        """
        tracker = OpticalTracker(target_grid_dim=512)
        grid_size = 48
        layout = ColorMatrixLayout(grid_size=grid_size, color_mode=MODE_2BIT_4COLOR)
        payload = b"WarpCheck"
        pkt = pack_packet(file_id=1, total_blocks=1, block_size=len(payload), seed=0, payload=payload)
        grid = bytes_to_color_grid(pkt, layout)

        upscaled = cv2.resize(grid, (512, 512), interpolation=cv2.INTER_NEAREST)
        upscaled_bgr = cv2.cvtColor(upscaled, cv2.COLOR_RGB2BGR)

        # Synthesize a camera frame with perspective transformation (e.g. tilted phone camera)
        src_corners = np.array([[0, 0], [512, 0], [512, 512], [0, 512]], dtype=np.float32)
        tilted_corners = np.array([[80, 60], [560, 40], [590, 580], [40, 550]], dtype=np.float32)
        M_tilt = cv2.getPerspectiveTransform(src_corners, tilted_corners)
        tilted_frame = cv2.warpPerspective(upscaled_bgr, M_tilt, (640, 640))

        # Find anchors and warp back
        anchors = tracker.find_anchors(tilted_frame)
        self.assertIsNotNone(anchors)

        warped = tracker.warp_matrix(tilted_frame, anchors, grid_size=grid_size)
        self.assertEqual(warped.shape, (512, 512, 3))

        # Sample grid from warped image and verify 100% bit recovery
        sampled_grid = tracker.sample_grid_cells(warped, grid_size=grid_size)
        raw_bytes = color_grid_to_bytes(sampled_grid, layout)
        res = unpack_packet(raw_bytes)
        self.assertIsNotNone(res, "Failed to recover packet from perspective-warped frame")
        header, unpacked_payload = res
        self.assertEqual(unpacked_payload, b"WarpCheck")

    def test_find_matrix_interface_contract(self):
        """Validates MatrixTracker.find_matrix(frame) interface contract."""
        tracker = MatrixTracker(target_grid_dim=512)
        layout = ColorMatrixLayout(grid_size=32, color_mode=MODE_1BIT_BW)
        payload = b"Contract"
        pkt = pack_packet(file_id=5, total_blocks=1, block_size=len(payload), seed=0, payload=payload)
        grid = bytes_to_color_grid(pkt, layout)
        bgr = cv2.cvtColor(cv2.resize(grid, (512, 512), interpolation=cv2.INTER_NEAREST), cv2.COLOR_RGB2BGR)

        warped, quad, status = tracker.find_matrix(bgr, grid_size=32)
        self.assertTrue(status)
        self.assertIsNotNone(warped)
        self.assertEqual(warped.shape, (512, 512, 3))
        self.assertIsNotNone(quad)
        self.assertEqual(quad.shape, (4, 2))

    def test_360_4way_rotation_invariance_all_modes(self):
        """
        Tests 360° 4-way rotation invariance (0°, 90°, 180°, 270°) across:
        - 1-Bit B&W Potato Mode
        - 2-Bit 4-Color Balanced Mode
        - 3-Bit 8-Color Turbo Mode
        Verifies 100% packet decoding when the camera or screen is held in any 90-degree orientation.
        """
        for mode in [MODE_1BIT_BW, MODE_2BIT_4COLOR, MODE_3BIT_8COLOR]:
            for size in [32, 48, 64]:
                layout = ColorMatrixLayout(grid_size=size, color_mode=mode)
                test_payload = os.urandom(min(layout.max_payload_bytes - 16, 40))
                pkt = pack_packet(file_id=100 + mode, total_blocks=1, block_size=len(test_payload), seed=42, payload=test_payload)
                grid = bytes_to_color_grid(pkt, layout)

                upscaled = cv2.resize(grid, (512, 512), interpolation=cv2.INTER_NEAREST)
                base_frame = cv2.cvtColor(upscaled, cv2.COLOR_RGB2BGR)

                for rot_deg in [0, 90, 180, 270]:
                    # Rotate the physical camera frame
                    if rot_deg == 0:
                        frame = base_frame.copy()
                    elif rot_deg == 90:
                        frame = cv2.rotate(base_frame, cv2.ROTATE_90_CLOCKWISE)
                    elif rot_deg == 180:
                        frame = cv2.rotate(base_frame, cv2.ROTATE_180)
                    elif rot_deg == 270:
                        frame = cv2.rotate(base_frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

                    receiver = ChromaBeamReceiver(grid_size=size, auto_density=True)
                    annotated, stats = receiver.process_frame(frame)

                    self.assertTrue(stats["locked"], f"Failed to lock frame at mode={mode}, size={size}, rot={rot_deg}°")
                    self.assertEqual(stats["packets"], 1, f"Failed to decode packet at mode={mode}, size={size}, rot={rot_deg}°")
                    self.assertEqual(stats["crc_errors"], 0, f"CRC error occurred at mode={mode}, size={size}, rot={rot_deg}°")

    def test_auto_density_sweeping(self):
        """
        Verifies auto-density sweeping correctly detects and decodes 32x32, 48x48, and 64x64
        without requiring manual receiver density lock.
        """
        receiver = ChromaBeamReceiver(grid_size=None, auto_density=True)

        for size in [32, 48, 64]:
            layout = ColorMatrixLayout(grid_size=size, color_mode=MODE_2BIT_4COLOR)
            test_payload = f"AutoDensity_{size}x{size}".encode('utf-8')
            pkt = pack_packet(file_id=200 + size, total_blocks=1, block_size=len(test_payload), seed=7, payload=test_payload)
            grid = bytes_to_color_grid(pkt, layout)

            upscaled = cv2.resize(grid, (512, 512), interpolation=cv2.INTER_NEAREST)
            frame = cv2.cvtColor(upscaled, cv2.COLOR_RGB2BGR)

            annotated, stats = receiver.process_frame(frame)
            self.assertTrue(stats["locked"])
            self.assertEqual(stats["density"], size, f"Expected auto-detected density {size}, got {stats['density']}")
            self.assertEqual(stats["mode"], MODE_2BIT_4COLOR)


    def test_empty_or_corrupt_frames_handling(self):
        """Verifies tracker handles empty, None, solid color, and irregular frames gracefully without exceptions."""
        tracker = OpticalTracker(target_grid_dim=512)

        # None frame
        self.assertEqual(find_nested_anchor_centers(None), [])
        warped, quad, status = tracker.find_matrix(None)
        self.assertFalse(status)
        self.assertIsNone(warped)
        self.assertIsNone(quad)

        # Zero-sized frame
        empty_frame = np.zeros((0, 0, 3), dtype=np.uint8)
        self.assertEqual(find_nested_anchor_centers(empty_frame), [])
        warped, quad, status = tracker.find_matrix(empty_frame)
        self.assertFalse(status)

        # Solid black and solid white frames
        solid_black = np.zeros((480, 640, 3), dtype=np.uint8)
        self.assertEqual(find_nested_anchor_centers(solid_black), [])
        solid_white = np.ones((480, 640, 3), dtype=np.uint8) * 255
        self.assertEqual(find_nested_anchor_centers(solid_white), [])

        # Single channel grayscale frame
        gray_frame = np.random.randint(0, 255, (200, 200), dtype=np.uint8)
        anchors = tracker.find_anchors(gray_frame)
        # Random noise shouldn't form a valid 4-anchor matrix
        self.assertIsNone(anchors)

    def test_anchor_detection_false_positive_rejection(self):
        """Verifies anchor detector rejects circles, line patterns, single concentric shapes, and non-matrix quads."""
        tracker = OpticalTracker(target_grid_dim=512)
        canvas = np.zeros((600, 800, 3), dtype=np.uint8) + 40

        # Draw non-matching nested shapes (e.g. concentric circles, thick rectangles)
        for cx, cy in [(100, 100), (300, 100), (500, 100)]:
            cv2.circle(canvas, (cx, cy), 30, (255, 255, 255), -1)
            cv2.circle(canvas, (cx, cy), 20, (0, 0, 0), -1)
            cv2.circle(canvas, (cx, cy), 10, (255, 255, 255), -1)

        # Draw barcode-like stripes
        for x in range(50, 750, 15):
            cv2.line(canvas, (x, 300), (x, 400), (255, 255, 255), 3)

        # Draw only 3 valid-looking anchor patterns (insufficient for a 4-point matrix)
        for ax, ay in [(150, 450), (450, 450), (150, 550)]:
            # 5x5 block with 1:1:1:1:1 pattern
            sub = np.zeros((50, 50, 3), dtype=np.uint8) + 255
            sub[10:40, 10:40] = 0
            sub[20:30, 20:30] = 255
            canvas[ay:ay+50, ax:ax+50] = sub

        # Should not lock onto a complete 4-anchor matrix
        anchors = tracker.find_anchors(canvas)
        self.assertIsNone(anchors, "Should reject canvas with fewer than 4 valid matrix anchors")

    def test_severe_perspective_distortion_and_recovery(self):
        """Tests that severe perspective distortion (up to 40° trapezoidal tilt) across all 3 color modes is restored."""
        tracker = OpticalTracker(target_grid_dim=512)

        for mode in [MODE_1BIT_BW, MODE_2BIT_4COLOR, MODE_3BIT_8COLOR]:
            size = 48
            layout = ColorMatrixLayout(grid_size=size, color_mode=mode)
            payload = f"PerspectiveRecovery_Mode_{mode}".encode('utf-8')
            pkt = pack_packet(file_id=50 + mode, total_blocks=1, block_size=len(payload), seed=12, payload=payload)
            grid = bytes_to_color_grid(pkt, layout)

            upscaled = cv2.resize(grid, (480, 480), interpolation=cv2.INTER_NEAREST)
            bgr = cv2.cvtColor(upscaled, cv2.COLOR_RGB2BGR)

            # Apply severe 3D perspective warp
            src = np.array([[0, 0], [480, 0], [480, 480], [0, 480]], dtype=np.float32)
            dst = np.array([[120, 60], [580, 30], [540, 560], [60, 500]], dtype=np.float32)
            M = cv2.getPerspectiveTransform(src, dst)
            tilted_canvas = cv2.warpPerspective(bgr, M, (640, 640))

            anchors = tracker.find_anchors(tilted_canvas)
            self.assertIsNotNone(anchors, f"Failed to detect anchors under severe tilt for mode {mode}")

            warped = tracker.warp_matrix(tilted_canvas, anchors, grid_size=size)
            sampled = tracker.sample_grid_cells(warped, grid_size=size)
            raw = color_grid_to_bytes(sampled, layout)
            res = unpack_packet(raw)
            self.assertIsNotNone(res, f"Failed to decode packet under severe tilt for mode {mode}")
            _, decoded_payload = res
            self.assertEqual(decoded_payload, payload)

    def test_interleaved_densities_and_rotations(self):
        """Tests sequential processing of frames alternating densities and rotations in a single receiver."""
        receiver = ChromaBeamReceiver(grid_size=None, auto_density=True)

        sequence = [
            (32, MODE_1BIT_BW, 0, b"Step1-32-Rot0"),
            (64, MODE_3BIT_8COLOR, 90, b"Step2-64-Rot90"),
            (48, MODE_2BIT_4COLOR, 180, b"Step3-48-Rot180"),
            (32, MODE_1BIT_BW, 270, b"Step4-32-Rot270"),
            (48, MODE_2BIT_4COLOR, 0, b"Step5-48-Rot0"),
        ]

        for step_idx, (size, mode, rot_deg, payload) in enumerate(sequence):
            layout = ColorMatrixLayout(grid_size=size, color_mode=mode)
            pkt = pack_packet(file_id=300 + step_idx, total_blocks=1, block_size=len(payload), seed=step_idx, payload=payload)
            grid = bytes_to_color_grid(pkt, layout)

            upscaled = cv2.resize(grid, (512, 512), interpolation=cv2.INTER_NEAREST)
            base_frame = cv2.cvtColor(upscaled, cv2.COLOR_RGB2BGR)

            if rot_deg == 90:
                frame = cv2.rotate(base_frame, cv2.ROTATE_90_CLOCKWISE)
            elif rot_deg == 180:
                frame = cv2.rotate(base_frame, cv2.ROTATE_180)
            elif rot_deg == 270:
                frame = cv2.rotate(base_frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
            else:
                frame = base_frame

            annotated, stats = receiver.process_frame(frame)
            self.assertTrue(stats["locked"], f"Failed lock at step {step_idx}")
            self.assertEqual(stats["density"], size, f"Density mismatch at step {step_idx}")
            self.assertEqual(stats["mode"], mode, f"Mode mismatch at step {step_idx}")
            expected_unrotation = (360 - rot_deg) % 360
            self.assertEqual(stats["rotation"], expected_unrotation, f"Rotation mismatch at step {step_idx}")
            self.assertEqual(stats["packets"], step_idx + 1, f"Packet count mismatch at step {step_idx}")


if __name__ == '__main__':
    unittest.main()

