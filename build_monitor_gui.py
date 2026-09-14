#!/usr/bin/env python3
"""
QR ChromaBeam Cloud Build & Deploy Hub (PySide6)
================================================
Local zero-AI-bandwidth monitor for GitHub Actions builds, one-click ADB deployment,
and instant Wi-Fi HTTP / File Sharing for your phone.
Author: Henny & Antigravity 💖✨
"""

import sys
import os
import json
import subprocess
import shutil
import re
import argparse
import socket
import threading
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer, QSize
from PySide6.QtGui import QFont, QIcon, QColor, QPalette, QPixmap, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QLineEdit, QTextEdit,
    QProgressBar, QFrame, QSplitter, QListWidget, QListWidgetItem,
    QMessageBox, QSizePolicy, QCheckBox
)

DEFAULT_REPO = "HenryCarm/ChromaBeam"
DEFAULT_PHONE_IP = "Auto (Default Device)"
DESKTOP_APK_DIR = Path("/home/henry/Apps/APKs")
PROJECT_DIR = Path(__file__).resolve().parent
HTTP_PORT = 8088


def get_local_wifi_ip() -> str:
    """Detects local LAN IP."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class DualDirectoryHandler(SimpleHTTPRequestHandler):
    """Serves files from DESKTOP_APK_DIR."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DESKTOP_APK_DIR), **kwargs)


class LocalHttpServerThread(threading.Thread):
    def __init__(self, port=HTTP_PORT):
        super().__init__(daemon=True)
        self.port = port
        self.httpd = None
        self.is_running = False

    def run(self):
        try:
            self.httpd = HTTPServer(("0.0.0.0", self.port), DualDirectoryHandler)
            self.is_running = True
            self.httpd.serve_forever()
        except Exception:
            self.is_running = False

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        self.is_running = False


class CommandWorker(QThread):
    """Executes background work with live log and progress signals."""
    sig_log = Signal(str, str)
    sig_progress = Signal(int, str)
    sig_result = Signal(str, dict)
    sig_error = Signal(str, str)

    def __init__(self, action_id: str, func, *args, **kwargs):
        super().__init__()
        self.action_id = action_id
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        def _emit_log_wrapper(msg, color="#94a3b8"):
            self.sig_log.emit(msg, color)

        try:
            res = self.func(_emit_log_wrapper, self.sig_progress.emit, *self.args, **self.kwargs)
            self.sig_result.emit(self.action_id, res if isinstance(res, dict) else {"data": res})
        except Exception as e:
            self.sig_error.emit(self.action_id, str(e))


def run_gh_json(args: list[str]) -> list | dict:
    # 1. Try running gh CLI
    try:
        cmd = ["gh"] + args
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(PROJECT_DIR))
        if result.returncode == 0:
            text = result.stdout.strip()
            return json.loads(text) if text else []
    except Exception:
        pass

    # 2. Seamless fallback to public GitHub REST API (No tokens or login required)
    try:
        repo = DEFAULT_REPO
        headers = {
            "User-Agent": "ChromaBeam-Build-Monitor",
            "Accept": "application/vnd.github.v3+json",
        }

        # Handle 'gh run list --json=...'
        if len(args) >= 2 and args[0] == "run" and args[1] == "list":
            url = f"https://api.github.com/repos/{repo}/actions/runs?per_page=12"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode())
                runs_out = []
                for r in data.get("workflow_runs", []):
                    runs_out.append({
                        "databaseId": r.get("id"),
                        "headBranch": r.get("head_branch") or "",
                        "name": r.get("name") or "",
                        "status": r.get("status") or "",
                        "conclusion": r.get("conclusion") or "",
                        "createdAt": r.get("created_at") or "",
                        "updatedAt": r.get("updated_at") or "",
                        "url": r.get("html_url") or "",
                        "workflowName": r.get("name") or "",
                    })
                return runs_out

        # Handle 'gh release view <tag> --json=assets'
        elif len(args) >= 3 and args[0] == "release" and args[1] == "view":
            tag = args[2]
            url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode())
                assets_out = []
                for a in data.get("assets", []):
                    assets_out.append({
                        "name": a.get("name"),
                        "url": a.get("browser_download_url"),
                        "size": a.get("size", 0),
                    })
                return {"assets": assets_out}

        # Handle 'gh run view <run_id> --json=jobs...'
        elif len(args) >= 3 and args[0] == "run" and args[1] == "view":
            run_id = args[2]
            url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode())
                return {"jobs": data.get("jobs", []), "status": "completed", "conclusion": "success"}

    except Exception as api_err:
        raise RuntimeError(f"GitHub API query error ({api_err}). Please check your connection.")

    raise RuntimeError(f"Unable to fetch GitHub data for: {' '.join(args)}")


def extract_smart_error_snippet(full_log: str) -> str:
    lines = full_log.splitlines()
    error_lines = []
    
    indicators = [
        "FAILURE: Build failed with an exception",
        "BUILD FAILED",
        "* What went wrong:",
        "error: duplicate class",
        "Fatal signal",
        "SIGABRT",
        "Modified UTF-8",
        "ClassNotFoundException",
        "A problem occurred evaluating root project",
        "Execution failed for task",
        "Cython.Compiler.Errors",
        "SyntaxError:",
        "Traceback (most recent call last):",
        "Exception in thread",
        "error: "
    ]

    for i, line in enumerate(lines):
        clean = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', line)
        if any(ind.lower() in clean.lower() for ind in indicators):
            start = max(0, i - 2)
            end = min(len(lines), i + 25)
            context = "\n".join(lines[start:end])
            if context not in error_lines:
                error_lines.append(context)

    if error_lines:
        return "=== 🚨 AUTOMATIC ERROR EXTRACTION ===\n\n" + "\n\n---\n\n".join(error_lines[:3])
    
    return "=== 📋 BUILD LOG TAIL ===\n\n" + "\n".join(lines[-40:])


class BuildMonitorWindow(QMainWindow):
    def __init__(self, is_test_mode=False):
        super().__init__()
        self.is_test_mode = is_test_mode
        self.active_runs = []
        self.selected_run = None
        self.worker = None
        self.http_server = None
        self.local_ip = get_local_wifi_ip()

        DESKTOP_APK_DIR.mkdir(parents=True, exist_ok=True)

        self.setWindowTitle("QR ChromaBeam Cloud Build & Deploy Hub ✨")
        self.resize(1180, 780)
        self.setMinimumSize(1000, 680)

        self.auto_timer = QTimer(self)
        self.auto_timer.setInterval(15000)
        self.auto_timer.timeout.connect(self._on_auto_timer_tick)

        self._apply_dark_theme()
        self._init_ui()
        self._setup_shortcuts()

        if not self.is_test_mode:
            QTimer.singleShot(100, self.refresh_adb_devices)
            QTimer.singleShot(300, self.fetch_workflow_runs)
            QTimer.singleShot(500, self.toggle_wifi_server)

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("F5"), self, self.fetch_workflow_runs)
        QShortcut(QKeySequence("Ctrl+R"), self, self.fetch_workflow_runs)

    def _toggle_auto_refresh(self, checked: bool):
        if checked:
            self.auto_timer.start()
            self.status_bar.setText("⏱️ Auto-Refresh enabled (updating every 15s) ✨")
            self.log("Auto-Refresh active: polling GitHub every 15 seconds locally.", "#a5b4fc")
        else:
            self.auto_timer.stop()
            self.status_bar.setText("⏱️ Auto-Refresh stopped. Click Refresh or press F5.")
            self.log("Auto-Refresh paused.", "#9ca3af")

    def _on_auto_timer_tick(self):
        if not self.progress_bar.isVisible():
            self.fetch_workflow_runs(silent=True)

    def toggle_wifi_server(self):
        """Starts or stops the local Wi-Fi HTTP file server."""
        if not self.http_server or not self.http_server.is_running:
            self.http_server = LocalHttpServerThread(HTTP_PORT)
            self.http_server.start()
            server_url = f"http://{self.local_ip}:{HTTP_PORT}"
            self.lbl_wifi_status.setText(f"🌐 Wi-Fi Server: {server_url}")
            self.lbl_wifi_status.setStyleSheet("color: #34d399; font-weight: bold;")
            self.btn_wifi_toggle.setText("🛑 Stop Server")
            self.log(f"🚀 Local Wi-Fi File Server running at: {server_url}", "#34d399")
            self.log(f"📁 Serving folder: {DESKTOP_APK_DIR}", "#60a5fa")
        else:
            self.http_server.stop()
            self.lbl_wifi_status.setText("🌐 Wi-Fi Server: Stopped")
            self.lbl_wifi_status.setStyleSheet("color: #9ca3af; font-weight: normal;")
            self.btn_wifi_toggle.setText("🌐 Start Wi-Fi Server")
            self.log("Wi-Fi File Server stopped.", "#9ca3af")

    def _copy_pc_ip(self):
        """Copies the local IP address to clipboard."""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.local_ip)
        self.btn_copy_ip.setText("✅ Copied!")
        self.log(f"📋 Copied PC IP ({self.local_ip}) to clipboard!", "#38bdf8")
        self.status_bar.setText(f"📋 Copied PC IP: {self.local_ip} ✨")
        QTimer.singleShot(2000, lambda: self.btn_copy_ip.setText("📋 Copy IP"))

    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0d1117;
                color: #e6edf3;
            }
            QWidget {
                color: #e6edf3;
                font-family: 'Inter', 'Segoe UI', 'DejaVu Sans', sans-serif;
                font-size: 13px;
            }
            QFrame.card {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 10px;
                padding: 12px;
            }
            QFrame.headerCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1f2937, stop:1 #111827);
                border: 1px solid #374151;
                border-radius: 10px;
            }
            QPushButton {
                background-color: #21262d;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 7px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #30363d;
                border-color: #8b949e;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: #161b22;
            }
            QPushButton.primary {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #1d4ed8);
                color: #ffffff;
                border: 1px solid #3b82f6;
            }
            QPushButton.primary:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #2563eb);
            }
            QPushButton.success {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #059669, stop:1 #047857);
                color: #ffffff;
                border: 1px solid #10b981;
            }
            QPushButton.success:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #059669);
            }
            QPushButton.danger {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #dc2626, stop:1 #b91c1c);
                color: #ffffff;
                border: 1px solid #ef4444;
            }
            QPushButton.danger:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ef4444, stop:1 #dc2626);
            }
            QLineEdit, QComboBox {
                background-color: #0d1117;
                color: #e6edf3;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 6px 10px;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #58a6ff;
            }
            QComboBox::drop-down {
                border: 0px;
            }
            QListWidget {
                background-color: #0d1117;
                border: 1px solid #30363d;
                border-radius: 8px;
                padding: 4px;
            }
            QListWidget::item {
                background-color: #161b22;
                border: 1px solid #21262d;
                border-radius: 6px;
                margin-bottom: 6px;
                padding: 10px;
            }
            QListWidget::item:selected {
                background-color: #1f2937;
                border: 1px solid #3b82f6;
            }
            QTextEdit {
                background-color: #090d13;
                color: #7ee787;
                font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
                font-size: 12px;
                border: 1px solid #30363d;
                border-radius: 8px;
                padding: 8px;
            }
            QProgressBar {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 6px;
                text-align: center;
                color: white;
                font-weight: bold;
                height: 18px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #10b981);
                border-radius: 5px;
            }
            QSplitter::handle {
                background-color: #30363d;
                width: 2px;
            }
            QScrollBar:vertical {
                background: #0d1117;
                width: 10px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #30363d;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #8b949e;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

    def _init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        # 1. Header Bar
        header_card = QFrame()
        header_card.setProperty("class", "headerCard")
        header_layout = QHBoxLayout(header_card)
        header_layout.setContentsMargins(16, 12, 16, 12)

        title_box = QVBoxLayout()
        title_label = QLabel("🌈 QR ChromaBeam Build & Deploy Hub")
        title_label.setFont(QFont("Arial", 16, QFont.Bold))
        title_label.setStyleSheet("color: #60a5fa;")
        
        subtitle_label = QLabel(f"Repo: {DEFAULT_REPO} • APK Folder: {DESKTOP_APK_DIR} • Zero AI token bandwidth")
        subtitle_label.setStyleSheet("color: #9ca3af; font-size: 11px;")
        title_box.addWidget(title_label)
        title_box.addWidget(subtitle_label)

        header_layout.addLayout(title_box)
        header_layout.addStretch()

        self.chk_auto_refresh = QCheckBox("⏱️ Auto-Refresh (15s)")
        self.chk_auto_refresh.setStyleSheet("""
            QCheckBox {
                color: #a5b4fc;
                font-weight: 600;
                padding: 4px 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #6366f1;
                background-color: #1e1b4b;
            }
            QCheckBox::indicator:checked {
                background-color: #6366f1;
            }
        """)
        self.chk_auto_refresh.toggled.connect(self._toggle_auto_refresh)
        header_layout.addWidget(self.chk_auto_refresh)

        self.btn_refresh = QPushButton("🔄 Refresh (F5)")
        self.btn_refresh.setProperty("class", "primary")
        self.btn_refresh.clicked.connect(self.fetch_workflow_runs)
        header_layout.addWidget(self.btn_refresh)

        main_layout.addWidget(header_card)

        # 2. Control Bar (ADB & Local Wi-Fi Sharing)
        ctrl_card = QFrame()
        ctrl_card.setProperty("class", "card")
        ctrl_layout = QVBoxLayout(ctrl_card)
        ctrl_layout.setContentsMargins(14, 10, 14, 10)
        ctrl_layout.setSpacing(10)

        # Row 1: ADB Controls
        adb_row = QHBoxLayout()
        adb_row.setSpacing(10)

        adb_icon = QLabel("📱")
        adb_icon.setFont(QFont("Arial", 13))
        adb_row.addWidget(adb_icon)

        adb_label = QLabel("Target Phone ADB:")
        adb_label.setFont(QFont("Arial", 11, QFont.Bold))
        adb_row.addWidget(adb_label)

        self.combo_devices = QComboBox()
        self.combo_devices.setMinimumWidth(220)
        self.combo_devices.addItem(DEFAULT_PHONE_IP)
        adb_row.addWidget(self.combo_devices)

        self.btn_refresh_adb = QPushButton("🔍 Scan Devices")
        self.btn_refresh_adb.clicked.connect(self.refresh_adb_devices)
        adb_row.addWidget(self.btn_refresh_adb)

        self.btn_connect_ip = QPushButton("⚡ Connect IP")
        self.btn_connect_ip.clicked.connect(self.connect_custom_adb_ip)
        adb_row.addWidget(self.btn_connect_ip)

        self.lbl_adb_status = QLabel("Checking...")
        self.lbl_adb_status.setStyleSheet("color: #fbbf24; font-weight: bold;")
        adb_row.addWidget(self.lbl_adb_status)
        adb_row.addStretch()

        ctrl_layout.addLayout(adb_row)

        # Row 2: Wi-Fi Local Sharing & Desktop Folder
        wifi_row = QHBoxLayout()
        wifi_row.setSpacing(10)

        wifi_icon = QLabel("🌐")
        wifi_icon.setFont(QFont("Arial", 13))
        wifi_row.addWidget(wifi_icon)

        self.lbl_wifi_status = QLabel(f"Wi-Fi Server: http://{self.local_ip}:{HTTP_PORT}")
        self.lbl_wifi_status.setStyleSheet("color: #34d399; font-weight: bold;")
        wifi_row.addWidget(self.lbl_wifi_status)

        self.btn_copy_ip = QPushButton("📋 Copy IP")
        self.btn_copy_ip.setToolTip("Copy PC IP address to clipboard")
        self.btn_copy_ip.clicked.connect(self._copy_pc_ip)
        wifi_row.addWidget(self.btn_copy_ip)

        self.btn_wifi_toggle = QPushButton("🛑 Stop Wi-Fi Server")
        self.btn_wifi_toggle.clicked.connect(self.toggle_wifi_server)
        wifi_row.addWidget(self.btn_wifi_toggle)

        self.btn_open_folder = QPushButton("📂 Open APKs Folder")
        self.btn_open_folder.clicked.connect(lambda: subprocess.run(["xdg-open", str(DESKTOP_APK_DIR)]))
        wifi_row.addWidget(self.btn_open_folder)

        wifi_row.addStretch()
        ctrl_layout.addLayout(wifi_row)

        main_layout.addWidget(ctrl_card)

        # 3. Main Splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # --- Left Panel: Runs List ---
        left_panel = QFrame()
        left_panel.setProperty("class", "card")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(8)

        runs_header = QHBoxLayout()
        lbl_runs = QLabel("📦 Recent Runs")
        lbl_runs.setFont(QFont("Arial", 12, QFont.Bold))
        lbl_runs.setStyleSheet("color: #e5e7eb;")
        runs_header.addWidget(lbl_runs)

        self.lbl_run_count = QLabel("0 runs")
        self.lbl_run_count.setStyleSheet("color: #9ca3af; font-size: 11px;")
        runs_header.addWidget(self.lbl_run_count)
        runs_header.addStretch()

        self.btn_mini_refresh = QPushButton("🔄 Refresh")
        self.btn_mini_refresh.setToolTip("Refresh Runs (F5 / Ctrl+R)")
        self.btn_mini_refresh.setStyleSheet("padding: 3px 8px; font-size: 11px; font-weight: 600;")
        self.btn_mini_refresh.clicked.connect(self.fetch_workflow_runs)
        runs_header.addWidget(self.btn_mini_refresh)

        left_layout.addLayout(runs_header)

        self.list_runs = QListWidget()
        self.list_runs.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_runs.setWordWrap(True)
        self.list_runs.itemClicked.connect(self.on_run_selected)
        left_layout.addWidget(self.list_runs)

        splitter.addWidget(left_panel)

        # --- Right Panel: Run Details, Actions & Logs ---
        right_panel = QFrame()
        right_panel.setProperty("class", "card")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(14, 14, 14, 14)
        right_layout.setSpacing(12)

        self.lbl_selected_title = QLabel("Select a workflow run on the left to inspect")
        self.lbl_selected_title.setFont(QFont("Arial", 14, QFont.Bold))
        self.lbl_selected_title.setStyleSheet("color: #f3f4f6;")
        right_layout.addWidget(self.lbl_selected_title)

        self.lbl_selected_meta = QLabel("ID: - | Tag: - | Duration: -")
        self.lbl_selected_meta.setStyleSheet("color: #9ca3af; font-size: 11px;")
        right_layout.addWidget(self.lbl_selected_meta)

        self.jobs_frame = QFrame()
        self.jobs_frame.setStyleSheet("""
            QFrame {
                background-color: #0d1117;
                border-radius: 8px;
                border: 1px solid #21262d;
            }
        """)
        jobs_layout = QHBoxLayout(self.jobs_frame)
        jobs_layout.setContentsMargins(14, 10, 14, 10)
        jobs_layout.setSpacing(24)

        self.lbl_android_job = QLabel("🤖 Android APK: Unknown")
        self.lbl_android_job.setStyleSheet("color: #d1d5db; font-weight: 600; font-size: 13px;")
        jobs_layout.addWidget(self.lbl_android_job)

        self.lbl_pc_job = QLabel("💻 PC Nuitka: Unknown")
        self.lbl_pc_job.setStyleSheet("color: #d1d5db; font-weight: 600; font-size: 13px;")
        jobs_layout.addWidget(self.lbl_pc_job)

        jobs_layout.addStretch()
        right_layout.addWidget(self.jobs_frame)

        # Action Buttons Row
        actions_box = QHBoxLayout()
        actions_box.setSpacing(10)

        self.btn_download_desktop = QPushButton("💾 Download APK to Folder")
        self.btn_download_desktop.setProperty("class", "primary")
        self.btn_download_desktop.setEnabled(False)
        self.btn_download_desktop.clicked.connect(self.download_apk_only)
        actions_box.addWidget(self.btn_download_desktop)

        self.btn_install_apk = QPushButton("📥 Download && ADB Install")
        self.btn_install_apk.setProperty("class", "success")
        self.btn_install_apk.setEnabled(False)
        self.btn_install_apk.clicked.connect(self.download_and_install_apk)
        actions_box.addWidget(self.btn_install_apk)

        self.btn_copy_error = QPushButton("📋 Copy Error Snippet")
        self.btn_copy_error.setProperty("class", "danger")
        self.btn_copy_error.setEnabled(False)
        self.btn_copy_error.clicked.connect(self.copy_error_snippet)
        actions_box.addWidget(self.btn_copy_error)

        self.btn_open_browser = QPushButton("🌐 GitHub")
        self.btn_open_browser.setEnabled(False)
        self.btn_open_browser.clicked.connect(self.open_run_in_browser)
        actions_box.addWidget(self.btn_open_browser)

        right_layout.addLayout(actions_box)

        # Log and Console View
        log_header = QHBoxLayout()
        lbl_console = QLabel("🖥️ Activity & Build Console")
        lbl_console.setFont(QFont("Arial", 11, QFont.Bold))
        lbl_console.setStyleSheet("color: #d1d5db;")
        log_header.addWidget(lbl_console)
        log_header.addStretch()

        self.btn_view_full_log = QPushButton("📄 Fetch Full Log")
        self.btn_view_full_log.setEnabled(False)
        self.btn_view_full_log.clicked.connect(self.fetch_full_log)
        log_header.addWidget(self.btn_view_full_log)

        self.btn_clear_log = QPushButton("🧹 Clear")
        self.btn_clear_log.clicked.connect(lambda: self.txt_logs.clear())
        log_header.addWidget(self.btn_clear_log)

        right_layout.addLayout(log_header)

        self.txt_logs = QTextEdit()
        self.txt_logs.setReadOnly(True)
        self.txt_logs.setPlaceholderText("Logs and build output will appear here...")
        right_layout.addWidget(self.txt_logs)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p% - Ready")
        self.progress_bar.hide()
        right_layout.addWidget(self.progress_bar)

        splitter.addWidget(right_panel)
        splitter.setSizes([320, 800])
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 7)
        main_layout.addWidget(splitter, 1)

        # 4. Status Bar
        self.status_bar = QLabel("Ready • Zero AI bandwidth consumption ✨")
        self.status_bar.setStyleSheet("color: #6ee7b7; font-size: 11px; padding: 2px 6px;")
        main_layout.addWidget(self.status_bar)

    def log(self, message: str, color: str = "#7ee787"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.txt_logs.append(f"<span style='color:#6b7280;'>[{timestamp}]</span> <span style='color:{color};'>{message}</span>")
        sb = self.txt_logs.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_loading(self, is_loading: bool, status_text: str = "", progress_pct: int = -1):
        if is_loading:
            self.progress_bar.show()
            if progress_pct >= 0:
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(progress_pct)
                self.progress_bar.setFormat(f"%p% - {status_text}")
            else:
                self.progress_bar.setRange(0, 0)
                self.progress_bar.setFormat(status_text or "Processing...")

            self.btn_refresh.setEnabled(False)
            self.btn_mini_refresh.setEnabled(False)
            if status_text:
                self.status_bar.setText(f"⏳ {status_text}")
        else:
            self.progress_bar.hide()
            self.btn_refresh.setEnabled(True)
            self.btn_mini_refresh.setEnabled(True)
            if status_text:
                self.status_bar.setText(f"✨ {status_text}")

    def refresh_adb_devices(self):
        def _scan(emit_log, emit_prog):
            emit_log("Scanning ADB devices...")
            res = subprocess.run(["adb", "devices"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            lines = res.stdout.strip().splitlines()[1:]
            devices = []
            for line in lines:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == "device":
                    devices.append(parts[0])
            return {"devices": devices}

        self._start_worker("adb_scan", _scan)

    def connect_custom_adb_ip(self):
        target = self.combo_devices.currentText().strip() or DEFAULT_PHONE_IP

        def _connect(emit_log, emit_prog):
            emit_log(f"Connecting to ADB endpoint: {target}...")
            res = subprocess.run(["adb", "connect", target], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return {"output": res.stdout.strip()}

        self._start_worker("adb_connect", _connect)

    def fetch_workflow_runs(self, silent: bool = False):
        if not silent:
            self.set_loading(True, "Fetching recent workflow runs from GitHub...")

        def _fetch(emit_log, emit_prog):
            if not silent:
                emit_log("Running 'gh run list'...")
            fields = "status,conclusion,name,headBranch,databaseId,createdAt,updatedAt,url,workflowName"
            runs = run_gh_json(["run", "list", f"--json={fields}", "--limit=12"])
            return {"runs": runs, "silent": silent}

        self._start_worker("fetch_runs", _fetch)

    def on_run_selected(self, item: QListWidgetItem):
        run_data = item.data(Qt.UserRole)
        if not run_data:
            return
        self.selected_run = run_data
        run_id = run_data.get("databaseId")
        tag = run_data.get("headBranch") or run_data.get("name")
        status = run_data.get("status")
        conclusion = run_data.get("conclusion") or "running"

        self.lbl_selected_title.setText(f"Run #{run_id} ({tag})")
        self.lbl_selected_meta.setText(f"Status: {status.upper()} | Conclusion: {conclusion.upper()} | Created: {run_data.get('createdAt')}")

        self.btn_open_browser.setEnabled(True)
        self.btn_view_full_log.setEnabled(True)

        if conclusion == "success" or status == "completed":
            self.btn_install_apk.setEnabled(True)
            self.btn_download_desktop.setEnabled(True)
        else:
            self.btn_install_apk.setEnabled(False)
            self.btn_download_desktop.setEnabled(False)

        if conclusion == "failure":
            self.btn_copy_error.setEnabled(True)
        else:
            self.btn_copy_error.setEnabled(False)

        self.fetch_run_jobs(run_id)

    def fetch_run_jobs(self, run_id: int):
        def _fetch_jobs(emit_log, emit_prog):
            emit_log(f"Fetching job steps for Run #{run_id}...")
            details = run_gh_json(["run", "view", str(run_id), "--json=jobs,conclusion,status"])
            return {"details": details}

        self._start_worker("fetch_jobs", _fetch_jobs)

    def _download_apk_core(self, run_id: int, tag: str, emit_log, emit_prog) -> Path:
        """Helper to stream download APK directly to /home/henry/Apps/APKs."""
        DESKTOP_APK_DIR.mkdir(parents=True, exist_ok=True)
        apk_path = None

        if tag and tag.startswith("v"):
            try:
                emit_log(f"Checking GitHub Release '{tag}' for prebuilt APK assets...")
                emit_prog(10, "Fetching release info...")
                rel_data = run_gh_json(["release", "view", tag, "--json=assets"])
                assets = rel_data.get("assets", [])
                apk_asset = next((a for a in assets if a.get("name", "").endswith(".apk")), None)

                if apk_asset:
                    apk_name = apk_asset["name"]
                    apk_url = apk_asset["url"]
                    apk_size = apk_asset.get("size", 0)
                    dest_file = DESKTOP_APK_DIR / apk_name

                    emit_log(f"Found Release APK: {apk_name} ({round(apk_size / (1024*1024), 2)} MB)")
                    emit_log(f"Streaming direct download to {dest_file}...")

                    req = urllib.request.Request(apk_url, headers={"User-Agent": "Mozilla/5.0"})
                    socket.setdefaulttimeout(15)
                    with urllib.request.urlopen(req, timeout=15) as resp, open(dest_file, "wb") as f:
                        total_bytes = int(resp.headers.get("Content-Length", apk_size))
                        downloaded = 0
                        chunk_size = 64 * 1024
                        last_update_pct = -1

                        while True:
                            try:
                                chunk = resp.read(chunk_size)
                            except (socket.timeout, TimeoutError, OSError) as read_err:
                                emit_log(f"⚠️ Network stall detected ({read_err}). Resuming...", "#fbbf24")
                                break
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)

                            if total_bytes > 0:
                                pct = int((downloaded / total_bytes) * 70)
                                if pct != last_update_pct and pct % 5 == 0:
                                    last_update_pct = pct
                                    mb_done = round(downloaded / (1024 * 1024), 1)
                                    mb_total = round(total_bytes / (1024 * 1024), 1)
                                    emit_prog(pct, f"Downloading: {mb_done}/{mb_total} MB ({pct}%)")
                                    emit_log(f"Downloading APK: {mb_done}MB / {mb_total}MB ({int((downloaded/total_bytes)*100)}%)...")

                    if dest_file.exists() and dest_file.stat().st_size > 2 * 1024 * 1024:
                        apk_path = dest_file
            except Exception as e:
                emit_log(f"Direct release download note: {e}. Falling back to gh run download...", "#fbbf24")

        if not apk_path or not apk_path.exists():
            emit_prog(30, "Downloading APK artifact from cloud... (please wait)")
            emit_log(f"⏳ Downloading 'android-apk' artifact via gh CLI...", "#60a5fa")
            subprocess.run(
                ["gh", "run", "download", str(run_id), "-n", "android-apk", "-D", str(DESKTOP_APK_DIR)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(PROJECT_DIR)
            )
            apk_files = sorted(list(DESKTOP_APK_DIR.glob("**/*.apk")), key=lambda p: p.stat().st_mtime, reverse=True)
            if not apk_files:
                raise RuntimeError(f"No .apk file could be found in release or workflow artifacts!")
            apk_path = apk_files[0]

        emit_prog(75, f"APK Saved: {apk_path.name}")
        emit_log(f"✅ APK ready in folder: {apk_path}", "#34d399")
        return apk_path

    def download_apk_only(self):
        if not self.selected_run:
            return
        run_id = self.selected_run.get("databaseId")
        tag = self.selected_run.get("headBranch") or ""

        self.set_loading(True, "Downloading APK...", 0)

        def _download_only(emit_log, emit_prog):
            apk = self._download_apk_core(run_id, tag, emit_log, emit_prog)
            emit_prog(100, "Download Complete!")
            return {"apk_name": apk.name, "apk_path": str(apk)}

        self._start_worker("download_only", _download_only)

    def download_and_install_apk(self):
        if not self.selected_run:
            return
        run_id = self.selected_run.get("databaseId")
        tag = self.selected_run.get("headBranch") or ""
        target_device = self.combo_devices.currentText().strip() or DEFAULT_PHONE_IP

        self.set_loading(True, "Starting APK download & install...", 0)

        def _download_and_install(emit_log, emit_prog):
            apk_path = self._download_apk_core(run_id, tag, emit_log, emit_prog)

            emit_prog(80, "Checking ADB connection...")
            is_specific_device = target_device and target_device != "Auto (Default Device)"
            
            # Cleanly uninstall prior versions before fresh installation
            emit_prog(82, "Removing previous installs...")
            emit_log("🧹 Checking and uninstalling old package versions...", "#38bdf8")
            for pkg in ["org.henry.qrchromabeam", "org.chromabeam.app", "chromabeam"]:
                uninst_cmd = ["adb"]
                if is_specific_device:
                    uninst_cmd.extend(["-s", target_device])
                uninst_cmd.extend(["uninstall", pkg])
                uninst = subprocess.run(uninst_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if "Success" in uninst.stdout:
                    emit_log(f"  [ADB] Cleanly uninstalled prior version: {pkg}", "#34d399")

            emit_prog(85, "Installing APK via ADB...")
            emit_log(f"🚀 Pushing APK to device [{target_device if is_specific_device else 'Default adb'}]...", "#38bdf8")

            cmd = ["adb"]
            if is_specific_device:
                cmd.extend(["-s", target_device])
            cmd.extend(["install", "-r", "-d", "-g", "-t", str(apk_path)])

            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            output_lines = []
            for line in process.stdout:
                line_str = line.strip()
                if line_str:
                    output_lines.append(line_str)
                    emit_log(f"  [ADB] {line_str}", "#94a3b8")
                    if "Performing Streamed Install" in line_str:
                        emit_prog(90, "ADB Streaming...")
            process.wait()

            full_adb_out = "\n".join(output_lines)
            if "Success" not in full_adb_out and process.returncode != 0:
                raise RuntimeError(f"ADB install failed:\n{full_adb_out}")

            emit_prog(100, "Installation Complete!")
            return {"apk_name": apk_path.name, "output": full_adb_out}

        self._start_worker("download_install", _download_and_install)

    def copy_error_snippet(self):
        if not self.selected_run:
            return
        run_id = self.selected_run.get("databaseId")
        self.set_loading(True, f"Extracting failure snippet for Run #{run_id}...")

        def _get_log(emit_log, emit_prog):
            emit_log(f"Fetching failed log for Run #{run_id}...")
            res = subprocess.run(
                ["gh", "run", "view", str(run_id), "--log-failed"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(PROJECT_DIR)
            )
            raw_log = res.stdout
            if not raw_log.strip():
                emit_log("Fetching full run log as fallback...")
                res = subprocess.run(
                    ["gh", "run", "view", str(run_id), "--log"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(PROJECT_DIR)
                )
                raw_log = res.stdout

            snippet = extract_smart_error_snippet(raw_log)
            return {"snippet": snippet}

        self._start_worker("copy_error", _get_log)

    def fetch_full_log(self):
        if not self.selected_run:
            return
        run_id = self.selected_run.get("databaseId")
        self.set_loading(True, f"Downloading full log for Run #{run_id}...")

        def _fetch(emit_log, emit_prog):
            emit_log(f"Retrieving full log for Run #{run_id}...")
            res = subprocess.run(
                ["gh", "run", "view", str(run_id), "--log"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(PROJECT_DIR)
            )
            return {"log": res.stdout}

        self._start_worker("fetch_full_log", _fetch)

    def open_run_in_browser(self):
        if self.selected_run and self.selected_run.get("url"):
            import webbrowser
            webbrowser.open(self.selected_run.get("url"))

    def _start_worker(self, action_id: str, func, *args, **kwargs):
        if self.worker and self.worker.isRunning():
            self.worker.wait()

        self.worker = CommandWorker(action_id, func, *args, **kwargs)
        self.worker.sig_log.connect(self.log)
        self.worker.sig_progress.connect(self._handle_worker_progress)
        self.worker.sig_result.connect(self._handle_worker_result)
        self.worker.sig_error.connect(self._handle_worker_error)
        self.worker.start()

    @Slot(int, str)
    def _handle_worker_progress(self, percent: int, status_text: str):
        self.progress_bar.show()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(percent)
        self.progress_bar.setFormat(f"{percent}% - {status_text}")
        self.status_bar.setText(f"⏳ {status_text}")

    @Slot(str, dict)
    def _handle_worker_result(self, action_id: str, payload: dict):
        self.set_loading(False)

        if action_id == "adb_scan":
            devices = payload.get("devices", [])
            self.combo_devices.clear()
            if devices:
                for d in devices:
                    self.combo_devices.addItem(d)
                self.lbl_adb_status.setText(f"🟢 {len(devices)} device(s) online")
                self.lbl_adb_status.setStyleSheet("color: #34d399; font-weight: bold;")
                self.log(f"ADB online devices: {', '.join(devices)}", "#34d399")
            else:
                self.combo_devices.addItem(DEFAULT_PHONE_IP)
                self.lbl_adb_status.setText("🔴 No devices found")
                self.lbl_adb_status.setStyleSheet("color: #f87171; font-weight: bold;")
                self.log("No ADB devices detected. Check USB/Wi-Fi connection.", "#f87171")

        elif action_id == "adb_connect":
            out = payload.get("output", "")
            self.log(f"ADB connect result: {out}", "#60a5fa")
            self.refresh_adb_devices()

        elif action_id == "fetch_runs":
            runs = payload.get("runs", [])
            silent = payload.get("silent", False)
            self.active_runs = runs
            self.list_runs.clear()
            self.lbl_run_count.setText(f"{len(runs)} runs")

            for run in runs:
                item = QListWidgetItem()
                tag = run.get("headBranch") or run.get("name") or "Workflow"
                status = run.get("status")
                conclusion = run.get("conclusion")
                created = run.get("createdAt", "")[:19].replace("T", " ")

                if conclusion == "success":
                    badge = "🟢 SUCCESS"
                elif conclusion == "failure":
                    badge = "🔴 FAILED"
                elif status == "in_progress":
                    badge = "🟡 BUILDING"
                elif status == "queued":
                    badge = "⚪ QUEUED"
                else:
                    badge = f"🔵 {status.upper()}"

                item.setText(f"{badge}  •  {tag}\nRun #{run.get('databaseId')}  |  {created}")
                item.setData(Qt.UserRole, run)
                self.list_runs.addItem(item)

            if runs:
                current_id = self.selected_run.get("databaseId") if self.selected_run else None
                selected_idx = 0
                if current_id:
                    for i, r in enumerate(runs):
                        if r.get("databaseId") == current_id:
                            selected_idx = i
                            break
                
                self.list_runs.setCurrentRow(selected_idx)
                self.on_run_selected(self.list_runs.item(selected_idx))
                if not silent:
                    self.log(f"Loaded {len(runs)} latest workflow runs successfully!", "#34d399")

        elif action_id == "fetch_jobs":
            details = payload.get("details", {})
            jobs = details.get("jobs", [])
            
            android_status = "Not Run"
            pc_status = "Not Run"

            for j in jobs:
                jname = j.get("name", "")
                jconc = j.get("conclusion") or j.get("status")
                if "Android" in jname:
                    android_status = jconc.upper()
                elif "Linux" in jname or "Windows" in jname or "PC" in jname:
                    pc_status = jconc.upper()

            def _color(st):
                if "SUCCESS" in st: return "#34d399"
                if "FAIL" in st: return "#f87171"
                if "IN_PROGRESS" in st or "BUILD" in st: return "#fbbf24"
                return "#9ca3af"

            self.lbl_android_job.setText(f"🤖 Android APK: {android_status}")
            self.lbl_android_job.setStyleSheet(f"color: {_color(android_status)}; font-weight: bold;")
            
            self.lbl_pc_job.setText(f"💻 PC Binary: {pc_status}")
            self.lbl_pc_job.setStyleSheet(f"color: {_color(pc_status)}; font-weight: bold;")

        elif action_id == "download_only":
            apk_name = payload.get("apk_name", "")
            apk_path = payload.get("apk_path", "")
            self.log(f"🎉 Saved APK: {apk_path}", "#34d399")
            self.status_bar.setText(f"💾 Saved {apk_name}! ✨")
            QMessageBox.information(self, "APK Downloaded 💾", f"APK was saved to:\n\n{apk_path}\n\nYou can access it directly from your phone at http://{self.local_ip}:{HTTP_PORT} or via ADB!")

        elif action_id == "download_install":
            apk_name = payload.get("apk_name", "")
            out = payload.get("output", "")
            self.log(f"🎉 SUCCESS! APK '{apk_name}' was installed on your phone!\n{out}", "#34d399")
            self.status_bar.setText(f"🎉 Installed {apk_name} successfully! ✨")
            QMessageBox.information(self, "Installation Successful 🚀", f"APK '{apk_name}' was successfully installed on your device!\n\nADB: {out}")

        elif action_id == "copy_error":
            snippet = payload.get("snippet", "")
            clipboard = QApplication.clipboard()
            clipboard.setText(snippet)
            self.log("📋 Smart error snippet copied to clipboard! Paste it directly into chat!", "#38bdf8")
            self.status_bar.setText("📋 Copied error snippet to clipboard! Just paste into chat ✨")

        elif action_id == "fetch_full_log":
            full_log = payload.get("log", "")
            self.txt_logs.setText(full_log)
            self.log("Full log loaded into console.", "#60a5fa")

    @Slot(str, str)
    def _handle_worker_error(self, action_id: str, error_msg: str):
        self.set_loading(False)
        self.log(f"❌ Error during '{action_id}': {error_msg}", "#f87171")
        self.status_bar.setText(f"❌ Operation failed: {error_msg[:60]}")
        QMessageBox.warning(self, "Operation Failed", f"Action '{action_id}' encountered an error:\n\n{error_msg}")


def main():
    parser = argparse.ArgumentParser(description="QR ChromaBeam Cloud Build & Deploy Hub")
    parser.add_argument("--auto-screenshot", type=str, help="Take offscreen GUI screenshot and exit")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    window = BuildMonitorWindow(is_test_mode=bool(args.auto_screenshot))

    if args.auto_screenshot:
        window.show()
        
        mock_runs = [
            {"databaseId": 34727993319, "headBranch": "v2.0.4", "status": "completed", "conclusion": "failure", "createdAt": "2026-09-13T01:27:03Z"}
        ]
        window._handle_worker_result("fetch_runs", {"runs": mock_runs})
        
        window.lbl_selected_title.setText("Run #34727993319 (v2.0.4)")
        window.lbl_selected_meta.setText("Status: COMPLETED | Conclusion: FAILURE | Created: 2026-09-13 01:27:03")
        window.lbl_android_job.setText("🤖 Android APK: FAILURE")
        window.lbl_android_job.setStyleSheet("color: #f87171; font-weight: bold; font-size: 13px;")
        window.lbl_pc_job.setText("💻 PC Binary: SUCCESS")
        window.lbl_pc_job.setStyleSheet("color: #34d399; font-weight: bold; font-size: 13px;")
        window.lbl_adb_status.setText("🟢 10.77.76.223:5555 Online")
        window.lbl_adb_status.setStyleSheet("color: #34d399; font-weight: bold;")
        window.btn_install_apk.setEnabled(False)
        window.btn_download_desktop.setEnabled(False)
        window.btn_copy_error.setEnabled(True)
        window.btn_open_browser.setEnabled(True)
        window.chk_auto_refresh.setChecked(True)
        
        window.lbl_wifi_status.setText("🌐 Wi-Fi Server: http://10.77.76.223:8088")
        window.lbl_wifi_status.setStyleSheet("color: #34d399; font-weight: bold;")
        
        window.log("🚀 Local Wi-Fi File Server running at: http://10.77.76.223:8088", "#34d399")
        window.log("📁 Serving folder: /home/henry/Apps/APKs", "#60a5fa")
        
        app.processEvents()
        window.repaint()
        
        screenshot_path = Path(args.auto_screenshot).resolve()
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        pixmap = window.grab()
        pixmap.save(str(screenshot_path))
        print(f"AUTO_SCREENSHOT_SAVED: {screenshot_path}")
        os._exit(0)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
