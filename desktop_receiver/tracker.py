"""
ChromaBeam OpenCV Optical Frame Tracker & Perspective Warper
Detects the 4 corner anchors (1:1:1:1:1 concentric squares) via cv2.RETR_TREE hierarchy,
computes 3D projective homography (H) directly to canonical anchor coordinates (2.5/N, 2.5/N),
and flattens the frame into a normalized top-down grid.
"""

import itertools
import cv2
import numpy as np
from typing import Optional, Tuple, List


def order_quad_points(pts: np.ndarray) -> np.ndarray:
    """
    Orders 4 points in consistent top-left, top-right, bottom-right, bottom-left order (clockwise).
    pts: (4, 2)
    """
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    center = pts.mean(axis=0)

    # Angles relative to center (-pi to +pi)
    angles = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
    sorted_pts = pts[np.argsort(angles)]

    # Find Top-Left (smallest x+y)
    sums = sorted_pts[:, 0] + sorted_pts[:, 1]
    tl_idx = int(np.argmin(sums))

    # Roll so Top-Left is at index 0
    ordered = np.roll(sorted_pts, -tl_idx, axis=0)

    # Ensure clockwise orientation: cross product of (P1 - P0) x (P2 - P1) must have positive z
    v0 = ordered[1] - ordered[0]
    v1 = ordered[2] - ordered[1]
    cross = v0[0] * v1[1] - v0[1] * v1[0]
    if cross < 0:
        ordered[[1, 3]] = ordered[[3, 1]]

    return ordered.astype(np.float32)


def find_nested_anchor_centers(frame: np.ndarray) -> List[Tuple[float, float, float]]:
    """
    Detects 1:1:1:1:1 concentric nested square finder patterns using cv2.RETR_TREE hierarchy.
    Identifies nested contour pairs with matching centroids (delta < 2.5 px)
    and area ratio Area(Core) / Area(Ring) in [0.035, 0.160].
    Returns list of candidate (cx, cy, ring_area) tuples.
    """
    if frame is None or frame.size == 0:
        return []

    if frame.ndim == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame.copy()

    h, w = gray.shape[:2]
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)

    # Multi-threshold binarization to handle varying lighting, contrast, and monitor glare
    thresh_images = [
        cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
        cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1],
        cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 3),
        cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 21, 3)
    ]

    raw_candidates = []

    for thresh in thresh_images:
        contours, hierarchy = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        if hierarchy is None or len(contours) < 2:
            continue

        hier = hierarchy[0]
        num_cnt = min(len(contours), 1000)

        for i in range(num_cnt):
            if len(raw_candidates) >= 200:
                break

            parent_idx = int(hier[i][3])
            if parent_idx < 0 or parent_idx >= len(contours):
                continue

            grandparent_idx = int(hier[parent_idx][3]) if 0 <= parent_idx < len(contours) else -1

            # Traverse immediate parent and grandparent in contour tree
            for ring_idx in [parent_idx, grandparent_idx]:
                if ring_idx < 0 or ring_idx >= len(contours):
                    continue

                area_core = cv2.contourArea(contours[i])
                area_ring = cv2.contourArea(contours[ring_idx])
                if area_core < 2.0 or area_ring < 10.0:
                    continue

                ratio = area_core / area_ring
                if not (0.035 <= ratio <= 0.160):
                    continue

                M_c = cv2.moments(contours[i])
                M_r = cv2.moments(contours[ring_idx])
                if M_c["m00"] == 0 or M_r["m00"] == 0:
                    continue

                cx_c = M_c["m10"] / M_c["m00"]
                cy_c = M_c["m01"] / M_c["m00"]
                cx_r = M_r["m10"] / M_r["m00"]
                cy_r = M_r["m01"] / M_r["m00"]

                delta = np.hypot(cx_c - cx_r, cy_c - cy_r)
                if delta >= 2.5:
                    continue

                # Check aspect ratio of ring bounding box (roughly square)
                rx, ry, rw, rh = cv2.boundingRect(contours[ring_idx])
                aspect = float(rw) / float(rh) if rh > 0 else 0.0
                if not (0.40 <= aspect <= 2.50):
                    continue

                # Mathematical squareness check: distinguish square anchors from circles/ellipses.
                # For any circle/ellipse, Area / MinAreaRect is strictly pi/4 (~0.785).
                # For a square/rectangle anchor, Area / MinAreaRect is >= 0.85.
                min_rect = cv2.minAreaRect(contours[ring_idx])
                min_rect_area = min_rect[1][0] * min_rect[1][1]
                if min_rect_area > 0:
                    fill_ratio = area_ring / min_rect_area
                    if fill_ratio < 0.83:
                        continue

                raw_candidates.append((cx_c, cy_c, area_ring))

    if not raw_candidates:
        return []

    # Deduplicate & cluster close candidates across threshold passes
    clusters = []
    for cx, cy, area in raw_candidates:
        matched = False
        for cluster in clusters:
            ccx, ccy, _ = cluster[0]
            if np.hypot(cx - ccx, cy - ccy) < 5.0:
                cluster.append((cx, cy, area))
                matched = True
                break
        if not matched:
            clusters.append([(cx, cy, area)])

    deduped = []
    for cluster in clusters:
        avg_x = float(np.mean([pt[0] for pt in cluster]))
        avg_y = float(np.mean([pt[1] for pt in cluster]))
        avg_area = float(np.mean([pt[2] for pt in cluster]))
        deduped.append((avg_x, avg_y, avg_area))

    return deduped


def filter_and_order_4_anchors(
    candidates: List[Tuple[float, float, float]],
    frame_shape: Tuple[int, int]
) -> Optional[np.ndarray]:
    """
    Selects the 4 true ChromaBeam anchor centroids forming a valid convex matrix,
    filtering out surrounding desktop UI text, taskbars, and reflections.
    Returns (4, 2) float32 array in canonical order [TL, TR, BR, BL], or None.
    """
    if len(candidates) < 4:
        return None

    h, w = frame_shape[:2]
    min_quad_area = (w * h) * 0.005  # At least 0.5% of frame

    # If many candidates, limit to top 16 to avoid combinatorial explosion
    if len(candidates) > 16:
        # Sort candidates prioritizing reasonable anchor areas
        candidates = sorted(candidates, key=lambda c: c[2], reverse=True)[:16]

    best_quad = None
    best_score = -1.0

    # Evaluate candidate 4-combinations
    for comb in itertools.combinations(candidates, 4):
        pts = np.array([[c[0], c[1]] for c in comb], dtype=np.float32)
        ordered = order_quad_points(pts)

        # 1. Check convexity
        hull = cv2.convexHull(ordered.reshape(-1, 1, 2).astype(np.int32))
        if len(hull) < 4 or not cv2.isContourConvex(hull):
            continue

        # 2. Check area
        area = cv2.contourArea(ordered)
        if area < min_quad_area:
            continue

        # 3. Check side length ratios
        d0 = np.hypot(ordered[0, 0] - ordered[1, 0], ordered[0, 1] - ordered[1, 1])
        d1 = np.hypot(ordered[1, 0] - ordered[2, 0], ordered[1, 1] - ordered[2, 1])
        d2 = np.hypot(ordered[2, 0] - ordered[3, 0], ordered[2, 1] - ordered[3, 1])
        d3 = np.hypot(ordered[3, 0] - ordered[0, 0], ordered[3, 1] - ordered[0, 1])

        sides = [d0, d1, d2, d3]
        s_min, s_max = min(sides), max(sides)
        if s_max == 0 or (s_min / s_max) < 0.25:
            continue

        # 4. Check diagonals
        diag1 = np.hypot(ordered[0, 0] - ordered[2, 0], ordered[0, 1] - ordered[2, 1])
        diag2 = np.hypot(ordered[1, 0] - ordered[3, 0], ordered[1, 1] - ordered[3, 1])
        d_min, d_max = min(diag1, diag2), max(diag1, diag2)
        if d_max == 0 or (d_min / d_max) < 0.35:
            continue

        # 5. Check anchor area uniformity
        c_areas = [c[2] for c in comb]
        a_min, a_max = min(c_areas), max(c_areas)
        if a_max == 0 or (a_min / a_max) < 0.05:
            continue

        # Scoring: quad_area * side_regularity * diag_regularity * area_uniformity
        score = area * (s_min / s_max) * (d_min / d_max) * np.sqrt(a_min / a_max)

        if score > best_score:
            best_score = score
            best_quad = ordered

    return best_quad


class OpticalTracker:
    """
    Tracks and extracts ChromaBeam optical matrix frames from camera streams
    using 1:1:1:1:1 concentric hierarchy detection and 3D projective homography.
    """
    def __init__(self, target_grid_dim: int = 512):
        self.target_dim = target_grid_dim

    def find_anchors(self, frame: Optional[np.ndarray]) -> Optional[np.ndarray]:
        """
        Locates the 4 standardized 1:1:1:1:1 concentric finder pattern anchor centroids.
        Returns (4, 2) float32 array in [TL, TR, BR, BL] order, or None.
        """
        if frame is None or frame.size == 0:
            return None
        candidates = find_nested_anchor_centers(frame)
        return filter_and_order_4_anchors(candidates, frame.shape[:2])

    def find_matrix_quad(self, frame: Optional[np.ndarray]) -> Optional[np.ndarray]:
        """
        Locates the ChromaBeam matrix quad points.
        First tries 1:1:1:1:1 concentric anchor detection.
        If anchors are not resolved, falls back to largest convex 4-sided boundary polygon.
        """
        if frame is None or frame.size == 0:
            return None

        # Primary: 1:1:1:1:1 Concentric Anchor Hierarchy Detection
        anchors = self.find_anchors(frame)
        if anchors is not None:
            return anchors

        # Fallback: Largest 4-sided convex polygon search
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame.copy()
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        thresh = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2
        )

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best_quad = None
        max_area = 0
        h, w = frame.shape[:2]
        min_allowed_area = (w * h) * 0.04

        for cnt in contours[:100]:
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

    def compute_homography(
        self,
        quad_pts: np.ndarray,
        grid_size: int = 48,
        is_anchor_centers: bool = True
    ) -> np.ndarray:
        """
        Computes 3D projective homography matrix H mapping detected anchor centers
        directly to canonical coordinates (2.5/N, 2.5/N).
        """
        D = float(self.target_dim)
        if is_anchor_centers:
            c = 2.5 / float(grid_size)
            dst_pts = np.array([
                [c * D, c * D],                      # TL
                [(1.0 - c) * D, c * D],              # TR
                [(1.0 - c) * D, (1.0 - c) * D],      # BR
                [c * D, (1.0 - c) * D]               # BL
            ], dtype=np.float32)
        else:
            dst_pts = np.array([
                [0.0, 0.0],
                [D - 1.0, 0.0],
                [D - 1.0, D - 1.0],
                [0.0, D - 1.0]
            ], dtype=np.float32)

        src_pts = quad_pts.astype(np.float32)
        return cv2.getPerspectiveTransform(src_pts, dst_pts)

    def warp_matrix(
        self,
        frame: np.ndarray,
        quad_pts: np.ndarray,
        grid_size: int = 48,
        is_anchor_centers: bool = True
    ) -> np.ndarray:
        """
        Applies homography perspective transformation H to produce a normalized top-down square image.
        Maps the 4 anchor centers directly to canonical (2.5/N, 2.5/N) coordinates.
        """
        H = self.compute_homography(quad_pts, grid_size=grid_size, is_anchor_centers=is_anchor_centers)
        warped = cv2.warpPerspective(
            frame, H, (self.target_dim, self.target_dim), flags=cv2.INTER_LINEAR
        )
        return warped

    def find_matrix(
        self,
        frame: Optional[np.ndarray],
        grid_size: int = 48
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], bool]:
        """
        Interface contract: finds matrix quad and returns (warped_image, quad_points, status).
        """
        if frame is None or frame.size == 0:
            return None, None, False

        quad = self.find_matrix_quad(frame)
        if quad is None:
            return None, None, False

        warped = self.warp_matrix(frame, quad, grid_size=grid_size)
        return warped, quad, True

    def sample_grid_cells(self, warped_bgr: np.ndarray, grid_size: int = 48) -> np.ndarray:
        """
        Samples the center of each cell in the warped grid and converts BGR -> RGB.
        Uses a 3x3 patch around cell center to eliminate subpixel noise.
        Returns an (grid_size, grid_size, 3) RGB matrix.
        """
        cell_size = float(self.target_dim) / float(grid_size)
        sampled_grid = np.zeros((grid_size, grid_size, 3), dtype=np.uint8)

        # Convert to RGB if 3-channel BGR
        if warped_bgr.ndim == 3 and warped_bgr.shape[2] == 3:
            warped_rgb = cv2.cvtColor(warped_bgr, cv2.COLOR_BGR2RGB)
        elif warped_bgr.ndim == 2:
            warped_rgb = cv2.cvtColor(warped_bgr, cv2.COLOR_GRAY2RGB)
        else:
            warped_rgb = warped_bgr

        dim = self.target_dim
        for r in range(grid_size):
            cy = int((r + 0.5) * cell_size)
            for c in range(grid_size):
                cx = int((c + 0.5) * cell_size)
                # Sample 3x3 patch around cell centroid
                y_min = max(0, cy - 1)
                y_max = min(dim, cy + 2)
                x_min = max(0, cx - 1)
                x_max = min(dim, cx + 2)

                patch = warped_rgb[y_min:y_max, x_min:x_max]
                sampled_grid[r, c] = np.mean(patch, axis=(0, 1)).astype(np.uint8)

        return sampled_grid


# Alias for interface contract compliance
MatrixTracker = OpticalTracker
