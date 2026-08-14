"""
ChromaBeam Unified Desktop Application (PyQt6)
Features:
- Grandma Presets: 🛡️ Potato Camera (1-bit B&W), ⚖️ Balanced (2-bit 4-Color), ⚡ Turbo (3-bit 8-Color)
- Pro Settings (Custom grid density, frame rate, color modes)
- Optical Webcam Receiver with Auto-Density Detection & Homography Warp
- 100% Offline Single-File HTML Export & Mobile Pairing
"""

import sys
import os
import time
import random
import numpy as np
import cv2

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider, QComboBox, QFileDialog, QFrame,
    QProgressBar, QGroupBox, QTabWidget, QTextEdit, QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QFont

APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0] if sys.argv[0] else __file__))
sys.path.insert(0, APP_DIR)

from core.protocol import pack_packet, unpack_packet, pack_file_metadata, unpack_file_metadata
from core.fountain import LTEncoder, LTDecoder
from core.color_matrix import (
    ColorMatrixLayout, bytes_to_color_grid, color_grid_to_bytes, upscale_grid_for_display,
    MODE_1BIT_BW, MODE_2BIT_4COLOR, MODE_3BIT_8COLOR
)
from desktop_receiver.tracker import OpticalTracker
from desktop_receiver.color_classifier import AdaptiveColorClassifier


class OpticalMatrixCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(380, 380)
        self.current_pixmap = None
        self.setStyleSheet("background-color: #000000; border-radius: 8px;")

    def update_frame(self, rgb_matrix: np.ndarray):
        h, w, ch = rgb_matrix.shape
        upscaled = upscale_grid_for_display(rgb_matrix, target_resolution=480)
        uh, uw, _ = upscaled.shape
        qimg = QImage(upscaled.data, uw, uh, ch * uw, QImage.Format.Format_RGB888)
        self.current_pixmap = QPixmap.fromImage(qimg)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))
        if self.current_pixmap:
            side = min(self.width(), self.height()) - 10
            x = (self.width() - side) // 2
            y = (self.height() - side) // 2
            painter.drawPixmap(x, y, side, side, self.current_pixmap)


class CameraWorkerThread(QThread):
    frame_ready = pyqtSignal(np.ndarray, dict)
    file_received = pyqtSignal(str, int, str)

    def __init__(self, cam_index=0, output_dir=None):
        super().__init__()
        self.cam_index = cam_index
        self.output_dir = output_dir or os.path.expanduser("~/Downloads/ChromaBeam_Received")
        os.makedirs(self.output_dir, exist_ok=True)
        self.running = False

    def run(self):
        cap = cv2.VideoCapture(self.cam_index)
        if not cap.isOpened():
            return

        tracker = OpticalTracker(target_grid_dim=512)
        decoder = None
        current_file_id = None
        packets_caught = 0
        crc_errors = 0
        complete = False
        self.running = True

        candidate_densities = [32, 48, 64]
        candidate_modes = [MODE_1BIT_BW, MODE_2BIT_4COLOR, MODE_3BIT_8COLOR]
        rotations = [0, 90, 180, 270]

        layouts = {
            (s, m): ColorMatrixLayout(grid_size=s, color_mode=m)
            for s in candidate_densities for m in candidate_modes
        }
        last_successful_config = None  # (size, mode, rot)

        while self.running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            stats = {
                "locked": False,
                "packets": packets_caught,
                "crc_errors": crc_errors,
                "progress": decoder.get_progress() if decoder else 0.0,
                "complete": complete,
                "density": None,
                "mode": None,
                "rotation": None
            }

            quad = tracker.find_matrix_quad(frame)
            if quad is not None:
                stats["locked"] = True

                decoded_packet = None
                detected_config = None

                # Fast path: test last successful config first
                if last_successful_config is not None:
                    cached_size, cached_mode, cached_rot = last_successful_config
                    warped = tracker.warp_matrix(frame, quad, grid_size=cached_size)
                    sampled_grid = tracker.sample_grid_cells(warped, grid_size=cached_size)
                    rotated = np.rot90(sampled_grid, k=-cached_rot // 90) if cached_rot != 0 else sampled_grid
                    layout = layouts.get((cached_size, cached_mode), ColorMatrixLayout(cached_size, cached_mode))
                    raw_bytes = color_grid_to_bytes(rotated, layout)
                    packet_data = unpack_packet(raw_bytes)
                    if packet_data is not None:
                        decoded_packet = packet_data
                        detected_config = last_successful_config

                # Full sweep across densities, rotations, and color modes
                if decoded_packet is None:
                    for size in candidate_densities:
                        warped = tracker.warp_matrix(frame, quad, grid_size=size)
                        sampled_grid = tracker.sample_grid_cells(warped, grid_size=size)

                        for rot in rotations:
                            rotated = np.rot90(sampled_grid, k=-rot // 90) if rot != 0 else sampled_grid

                            for mode in candidate_modes:
                                layout = layouts[(size, mode)]
                                raw_bytes = color_grid_to_bytes(rotated, layout)
                                packet_data = unpack_packet(raw_bytes)
                                if packet_data is not None:
                                    decoded_packet = packet_data
                                    detected_config = (size, mode, rot)
                                    break
                            if decoded_packet is not None:
                                break
                        if decoded_packet is not None:
                            break

                if decoded_packet is not None:
                    header, payload = decoded_packet
                    last_successful_config = detected_config
                    packets_caught += 1

                    size, mode, rot = detected_config
                    stats["density"] = size
                    stats["mode"] = mode
                    stats["rotation"] = rot

                    if decoder is None or current_file_id != header.file_id:
                        current_file_id = header.file_id
                        decoder = LTDecoder(
                            K=header.total_blocks,
                            block_size=header.block_size,
                            total_filesize=header.total_blocks * header.block_size
                        )
                        complete = False

                    is_solved = decoder.add_droplet(header.seed, payload)

                    if is_solved and not complete:
                        complete = True
                        data = decoder.reconstruct_data()
                        if data:
                            meta = unpack_file_metadata(data)
                            filename = "received_file.bin"
                            filesize = len(data)
                            if meta:
                                filename, filesize, _ = meta
                                data = data[len(data) - filesize:]

                            out_path = os.path.join(self.output_dir, filename)
                            with open(out_path, "wb") as f:
                                f.write(data)
                            self.file_received.emit(filename, filesize, out_path)
                else:
                    crc_errors += 1

                # Draw tracking overlays on frame for visual display
                cv2.polylines(frame, [quad.astype(np.int32)], True, (0, 255, 0), 2)
                for pt in quad:
                    cv2.circle(frame, tuple(pt.astype(int)), 5, (0, 0, 255), -1)

            stats["packets"] = packets_caught
            stats["crc_errors"] = crc_errors
            stats["progress"] = decoder.get_progress() if decoder else 0.0
            stats["complete"] = complete

            self.frame_ready.emit(frame, stats)
            time.sleep(0.01)

        cap.release()

    def stop(self):
        self.running = False
        self.wait(1000)


class UnifiedChromaBeamApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ChromaBeam // Ultra-Fast Optical File Transfer Suite")
        self.resize(980, 740)
        self.setMinimumSize(900, 660)

        self.setStyleSheet("""
            QMainWindow { background-color: #0b0f14; }
            QWidget { color: #e6edf3; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
            QTabWidget::pane { border: 1px solid #30363d; background: #161b22; border-radius: 8px; }
            QTabBar::tab { background: #0b0f14; color: #8b949e; padding: 10px 24px; font-weight: bold; border-top-left-radius: 6px; border-top-right-radius: 6px; }
            QTabBar::tab:selected { background: #161b22; color: #58a6ff; border-bottom: 2px solid #58a6ff; }
            QGroupBox { background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; margin-top: 18px; padding-top: 14px; font-weight: bold; color: #58a6ff; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 2px 8px; }
            QPushButton { background-color: #21262d; border: 1px solid #363b42; border-radius: 6px; padding: 8px 16px; font-weight: bold; color: #f0f6fc; }
            QPushButton:hover { background-color: #30363d; border-color: #8b949e; }
            QPushButton#primary_btn { background-color: #1f6feb; border-color: #388bfd; }
            QPushButton#primary_btn:hover { background-color: #388bfd; }
            QPushButton#danger_btn { background-color: #da3633; border-color: #f85149; }
            QPushButton#preset_btn { background-color: #161b22; border: 2px solid #30363d; text-align: left; padding: 10px; border-radius: 8px; }
            QPushButton#preset_btn:hover { border-color: #58a6ff; }
            QPushButton#preset_btn[active="true"] { border-color: #2ea043; background-color: rgba(46, 160, 67, 0.15); }
            QComboBox { background-color: #21262d; border: 1px solid #30363d; border-radius: 6px; padding: 6px 12px; color: #f0f6fc; }
            QSlider::groove:horizontal { height: 6px; background: #21262d; border-radius: 3px; }
            QSlider::handle:horizontal { background: #58a6ff; width: 16px; margin: -5px 0; border-radius: 8px; }
            QProgressBar { border: 1px solid #30363d; border-radius: 6px; text-align: center; background-color: #0b0f14; color: white; font-weight: bold; }
            QProgressBar::chunk { background-color: #2ea043; border-radius: 5px; }
            QLabel#stat_val { font-family: 'Consolas', 'Courier New', monospace; font-size: 14px; font-weight: bold; color: #7ee787; }
        """)

        # Sender state
        self.grid_size = 32
        self.color_mode = MODE_1BIT_BW # Default to Potato Mode B&W
        self.target_fps = 15
        self.is_streaming = False
        self.file_data = None
        self.filename = "None"
        self.filesize = 0
        self.file_id = random.randint(1000, 60000)
        self.layout_engine = ColorMatrixLayout(grid_size=self.grid_size, color_mode=self.color_mode)
        self.encoder = None
        self.droplet_seed = 0
        self.total_droplets_sent = 0
        self.start_stream_time = 0.0

        # Receiver state
        self.cam_thread = None

        self._init_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_sender_tick)
        self.timer.start(int(1000 / self.target_fps))

        self._load_demo_payload()
        self._apply_preset('potato')

    def _init_ui(self):
        tabs = QTabWidget(self)
        self.setCentralWidget(tabs)

        sender_widget = QWidget()
        self._build_sender_tab(sender_widget)
        tabs.addTab(sender_widget, "📡 Beam Sender (Screen)")

        receiver_widget = QWidget()
        self._build_receiver_tab(receiver_widget)
        tabs.addTab(receiver_widget, "📸 Optical Receiver (Webcam)")

        offline_widget = QWidget()
        self._build_offline_tab(offline_widget)
        tabs.addTab(offline_widget, "📱 Offline & Mobile Pairing")

    def _build_sender_tab(self, parent):
        layout = QHBoxLayout(parent)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        left = QVBoxLayout()
        self.canvas = OpticalMatrixCanvas(self)
        left.addWidget(self.canvas, stretch=1)
        layout.addLayout(left, stretch=3)

        right = QVBoxLayout()
        right.setSpacing(10)

        # 1. Grandma Presets
        preset_grp = QGroupBox("1. Transmission Presets (Grandma Mode)")
        pr_layout = QHBoxLayout(preset_grp)

        self.btn_potato = QPushButton("🛡️ Potato Camera\n1-Bit B&W (Max Reliability)")
        self.btn_potato.setObjectName("preset_btn")
        self.btn_potato.clicked.connect(lambda: self._apply_preset('potato'))

        self.btn_balanced = QPushButton("⚖️ Balanced\n4-Color (Recommended)")
        self.btn_balanced.setObjectName("preset_btn")
        self.btn_balanced.clicked.connect(lambda: self._apply_preset('balanced'))

        self.btn_turbo = QPushButton("⚡ Turbo Speed\n8-Color RGB (550 KB/s)")
        self.btn_turbo.setObjectName("preset_btn")
        self.btn_turbo.clicked.connect(lambda: self._apply_preset('turbo'))

        pr_layout.addWidget(self.btn_potato)
        pr_layout.addWidget(self.btn_balanced)
        pr_layout.addWidget(self.btn_turbo)
        right.addWidget(preset_grp)

        # 2. File Selection
        file_grp = QGroupBox("2. Payload Selection")
        fl = QVBoxLayout(file_grp)
        self.file_lbl = QLabel("File: chromabeam_sample.bin")
        self.size_lbl = QLabel("Size: 64 KB | Blocks: 168")
        btn_row = QHBoxLayout()
        b1 = QPushButton("📁 Choose File...")
        b1.clicked.connect(self._select_file)
        b2 = QPushButton("⚡ Load Demo 64KB")
        b2.clicked.connect(self._load_demo_payload)
        btn_row.addWidget(b1)
        btn_row.addWidget(b2)
        fl.addWidget(self.file_lbl)
        fl.addWidget(self.size_lbl)
        fl.addLayout(btn_row)
        right.addWidget(file_grp)

        # 3. Pro Mode Accordion
        self.pro_box = QGroupBox("⚙️ Advanced Parameters (Pro)")
        pl = QVBoxLayout(self.pro_box)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Color Depth:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["1-bit Monochrome (Black & White)", "2-bit 4-Color (K, R, G, W)", "3-bit 8-Color (JAB RGB)"])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self.mode_combo)
        pl.addLayout(mode_row)

        grid_row = QHBoxLayout()
        grid_row.addWidget(QLabel("Matrix Density:"))
        self.grid_combo = QComboBox()
        self.grid_combo.addItems(["32x32 (Ultra Large)", "48x48 (Balanced)", "64x64 (High Density)"])
        self.grid_combo.currentIndexChanged.connect(self._on_grid_changed)
        grid_row.addWidget(self.grid_combo)
        pl.addLayout(grid_row)

        fps_row = QHBoxLayout()
        self.fps_lbl = QLabel(f"FPS: {self.target_fps}")
        self.fps_slider = QSlider(Qt.Orientation.Horizontal)
        self.fps_slider.setRange(1, 60)
        self.fps_slider.setValue(self.target_fps)
        self.fps_slider.valueChanged.connect(self._on_fps_changed)
        fps_row.addWidget(self.fps_lbl)
        fps_row.addWidget(self.fps_slider)
        pl.addLayout(fps_row)
        right.addWidget(self.pro_box)

        # 4. Telemetry
        stat_grp = QGroupBox("Live Telemetry")
        sl = QVBoxLayout(stat_grp)
        self.rate_lbl = QLabel("0.0 KB/s")
        self.rate_lbl.setObjectName("stat_val")
        self.droplet_lbl = QLabel("Droplets Sent: 0")
        self.cycle_lbl = QLabel("Cycles: 0x")
        sl.addWidget(self.rate_lbl)
        sl.addWidget(self.droplet_lbl)
        sl.addWidget(self.cycle_lbl)
        right.addWidget(stat_grp)

        self.stream_btn = QPushButton("🚀 START OPTICAL BEAM")
        self.stream_btn.setObjectName("primary_btn")
        self.stream_btn.setFixedHeight(44)
        self.stream_btn.clicked.connect(self._toggle_stream)
        right.addWidget(self.stream_btn)

        right.addStretch()
        layout.addLayout(right, stretch=2)

    def _apply_preset(self, preset):
        for btn in [self.btn_potato, self.btn_balanced, self.btn_turbo]:
            btn.setProperty("active", "false")

        if preset == 'potato':
            self.btn_potato.setProperty("active", "true")
            self.color_mode = MODE_1BIT_BW
            self.grid_size = 32
            self.target_fps = 15
        elif preset == 'balanced':
            self.btn_balanced.setProperty("active", "true")
            self.color_mode = MODE_2BIT_4COLOR
            self.grid_size = 48
            self.target_fps = 25
        elif preset == 'turbo':
            self.btn_turbo.setProperty("active", "true")
            self.color_mode = MODE_3BIT_8COLOR
            self.grid_size = 64
            self.target_fps = 45

        for btn in [self.btn_potato, self.btn_balanced, self.btn_turbo]:
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        # Sync Pro controls
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentIndex(self.color_mode)
        self.mode_combo.blockSignals(False)

        self.grid_combo.blockSignals(True)
        self.grid_combo.setCurrentIndex(0 if self.grid_size == 32 else (1 if self.grid_size == 48 else 2))
        self.grid_combo.blockSignals(False)

        self.fps_slider.setValue(self.target_fps)
        self.fps_lbl.setText(f"FPS: {self.target_fps}")
        self.timer.setInterval(int(1000 / self.target_fps))

        self.layout_engine = ColorMatrixLayout(grid_size=self.grid_size, color_mode=self.color_mode)
        if self.file_data:
            self._set_payload(self.file_data, self.filename)

    def _build_receiver_tab(self, parent):
        layout = QHBoxLayout(parent)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        left = QVBoxLayout()
        self.cam_view = QLabel()
        self.cam_view.setMinimumSize(420, 360)
        self.cam_view.setStyleSheet("background: #000000; border: 1px solid #30363d; border-radius: 8px;")
        self.cam_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cam_view.setText("Webcam Scanner Offline\nClick 'Start Scanner' below")
        left.addWidget(self.cam_view, stretch=1)
        layout.addLayout(left, stretch=3)

        right = QVBoxLayout()
        right.setSpacing(12)

        ctrl_grp = QGroupBox("Webcam Setup (Auto-Detect Active)")
        cl = QVBoxLayout(ctrl_grp)
        cam_row = QHBoxLayout()
        cam_row.addWidget(QLabel("Camera Device:"))
        self.cam_combo = QComboBox()
        self.cam_combo.addItems(["Camera Index 0 (Default)", "Camera Index 1", "Camera Index 2"])
        cam_row.addWidget(self.cam_combo)
        cl.addLayout(cam_row)

        self.cam_btn = QPushButton("📸 START WEBCAM SCANNER")
        self.cam_btn.setObjectName("primary_btn")
        self.cam_btn.clicked.connect(self._toggle_camera)
        cl.addWidget(self.cam_btn)
        right.addWidget(ctrl_grp)

        prog_grp = QGroupBox("Fountain Solver Progress")
        prl = QVBoxLayout(prog_grp)
        self.rx_progress = QProgressBar()
        self.rx_progress.setValue(0)
        self.rx_status = QLabel("Status: Idle")
        self.rx_packets = QLabel("Caught: 0 (Drops: 0)")
        prl.addWidget(self.rx_status)
        prl.addWidget(self.rx_progress)
        prl.addWidget(self.rx_packets)
        right.addWidget(prog_grp)

        self.rx_log = QTextEdit()
        self.rx_log.setReadOnly(True)
        self.rx_log.setPlaceholderText("Transfer logs and downloaded files will appear here...")
        self.rx_log.setStyleSheet("background: #090d12; border: 1px solid #30363d; border-radius: 6px;")
        right.addWidget(self.rx_log)

        layout.addLayout(right, stretch=2)

    def _build_offline_tab(self, parent):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("100% Offline & Mobile Air-Gapped Transfer")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #58a6ff;")
        layout.addWidget(title)

        desc = QLabel(
            "ChromaBeam requires zero internet, zero Bluetooth, and zero local Wi-Fi pairing.\n"
            "You can transfer files to phones and PCs in complete airplane mode using light photons."
        )
        desc.setStyleSheet("color: #8b949e; line-height: 1.6;")
        layout.addWidget(desc)

        box = QGroupBox("Portable Standalone HTML App")
        bl = QVBoxLayout(box)
        b_desc = QLabel(
            "We have bundled the entire Web & Mobile sender/receiver into a single 48KB offline file.\n"
            "Copy 'chromabeam_offline.html' to any phone, USB stick, or laptop and open it directly in Chrome/Brave/Safari!"
        )
        b_desc.setWordWrap(True)
        b_btn = QPushButton("📁 Reveal 'chromabeam_offline.html' in File Manager")
        b_btn.clicked.connect(self._reveal_offline_file)
        bl.addWidget(b_desc)
        bl.addWidget(b_btn)
        layout.addWidget(box)

        layout.addStretch()

    def _select_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select File to Beam", "", "All Files (*)")
        if path:
            with open(path, "rb") as f:
                data = f.read()
            self._set_payload(data, os.path.basename(path))

    def _load_demo_payload(self):
        data = b"ChromaBeam-HighSpeedOpticalPayload\n" + (os.urandom(64 * 1024))
        self._set_payload(data, "chromabeam_demo_64kb.bin")

    def _set_payload(self, data: bytes, name: str):
        self.file_data = data
        self.filename = name
        self.filesize = len(data)
        self.file_id = random.randint(1000, 60000)

        block_size = max(24, self.layout_engine.max_payload_bytes - 16)
        meta_bytes = pack_file_metadata(self.filename, self.filesize)
        full_stream_payload = meta_bytes + self.file_data

        self.encoder = LTEncoder(full_stream_payload, block_size=block_size)
        self.droplet_seed = 0
        self.total_droplets_sent = 0

        self.file_lbl.setText(f"File: {self.filename}")
        self.size_lbl.setText(f"Size: {self.filesize / 1024:.1f} KB | Blocks K: {self.encoder.K} (Block: {block_size} B)")

    def _on_mode_changed(self, index: int):
        self.color_mode = index
        self.layout_engine = ColorMatrixLayout(grid_size=self.grid_size, color_mode=self.color_mode)
        if self.file_data:
            self._set_payload(self.file_data, self.filename)

    def _on_grid_changed(self, index: int):
        sizes = [32, 48, 64]
        self.grid_size = sizes[index]
        self.layout_engine = ColorMatrixLayout(grid_size=self.grid_size, color_mode=self.color_mode)
        if self.file_data:
            self._set_payload(self.file_data, self.filename)

    def _on_fps_changed(self, val: int):
        self.target_fps = val
        self.fps_lbl.setText(f"FPS: {self.target_fps}")
        self.timer.setInterval(int(1000 / self.target_fps))

    def _toggle_stream(self):
        self.is_streaming = not self.is_streaming
        if self.is_streaming:
            self.stream_btn.setText("🛑 STOP OPTICAL BEAM")
            self.stream_btn.setObjectName("danger_btn")
            self.start_stream_time = time.time()
            self.total_droplets_sent = 0
        else:
            self.stream_btn.setText("🚀 START OPTICAL BEAM")
            self.stream_btn.setObjectName("primary_btn")
            self.rate_lbl.setText("0.0 KB/s")
        self.stream_btn.style().unpolish(self.stream_btn)
        self.stream_btn.style().polish(self.stream_btn)

    def _on_sender_tick(self):
        if not self.is_streaming or self.encoder is None:
            return

        seed = self.droplet_seed
        self.droplet_seed += 1
        self.total_droplets_sent += 1

        degree, indices, block_payload = self.encoder.generate_droplet(seed)
        packet = pack_packet(
            file_id=self.file_id,
            total_blocks=self.encoder.K,
            block_size=self.encoder.block_size,
            seed=seed,
            payload=block_payload
        )

        rgb_grid = bytes_to_color_grid(packet, self.layout_engine)
        self.canvas.update_frame(rgb_grid)

        elapsed = max(0.001, time.time() - self.start_stream_time)
        bytes_sent = self.total_droplets_sent * len(packet)
        kb_per_sec = (bytes_sent / 1024.0) / elapsed
        cycles = self.total_droplets_sent // max(1, self.encoder.K)

        self.rate_lbl.setText(f"{kb_per_sec:.1f} KB/s")
        self.droplet_lbl.setText(f"Droplets: {self.total_droplets_sent} (Seed #{seed})")
        self.cycle_lbl.setText(f"Cycles: {cycles}x | Degree: {degree}")

    def _toggle_camera(self):
        if self.cam_thread and self.cam_thread.isRunning():
            self.cam_thread.stop()
            self.cam_thread = None
            self.cam_btn.setText("📸 START WEBCAM SCANNER")
            self.cam_btn.setObjectName("primary_btn")
            self.rx_status.setText("Status: Offline")
        else:
            cam_idx = self.cam_combo.currentIndex()
            self.cam_thread = CameraWorkerThread(cam_index=cam_idx)
            self.cam_thread.frame_ready.connect(self._on_cam_frame)
            self.cam_thread.file_received.connect(self._on_file_received)
            self.cam_thread.start()
            self.cam_btn.setText("🛑 STOP WEBCAM SCANNER")
            self.cam_btn.setObjectName("danger_btn")
            self.rx_status.setText("Status: Scanning for optical stream...")

        self.cam_btn.style().unpolish(self.cam_btn)
        self.cam_btn.style().polish(self.cam_btn)

    def _on_cam_frame(self, frame: np.ndarray, stats: dict):
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_frame.shape
        qimg = QImage(rgb_frame.data, w, h, ch * w, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg).scaled(
            self.cam_view.width(), self.cam_view.height(),
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        self.cam_view.setPixmap(pixmap)

        lock_text = "LOCKED ON BEAM" if stats["locked"] else "Scanning..."
        self.rx_status.setText(f"Status: {lock_text}")
        self.rx_progress.setValue(int(stats["progress"] * 100))
        self.rx_packets.setText(f"Caught: {stats['packets']} (CRC Drops: {stats['crc_errors']})")

    def _on_file_received(self, filename: str, filesize: int, path: str):
        self.rx_log.append(f"🎉 <b>SUCCESS!</b> Received <b>{filename}</b> ({(filesize/1024):.1f} KB)<br>Saved to: <code>{path}</code>")

    def _reveal_offline_file(self):
        offline_path = os.path.join(APP_DIR, "chromabeam_offline.html")
        os.system(f"xdg-open '{os.path.dirname(offline_path)}' &")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="ChromaBeam Unified Desktop Suite")
    parser.add_argument("--auto-screenshot", type=str, default=None, help="Capture screenshot to path and exit")
    args = parser.parse_args()

    if args.auto_screenshot and "QT_QPA_PLATFORM" not in os.environ and "DISPLAY" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    app = QApplication(sys.argv)
    win = UnifiedChromaBeamApp()
    win.show()

    if args.auto_screenshot:
        win._toggle_stream()
        for _ in range(5):
            win._on_sender_tick()
            app.processEvents()

        pix = win.grab()
        os.makedirs(os.path.dirname(os.path.abspath(args.auto_screenshot)), exist_ok=True)
        pix.save(args.auto_screenshot, "PNG")
        print(f"[ChromaBeam] Saved screenshot -> {args.auto_screenshot}")
        sys.exit(0)

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
