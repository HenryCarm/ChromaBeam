"""
ChromaBeam Multi-Mode Optical Color Matrix Engine
Supports:
- Mode 0: 1-Bit High-Contrast Monochrome (Potato Camera / Low Light / Max Reliability)
- Mode 1: 2-Bit 4-Color Palette (Balanced)
- Mode 2: 3-Bit 8-Color RGB Palette (Turbo Speed)
Includes self-describing header encoding so the receiver automatically identifies mode and density!
"""

import numpy as np
from typing import Tuple, List, Optional

# Color Palettes
# Mode 0: 1-bit Monochrome (Black, White)
PALETTE_1BIT = np.array([
    [0,   0,   0],    # 0: Black
    [255, 255, 255]   # 1: White
], dtype=np.int32)
PALETTE_1BIT_BW = PALETTE_1BIT

# Mode 1: 2-bit 4-Color (Black, Red, Green, White)
PALETTE_2BIT = np.array([
    [0,   0,   0],    # 00: Black
    [255, 50,  50],   # 01: Red
    [50,  255, 50],   # 10: Green
    [255, 255, 255]   # 11: White
], dtype=np.int32)
PALETTE_2BIT_4COLOR = PALETTE_2BIT

# Mode 2: 3-bit 8-Color RGB (JAB)
PALETTE_3BIT = np.array([
    [0,   0,   0],    # 000: Black
    [0,   0,   255],  # 001: Blue
    [0,   255, 0],    # 010: Green
    [0,   255, 255],  # 011: Cyan
    [255, 0,   0],    # 100: Red
    [255, 0,   255],  # 101: Magenta
    [255, 255, 0],    # 110: Yellow
    [255, 255, 255]   # 111: White
], dtype=np.int32)
PALETTE_3BIT_8COLOR = PALETTE_3BIT

ANCHOR_SIZE = 7

MODE_1BIT_BW = 0
MODE_2BIT_4COLOR = 1
MODE_3BIT_8COLOR = 2


class ColorMatrixLayout:
    def __init__(self, grid_size: int = 48, color_mode: int = MODE_3BIT_8COLOR):
        self.grid_size = grid_size
        self.color_mode = color_mode
        self.anchor_size = ANCHOR_SIZE

        if self.color_mode == MODE_1BIT_BW:
            self.palette = PALETTE_1BIT
            self.bits_per_cell = 1
        elif self.color_mode == MODE_2BIT_4COLOR:
            self.palette = PALETTE_2BIT
            self.bits_per_cell = 2
        else:
            self.palette = PALETTE_3BIT
            self.bits_per_cell = 3

        # Binary mask: 1 = data cell, 0 = reserved
        self.data_mask = np.ones((grid_size, grid_size), dtype=bool)
        s = self.anchor_size
        N = self.grid_size

        # 3 Corners reserved for 1:1:3:1:1 standard QR finder patterns (TL, TR, BL)
        self.data_mask[0:s, 0:s] = False
        self.data_mask[0:s, N-s:N] = False
        self.data_mask[N-s:N, 0:s] = False

        # Top border: Calibration & Mode Header cells
        cal_start = s
        cal_end = min(N - s, s + 5)
        self.cal_cells = []
        for c in range(cal_start, cal_end):
            self.data_mask[0, c] = False
            self.cal_cells.append((0, c))

        # Timing Tracks along top and bottom
        self.timing_cells = []
        for c in range(cal_end, N - s):
            self.data_mask[0, c] = False
            self.timing_cells.append((0, c, (c % 2)))

        for c in range(s, N - s):
            self.data_mask[N - 1, c] = False
            self.timing_cells.append((N - 1, c, (c % 2)))

        self.data_coords = np.argwhere(self.data_mask)
        self.num_data_cells = len(self.data_coords)
        self.max_payload_bits = self.num_data_cells * self.bits_per_cell
        self.max_payload_bytes = self.max_payload_bits // 8

    @property
    def anchor_centers(self) -> List[Tuple[float, float]]:
        """
        Normalized canonical floating point centroids [TL, TR, BR, BL] in [0, 1]^2 space.
        """
        N = float(self.grid_size)
        c = 3.5 / N
        return [
            (c, c),              # Top-Left
            (1.0 - c, c),        # Top-Right
            (1.0 - c, 1.0 - c),  # Bottom-Right (Extrapolated)
            (c, 1.0 - c)         # Bottom-Left
        ]

    def render_anchors(self, grid: np.ndarray):
        s = self.anchor_size
        N = self.grid_size
        white = self.palette[-1]
        black = self.palette[0]

        # 1:1:3:1:1 Standard QR Finder Patterns in 3 corners (TL, TR, BL)

        # Top-Left: Solid Black outer (7x7), White ring (5x5), Black center (3x3)
        grid[0:s, 0:s] = black
        grid[1:s-1, 1:s-1] = white
        grid[2:s-2, 2:s-2] = black

        # Top-Right
        grid[0:s, N-s:N] = black
        grid[1:s-1, N-s+1:N-1] = white
        grid[2:s-2, N-s+2:N-2] = black

        # Bottom-Left
        grid[N-s:N, 0:s] = black
        grid[N-s+1:N-1, 1:s-1] = white
        grid[N-s+2:N-2, 2:s-2] = black

        # Calibration swatches along top border (coordinates (0, 5) ... (0, 9))
        if self.color_mode == MODE_3BIT_8COLOR:
            cal_indices = [0, 4, 2, 1, 7] # K, R, G, B, W
        elif self.color_mode == MODE_2BIT_4COLOR:
            cal_indices = [0, 1, 2, 3]    # K, R, G, W
        else:
            cal_indices = [0, 1, 0, 1]    # K, W, K, W

        for i, (r, c) in enumerate(self.cal_cells[:len(cal_indices)]):
            grid[r, c] = self.palette[cal_indices[i]]

        # Timing tracks
        for r, c, tick in self.timing_cells:
            grid[r, c] = white if tick else black


def bytes_to_color_grid(data: bytes, layout: ColorMatrixLayout) -> np.ndarray:
    grid = np.zeros((layout.grid_size, layout.grid_size, 3), dtype=np.uint8)
    layout.render_anchors(grid)

    if len(data) > layout.max_payload_bytes:
        data = data[:layout.max_payload_bytes]

    byte_arr = np.frombuffer(data, dtype=np.uint8)
    bits = np.unpackbits(byte_arr)
    bpc = layout.bits_per_cell

    # Pad bits to multiple of bits_per_cell
    rem = len(bits) % bpc
    if rem != 0:
        bits = np.concatenate([bits, np.zeros(bpc - rem, dtype=np.uint8)])

    chunks = bits.reshape(-1, bpc)
    if bpc == 1:
        color_indices = chunks[:, 0]
    elif bpc == 2:
        color_indices = (chunks[:, 0] << 1) | chunks[:, 1]
    else:
        color_indices = (chunks[:, 0] << 2) | (chunks[:, 1] << 1) | chunks[:, 2]

    num_to_draw = min(len(color_indices), layout.num_data_cells)
    coords = layout.data_coords[:num_to_draw]

    for i in range(num_to_draw):
        r, c = coords[i]
        grid[r, c] = layout.palette[color_indices[i]]

    return grid


def color_grid_to_bytes(grid: np.ndarray, layout: ColorMatrixLayout, classifier_fn=None) -> bytes:
    num_cells = layout.num_data_cells
    coords = layout.data_coords
    rgb_values = grid[coords[:, 0], coords[:, 1]]
    bpc = layout.bits_per_cell

    if classifier_fn is not None:
        indices = classifier_fn(rgb_values, layout.color_mode)
    else:
        # Default nearest palette index classifier
        rgb_int = rgb_values.astype(np.int32)
        palette_int = layout.palette.astype(np.int32)
        dists = np.sum((rgb_int[:, np.newaxis, :] - palette_int[np.newaxis, :, :]) ** 2, axis=2)
        indices = np.argmin(dists, axis=1)

    if bpc == 1:
        bits = indices.astype(np.uint8)
    elif bpc == 2:
        b0 = ((indices >> 1) & 1).astype(np.uint8)
        b1 = (indices & 1).astype(np.uint8)
        bits = np.column_stack([b0, b1]).flatten()
    else:
        b0 = ((indices >> 2) & 1).astype(np.uint8)
        b1 = ((indices >> 1) & 1).astype(np.uint8)
        b2 = (indices & 1).astype(np.uint8)
        bits = np.column_stack([b0, b1, b2]).flatten()

    num_bytes = len(bits) // 8
    byte_bits = bits[:num_bytes * 8].reshape(-1, 8)
    return np.packbits(byte_bits).tobytes()


def packet_to_standard_qr_rgb(packet: bytes) -> np.ndarray:
    """
    Renders packet bytes as a standard QR code frame with 1:1:3:1:1 finder patterns
    and built-in Reed-Solomon error correction for bulletproof optical scanning.
    """
    import base64
    import qrcode
    b64_str = base64.b64encode(packet).decode('ascii')
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, border=2)
    qr.add_data(b64_str)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    h = len(matrix)
    w = len(matrix[0])
    raw_grid = np.zeros((h, w, 3), dtype=np.uint8)
    for r in range(h):
        for c in range(w):
            val = 0 if matrix[r][c] else 255
            raw_grid[r, c] = [val, val, val]
    return raw_grid


def upscale_grid_for_display(grid: np.ndarray, target_resolution: int = 512) -> np.ndarray:
    scale = max(1, target_resolution // grid.shape[0])
    return np.repeat(np.repeat(grid, scale, axis=0), scale, axis=1)
