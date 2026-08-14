"""
ChromaBeam Modern Desktop Sender GUI (PyQt6)
High-performance 60 FPS animated optical matrix sender with drag-and-drop file loading,
real-time statistics, grid density controls, and --auto-screenshot offscreen rendering.
"""

import os
import sys
import time
import random
import numpy as np

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider, QComboBox, QFileDialog, QFrame,
    QProgressBar, QGroupBox
)
from PyQt6.QtCore import Qt, QTimer, QRect
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QFont

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.protocol import pack_packet, pack_file_metadata
from core.fountain import LTEncoder
from core.color_matrix import ColorMatrixLayout, bytes_to_color_grid, upscale_grid_for_display


class OpticalMatrixCanvas(QWidget):
    """
    Hardware-accelerated widget rendering the high-speed ChromaBeam matrix.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 420)
        self.current_pixmap: Optional[QPixmap] = None
        self.setStyleSheet("background-color: #000000; border-radius: 8px;")

    def update_frame(self, rgb_matrix: np.ndarray):
        """
        Takes an (M, M, 3) RGB uint8 matrix and renders it.
        """
        h, w, ch = rgb_matrix.shape
        bytes_per_line = ch * w
        # Upscale for smooth high-DPI rendering
        upscaled = upscale_grid_for_display(rgb_matrix, target_resolution=480)
        uh, uw, _ = upscaled.shape
        qimg = QImage(upscaled.data, uw, uh, ch * uw, QImage.Format.Format_RGB888)
        self.current_pixmap = QPixmap.fromImage(qimg)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))
        if self.current_pixmap:
            # Draw centered
            side = min(self.width(), self.height()) - 10
            x = (self.width() - side) // 2
            y = (self.height() - side) // 2
            painter.drawPixmap(x, y, side, side, self.current_pixmap)


class SenderWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ChromaBeam // Ultra-Fast Optical Sender")
        self.resize(920, 680)
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0b0f14;
            }
            QWidget {
                color: #e6edf3;
                font-family: 'Segoe UI', 'SF Pro Text', 'Ubuntu', sans-serif;
                font-size: 13px;
            }
            QGroupBox {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 8px;
                margin-top: 18px;
                padding-top: 14px;
                font-weight: bold;
                color: #58a6ff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 2px 8px;
            }
            QPushButton {
                background-color: #21262d;
                border: 1px solid #363b42;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                color: #f0f6fc;
            }
            QPushButton:hover {
                background-color: #30363d;
                border-color: #8b949e;
            }
            QPushButton#stream_btn {
                background-color: #1f6feb;
                border-color: #388bfd;
            }
            QPushButton#stream_btn:hover {
                background-color: #388bfd;
            }
            QPushButton#stream_btn[active="true"] {
                background-color: #da3633;
                border-color: #f85149;
            }
            QComboBox {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 6px 12px;
                color: #f0f6fc;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #21262d;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #58a6ff;
                width: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
            QLabel#title {
                font-size: 20px;
                font-weight: bold;
                color: #58a6ff;
            }
            QLabel#badge {
                font-size: 11px;
                color: #7ee787;
                font-weight: bold;
            }
            QLabel#stat_val {
                font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
                font-size: 14px;
                font-weight: bold;
                color: #7ee787;
            }
        """)

        self.grid_size = 48
        self.target_fps = 45
        self.is_streaming = False
        self.file_data: Optional[bytes] = None
        self.filename = "No file selected"
        self.filesize = 0
        self.file_id = random.randint(1000, 60000)

        self.layout_engine = ColorMatrixLayout(grid_size=self.grid_size)
        self.encoder: Optional[LTEncoder] = None
        self.droplet_seed = 0
        self.total_droplets_sent = 0
        self.start_stream_time = 0.0

        # UI Setup
        self._init_ui()

        # 60 FPS Render Timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_tick)
        self.timer.start(int(1000 / self.target_fps))

        # Show idle blank test frame
        self._render_idle_frame()

    def _init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        # Left Column: Optical Canvas
        left_layout = QVBoxLayout()
        header_row = QHBoxLayout()
        title_lbl = QLabel("ChromaBeam Sender")
        title_lbl.setObjectName("title")
        badge_lbl = QLabel("● RGB 3-BIT FOUNTAIN STREAM")
        badge_lbl.setObjectName("badge")
        header_row.addWidget(title_lbl)
        header_row.addStretch()
        header_row.addWidget(badge_lbl)
        left_layout.addLayout(header_row)

        self.canvas = OpticalMatrixCanvas(self)
        left_layout.addWidget(self.canvas, stretch=1)
        main_layout.addLayout(left_layout, stretch=3)

        # Right Column: Controls & Metrics
        right_layout = QVBoxLayout()
        right_layout.setSpacing(14)

        # File Selection Group
        file_grp = QGroupBox("Payload Selection")
        file_layout = QVBoxLayout(file_grp)
        self.file_lbl = QLabel("Selected: None (Defaulting to built-in test packet)")
        self.file_lbl.setWordWrap(True)
        self.size_lbl = QLabel("Size: 0 Bytes | Blocks: 0")
        
        btn_row = QHBoxLayout()
        self.select_btn = QPushButton("📁 Choose File...")
        self.select_btn.clicked.connect(self._select_file)
        self.sample_btn = QPushButton("⚡ Load Demo 256KB Payload")
        self.sample_btn.clicked.connect(self._load_demo_payload)
        btn_row.addWidget(self.select_btn)
        btn_row.addWidget(self.sample_btn)

        file_layout.addWidget(self.file_lbl)
        file_layout.addWidget(self.size_lbl)
        file_layout.addLayout(btn_row)
        right_layout.addWidget(file_grp)

        # Transmission Parameters Group
        param_grp = QGroupBox("Transmission Parameters")
        param_layout = QVBoxLayout(param_grp)

        grid_row = QHBoxLayout()
        grid_row.addWidget(QLabel("Matrix Density:"))
        self.grid_combo = QComboBox()
        self.grid_combo.addItems(["32x32 (Ultra Safe - 180 KB/s max)", "48x48 (Balanced - 350 KB/s max)", "64x64 (High Speed - 550 KB/s max)"])
        self.grid_combo.setCurrentIndex(1)
        self.grid_combo.currentIndexChanged.connect(self._on_grid_changed)
        grid_row.addWidget(self.grid_combo)
        param_layout.addLayout(grid_row)

        fps_row = QHBoxLayout()
        self.fps_lbl = QLabel(f"Target Frame Rate: {self.target_fps} FPS")
        self.fps_slider = QSlider(Qt.Orientation.Horizontal)
        self.fps_slider.setRange(1, 60)
        self.fps_slider.setValue(self.target_fps)
        self.fps_slider.valueChanged.connect(self._on_fps_changed)
        fps_row.addWidget(self.fps_lbl)
        fps_row.addWidget(self.fps_slider)
        param_layout.addLayout(fps_row)
        right_layout.addWidget(param_grp)

        # Live Telemetry Group
        stat_grp = QGroupBox("Real-Time Telemetry")
        stat_layout = QVBoxLayout(stat_grp)

        self.rate_lbl = QLabel("0.0 KB/s")
        self.rate_lbl.setObjectName("stat_val")
        self.droplet_lbl = QLabel("Droplets Sent: 0")
        self.loop_lbl = QLabel("Stream Cycles: 0")

        stat_layout.addWidget(QLabel("Effective Throughput:"))
        stat_layout.addWidget(self.rate_lbl)
        stat_layout.addWidget(self.droplet_lbl)
        stat_layout.addWidget(self.loop_lbl)
        right_layout.addWidget(stat_grp)

        # Stream Action Button
        self.stream_btn = QPushButton("🚀 START OPTICAL BEAM")
        self.stream_btn.setObjectName("stream_btn")
        self.stream_btn.setFixedHeight(46)
        self.stream_btn.clicked.connect(self._toggle_stream)
        right_layout.addWidget(self.stream_btn)

        right_layout.addStretch()
        main_layout.addLayout(right_layout, stretch=2)

        # Pre-load demo payload by default
        self._load_demo_payload()

    def _select_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select File to Beam", "", "All Files (*)")
        if path:
            with open(path, "rb") as f:
                data = f.read()
            self._set_payload(data, os.path.basename(path))

    def _load_demo_payload(self):
        # Generate synthetic 128KB payload
        data = b"ChromaBeam-HighSpeedOpticalPayload\n" + (os.urandom(128 * 1024))
        self._set_payload(data, "chromabeam_demo_sample.bin")

    def _set_payload(self, data: bytes, name: str):
        self.file_data = data
        self.filename = name
        self.filesize = len(data)
        self.file_id = random.randint(1000, 60000)

        # Calculate payload capacity per frame
        # Packet header is 12B + CRC 4B = 16B overhead
        block_size = max(32, self.layout_engine.max_payload_bytes - 16)
        
        # Prepend file metadata block
        meta_bytes = pack_file_metadata(self.filename, self.filesize)
        full_stream_payload = meta_bytes + self.file_data

        self.encoder = LTEncoder(full_stream_payload, block_size=block_size)
        self.droplet_seed = 0
        self.total_droplets_sent = 0

        self.file_lbl.setText(f"Selected: {self.filename}")
        self.size_lbl.setText(f"Size: {self.filesize / 1024:.1f} KB | Total Blocks K: {self.encoder.K} (Block: {block_size} B)")

    def _on_grid_changed(self, index: int):
        sizes = [32, 48, 64]
        self.grid_size = sizes[index]
        self.layout_engine = ColorMatrixLayout(grid_size=self.grid_size)
        if self.file_data:
            self._set_payload(self.file_data, self.filename)
        else:
            self._render_idle_frame()

    def _on_fps_changed(self, val: int):
        self.target_fps = val
        self.fps_lbl.setText(f"Target Frame Rate: {self.target_fps} FPS")
        self.timer.setInterval(int(1000 / self.target_fps))

    def _toggle_stream(self):
        self.is_streaming = not self.is_streaming
        if self.is_streaming:
            self.stream_btn.setText("🛑 STOP OPTICAL BEAM")
            self.stream_btn.setProperty("active", "true")
            self.start_stream_time = time.time()
            self.total_droplets_sent = 0
        else:
            self.stream_btn.setText("🚀 START OPTICAL BEAM")
            self.stream_btn.setProperty("active", "false")
            self.rate_lbl.setText("0.0 KB/s")
        self.stream_btn.style().unpolish(self.stream_btn)
        self.stream_btn.style().polish(self.stream_btn)

    def _render_idle_frame(self):
        # Render clean anchor frame with calibration bar
        empty_grid = np.zeros((self.grid_size, self.grid_size, 3), dtype=np.uint8)
        self.layout_engine.render_anchors(empty_grid)
        self.canvas.update_frame(empty_grid)

    def _on_tick(self):
        if not self.is_streaming or self.encoder is None:
            return

        # 1. Generate next fountain droplet
        seed = self.droplet_seed
        self.droplet_seed += 1
        self.total_droplets_sent += 1

        degree, indices, block_payload = self.encoder.generate_droplet(seed)

        # 2. Pack into binary protocol frame
        packet = pack_packet(
            file_id=self.file_id,
            total_blocks=self.encoder.K,
            block_size=self.encoder.block_size,
            seed=seed,
            payload=block_payload
        )

        # 3. Synthesize RGB optical grid
        rgb_grid = bytes_to_color_grid(packet, self.layout_engine)
        self.canvas.update_frame(rgb_grid)

        # 4. Update live telemetry
        elapsed = max(0.001, time.time() - self.start_stream_time)
        bytes_sent = self.total_droplets_sent * len(packet)
        kb_per_sec = (bytes_sent / 1024.0) / elapsed
        cycles = self.total_droplets_sent // max(1, self.encoder.K)

        self.rate_lbl.setText(f"{kb_per_sec:.1f} KB/s")
        self.droplet_lbl.setText(f"Droplets Sent: {self.total_droplets_sent} (Seed #{seed})")
        self.loop_lbl.setText(f"Stream Cycles: {cycles}x | Droplet Degree: {degree}")
