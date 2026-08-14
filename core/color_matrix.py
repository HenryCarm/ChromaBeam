"""
ChromaBeam Optical Color Matrix Synthesizer & Rasterizer
Handles 3-bit RGB color multiplexing, 4-corner ArUco/geometric anchors, timing tracks, calibration borders, and rasterization.
"""

import numpy as np
from typing import Tuple, List, Optional

# 3-bit RGB Color Table (R, G, B in 0-255)
# Index: (R << 2) | (G << 1) | B
COLOR_PALETTE = np.array([
    [0,   0,   0],    # 000: Black
    [0,   0,   255],  # 001: Blue
    [0,   255, 0],    # 010: Green
    [0,   255, 255],  # 011: Cyan
    [255, 0,   0],    # 100: Red
    [255, 0,   255],  # 101: Magenta
    [255, 255, 0],    # 110: Yellow
    [255, 255, 255],  # 111: White
], dtype=np.uint8)

# Corner Anchor size in cells
ANCHOR_SIZE = 5


class ColorMatrixLayout:
    """
    Computes grid coordinates, payload cell masks, timing tracks, and anchor positions for an M x M grid.
    """
    def __init__(self, grid_size: int = 48):
        self.grid_size = grid_size
        self.anchor_size = ANCHOR_SIZE
        
        # Binary mask: 1 = data cell, 0 = reserved (anchor, calibration, or timing track)
        self.data_mask = np.ones((grid_size, grid_size), dtype=bool)
        
        # 1. Mark 4 corners as reserved for anchors
        s = self.anchor_size
        self.data_mask[0:s, 0:s] = False                                     # Top-Left (TL)
        self.data_mask[0:s, grid_size-s:grid_size] = False                   # Top-Right (TR)
        self.data_mask[grid_size-s:grid_size, 0:s] = False                   # Bottom-Left (BL)
        self.data_mask[grid_size-s:grid_size, grid_size-s:grid_size] = False # Bottom-Right (BR)
        
        # 2. Calibration cells along top border
        cal_start = s
        cal_end = min(grid_size - s, cal_start + 5)
        self.cal_cells = []
        for c in range(cal_start, cal_end):
            self.data_mask[0, c] = False
            self.cal_cells.append((0, c))

        # 3. Top and Bottom Timing Tracks (alternating Black/White clock ticks)
        self.timing_cells = []
        # Top timing track (rest of top row)
        for c in range(cal_end, grid_size - s):
            self.data_mask[0, c] = False
            self.timing_cells.append((0, c, (c % 2) * 7))  # 0 or 7 (Black/White)

        # Bottom timing track
        for c in range(s, grid_size - s):
            self.data_mask[grid_size - 1, c] = False
            self.timing_cells.append((grid_size - 1, c, (c % 2) * 7))

        # Flattened list of data cell coordinates (row, col)
        self.data_coords = np.argwhere(self.data_mask)
        self.num_data_cells = len(self.data_coords)
        
        # 3 bits per cell -> Total available payload bytes
        self.max_payload_bits = self.num_data_cells * 3
        self.max_payload_bytes = self.max_payload_bits // 8

    def render_anchors(self, grid: np.ndarray):
        """
        Renders distinct high-contrast geometric anchors in the 4 corners,
        plus timing tracks and calibration swatches.
        """
        s = self.anchor_size
        N = self.grid_size

        # Anchor 0: Top-Left (Concentric box with solid center)
        grid[0:s, 0:s] = COLOR_PALETTE[7]  # White outer border
        grid[1:s-1, 1:s-1] = COLOR_PALETTE[0]  # Black ring
        grid[2:s-2, 2:s-2] = COLOR_PALETTE[7]  # White center dot

        # Anchor 1: Top-Right (Solid White box with single Black corner notch)
        grid[0:s, N-s:N] = COLOR_PALETTE[7]
        grid[1:s-1, N-s+1:N-1] = COLOR_PALETTE[0]
        grid[1, N-2] = COLOR_PALETTE[7]

        # Anchor 2: Bottom-Right (Concentric Black/White target with Red center for orientation)
        grid[N-s:N, N-s:N] = COLOR_PALETTE[7]
        grid[N-s+1:N-1, N-s+1:N-1] = COLOR_PALETTE[0]
        grid[N-s+2:N-2, N-s+2:N-2] = COLOR_PALETTE[4]

        # Anchor 3: Bottom-Left (Crosshair pattern)
        grid[N-s:N, 0:s] = COLOR_PALETTE[7]
        grid[N-s+1:N-1, 1:s-1] = COLOR_PALETTE[0]
        grid[N-s+2:N-2, 1:s-1] = COLOR_PALETTE[7]
        grid[N-s+1:N-1, 2:s-2] = COLOR_PALETTE[7]

        # Render 5-Point Calibration Bar (Black, Red, Green, Blue, White)
        cal_colors = [0, 4, 2, 1, 7]  # Palette indices for K, R, G, B, W
        for i, (r, c) in enumerate(self.cal_cells[:len(cal_colors)]):
            grid[r, c] = COLOR_PALETTE[cal_colors[i]]

        # Render Timing Tracks
        for r, c, col_idx in self.timing_cells:
            grid[r, c] = COLOR_PALETTE[col_idx]


def bytes_to_color_grid(data: bytes, layout: ColorMatrixLayout) -> np.ndarray:
    """
    Encodes raw byte sequence into an (M, M, 3) RGB uint8 image grid.
    Pads bits to full triplets so zero bits are truncated.
    """
    grid = np.zeros((layout.grid_size, layout.grid_size, 3), dtype=np.uint8)
    layout.render_anchors(grid)

    if len(data) > layout.max_payload_bytes:
        data = data[:layout.max_payload_bytes]

    byte_arr = np.frombuffer(data, dtype=np.uint8)
    bits = np.unpackbits(byte_arr)

    # Pad with zeros to multiple of 3 if needed
    rem = len(bits) % 3
    if rem != 0:
        pad_len = 3 - rem
        bits = np.concatenate([bits, np.zeros(pad_len, dtype=np.uint8)])

    # Reshape into triplets (3 bits per pixel)
    triplets = bits.reshape(-1, 3)

    # Compute color indices: (b0 << 2) | (b1 << 1) | b2
    color_indices = (triplets[:, 0] << 2) | (triplets[:, 1] << 1) | triplets[:, 2]

    # Map onto data coordinates
    num_to_draw = min(len(color_indices), layout.num_data_cells)
    coords = layout.data_coords[:num_to_draw]

    for i in range(num_to_draw):
        r, c = coords[i]
        grid[r, c] = COLOR_PALETTE[color_indices[i]]

    return grid


def color_grid_to_bytes(grid: np.ndarray, layout: ColorMatrixLayout, color_classifier_fn=None) -> bytes:
    """
    Samples cells from an (M, M, 3) image grid and decodes back into raw bytes.
    """
    num_cells = layout.num_data_cells
    coords = layout.data_coords
    
    # Extract RGB values at data cell coordinates
    rgb_values = grid[coords[:, 0], coords[:, 1]]  # Shape: (num_cells, 3)

    if color_classifier_fn is None:
        # Default simple threshold classifier (midpoint 128)
        # R > 128 -> bit 0, G > 128 -> bit 1, B > 128 -> bit 2
        r_bit = (rgb_values[:, 0] > 128).astype(np.uint8)
        g_bit = (rgb_values[:, 1] > 128).astype(np.uint8)
        b_bit = (rgb_values[:, 2] > 128).astype(np.uint8)
    else:
        r_bit, g_bit, b_bit = color_classifier_fn(rgb_values)

    # Stack bits: (num_cells, 3) -> flattened bits
    bits = np.column_stack([r_bit, g_bit, b_bit]).flatten()

    # Pack bits into bytes
    num_bytes = len(bits) // 8
    byte_bits = bits[:num_bytes * 8].reshape(-1, 8)
    raw_bytes = np.packbits(byte_bits).tobytes()

    return raw_bytes


def upscale_grid_for_display(grid: np.ndarray, target_resolution: int = 512) -> np.ndarray:
    """
    Upscales the (M, M, 3) matrix to target_resolution x target_resolution using nearest neighbor
    to produce sharp, crisp visual cells on screens without blurry antialiasing.
    """
    scale = max(1, target_resolution // grid.shape[0])
    upscaled = np.repeat(np.repeat(grid, scale, axis=0), scale, axis=1)
    return upscaled
