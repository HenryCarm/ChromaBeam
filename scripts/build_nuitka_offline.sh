#!/usr/bin/env bash
# ChromaBeam Offline Nuitka Dual Packaging Script
set -e

PROJECT_DIR="/home/henry/Documents/Projects/Python/QR ChromaBeam"
VENV_PYTHON="/home/henry/Documents/Projects/Python/venv/bin/python"

cd "$PROJECT_DIR"
"$VENV_PYTHON" "$PROJECT_DIR/scripts/build_nuitka_offline.py"
