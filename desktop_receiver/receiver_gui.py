"""
ChromaBeam Desktop Optical Receiver (OpenCV HUD)
Processes high-speed camera stream, tracks optical screen, solves LT droplets, and outputs reconstructed files.
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
from core.color_matrix import ColorMatrixLayout, color_grid_to_bytes
from desktop_receiver.tracker import OpticalTracker
from desktop_receiver.color_classifier import AdaptiveColorClassifier


class ChromaBeamReceiver:
    def __init__(self, grid_size: int = 48, output_dir: str = "/tmp/chromabeam_downloads"):
        self.grid_size = grid_size
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

        self.layout = ColorMatrixLayout(grid_size=self.grid_size)
        self.tracker = OpticalTracker(target_grid_dim=512)
        self.classifier = AdaptiveColorClassifier()

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
        Processes a single camera frame.
        Returns (annotated_frame, stats_dict).
        """
        stats = {
            "locked": False,
            "packets": self.packets_received,
            "crc_errors": self.crc_errors,
            "progress": self.decoder.get_progress() if self.decoder else 0.0,
            "complete": self.complete,
            "fps": 0.0
        }

        h, w = frame.shape[:2]
        quad = self.tracker.find_matrix_quad(frame)

        if quad is not None:
            stats["locked"] = True
            # Draw tracking boundary
            cv2.polylines(frame, [quad.astype(np.int32)], True, (0, 255, 0), 2)
            for pt in quad:
                cv2.circle(frame, tuple(pt.astype(int)), 6, (0, 0, 255), -1)

            # Warp and extract cells
            warped = self.tracker.warp_matrix(frame, quad)
            sampled_grid = self.tracker.sample_grid_cells(warped, grid_size=self.grid_size)

            # Decode bytes from grid
            raw_bytes = color_grid_to_bytes(sampled_grid, self.layout)
            packet_data = unpack_packet(raw_bytes)

            if packet_data is not None:
                header, payload = packet_data
                self.packets_received += 1

                if self.start_time is None:
                    self.start_time = time.time()

                # Initialize decoder if new file session
                if self.decoder is None or self.current_file_id != header.file_id:
                    self.current_file_id = header.file_id
                    # Initial dummy filesize until metadata arrives
                    self.decoder = LTDecoder(
                        K=header.total_blocks,
                        block_size=header.block_size,
                        total_filesize=header.total_blocks * header.block_size
                    )

                # Feed droplet to fountain solver
                is_solved = self.decoder.add_droplet(header.seed, payload)
                stats["progress"] = self.decoder.get_progress()

                if is_solved and not self.complete:
                    self.complete = True
                    self._save_reconstructed_file()
            else:
                self.crc_errors += 1

        # Draw HUD overlay
        self._draw_hud(frame, stats)
        return frame, stats

    def _save_reconstructed_file(self):
        data = self.decoder.reconstruct_data()
        if data:
            meta = unpack_file_metadata(data)
            if meta:
                self.filename, self.filesize, _ = meta
                data = data[len(data) - self.filesize:]  # Extract actual payload

            out_path = os.path.join(self.output_dir, self.filename)
            with open(out_path, "wb") as f:
                f.write(data)
            print(f"[ChromaBeam] File successfully saved to: {out_path}")

    def _draw_hud(self, frame: np.ndarray, stats: dict):
        h, w = frame.shape[:2]
        # Top banner HUD
        cv2.rectangle(frame, (10, 10), (320, 130), (20, 20, 20), -1)
        cv2.rectangle(frame, (10, 10), (320, 130), (80, 80, 80), 1)

        lock_status = "LOCKED" if stats["locked"] else "SEARCHING..."
        lock_color = (0, 255, 0) if stats["locked"] else (0, 165, 255)
        cv2.putText(frame, f"STATUS: {lock_status}", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.6, lock_color, 2)

        prog_pct = stats["progress"] * 100.0
        cv2.putText(frame, f"PROGRESS: {prog_pct:.1f}%", (20, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.putText(frame, f"DROPLETS: {stats['packets']} (CRC Drops: {stats['crc_errors']})", (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

        # Progress bar
        bar_w = 280
        fill_w = int(bar_w * stats["progress"])
        cv2.rectangle(frame, (20, 105), (20 + bar_w, 120), (50, 50, 50), -1)
        if fill_w > 0:
            cv2.rectangle(frame, (20, 105), (20 + fill_w, 120), (0, 220, 0), -1)


def run_camera_receiver(cam_index: int = 0, grid_size: int = 48):
    """
    Runs interactive camera receiver loop.
    """
    cap = cv2.VideoCapture(cam_index)
    if not cap.isOpened():
        print(f"[Error] Could not open camera {cam_index}")
        return

    receiver = ChromaBeamReceiver(grid_size=grid_size)
    print("[ChromaBeam Receiver] Point camera at sender screen. Press 'q' to quit.")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        annotated, stats = receiver.process_frame(frame)
        cv2.imshow("ChromaBeam Optical Receiver", annotated)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == '__main__':
    run_camera_receiver()
