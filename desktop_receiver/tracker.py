"""
ChromaBeam OpenCV Optical Frame Tracker & Perspective Warper
Detects the 4 corner anchors / matrix boundaries and flattens into a normalized top-down grid.
"""

import cv2
import numpy as np
from typing import Optional, Tuple, List


def order_quad_points(pts: np.ndarray) -> np.ndarray:
    """
    Orders 4 points in consistent top-left, top-right, bottom-right, bottom-left order.
    pts: (4, 2)
    """
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]  # Top-left has smallest sum (x+y)
    rect[2] = pts[np.argmax(s)]  # Bottom-right has largest sum (x+y)

    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # Top-right has smallest difference (y-x)
    rect[3] = pts[np.argmax(diff)]  # Bottom-left has largest difference (y-x)

    return rect


class OpticalTracker:
    """
    Tracks and extracts ChromaBeam optical matrix frames from camera streams.
    """
    def __init__(self, target_grid_dim: int = 512):
        self.target_dim = target_grid_dim

    def find_matrix_quad(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """
        Locates the largest 4-sided convex polygon corresponding to the ChromaBeam display frame.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # Adaptive threshold to handle bright monitor screens
        thresh = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2
        )

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        best_quad = None
        max_area = 0

        h, w = frame.shape[:2]
        min_allowed_area = (w * h) * 0.04  # Must be at least 4% of camera frame

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_allowed_area:
                continue

            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)

            if len(approx) == 4 and cv2.isContourConvex(approx):
                if area > max_area:
                    max_area = area
                    best_quad = approx.reshape(4, 2)

        if best_quad is not None:
            return order_quad_points(best_quad.astype(np.float32))

        return None

    def warp_matrix(self, frame: np.ndarray, quad_pts: np.ndarray) -> np.ndarray:
        """
        Applies homography perspective transformation to produce a normalized top-down square image.
        """
        dst_pts = np.array([
            [0, 0],
            [self.target_dim - 1, 0],
            [self.target_dim - 1, self.target_dim - 1],
            [0, self.target_dim - 1]
        ], dtype="float32")

        M = cv2.getPerspectiveTransform(quad_pts, dst_pts)
        warped = cv2.warpPerspective(frame, M, (self.target_dim, self.target_dim))
        return warped

    def sample_grid_cells(self, warped_bgr: np.ndarray, grid_size: int = 48) -> np.ndarray:
        """
        Samples the center of each cell in the warped grid and converts BGR -> RGB.
        Returns an (grid_size, grid_size, 3) matrix.
        """
        cell_size = self.target_dim / grid_size
        sampled_grid = np.zeros((grid_size, grid_size, 3), dtype=np.uint8)

        # Convert to RGB
        warped_rgb = cv2.cvtColor(warped_bgr, cv2.COLOR_BGR2RGB)

        for r in range(grid_size):
            cy = int((r + 0.5) * cell_size)
            for c in range(grid_size):
                cx = int((c + 0.5) * cell_size)
                # Sample 3x3 patch around center to reduce single-pixel noise
                patch = warped_rgb[max(0, cy-1):min(self.target_dim, cy+2),
                                   max(0, cx-1):min(self.target_dim, cx+2)]
                sampled_grid[r, c] = np.mean(patch, axis=(0, 1)).astype(np.uint8)

        return sampled_grid
