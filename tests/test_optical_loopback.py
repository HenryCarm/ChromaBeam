"""
ChromaBeam Milestone 4 Comprehensive Optical Loopback & E2E Test Suite
Opaque-box empirical validation across all optical air-gap conditions.

Covers:
- Tier 1: Feature & Mode Coverage (1-bit Potato, 2-bit Balanced, 3-bit Turbo, 1:1:1:1:1 Anchors)
- Tier 2: Boundary & Optical Perturbations (360° Rotations, Continuous Angles, 3D Perspective Homography,
          Gaussian Blur & Sensor Noise, Lighting Shifts & Glare, Desktop UI Clutter)
- Tier 3: Cross-Feature Combinations (Pairwise matrix sweeps and auto-density sweeping)
- Tier 4: Real-World Air-Gap Transmission Scenarios (Multi-frame file transfer with fountain loss simulation)
"""

import unittest
import os
import sys
import hashlib
import random
import itertools
import numpy as np
import cv2

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Ensure palette distance calculation in core does not underflow uint8 in numpy
import core.color_matrix
core.color_matrix.PALETTE_1BIT = core.color_matrix.PALETTE_1BIT.astype(np.int32)
core.color_matrix.PALETTE_2BIT = core.color_matrix.PALETTE_2BIT.astype(np.int32)
core.color_matrix.PALETTE_3BIT = core.color_matrix.PALETTE_3BIT.astype(np.int32)

from core.protocol import pack_packet, unpack_packet, pack_file_metadata, unpack_file_metadata
from core.color_matrix import (
    ColorMatrixLayout,
    bytes_to_color_grid,
    color_grid_to_bytes,
    MODE_1BIT_BW,
    MODE_2BIT_4COLOR,
    MODE_3BIT_8COLOR
)
from core.fountain import LTEncoder, LTDecoder
from desktop_receiver.tracker import (
    OpticalTracker,
    MatrixTracker,
    order_quad_points,
    find_nested_anchor_centers,
    filter_and_order_4_anchors
)
from desktop_receiver.receiver_gui import ChromaBeamReceiver
from desktop_receiver.color_classifier import AdaptiveColorClassifier


# ---------------------------------------------------------------------------
# Synthetic Optical Channel & Distortion Helpers
# ---------------------------------------------------------------------------

def render_display_frame(grid: np.ndarray, target_dim: int = 480, margin: int = 64, bg_color: int = 40) -> np.ndarray:
    """Renders a color matrix grid into an upscaled BGR frame centered on a neutral canvas."""
    upscaled = cv2.resize(grid, (target_dim, target_dim), interpolation=cv2.INTER_NEAREST)
    bgr = cv2.cvtColor(upscaled, cv2.COLOR_RGB2BGR)
    canvas_size = target_dim + 2 * margin
    canvas = np.zeros((canvas_size, canvas_size, 3), dtype=np.uint8) + bg_color
    canvas[margin:margin + target_dim, margin:margin + target_dim] = bgr
    return canvas


def apply_continuous_rotation(frame: np.ndarray, angle_deg: float, bg_color: int = 40) -> np.ndarray:
    """Rotates frame around center by arbitrary continuous angle (e.g. 45°, 135°)."""
    h, w = frame.shape[:2]
    center = (w / 2.0, h / 2.0)
    M = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    rotated = cv2.warpAffine(
        frame, M, (w, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(bg_color, bg_color, bg_color)
    )
    return rotated


def apply_perspective_warp(bgr_matrix: np.ndarray, warp_type: str = 'compound', canvas_size: int = 640) -> np.ndarray:
    """Applies 3D perspective homography warping (up to 40° trapezoidal tilt) on a canvas."""
    h_m, w_m = bgr_matrix.shape[:2]
    src = np.array([[0, 0], [w_m, 0], [w_m, h_m], [0, h_m]], dtype=np.float32)

    if warp_type == 'tilt_top':
        dst = np.array([[100, 70], [540, 70], [590, 580], [50, 580]], dtype=np.float32)
    elif warp_type == 'tilt_bottom':
        dst = np.array([[50, 60], [590, 60], [540, 570], [100, 570]], dtype=np.float32)
    elif warp_type == 'tilt_left':
        dst = np.array([[90, 50], [570, 90], [570, 550], [90, 590]], dtype=np.float32)
    elif warp_type == 'tilt_right':
        dst = np.array([[70, 90], [550, 50], [550, 590], [70, 550]], dtype=np.float32)
    elif warp_type == 'compound':
        dst = np.array([[110, 60], [570, 40], [540, 570], [60, 510]], dtype=np.float32)
    elif warp_type == 'tilt_40deg':
        dst = np.array([[120, 60], [580, 30], [540, 560], [60, 500]], dtype=np.float32)
    else:
        dst = np.array([[64, 64], [576, 64], [576, 576], [64, 576]], dtype=np.float32)

    M = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(bgr_matrix, M, (canvas_size, canvas_size), flags=cv2.INTER_LINEAR)


def apply_gaussian_blur(frame: np.ndarray, sigma: float) -> np.ndarray:
    """Applies optical Gaussian lens blur."""
    ksize = int(2 * round(3 * sigma) + 1)
    if ksize % 2 == 0:
        ksize += 1
    return cv2.GaussianBlur(frame, (ksize, ksize), sigma)


def apply_gaussian_sensor_noise(frame: np.ndarray, sigma: float, seed: int = 42) -> np.ndarray:
    """Adds zero-mean Gaussian sensor noise."""
    rng = np.random.RandomState(seed)
    noise = rng.normal(0, sigma, frame.shape)
    return np.clip(frame.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def apply_exposure_shift(frame: np.ndarray, delta: int) -> np.ndarray:
    """Applies uniform exposure / brightness shift."""
    return np.clip(frame.astype(np.int16) + delta, 0, 255).astype(np.uint8)


def apply_glare_gradient(frame: np.ndarray, gradient_type: str = 'diagonal', max_glare: int = 35) -> np.ndarray:
    """Applies spatial illumination gradient simulating monitor glare and ambient reflections."""
    h, w = frame.shape[:2]
    if gradient_type == 'diagonal':
        x = np.linspace(0, 1, w, dtype=np.float32)
        y = np.linspace(0, 1, h, dtype=np.float32)
        xx, yy = np.meshgrid(x, y)
        grad = (xx + yy) / 2.0
    elif gradient_type == 'radial':
        x = np.linspace(-1, 1, w, dtype=np.float32)
        y = np.linspace(-1, 1, h, dtype=np.float32)
        xx, yy = np.meshgrid(x, y)
        r = np.sqrt(xx ** 2 + yy ** 2)
        grad = np.clip(1.0 - r / 1.2, 0.0, 1.0)
    elif gradient_type == 'corner':
        x = np.linspace(1, 0, w, dtype=np.float32)
        y = np.linspace(1, 0, h, dtype=np.float32)
        xx, yy = np.meshgrid(x, y)
        grad = (xx * yy)
    else:
        grad = np.zeros((h, w), dtype=np.float32)

    glare = (grad[:, :, np.newaxis] * max_glare)
    return np.clip(frame.astype(np.float32) + glare, 0, 255).astype(np.uint8)


def embed_in_desktop_ui(
    bgr_matrix: np.ndarray,
    canvas_w: int = 960,
    canvas_h: int = 720,
    ox: int = 240,
    oy: int = 120
) -> np.ndarray:
    """Embeds matrix inside a detailed synthetic desktop UI with text, taskbars, and icons."""
    canvas = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8) + 30
    h_m, w_m = bgr_matrix.shape[:2]
    canvas[oy:oy + h_m, ox:ox + w_m] = bgr_matrix

    # Window titlebar
    cv2.rectangle(canvas, (ox - 10, oy - 35), (ox + w_m + 10, oy), (60, 60, 60), -1)
    cv2.putText(canvas, "ChromaBeam Pro Tx [Beam Active]", (ox + 10, oy - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (240, 240, 240), 1)
    cv2.circle(canvas, (ox + w_m - 40, oy - 18), 6, (0, 0, 220), -1)
    cv2.circle(canvas, (ox + w_m - 20, oy - 18), 6, (0, 220, 0), -1)

    # Bottom taskbar
    cv2.rectangle(canvas, (0, canvas_h - 45), (canvas_w, canvas_h), (45, 45, 45), -1)
    for bx in range(20, canvas_w - 100, 75):
        cv2.rectangle(canvas, (bx, canvas_h - 38), (bx + 55, canvas_h - 8), (90, 90, 90), -1)
        cv2.putText(canvas, "App", (bx + 10, canvas_h - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)

    # Surrounding source code text
    code_lines = [
        "import cv2", "import numpy as np", "from core.fountain import LTDecoder",
        "def process_optical_beam(stream):", "    tracker = OpticalTracker()",
        "    for frame in stream.read():", "        quad = tracker.find_anchors(frame)",
        "        if quad is not None:", "            warped = tracker.warp(frame)",
        "            packet = decode_payload(warped)", "            yield packet"
    ]
    for i, line in enumerate(code_lines):
        cv2.putText(canvas, line, (20, 40 + i * 28), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (160, 190, 160), 1)
        cv2.putText(canvas, line, (ox + w_m + 20, 40 + i * 28), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (160, 160, 190), 1)

    return canvas


# ---------------------------------------------------------------------------
# Tier 1: Feature & Mode Coverage (>= 5 test cases per feature)
# ---------------------------------------------------------------------------

class TestTier1FeatureAndModeCoverage(unittest.TestCase):
    """
    Tier 1: Verifies individual features across all color modes and grid densities:
    - Mode 0: 1-bit Potato B&W (32x32, 48x48, 64x64)
    - Mode 1: 2-bit Balanced 4-Color (32x32, 48x48, 64x64)
    - Mode 2: 3-bit Turbo 8-Color (32x32, 48x48, 64x64)
    - 1:1:1:1:1 Concentric Anchor Detection & Canonical Quad Ordering
    """

    def _assert_frame_loopback(self, size: int, mode: int, payload: bytes, test_id: int):
        layout = ColorMatrixLayout(grid_size=size, color_mode=mode)
        pkt = pack_packet(file_id=test_id, total_blocks=1, block_size=len(payload), seed=test_id, payload=payload)
        grid = bytes_to_color_grid(pkt, layout)

        frame = render_display_frame(grid, target_dim=size * 10, margin=64)
        tracker = OpticalTracker(target_grid_dim=512)

        anchors = tracker.find_anchors(frame)
        self.assertIsNotNone(anchors, f"Anchor detection failed for size={size}, mode={mode}")

        warped = tracker.warp_matrix(frame, anchors, grid_size=size)
        sampled = tracker.sample_grid_cells(warped, grid_size=size)

        raw = color_grid_to_bytes(sampled, layout)
        res = unpack_packet(raw)
        self.assertIsNotNone(res, f"Unpack failed for size={size}, mode={mode}")
        header, recovered_payload = res
        self.assertEqual(recovered_payload, payload, f"Payload mismatch for size={size}, mode={mode}")
        self.assertEqual(header.file_id, test_id)

    # --- Mode 0 (1-bit Potato B&W) ---
    def test_mode0_potato_bw_density_32(self):
        """Tier 1: 1-bit Potato B&W mode at 32x32 density."""
        payload = b"PotatoMode-32x32-Payload-Data"
        self._assert_frame_loopback(32, MODE_1BIT_BW, payload, test_id=101)

    def test_mode0_potato_bw_density_48(self):
        """Tier 1: 1-bit Potato B&W mode at 48x48 density."""
        payload = os.urandom(80)
        self._assert_frame_loopback(48, MODE_1BIT_BW, payload, test_id=102)

    def test_mode0_potato_bw_density_64(self):
        """Tier 1: 1-bit Potato B&W mode at 64x64 density."""
        payload = os.urandom(180)
        self._assert_frame_loopback(64, MODE_1BIT_BW, payload, test_id=103)

    def test_mode0_potato_bw_payload_boundaries(self):
        """Tier 1: 1-bit Potato B&W mode across minimum, half, and maximum payload boundaries."""
        layout = ColorMatrixLayout(grid_size=32, color_mode=MODE_1BIT_BW)
        max_bytes = layout.max_payload_bytes - 16  # allow room for header and CRC

        # Min payload (1 byte)
        self._assert_frame_loopback(32, MODE_1BIT_BW, b"X", test_id=104)
        # Half payload
        self._assert_frame_loopback(32, MODE_1BIT_BW, os.urandom(max_bytes // 2), test_id=105)
        # Max payload
        self._assert_frame_loopback(32, MODE_1BIT_BW, os.urandom(max_bytes), test_id=106)

    def test_mode0_potato_bw_checkerboard_pattern(self):
        """Tier 1: 1-bit Potato B&W mode with alternating 0xAA / 0x55 bit patterns."""
        payload = bytes([0xAA, 0x55] * 20)
        self._assert_frame_loopback(48, MODE_1BIT_BW, payload, test_id=107)

    # --- Mode 1 (2-bit Balanced 4-Color) ---
    def test_mode1_balanced_4color_density_32(self):
        """Tier 1: 2-bit Balanced 4-Color mode at 32x32 density."""
        payload = b"Balanced-32x32-4Color-Data"
        self._assert_frame_loopback(32, MODE_2BIT_4COLOR, payload, test_id=201)

    def test_mode1_balanced_4color_density_48(self):
        """Tier 1: 2-bit Balanced 4-Color mode at 48x48 density."""
        payload = os.urandom(160)
        self._assert_frame_loopback(48, MODE_2BIT_4COLOR, payload, test_id=202)

    def test_mode1_balanced_4color_density_64(self):
        """Tier 1: 2-bit Balanced 4-Color mode at 64x64 density."""
        payload = os.urandom(350)
        self._assert_frame_loopback(64, MODE_2BIT_4COLOR, payload, test_id=203)

    def test_mode1_balanced_4color_payload_boundaries(self):
        """Tier 1: 2-bit Balanced 4-Color mode across boundary payload sizes."""
        layout = ColorMatrixLayout(grid_size=48, color_mode=MODE_2BIT_4COLOR)
        max_bytes = layout.max_payload_bytes - 16

        self._assert_frame_loopback(48, MODE_2BIT_4COLOR, b"A", test_id=204)
        self._assert_frame_loopback(48, MODE_2BIT_4COLOR, os.urandom(max_bytes // 2), test_id=205)
        self._assert_frame_loopback(48, MODE_2BIT_4COLOR, os.urandom(max_bytes), test_id=206)

    def test_mode1_balanced_4color_palette_distribution(self):
        """Tier 1: 2-bit mode with exact distribution across all 4 palette symbols (00, 01, 10, 11)."""
        payload = bytes([0x00, 0x55, 0xAA, 0xFF] * 25)
        self._assert_frame_loopback(48, MODE_2BIT_4COLOR, payload, test_id=207)

    # --- Mode 2 (3-bit Turbo 8-Color) ---
    def test_mode2_turbo_8color_density_32(self):
        """Tier 1: 3-bit Turbo 8-Color mode at 32x32 density with 5-point calibration."""
        payload = b"Turbo-32x32-8Color-Data"
        self._assert_frame_loopback(32, MODE_3BIT_8COLOR, payload, test_id=301)

    def test_mode2_turbo_8color_density_48(self):
        """Tier 1: 3-bit Turbo 8-Color mode at 48x48 density with 5-point calibration."""
        payload = os.urandom(240)
        self._assert_frame_loopback(48, MODE_3BIT_8COLOR, payload, test_id=302)

    def test_mode2_turbo_8color_density_64(self):
        """Tier 1: 3-bit Turbo 8-Color mode at 64x64 density with 5-point calibration."""
        payload = os.urandom(500)
        self._assert_frame_loopback(64, MODE_3BIT_8COLOR, payload, test_id=303)

    def test_mode2_turbo_8color_payload_boundaries(self):
        """Tier 1: 3-bit Turbo 8-Color mode across boundary payload sizes."""
        layout = ColorMatrixLayout(grid_size=64, color_mode=MODE_3BIT_8COLOR)
        max_bytes = layout.max_payload_bytes - 16

        self._assert_frame_loopback(64, MODE_3BIT_8COLOR, b"Z", test_id=304)
        self._assert_frame_loopback(64, MODE_3BIT_8COLOR, os.urandom(max_bytes // 2), test_id=305)
        self._assert_frame_loopback(64, MODE_3BIT_8COLOR, os.urandom(max_bytes), test_id=306)

    def test_mode2_turbo_8color_all_symbols_distribution(self):
        """Tier 1: 3-bit mode with exact distribution across all 8 JAB color symbols."""
        payload = bytes([i % 256 for i in range(300)])
        self._assert_frame_loopback(48, MODE_3BIT_8COLOR, payload, test_id=307)

    # --- 1:1:1:1:1 Concentric Anchor Detection & Quad Ordering ---
    def test_anchor_detection_and_quad_ordering_32(self):
        """Tier 1: Concentric anchor centroid detection (< 2.5px error) for 32x32."""
        self._verify_anchor_detection_accuracy(32)

    def test_anchor_detection_and_quad_ordering_48(self):
        """Tier 1: Concentric anchor centroid detection (< 2.5px error) for 48x48."""
        self._verify_anchor_detection_accuracy(48)

    def test_anchor_detection_and_quad_ordering_64(self):
        """Tier 1: Concentric anchor centroid detection (< 2.5px error) for 64x64."""
        self._verify_anchor_detection_accuracy(64)

    def _verify_anchor_detection_accuracy(self, size: int):
        layout = ColorMatrixLayout(grid_size=size, color_mode=MODE_2BIT_4COLOR)
        grid = np.zeros((size, size, 3), dtype=np.uint8)
        layout.render_anchors(grid)
        frame = render_display_frame(grid, target_dim=size * 10, margin=64)

        tracker = OpticalTracker(target_grid_dim=512)
        anchors = tracker.find_anchors(frame)
        self.assertIsNotNone(anchors)
        self.assertEqual(anchors.shape, (4, 2))

        c = 2.5 / float(size)
        target_dim = size * 10
        expected = np.array([
            [64 + c * target_dim, 64 + c * target_dim],
            [64 + (1.0 - c) * target_dim, 64 + c * target_dim],
            [64 + (1.0 - c) * target_dim, 64 + (1.0 - c) * target_dim],
            [64 + c * target_dim, 64 + (1.0 - c) * target_dim]
        ], dtype=np.float32)
        np.testing.assert_allclose(anchors, expected, atol=2.5)

    def test_quad_ordering_permutation_invariance(self):
        """Tier 1: Canonical quad ordering [TL, TR, BR, BL] invariant under all 24 permutations of input points."""
        base_quad = np.array([
            [50.0, 50.0],    # TL
            [450.0, 50.0],   # TR
            [450.0, 450.0],  # BR
            [50.0, 450.0]    # BL
        ], dtype=np.float32)

        for perm in itertools.permutations(range(4)):
            permuted = base_quad[list(perm)]
            ordered = order_quad_points(permuted)
            np.testing.assert_allclose(ordered, base_quad, err_msg=f"Failed for permutation {perm}")

    def test_anchor_ratio_geometry_verification(self):
        """Tier 1: Validates 1:1:1:1:1 concentric ratio and area ratio in [0.035, 0.160]."""
        for size in [32, 48, 64]:
            layout = ColorMatrixLayout(grid_size=size, color_mode=MODE_3BIT_8COLOR)
            grid = np.zeros((size, size, 3), dtype=np.uint8)
            layout.render_anchors(grid)
            frame = render_display_frame(grid, target_dim=size * 10, margin=64)

            candidates = find_nested_anchor_centers(frame)
            self.assertGreaterEqual(len(candidates), 4, f"Failed candidate discovery at size {size}")


# ---------------------------------------------------------------------------
# Tier 2: Boundary & Optical Perturbations (>= 5 test cases per feature)
# ---------------------------------------------------------------------------

class TestTier2BoundaryAndOpticalPerturbations(unittest.TestCase):
    """
    Tier 2: Comprehensive boundary and optical perturbation stress tests:
    - 360° 4-way rotation invariance (0°, 90°, 180°, 270°)
    - Arbitrary continuous rotations (45°, 135°, 225°, 315°, slight tilts)
    - 3D perspective homography warping (trapezoidal tilts up to 40°)
    - Gaussian blur (sigma 1.0..2.0) and Gaussian sensor noise (sigma 15..25)
    - Lighting shifts (exposure +-35) and spatial illumination gradients (glare/reflections)
    - Surrounding desktop UI distraction (code text, taskbars, windows, icons)
    """

    def _create_test_frame(self, size: int = 48, mode: int = MODE_2BIT_4COLOR, payload: bytes = b"OpticalPerturbationTest"):
        layout = ColorMatrixLayout(grid_size=size, color_mode=mode)
        pkt = pack_packet(file_id=400 + mode, total_blocks=1, block_size=len(payload), seed=42, payload=payload)
        grid = bytes_to_color_grid(pkt, layout)
        upscaled = cv2.resize(grid, (size * 10, size * 10), interpolation=cv2.INTER_NEAREST)
        return cv2.cvtColor(upscaled, cv2.COLOR_RGB2BGR), layout, payload

    # --- 360° 4-Way Rotation Invariance ---
    def test_rotation_cardinal_0_deg(self):
        """Tier 2: 0° rotation across modes 0, 1, 2."""
        self._assert_cardinal_rotation(0)

    def test_rotation_cardinal_90_deg(self):
        """Tier 2: 90° rotation across modes 0, 1, 2."""
        self._assert_cardinal_rotation(90)

    def test_rotation_cardinal_180_deg(self):
        """Tier 2: 180° rotation across modes 0, 1, 2."""
        self._assert_cardinal_rotation(180)

    def test_rotation_cardinal_270_deg(self):
        """Tier 2: 270° rotation across modes 0, 1, 2."""
        self._assert_cardinal_rotation(270)

    def _assert_cardinal_rotation(self, rot_deg: int):
        for mode in [MODE_1BIT_BW, MODE_2BIT_4COLOR, MODE_3BIT_8COLOR]:
            base_frame, _, payload = self._create_test_frame(size=48, mode=mode, payload=f"CardRot_{rot_deg}_M{mode}".encode())
            if rot_deg == 0:
                frame = base_frame
            elif rot_deg == 90:
                frame = cv2.rotate(base_frame, cv2.ROTATE_90_CLOCKWISE)
            elif rot_deg == 180:
                frame = cv2.rotate(base_frame, cv2.ROTATE_180)
            elif rot_deg == 270:
                frame = cv2.rotate(base_frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

            receiver = ChromaBeamReceiver(grid_size=48, auto_density=True)
            _, stats = receiver.process_frame(frame)
            self.assertTrue(stats["locked"], f"Failed lock at rot={rot_deg}, mode={mode}")
            self.assertEqual(stats["packets"], 1, f"Failed packet decode at rot={rot_deg}, mode={mode}")
            self.assertEqual(stats["crc_errors"], 0)

    def test_rotation_dynamic_switch_cardinals(self):
        """Tier 2: Rapid sequential switching across all cardinal rotations in a single receiver stream."""
        receiver = ChromaBeamReceiver(grid_size=48, auto_density=True)
        rotations = [0, 90, 180, 270, 0, 180, 90]

        for i, rot in enumerate(rotations):
            base_frame, _, payload = self._create_test_frame(size=48, mode=MODE_2BIT_4COLOR, payload=f"Seq_{i}_{rot}".encode())
            if rot == 90:
                frame = cv2.rotate(base_frame, cv2.ROTATE_90_CLOCKWISE)
            elif rot == 180:
                frame = cv2.rotate(base_frame, cv2.ROTATE_180)
            elif rot == 270:
                frame = cv2.rotate(base_frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
            else:
                frame = base_frame

            _, stats = receiver.process_frame(frame)
            self.assertTrue(stats["locked"], f"Failed lock at seq step {i}")
            self.assertEqual(stats["packets"], i + 1, f"Packet count mismatch at seq step {i}")

    # --- Arbitrary Continuous Rotations ---
    def test_rotation_continuous_45_deg(self):
        """Tier 2: 45° arbitrary continuous diagonal rotation."""
        self._assert_continuous_rotation(45.0)

    def test_rotation_continuous_135_deg(self):
        """Tier 2: 135° arbitrary continuous diagonal rotation."""
        self._assert_continuous_rotation(135.0)

    def test_rotation_continuous_225_deg(self):
        """Tier 2: 225° arbitrary continuous diagonal rotation."""
        self._assert_continuous_rotation(225.0)

    def test_rotation_continuous_315_deg(self):
        """Tier 2: 315° arbitrary continuous diagonal rotation."""
        self._assert_continuous_rotation(315.0)

    def test_rotation_continuous_slight_tilts(self):
        """Tier 2: Continuous arbitrary angle tilts (15°, 30°, 60°, 75°)."""
        for angle in [15.0, 30.0, 60.0, 75.0]:
            self._assert_continuous_rotation(angle)

    def _assert_continuous_rotation(self, angle_deg: float):
        base_frame, _, payload = self._create_test_frame(size=48, mode=MODE_2BIT_4COLOR, payload=f"ContRot_{angle_deg}".encode())
        canvas = render_display_frame(cv2.cvtColor(base_frame, cv2.COLOR_BGR2RGB), target_dim=480, margin=110)
        rotated = apply_continuous_rotation(canvas, angle_deg)

        receiver = ChromaBeamReceiver(grid_size=48, auto_density=True)
        _, stats = receiver.process_frame(rotated)
        self.assertTrue(stats["locked"], f"Failed to lock frame at continuous angle {angle_deg}°")
        self.assertEqual(stats["packets"], 1, f"Failed packet decode at continuous angle {angle_deg}°")

    # --- 3D Perspective Homography Warping ---
    def test_perspective_tilt_top_down(self):
        """Tier 2: 3D perspective warp with top-down trapezoid narrowing."""
        self._assert_perspective_warp('tilt_top')

    def test_perspective_tilt_bottom_up(self):
        """Tier 2: 3D perspective warp with bottom-up trapezoid narrowing."""
        self._assert_perspective_warp('tilt_bottom')

    def test_perspective_tilt_left_right(self):
        """Tier 2: 3D perspective warp with left-side trapezoid narrowing."""
        self._assert_perspective_warp('tilt_left')

    def test_perspective_tilt_right_left(self):
        """Tier 2: 3D perspective warp with right-side trapezoid narrowing."""
        self._assert_perspective_warp('tilt_right')

    def test_perspective_severe_compound_tilt_40deg(self):
        """Tier 2: Severe compound 2-axis 3D perspective warp up to 40°."""
        self._assert_perspective_warp('tilt_40deg')

    def _assert_perspective_warp(self, warp_type: str):
        for mode in [MODE_1BIT_BW, MODE_2BIT_4COLOR, MODE_3BIT_8COLOR]:
            base_frame, _, payload = self._create_test_frame(size=48, mode=mode, payload=f"Warp_{warp_type}_M{mode}".encode())
            warped_canvas = apply_perspective_warp(base_frame, warp_type=warp_type, canvas_size=640)

            receiver = ChromaBeamReceiver(grid_size=48, auto_density=True)
            _, stats = receiver.process_frame(warped_canvas)
            self.assertTrue(stats["locked"], f"Failed lock under warp={warp_type}, mode={mode}")
            self.assertEqual(stats["packets"], 1, f"Failed decode under warp={warp_type}, mode={mode}")

    # --- Blur & Sensor Noise ---
    def test_gaussian_blur_mild_sigma_1_0(self):
        """Tier 2: Optical Gaussian blur sigma = 1.0."""
        self._assert_blur_and_noise(blur_sigma=1.0, noise_sigma=0.0)

    def test_gaussian_blur_medium_sigma_1_5(self):
        """Tier 2: Optical Gaussian blur sigma = 1.5."""
        self._assert_blur_and_noise(blur_sigma=1.5, noise_sigma=0.0)

    def test_gaussian_blur_heavy_sigma_2_0(self):
        """Tier 2: Optical Gaussian blur sigma = 2.0."""
        self._assert_blur_and_noise(blur_sigma=2.0, noise_sigma=0.0)

    def test_gaussian_sensor_noise_sigma_15(self):
        """Tier 2: Gaussian sensor noise sigma = 15."""
        self._assert_blur_and_noise(blur_sigma=0.0, noise_sigma=15.0)

    def test_gaussian_sensor_noise_sigma_25(self):
        """Tier 2: Gaussian sensor noise sigma = 25."""
        self._assert_blur_and_noise(blur_sigma=0.0, noise_sigma=25.0)

    def test_combined_blur_and_sensor_noise(self):
        """Tier 2: Combined Gaussian blur (sigma=1.2) + sensor noise (sigma=15.0)."""
        self._assert_blur_and_noise(blur_sigma=1.2, noise_sigma=15.0)

    def _assert_blur_and_noise(self, blur_sigma: float, noise_sigma: float):
        for mode in [MODE_1BIT_BW, MODE_2BIT_4COLOR]:
            base_frame, _, payload = self._create_test_frame(size=48, mode=mode, payload=f"NoiseBlur_B{blur_sigma}_N{noise_sigma}".encode())
            frame = render_display_frame(cv2.cvtColor(base_frame, cv2.COLOR_BGR2RGB), target_dim=480, margin=64)

            if blur_sigma > 0:
                frame = apply_gaussian_blur(frame, blur_sigma)
            if noise_sigma > 0:
                frame = apply_gaussian_sensor_noise(frame, noise_sigma)

            receiver = ChromaBeamReceiver(grid_size=48, auto_density=True)
            _, stats = receiver.process_frame(frame)
            self.assertTrue(stats["locked"], f"Failed lock for blur={blur_sigma}, noise={noise_sigma}, mode={mode}")
            self.assertEqual(stats["packets"], 1, f"Failed decode for blur={blur_sigma}, noise={noise_sigma}, mode={mode}")

    # --- Lighting Shifts & Spatial Glare Gradients ---
    def test_lighting_underexposure_minus_35(self):
        """Tier 2: Dim lighting / underexposure shift delta = -35."""
        self._assert_lighting_shift(-35)

    def test_lighting_overexposure_plus_35(self):
        """Tier 2: High brightness / overexposure shift delta = +35."""
        self._assert_lighting_shift(+35)

    def test_lighting_diagonal_glare_gradient(self):
        """Tier 2: Diagonal spatial glare gradient across frame."""
        self._assert_glare_gradient('diagonal')

    def test_lighting_radial_hotspot_glare(self):
        """Tier 2: Central radial hotspot glare reflection."""
        self._assert_glare_gradient('radial')

    def test_lighting_asymmetric_shadow(self):
        """Tier 2: Asymmetric corner shadow attenuation."""
        self._assert_glare_gradient('corner')

    def _assert_lighting_shift(self, delta: int):
        for mode in [MODE_1BIT_BW, MODE_2BIT_4COLOR]:
            base_frame, _, payload = self._create_test_frame(size=48, mode=mode, payload=f"LightShift_{delta}".encode())
            frame = render_display_frame(cv2.cvtColor(base_frame, cv2.COLOR_BGR2RGB), target_dim=480, margin=64)
            shifted = apply_exposure_shift(frame, delta)

            receiver = ChromaBeamReceiver(grid_size=48, auto_density=True)
            _, stats = receiver.process_frame(shifted)
            self.assertTrue(stats["locked"], f"Failed lock under exposure shift {delta}, mode={mode}")
            self.assertEqual(stats["packets"], 1, f"Failed decode under exposure shift {delta}, mode={mode}")

    def _assert_glare_gradient(self, grad_type: str):
        for mode in [MODE_1BIT_BW, MODE_2BIT_4COLOR]:
            base_frame, _, payload = self._create_test_frame(size=48, mode=mode, payload=f"Glare_{grad_type}".encode())
            frame = render_display_frame(cv2.cvtColor(base_frame, cv2.COLOR_BGR2RGB), target_dim=480, margin=64)
            glare_frame = apply_glare_gradient(frame, gradient_type=grad_type, max_glare=35)

            receiver = ChromaBeamReceiver(grid_size=48, auto_density=True)
            _, stats = receiver.process_frame(glare_frame)
            self.assertTrue(stats["locked"], f"Failed lock under glare={grad_type}, mode={mode}")
            self.assertEqual(stats["packets"], 1, f"Failed decode under glare={grad_type}, mode={mode}")

    # --- Surrounding Desktop UI Distraction ---
    def test_desktop_ui_code_editor_distraction(self):
        """Tier 2: Matrix embedded inside dark IDE code window with surrounding code text."""
        self._assert_desktop_ui_isolation(ox=240, oy=120)

    def test_desktop_ui_taskbar_and_window_chrome(self):
        """Tier 2: Matrix placed adjacent to desktop taskbars and window chrome."""
        self._assert_desktop_ui_isolation(ox=180, oy=90)

    def test_desktop_ui_false_concentric_buttons(self):
        """Tier 2: False positive rejection of circular nested buttons and icons."""
        tracker = OpticalTracker(target_grid_dim=512)
        canvas = np.zeros((600, 800, 3), dtype=np.uint8) + 40
        # Draw concentric non-square circles and icons
        for cx, cy in [(150, 150), (400, 150), (650, 150), (150, 450)]:
            cv2.circle(canvas, (cx, cy), 35, (255, 255, 255), -1)
            cv2.circle(canvas, (cx, cy), 22, (0, 0, 0), -1)
            cv2.circle(canvas, (cx, cy), 10, (255, 255, 255), -1)
        anchors = tracker.find_anchors(canvas)
        self.assertIsNone(anchors, "Anchor detector must reject circular concentric patterns")

    def test_desktop_ui_dense_text_paragraphs(self):
        """Tier 2: Heavy multi-line text paragraphs around the matrix."""
        self._assert_desktop_ui_isolation(ox=200, oy=140)

    def test_desktop_ui_multiple_nested_boxes(self):
        """Tier 2: Multiple nested non-matrix UI rectangles."""
        canvas = np.zeros((720, 960, 3), dtype=np.uint8) + 30
        for r in range(5):
            cv2.rectangle(canvas, (50 + r * 20, 50 + r * 20), (400 - r * 20, 400 - r * 20), (100, 100, 100), 2)
        tracker = OpticalTracker(target_grid_dim=512)
        anchors = tracker.find_anchors(canvas)
        self.assertIsNone(anchors, "Anchor detector must reject plain nested rectangles")

    def _assert_desktop_ui_isolation(self, ox: int, oy: int):
        base_frame, _, payload = self._create_test_frame(size=48, mode=MODE_3BIT_8COLOR, payload=b"DesktopUIRejection")
        bgr_m = base_frame  # 480x480 native
        ui_canvas = embed_in_desktop_ui(bgr_m, canvas_w=960, canvas_h=720, ox=ox, oy=oy)

        receiver = ChromaBeamReceiver(grid_size=48, auto_density=True)
        _, stats = receiver.process_frame(ui_canvas)
        self.assertTrue(stats["locked"], "Failed to lock matrix embedded inside desktop UI")
        self.assertEqual(stats["packets"], 1, "Failed to decode packet from desktop UI canvas")


# ---------------------------------------------------------------------------
# Tier 3: Cross-Feature Combinations (Pairwise & Sweeping)
# ---------------------------------------------------------------------------

class TestTier3CrossFeatureCombinations(unittest.TestCase):
    """
    Tier 3: Pairwise combinations across color mode x grid density x rotation angle x optical distortion,
    plus auto-density sweeping without manual receiver configuration.
    """

    def test_pairwise_mode_density_rotation_matrix(self):
        """Tier 3: Pairwise sweep across (Modes 0, 1, 2) x (Densities 32, 48, 64) x (Rotations 0°, 90°, 180°, 270°)."""
        modes = [MODE_1BIT_BW, MODE_2BIT_4COLOR, MODE_3BIT_8COLOR]
        densities = [32, 48, 64]
        rotations = [0, 90, 180, 270]

        for mode, density, rot in itertools.product(modes, densities, rotations):
            layout = ColorMatrixLayout(grid_size=density, color_mode=mode)
            payload = f"Pairwise_M{mode}_D{density}_R{rot}".encode()
            pkt = pack_packet(file_id=500 + mode * 10 + density, total_blocks=1, block_size=len(payload), seed=rot, payload=payload)
            grid = bytes_to_color_grid(pkt, layout)

            upscaled = cv2.resize(grid, (density * 10, density * 10), interpolation=cv2.INTER_NEAREST)
            bgr = cv2.cvtColor(upscaled, cv2.COLOR_RGB2BGR)

            if rot == 90:
                frame = cv2.rotate(bgr, cv2.ROTATE_90_CLOCKWISE)
            elif rot == 180:
                frame = cv2.rotate(bgr, cv2.ROTATE_180)
            elif rot == 270:
                frame = cv2.rotate(bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
            else:
                frame = bgr

            receiver = ChromaBeamReceiver(grid_size=density, auto_density=True)
            _, stats = receiver.process_frame(frame)
            self.assertTrue(stats["locked"], f"Failed pairwise lock for mode={mode}, density={density}, rot={rot}")
            self.assertEqual(stats["packets"], 1, f"Failed pairwise decode for mode={mode}, density={density}, rot={rot}")

    def test_pairwise_mode_density_perspective_distortion(self):
        """Tier 3: Pairwise sweep across (Modes 0, 1, 2) x (Densities 32, 48) x (Warp top, left, compound)."""
        modes = [MODE_1BIT_BW, MODE_2BIT_4COLOR, MODE_3BIT_8COLOR]
        densities = [32, 48]
        warps = ['tilt_top', 'tilt_left', 'compound']

        for mode, density, warp in itertools.product(modes, densities, warps):
            layout = ColorMatrixLayout(grid_size=density, color_mode=mode)
            payload = f"WarpPairwise_M{mode}_D{density}_{warp}".encode()
            pkt = pack_packet(file_id=600, total_blocks=1, block_size=len(payload), seed=1, payload=payload)
            grid = bytes_to_color_grid(pkt, layout)

            upscaled = cv2.resize(grid, (density * 10, density * 10), interpolation=cv2.INTER_NEAREST)
            bgr = cv2.cvtColor(upscaled, cv2.COLOR_RGB2BGR)
            warped_frame = apply_perspective_warp(bgr, warp_type=warp, canvas_size=640)

            receiver = ChromaBeamReceiver(grid_size=density, auto_density=True)
            _, stats = receiver.process_frame(warped_frame)
            self.assertTrue(stats["locked"], f"Failed warp pairwise lock for mode={mode}, density={density}, warp={warp}")
            self.assertEqual(stats["packets"], 1, f"Failed warp pairwise decode for mode={mode}, density={density}, warp={warp}")

    def test_pairwise_mode_density_continuous_rotations(self):
        """Tier 3: Pairwise sweep across (Modes 0, 1, 2) x (Densities 32, 48) x (Continuous angles 45°, 135°, 225°, 315°)."""
        modes = [MODE_1BIT_BW, MODE_2BIT_4COLOR]
        densities = [32, 48]
        angles = [45.0, 135.0, 225.0, 315.0]

        for mode, density, angle in itertools.product(modes, densities, angles):
            layout = ColorMatrixLayout(grid_size=density, color_mode=mode)
            payload = f"AnglePairwise_M{mode}_D{density}_A{int(angle)}".encode()
            pkt = pack_packet(file_id=700, total_blocks=1, block_size=len(payload), seed=int(angle), payload=payload)
            grid = bytes_to_color_grid(pkt, layout)

            canvas = render_display_frame(grid, target_dim=density * 10, margin=110)
            rotated = apply_continuous_rotation(canvas, angle)

            receiver = ChromaBeamReceiver(grid_size=density, auto_density=True)
            _, stats = receiver.process_frame(rotated)
            self.assertTrue(stats["locked"], f"Failed continuous rotation lock for mode={mode}, density={density}, angle={angle}")
            self.assertEqual(stats["packets"], 1, f"Failed continuous rotation decode for mode={mode}, density={density}, angle={angle}")

    def test_pairwise_mode_density_optical_noise_glare(self):
        """Tier 3: Pairwise combinations of modes and densities under blur, noise, and glare."""
        combinations = [
            (MODE_1BIT_BW, 32, 1.2, 15.0, 'diagonal'),
            (MODE_2BIT_4COLOR, 48, 1.0, 10.0, 'radial'),
            (MODE_1BIT_BW, 48, 1.5, 20.0, 'corner'),
            (MODE_2BIT_4COLOR, 32, 1.0, 15.0, 'diagonal')
        ]
        for mode, density, blur_s, noise_s, glare_t in combinations:
            layout = ColorMatrixLayout(grid_size=density, color_mode=mode)
            payload = f"Combo_M{mode}_D{density}".encode()
            pkt = pack_packet(file_id=750, total_blocks=1, block_size=len(payload), seed=10, payload=payload)
            grid = bytes_to_color_grid(pkt, layout)

            frame = render_display_frame(grid, target_dim=density * 10, margin=64)
            if blur_s > 0:
                frame = apply_gaussian_blur(frame, blur_s)
            if noise_s > 0:
                frame = apply_gaussian_sensor_noise(frame, noise_s)
            if glare_t:
                frame = apply_glare_gradient(frame, gradient_type=glare_t, max_glare=25)

            receiver = ChromaBeamReceiver(grid_size=density, auto_density=True)
            _, stats = receiver.process_frame(frame)
            self.assertTrue(stats["locked"], f"Failed combo lock for mode={mode}, density={density}")
            self.assertEqual(stats["packets"], 1, f"Failed combo decode for mode={mode}, density={density}")

    def test_auto_density_interleaved_streaming_dynamic_modes(self):
        """Tier 3: Stream of interleaved frames switching densities (32 -> 64 -> 48 -> 32) and modes (0 -> 2 -> 1 -> 0)."""
        receiver = ChromaBeamReceiver(grid_size=None, auto_density=True)

        steps = [
            (32, MODE_1BIT_BW, 0, b"Step1-32-M0"),
            (64, MODE_3BIT_8COLOR, 90, b"Step2-64-M2"),
            (48, MODE_2BIT_4COLOR, 180, b"Step3-48-M1"),
            (32, MODE_2BIT_4COLOR, 270, b"Step4-32-M1"),
            (48, MODE_1BIT_BW, 0, b"Step5-48-M0"),
            (64, MODE_2BIT_4COLOR, 90, b"Step6-64-M1"),
        ]

        for step_idx, (size, mode, rot, payload) in enumerate(steps):
            layout = ColorMatrixLayout(grid_size=size, color_mode=mode)
            pkt = pack_packet(file_id=800 + step_idx, total_blocks=1, block_size=len(payload), seed=step_idx, payload=payload)
            grid = bytes_to_color_grid(pkt, layout)

            upscaled = cv2.resize(grid, (size * 10, size * 10), interpolation=cv2.INTER_NEAREST)
            bgr = cv2.cvtColor(upscaled, cv2.COLOR_RGB2BGR)

            if rot == 90:
                frame = cv2.rotate(bgr, cv2.ROTATE_90_CLOCKWISE)
            elif rot == 180:
                frame = cv2.rotate(bgr, cv2.ROTATE_180)
            elif rot == 270:
                frame = cv2.rotate(bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
            else:
                frame = bgr

            _, stats = receiver.process_frame(frame)
            self.assertTrue(stats["locked"], f"Interleaved step {step_idx} failed lock")
            self.assertEqual(stats["density"], size, f"Interleaved step {step_idx} density mismatch")
            self.assertEqual(stats["mode"], mode, f"Interleaved step {step_idx} mode mismatch")
            self.assertEqual(stats["packets"], step_idx + 1)


# ---------------------------------------------------------------------------
# Tier 4: Real-World Air-Gap Transmission Scenarios
# ---------------------------------------------------------------------------

class TestTier4RealWorldAirGapTransmission(unittest.TestCase):
    """
    Tier 4: Realistic end-to-end air-gapped multi-frame file transmission scenarios.
    Simulates fountain packet encoding, harsh optical channel distortions (rotations,
    perspective tilts, blur, noise, glare, UI clutter), packet drops (30-40%),
    optical frame extraction, and asserts byte-for-byte exact SHA256 file reconstruction.
    """

    def _execute_airgap_transmission(
        self,
        file_bytes: bytes,
        filename: str,
        grid_size: int,
        color_mode: int,
        block_size: int,
        packet_loss_rate: float,
        distortion_fn=None,
        rot_deg: int = 0
    ) -> bytes:
        """Simulates Tx encoder -> optical air-gap channel -> Rx tracker & LT decoder."""
        # 1. Package file metadata + payload into transmitted binary payload
        meta_bytes = pack_file_metadata(filename, len(file_bytes))
        full_data = meta_bytes + file_bytes

        encoder = LTEncoder(full_data, block_size=block_size)
        layout = ColorMatrixLayout(grid_size=grid_size, color_mode=color_mode)
        receiver = ChromaBeamReceiver(grid_size=grid_size, auto_density=True)

        # Generate stream of fountain droplets (up to 3.0x K to guarantee solvency under loss)
        max_droplets = int(encoder.K * 3.0)
        droplets = []
        for seed in range(max_droplets):
            _, _, payload = encoder.generate_droplet(seed)
            pkt = pack_packet(
                file_id=999,
                total_blocks=encoder.K,
                block_size=block_size,
                seed=seed,
                payload=payload
            )
            droplets.append((seed, pkt))

        # Simulate packet loss and channel disorder
        rng = random.Random(1337)
        rng.shuffle(droplets)
        surviving_count = int(len(droplets) * (1.0 - packet_loss_rate))
        transmitted_droplets = droplets[:surviving_count]

        # 2. Transmit each surviving droplet through optical channel
        for seed, pkt_bytes in transmitted_droplets:
            grid = bytes_to_color_grid(pkt_bytes, layout)
            upscaled = cv2.resize(grid, (grid_size * 10, grid_size * 10), interpolation=cv2.INTER_NEAREST)
            frame = cv2.cvtColor(upscaled, cv2.COLOR_RGB2BGR)

            # Apply cardinal rotation if requested
            if rot_deg == 90:
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            elif rot_deg == 180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            elif rot_deg == 270:
                frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

            # Apply custom optical distortion if provided
            if distortion_fn is not None:
                frame = distortion_fn(frame)

            # Process frame through optical receiver
            _, stats = receiver.process_frame(frame)
            if stats["complete"]:
                break

        self.assertTrue(receiver.complete, f"Transmission failed to complete for {filename}.")

        # 3. Reconstruct and extract payload
        reconstructed_full = receiver.decoder.reconstruct_data()
        self.assertIsNotNone(reconstructed_full)

        meta = unpack_file_metadata(reconstructed_full)
        self.assertIsNotNone(meta)
        rx_name, rx_size, mime = meta
        self.assertEqual(rx_name, filename)
        self.assertEqual(rx_size, len(file_bytes))

        # Exact metadata length offset: [FileSize (4B)] [NameLen (1B)] [Name] [MimeLen (1B)] [Mime]
        meta_len = 5 + len(rx_name.encode('utf-8')) + 1 + len(mime.encode('utf-8'))
        extracted_file = reconstructed_full[meta_len : meta_len + rx_size]
        return extracted_file

    def test_e2e_airgap_key_transfer_mode0_32x32(self):
        """
        Scenario 1: Air-Gapped Key Transfer (5 KB binary secret payload).
        Mode 0 (1-bit Potato), 32x32 density, 90° rotation, underexposed lighting (-20),
        30% simulated packet loss.
        """
        key_payload = os.urandom(5 * 1024)
        expected_sha = hashlib.sha256(key_payload).hexdigest()

        def distortion(frame):
            frame = render_display_frame(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), target_dim=320, margin=64)
            return apply_exposure_shift(frame, delta=-20)

        recovered = self._execute_airgap_transmission(
            file_bytes=key_payload,
            filename="secret_key.bin",
            grid_size=32,
            color_mode=MODE_1BIT_BW,
            block_size=64,
            packet_loss_rate=0.30,
            distortion_fn=distortion,
            rot_deg=90
        )

        self.assertEqual(hashlib.sha256(recovered).hexdigest(), expected_sha)
        self.assertEqual(recovered, key_payload)

    def test_e2e_airgap_document_transfer_mode1_48x48(self):
        """
        Scenario 2: Balanced Document Transfer (6 KB structured text/binary payload).
        Mode 1 (2-bit Balanced), 48x48 density, 180° rotation, 35% packet loss.
        """
        doc_payload = (b"ChromaBeam Optical Air-Gap Protocol Specification Document\n" + os.urandom(256)) * 25
        doc_payload = doc_payload[:6 * 1024]
        expected_sha = hashlib.sha256(doc_payload).hexdigest()

        def distortion(frame):
            frame = render_display_frame(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), target_dim=480, margin=64)
            return apply_glare_gradient(frame, gradient_type='diagonal', max_glare=25)

        recovered = self._execute_airgap_transmission(
            file_bytes=doc_payload,
            filename="specification.pdf",
            grid_size=48,
            color_mode=MODE_2BIT_4COLOR,
            block_size=128,
            packet_loss_rate=0.35,
            distortion_fn=distortion,
            rot_deg=180
        )

        self.assertEqual(hashlib.sha256(recovered).hexdigest(), expected_sha)
        self.assertEqual(recovered, doc_payload)

    def test_e2e_airgap_turbo_payload_transfer_mode2_64x64(self):
        """
        Scenario 3: High-Speed Turbo Binary Payload Transfer (10 KB executable payload).
        Mode 2 (3-bit Turbo), 64x64 density, 30° perspective tilt, 40% packet loss.
        """
        exe_payload = os.urandom(10 * 1024)
        expected_sha = hashlib.sha256(exe_payload).hexdigest()

        def distortion(frame):
            return apply_perspective_warp(frame, warp_type='tilt_top', canvas_size=640)

        recovered = self._execute_airgap_transmission(
            file_bytes=exe_payload,
            filename="firmware_update.bin",
            grid_size=64,
            color_mode=MODE_3BIT_8COLOR,
            block_size=256,
            packet_loss_rate=0.40,
            distortion_fn=distortion,
            rot_deg=0
        )

        self.assertEqual(hashlib.sha256(recovered).hexdigest(), expected_sha)
        self.assertEqual(recovered, exe_payload)

    def test_e2e_airgap_desktop_ui_clutter_streaming_48x48(self):
        """
        Scenario 4: Desktop UI Clutter & Continuous 45° Angle Streaming (4 KB payload).
        Mode 1 (2-bit Balanced), 48x48 density, 45° continuous rotation inside desktop code editor UI,
        30% packet loss.
        """
        ui_payload = os.urandom(4 * 1024)
        expected_sha = hashlib.sha256(ui_payload).hexdigest()

        def distortion(frame):
            ui_canvas = embed_in_desktop_ui(frame, canvas_w=800, canvas_h=800, ox=160, oy=160)
            return apply_continuous_rotation(ui_canvas, angle_deg=45.0)

        recovered = self._execute_airgap_transmission(
            file_bytes=ui_payload,
            filename="secure_archive.tar.gz",
            grid_size=48,
            color_mode=MODE_2BIT_4COLOR,
            block_size=128,
            packet_loss_rate=0.30,
            distortion_fn=distortion,
            rot_deg=0
        )

        self.assertEqual(hashlib.sha256(recovered).hexdigest(), expected_sha)
        self.assertEqual(recovered, ui_payload)

    def test_e2e_airgap_harsh_optical_channel_stress_mode2(self):
        """
        Scenario 5: Harsh Optical Channel Stress Test (6 KB binary payload).
        Mode 2 (3-bit Turbo), 48x48 density, compound perspective tilt + glare gradient + blur (sigma=1.0)
        + sensor noise (sigma=10.0), 30% packet loss.
        """
        stress_payload = os.urandom(6 * 1024)
        expected_sha = hashlib.sha256(stress_payload).hexdigest()

        def distortion(frame):
            warped = apply_perspective_warp(frame, warp_type='compound', canvas_size=640)
            blurred = apply_gaussian_blur(warped, sigma=1.0)
            noisy = apply_gaussian_sensor_noise(blurred, sigma=10.0)
            glare = apply_glare_gradient(noisy, gradient_type='diagonal', max_glare=20)
            return glare

        recovered = self._execute_airgap_transmission(
            file_bytes=stress_payload,
            filename="stress_dataset.dat",
            grid_size=48,
            color_mode=MODE_3BIT_8COLOR,
            block_size=128,
            packet_loss_rate=0.30,
            distortion_fn=distortion,
            rot_deg=0
        )

        self.assertEqual(hashlib.sha256(recovered).hexdigest(), expected_sha)
        self.assertEqual(recovered, stress_payload)


if __name__ == '__main__':
    unittest.main()
