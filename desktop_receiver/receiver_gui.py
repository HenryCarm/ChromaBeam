"""
ChromaBeam Desktop Optical Receiver (OpenCV HUD)
Processes high-speed camera stream, tracks optical screen with 1:1:1:1:1 concentric anchors,
applies 360° 4-way rotation invariance (0°, 90°, 180°, 270°), auto-density sweeping,
solves LT droplets, and outputs reconstructed files.
"""

import cv2
import numpy as np
import time
import os
import sys
from typing import Optional, Tuple, List, Dict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.protocol import unpack_packet, unpack_file_metadata
from core.fountain import LTDecoder
from core.color_matrix import (
    ColorMatrixLayout, color_grid_to_bytes,
    MODE_1BIT_BW, MODE_2BIT_4COLOR, MODE_3BIT_8COLOR
)
from desktop_receiver.tracker import OpticalTracker
from desktop_receiver.color_classifier import AdaptiveColorClassifier


class ChromaBeamReceiver:
    def __init__(
        self,
        grid_size: Optional[int] = 48,
        output_dir: str = "/tmp/chromabeam_downloads",
        auto_density: bool = True
    ):
        self.grid_size = grid_size
        self.auto_density = auto_density
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

        self.tracker = OpticalTracker(target_grid_dim=512)
        self.classifier = AdaptiveColorClassifier()

        # Layout cache
        self.candidate_densities = [32, 48, 64]
        if self.grid_size is not None and self.grid_size not in self.candidate_densities:
            self.candidate_densities.insert(0, self.grid_size)
        elif self.grid_size is not None:
            # Prioritize specified grid size
            self.candidate_densities.remove(self.grid_size)
            self.candidate_densities.insert(0, self.grid_size)

        self.candidate_modes = [MODE_1BIT_BW, MODE_2BIT_4COLOR, MODE_3BIT_8COLOR]
        self.rotations = [0, 90, 180, 270]

        self.layouts: Dict[Tuple[int, int], ColorMatrixLayout] = {}
        for s in self.candidate_densities:
            for m in self.candidate_modes:
                self.layouts[(s, m)] = ColorMatrixLayout(grid_size=s, color_mode=m)

        self.last_successful_config: Optional[Tuple[int, int, int]] = None  # (size, mode, rot)

        self.decoder: Optional[LTDecoder] = None
        self.current_file_id: Optional[int] = None
        self.metadata_decoded = False
        self.filename = "received_file.bin"
        self.filesize = 0

        self.packets_received = 0
        self.crc_errors = 0
        self.start_time = None
        self.complete = False

    def process_frame(self, frame: np.ndarray) -> Tuple[np.ndarray, dict]:
        """
        Processes a single camera frame with 360° 4-way rotation invariance and auto-density sweeping.
        Returns (annotated_frame, stats_dict).
        """
        stats = {
            "locked": False,
            "packets": self.packets_received,
            "crc_errors": self.crc_errors,
            "progress": self.decoder.get_progress() if self.decoder else 0.0,
            "complete": self.complete,
            "density": None,
            "mode": None,
            "rotation": None,
            "fps": 0.0
        }

        h, w = frame.shape[:2]
        quad = self.tracker.find_matrix_quad(frame)

        if quad is not None:
            stats["locked"] = True

            # Evaluate 360° 4-way rotations and auto-density configurations on pristine frame
            decoded_packet = None
            detected_config = None

            # Fast path: try cached configuration first if available
            if self.last_successful_config is not None:
                cached_size, cached_mode, cached_rot = self.last_successful_config
                warped = self.tracker.warp_matrix(frame, quad, grid_size=cached_size)
                sampled_grid = self.tracker.sample_grid_cells(warped, grid_size=cached_size)
                rotated = np.rot90(sampled_grid, k=-cached_rot // 90) if cached_rot != 0 else sampled_grid
                layout = self.layouts.get((cached_size, cached_mode), ColorMatrixLayout(cached_size, cached_mode))
                raw_bytes = color_grid_to_bytes(rotated, layout)
                packet_data = unpack_packet(raw_bytes)
                if packet_data is not None:
                    decoded_packet = packet_data
                    detected_config = (cached_size, cached_mode, cached_rot)

            # Full sweep if fast path missed
            if decoded_packet is None:
                densities_to_try = self.candidate_densities if self.auto_density or self.grid_size is None else [self.grid_size]
                for density in densities_to_try:
                    warped = self.tracker.warp_matrix(frame, quad, grid_size=density)
                    sampled_grid = self.tracker.sample_grid_cells(warped, grid_size=density)

                    for rot in self.rotations:
                        rotated = np.rot90(sampled_grid, k=-rot // 90) if rot != 0 else sampled_grid

                        for mode in self.candidate_modes:
                            layout = self.layouts.get((density, mode), ColorMatrixLayout(density, mode))
                            raw_bytes = color_grid_to_bytes(rotated, layout)
                            packet_data = unpack_packet(raw_bytes)
                            if packet_data is not None:
                                decoded_packet = packet_data
                                detected_config = (density, mode, rot)
                                break
                        if decoded_packet is not None:
                            break
                    if decoded_packet is not None:
                        break

            if decoded_packet is not None:
                header, payload = decoded_packet
                self.last_successful_config = detected_config
                self.packets_received += 1

                density, mode, rot = detected_config
                stats["density"] = density
                stats["mode"] = mode
                stats["rotation"] = rot

                if self.start_time is None:
                    self.start_time = time.time()

                # Initialize decoder if new file session
                if self.decoder is None or self.current_file_id != header.file_id:
                    self.current_file_id = header.file_id
                    self.decoder = LTDecoder(
                        K=header.total_blocks,
                        block_size=header.block_size,
                        total_filesize=header.total_blocks * header.block_size
                    )

                # Feed droplet to fountain solver
                is_solved = self.decoder.add_droplet(header.seed, payload)

                if is_solved and not self.complete:
                    self.complete = True
                    self._save_reconstructed_file()
            else:
                self.crc_errors += 1

            # Draw tracking boundary and anchor corners on frame for visual display
            cv2.polylines(frame, [quad.astype(np.int32)], True, (0, 255, 0), 2)
            corner_colors = [(0, 0, 255), (0, 255, 255), (255, 0, 0), (255, 255, 0)]  # TL=Red, TR=Yellow, BR=Blue, BL=Cyan
            for idx, pt in enumerate(quad):
                cv2.circle(frame, tuple(pt.astype(int)), 6, corner_colors[idx % 4], -1)

        # Update stats
        stats["packets"] = self.packets_received
        stats["crc_errors"] = self.crc_errors
        stats["progress"] = self.decoder.get_progress() if self.decoder else 0.0
        stats["complete"] = self.complete

        # Draw HUD overlay
        self._draw_hud(frame, stats)
        return frame, stats

    def _save_reconstructed_file(self):
        data = self.decoder.reconstruct_data()
        if data:
            meta = unpack_file_metadata(data)
            if meta:
                self.filename, self.filesize, _ = meta
                self.filename = self.filename.strip() if self.filename else "received_file.bin"
                if not self.filename:
                    self.filename = "received_file.bin"
                data = data[:self.filesize] if self.filesize else data
            else:
                self.filename = self.filename.strip() if self.filename else "received_file.bin"
                if not self.filename:
                    self.filename = "received_file.bin"

            os.makedirs(self.output_dir, exist_ok=True)
            out_path = os.path.join(self.output_dir, self.filename)
            with open(out_path, "wb") as f:
                f.write(data)
            print(f"[ChromaBeam] File successfully saved to: {out_path}")

    def _draw_hud(self, frame: np.ndarray, stats: dict):
        h, w = frame.shape[:2]
        # Top banner HUD
        cv2.rectangle(frame, (10, 10), (350, 140), (20, 20, 20), -1)
        cv2.rectangle(frame, (10, 10), (350, 140), (80, 80, 80), 1)

        lock_status = "LOCKED" if stats["locked"] else "SEARCHING..."
        lock_color = (0, 255, 0) if stats["locked"] else (0, 165, 255)

        cfg_str = ""
        if stats.get("density") is not None:
            cfg_str = f" [{stats['density']}x{stats['density']} M{stats['mode']} {stats['rotation']}°]"

        cv2.putText(frame, f"STATUS: {lock_status}{cfg_str}", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.55, lock_color, 2)

        prog_pct = stats["progress"] * 100.0
        cv2.putText(frame, f"PROGRESS: {prog_pct:.1f}%", (20, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.putText(frame, f"DROPLETS: {stats['packets']} (CRC Drops: {stats['crc_errors']})", (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

        # Progress bar
        bar_w = 310
        fill_w = int(bar_w * stats["progress"])
        cv2.rectangle(frame, (20, 105), (20 + bar_w, 120), (50, 50, 50), -1)
        if fill_w > 0:
            cv2.rectangle(frame, (20, 105), (20 + fill_w, 120), (0, 220, 0), -1)


def run_camera_receiver(
    cam_index: int = 0,
    grid_size: Optional[int] = 48,
    max_frames: Optional[int] = None,
    timeout_seconds: Optional[float] = None
):
    """
    Runs interactive camera receiver loop with explicit finite bounds and timeout guards.
    Never blocks indefinitely.
    """
    cap = cv2.VideoCapture(cam_index)
    if not cap.isOpened():
        print(f"[Error] Could not open camera {cam_index}")
        return

    receiver = ChromaBeamReceiver(grid_size=grid_size, auto_density=True)
    print("[ChromaBeam Receiver] Point camera at sender screen. Press 'q' to quit.")

    start_time = time.time()
    frames_processed = 0

    while True:
        if max_frames is not None and frames_processed >= max_frames:
            break
        if timeout_seconds is not None and (time.time() - start_time) >= timeout_seconds:
            break

        ret, frame = cap.read()
        if not ret:
            break

        frames_processed += 1
        annotated, stats = receiver.process_frame(frame)
        cv2.imshow("ChromaBeam Optical Receiver", annotated)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == '__main__':
    run_camera_receiver()
