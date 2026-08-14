# ChromaBeam Codebase & Architecture Survey Report

**Author**: Explorer 1 (Replacement)  
**Date**: 2026-08-14  
**Project**: ChromaBeam (SpectrumDrop)  
**Project Root**: `/home/henry/Documents/Projects/Python/QR ChromaBeam`  

---

## 1. Executive Summary

ChromaBeam is a high-speed, air-gapped optical data transmission suite combining **3-bit RGB color multiplexing**, **Luby Transform (LT) Fountain Codes**, **1:1:1:1:1 nested square finder pattern detection**, and **3D projective homography** to achieve optical throughput of **350–550+ KB/s** across screens and camera lenses.

The repository contains a fully dual-stack architecture:
1. **Python Desktop Stack (PyQt6 + OpenCV + NumPy + Pillow + Nuitka)**: Provides a unified desktop application (`desktop_app.py`), standalone sender (`desktop_sender/`), webcam receiver (`desktop_receiver/`), and core mathematical primitives (`core/`).
2. **Web / Mobile Stack (HTML5 + Web Workers + Pure ES6 JS + WebRTC)**: Zero-install web application (`web/`) and 100% self-contained offline portable app (`chromabeam_offline.html`) served via multi-threaded HTTPS (`web/server.py`).

All existing 9 Python unit tests execute and pass 100% in ~1.04s.

---

## 2. Directory Structure & File Map

```
/home/henry/Documents/Projects/Python/QR ChromaBeam/
├── .github/
│   └── workflows/
│       └── build_and_release.yml      # CI/CD for Linux (Nuitka), Windows (Nuitka .exe), and Android (Buildozer)
├── core/
│   ├── __init__.py                     # Package exports
│   ├── color_matrix.py                 # Multi-mode color matrix layout, 1:1:1:1:1 anchors, palette packing/unpacking
│   ├── fountain.py                     # Luby Transform (LT) encoder/decoder, Mulberry32 PRNG, GF(2) Gaussian solver
│   └── protocol.py                     # Binary frame encapsulation (12B header, CRC32, file metadata packing)
├── desktop_app.py                      # Unified PyQt6 desktop suite (Sender, Webcam Receiver, Offline Pairing)
├── desktop_receiver/
│   ├── __init__.py
│   ├── color_classifier.py             # Adaptive RGB decision boundaries & dynamic swatch calibration
│   ├── receiver_gui.py                 # OpenCV interactive camera HUD receiver
│   └── tracker.py                      # Optical matrix contour tracking & homography perspective warper
├── desktop_sender/
│   ├── __init__.py
│   ├── main.py                         # CLI launcher with --auto-screenshot offscreen render support
│   └── sender_gui.py                   # PyQt6 hardware-accelerated sender GUI
├── tests/
│   ├── test_end_to_end.py              # End-to-end matrix encode/decode validation across modes 0, 1, 2
│   ├── test_fountain.py                # Luby Transform systematic & 40% lossy channel recovery tests
│   └── test_protocol.py                # Binary frame packing, unpacking, CRC32 corruption validation
├── web/
│   ├── cert/                           # Self-signed SSL certificate and private key for HTTPS
│   │   ├── cert.pem
│   │   └── key.pem
│   ├── diag.html                       # In-browser JS loopback diagnostic
│   ├── diag_cam.html                   # In-browser camera simulation & alignment diagnostic
│   ├── fountain.js                     # JS Luby Transform, Mulberry32 PRNG, Robust Soliton CDF, GF(2) solver
│   ├── index.html                      # Responsive web application with Sender and Receiver tabs
│   ├── matrix.js                       # JS color matrix layout engine, anchor rendering, palette mapper
│   ├── protocol.js                     # JS binary packet serializer, CRC32 calculator, metadata pack/unpack
│   ├── receiver.js                     # Receiver controller, WebRTC camera loop, diagnostic logger, AR reticles
│   ├── scanner_worker.js               # Dedicated Web Worker for background CV detection & fountain decoding
│   ├── sender.js                       # Sender controller, requestAnimationFrame render loop, Grandma Presets
│   ├── server.py                       # Multi-threaded Python HTTPS server (port 8443)
│   ├── style.css                       # Modern dark-mode UI stylesheet
│   └── vision_engine.js                # 3D projective homography, 360° rotation invariance, anchor clustering
├── build_offline_html.py               # Inlines web assets into single-file offline HTML
├── buildozer.spec                      # Buildozer Android compilation spec with numeric version 2680317
├── chromabeam_offline.html             # Self-contained 79 KB offline web application
├── ORIGINAL_REQUEST.md                 # Authoritative project requirements (R1–R5)
├── README.md                           # Documentation, protocol specifications, quick start guide
└── requirements.txt                    # Python dependencies (PyQt6, opencv-python, numpy, Pillow, nuitka)
```

---

## 3. Core Architecture & Technical Implementation

### 3.1. Binary Protocol Framing (`core/protocol.py` & `web/protocol.js`)
- **Magic Bytes**: `0x4342` ("CB") uint16_be to reject out-of-focus or non-ChromaBeam frames.
- **Binary Header (12 Bytes)**:
  - `Magic`: 2 bytes (`0x4342`)
  - `File ID`: 2 bytes (`uint16_be`)
  - `Total Blocks (K)`: 2 bytes (`uint16_be`)
  - `Block Size (B)`: 2 bytes (`uint16_be`)
  - `Seed / Droplet ID`: 4 bytes (`uint32_be`)
- **Payload**: XOR-combined block data of length `block_size`.
- **Integrity (4 Bytes)**: Standard IEEE 802.3 CRC32 of the payload bytes.
- **Metadata Framing**: Prepend compact file descriptor `[FileSize (4B)] [NameLen (1B)] [Filename] [MimeLen (1B)] [MimeType]`.

### 3.2. Luby Transform (LT) Fountain Codes (`core/fountain.py` & `web/fountain.js`)
- **Deterministic PRNG**: `Mulberry32` 32-bit state generator identically implemented in Python and JavaScript:
  $$\text{state} \leftarrow (\text{state} + \text{0x6D2B79F5}) \pmod{2^{32}}$$
- **Degree Distribution**: Robust Soliton distribution $\mu(d) = \rho(d) + \tau(d)$ parameterized with $c = 0.1, \delta = 0.05$.
- **Systematic Transmission**: For seeds $0 \le s < K$, degree is strictly 1 with index $[s]$ for zero-overhead instant recovery under clean conditions.
- **Dual-Engine Decoder**:
  1. *Fast Ripple Peeling*: Resolves singletons ($d=1$) in $O(K \log K)$ time.
  2. *Incremental $\text{GF}(2)$ Gaussian Elimination*: Inserts multi-degree droplets into a triangular basis matrix using XOR Gaussian reduction, guaranteeing 100% mathematical recovery even when packet loss exceeds 40%.

### 3.3. Multi-Mode Optical Color Matrix Engine (`core/color_matrix.py` & `web/matrix.js`)
- **Mode 0 (1-bit Monochrome B&W)**:
  - Palette: Black (`#000000`), White (`#FFFFFF`).
  - Bit density: 1 bit/cell.
  - Target: Budget "Potato" cameras, high motion blur, extreme contrast, low light.
- **Mode 1 (2-bit 4-Color Balanced)**:
  - Palette: Black, Red (`#FF3232`), Green (`#32FF32`), White.
  - Bit density: 2 bits/cell ($2\times$ standard QR density).
- **Mode 2 (3-bit 8-Color JAB RGB Turbo)**:
  - Palette: Black, Blue, Green, Cyan, Red, Magenta, Yellow, White.
  - Bit density: 3 bits/cell ($3\times$ speed, up to 550+ KB/s @ 60 FPS).
- **Matrix Geometry & Physical Layout**:
  - Four 5x5 corner anchors with 1:1:1:1:1 nested square concentric patterns.
  - Top border calibration cells (K, R, G, B, W swatches).
  - Timing tracks along top and bottom alternating black/white.
  - Available grid sizes: $32 \times 32$, $48 \times 48$, $64 \times 64$.

### 3.4. Computer Vision, Homography & Web Worker Pipeline (`web/vision_engine.js` & `web/scanner_worker.js`)
- **3D Projective Homography**: Solves $3\times3$ projective transform matrix $H$ mapping canonical $[0,1]^2 \to$ detected quad coordinates $(x_i, y_i)$.
- **360° 4-Way Rotation Invariance**: `decodeGridMultiOrientation` evaluates grid orientations ($0^\circ, 90^\circ, 180^\circ, 270^\circ$) against CRC32.
- **Background Worker**: `scanner_worker.js` processes frames asynchronously with zero-copy `ArrayBuffer` transfer, keeping the main camera viewfinder rendering at full 60 FPS.
- **Diagnostic Telemetry**: Reports detection method, worker latency, luma/contrast metrics, droplet count, CRC drops, and Pi-accurate progress ($0.0000\%$).

---

## 4. Dependencies, Environment & Build Infrastructure

### 4.1. Python Environment
- Central Python Venv: `/home/henry/Documents/Projects/Python/venv/bin/python` (Python 3.12).
- Installed packages: `PyQt6 (6.8.0)`, `opencv-python (4.10.0.84)`, `numpy (1.26.4)`, `Pillow (10.4.0)`, `nuitka (2.5.1)`.

### 4.2. Android Packaging & Buildozer Spec
- `buildozer.spec` configures Kivy/Python-for-Android packaging:
  - `android.numeric_version = 2680317` (strictly conforms to learned invariant preventing Gradle 32-bit integer overflow).
  - Target API 33, Min API 24, NDK 25b.
  - Permissions: `CAMERA`, `READ_EXTERNAL_STORAGE`, `WRITE_EXTERNAL_STORAGE`, `MANAGE_EXTERNAL_STORAGE`, `INTERNET`.
- CI/CD: Cloud Build in `.github/workflows/build_and_release.yml` on Ubuntu 22.04 with Cython 0.29.36.

### 4.3. Desktop Executable Distribution (Nuitka)
- Dual build strategy implemented in GitHub Actions:
  - **Standalone**: Fast-startup folder distribution (`--standalone`).
  - **Onefile**: Single portable executable (`--onefile`).

---

## 5. Verification & Test Execution Status

Unit test suite executed via `/home/henry/Documents/Projects/Python/venv/bin/python -m unittest discover -s tests -v`:

| Test Suite | Test Method | Description | Result |
|---|---|---|---|
| `test_fountain.py` | `test_mulberry32_prng_determinism` | Deterministic PRNG seed repeatability | **PASS** (0.001s) |
| `test_fountain.py` | `test_systematic_decoding_instant` | Systematic degree-1 frame decoding in $K$ packets | **PASS** (0.001s) |
| `test_fountain.py` | `test_lossy_fountain_channel_reconstruction` | 40% packet drops + shuffled order recovery (128 KB) | **PASS** (0.975s) |
| `test_protocol.py` | `test_pack_and_unpack_packet_valid` | Packet serialization & field unpacking | **PASS** (0.001s) |
| `test_protocol.py` | `test_unpack_corrupt_crc` | Corruption detection and rejection via CRC32 | **PASS** (0.001s) |
| `test_protocol.py` | `test_pack_unpack_metadata` | File descriptor serialization & decoding | **PASS** (0.001s) |
| `test_end_to_end.py` | `test_mode0_bw_lossless` | 1-bit B&W 32x32 matrix encode/decode loopback | **PASS** (0.015s) |
| `test_end_to_end.py` | `test_mode1_4color_lossless` | 2-bit 4-Color 48x48 matrix encode/decode loopback | **PASS** (0.021s) |
| `test_end_to_end.py` | `test_mode2_8color_lossless` | 3-bit 8-Color 64x64 matrix encode/decode loopback | **PASS** (0.024s) |

**Overall Test Result**: 9 / 9 Passed in 1.039s.

---

## 6. Gap Analysis & Technical Debt vs. R1–R5

| Requirement | Spec Requirement | Current Implementation Status | Gap / Technical Debt / Structural Risk |
|---|---|---|---|
| **R1. 1:1:1:1:1 Finder Pattern & Dense QR Segmentation** | QR/Aztec-grade contour hierarchy & 1:1:1:1:1 ratio scanlines; isolate dense matrix from surrounding desktop UI text & taskbars. | Implemented in JS `vision_engine.js` (`findAnchorClusters`) and Python `desktop_receiver/tracker.py` (external contour poly approximation). | • Python tracker relies on external bounding contour and does not yet implement 1:1:1:1:1 anchor scanline/contour hierarchy detection.<br>• JS `findAnchorClusters` only scans horizontal lines (susceptible to horizontal UI artifacts/stripes). |
| **R2. 360° 3D Projective Homography & 4-Way Rotation** | Projective transformation ($H$) with $0^\circ, 90^\circ, 180^\circ, 270^\circ$ rotation evaluation against CRC32. | Implemented in JS `vision_engine.js` (`ProjectiveTransform`, `decodeGridMultiOrientation`). | • Python `desktop_receiver/receiver_gui.py` and `desktop_app.py` do NOT test 4 rotations ($0^\circ, 90^\circ, 180^\circ, 270^\circ$) against CRC32; assumes upright orientation.<br>• Python quad point ordering can invert under extreme roll angle. |
| **R3. Background Web Worker & Live Diagnostic HUD** | Web Worker offloading binarization/decoding at 60 FPS, live terminal log stream, Pi-accurate progress ($0.0000\%$), lighting contrast metrics. | Implemented in `web/scanner_worker.js`, `web/receiver.js`, `web/index.html`. | • `build_offline_html.py` does not inline `scanner_worker.js` as an inline Blob worker, so running `chromabeam_offline.html` from `file://` causes Worker CORS restriction and falls back to main thread. |
| **R4. Adaptive Multi-Mode Encoding & Grandma Presets** | 3 Presets: Potato (1-bit B&W), Balanced (2-bit 4-Color), Turbo (3-bit 8-Color JAB) with auto-density & calibration swatches. | Implemented in Python (`core/color_matrix.py`, `desktop_app.py`) and JS (`web/matrix.js`, `web/sender.js`, `web/scanner_worker.js`). | • Mode 1 and Mode 2 color decoding in `core/color_matrix.py` defaults to fixed Euclidean distance when no classifier callback is passed; needs dynamic calibration for camera temperature. |
| **R5. PC & Mobile Loopback Validation** | Full optical loopback automation across 32x32, 48x48, 64x64 and all color modes. | Python unit tests cover all 3 modes and lossy channels. Web has `diag.html` and `diag_cam.html`. | • Lacks automated optical synthetic image loopback test in Python test suite that applies synthetic perspective warping, noise, and rotation to verify detector end-to-end. |

---

## 7. Recommendations for Subsequent Implementation Phases

1. **Python OpenCV Receiver Parity (R1 & R2)**:
   - Port 1:1:1:1:1 anchor contour/scanline detector to Python `desktop_receiver/tracker.py`.
   - Add 4-way rotation check ($0^\circ, 90^\circ, 180^\circ, 270^\circ$) in `desktop_receiver/receiver_gui.py` and `desktop_app.py`.
2. **Offline HTML Blob Worker Inlining (R3)**:
   - Update `build_offline_html.py` to bundle `scanner_worker.js` and its dependencies as an inline `Blob([workerCode], {type: 'application/javascript'})` object URL so Web Workers function seamlessly even when opened directly via `file://` in airplane mode.
3. **Comprehensive Optical Synthetic Test Suite (R5)**:
   - Add `tests/test_optical_simulation.py` with parameterized rotations ($0^\circ, 90^\circ, 180^\circ, 270^\circ$), perspective warps, and Gaussian noise to validate loopback robustness across all modes (32x32 B&W, 48x48 4-color, 64x64 8-color).
