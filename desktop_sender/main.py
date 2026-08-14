"""
ChromaBeam Desktop Sender Launcher
Supports CLI arguments, interactive execution, and --auto-screenshot offscreen render capture.
"""

import sys
import os
import argparse
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from desktop_sender.sender_gui import SenderWindow


def main():
    parser = argparse.ArgumentParser(description="ChromaBeam Desktop Optical Sender")
    parser.add_argument("--auto-screenshot", type=str, default=None, help="Save window screenshot to path and exit")
    parser.add_argument("--stream", action="store_true", help="Auto-start streaming immediately")
    parser.add_argument("--fps", type=int, default=45, help="Target frame rate (15-60)")
    args = parser.parse_args()

    # Offscreen / platform support
    if args.auto_screenshot and "QT_QPA_PLATFORM" not in os.environ and "DISPLAY" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    app = QApplication(sys.argv)
    window = SenderWindow()
    window.show()

    if args.stream:
        window._toggle_stream()

    if args.auto_screenshot:
        # Step the animation a couple frames to show active matrix
        window._toggle_stream()
        for _ in range(5):
            window._on_tick()
            app.processEvents()

        # Grab window directly from internal render buffer
        pixmap = window.grab()
        out_dir = os.path.dirname(os.path.abspath(args.auto_screenshot))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        success = pixmap.save(args.auto_screenshot, "PNG")
        print(f"[ChromaBeam] Screenshot saved to: {args.auto_screenshot} (Success: {success})")
        sys.exit(0)

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
