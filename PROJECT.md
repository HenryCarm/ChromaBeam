# Project: ChromaBeam

## Architecture
ChromaBeam is an optical air-gapped file transfer suite utilizing fountain codes (Luby Transform with systematic degree-1 packets and incremental GF(2) Gaussian elimination back-substitution), adaptive multi-mode color matrices (1-bit B&W Potato, 2-bit Balanced 4-Color, 3-bit Turbo 8-Color JAB), 1:1:1:1:1 concentric anchor tracking, 360° 3D projective homography, 4-way rotation CRC32 validation, and multi-threaded Web Worker background processing with real-time diagnostic HUD.

```
┌─────────────────────────────────────────────────────────────┐
│                      SENDER (Tx)                            │
│  [File / Data] ──> [LT Encoder (Mulberry32)]                │
│       ──> [Packet Serialization (>HHHHI + CRC32)]           │
│       ──> [Multi-Mode Color Matrix (1-bit / 2-bit / 3-bit)] │
│       ──> [1:1:1:1:1 Anchors + 5-Point Calibration]         │
│       ──> [Animated Display 15-45 FPS]                      │
└──────────────────────────────┬──────────────────────────────┘
                               │ (Optical Air-Gap)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                     RECEIVER (Rx)                           │
│  [Camera Feed (Webcam / Mobile)] ──> [Frame Extraction]     │
│       ──> [Hierarchical 1:1:1:1:1 Anchor Detection]         │
│       ──> [Direct 4-Point Homography Warp H]                │
│       ──> [4-Way Rotation Invariance (0°, 90°, 180°, 270°)] │
│       ──> [Adaptive 5-Point Color Classification]           │
│       ──> [CRC32 Frame Validation]                          │
│       ──> [LT Decoder / GF(2) Incremental Elimination]      │
│       ──> [Lossless File Reconstruction]                    │
└─────────────────────────────────────────────────────────────┘
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | R1: 1:1:1:1:1 Concentric Anchor Standard | Standardize 4 anchor cores to White (`palette[-1]`) in Python and JS generators for binarization invariance. | M1 | ORIGINAL_REQUEST §R1 |
| 2 | R1: Hierarchical Anchor Detection & UI Segmentation | Implement `cv2.RETR_TREE` concentric anchor hierarchy detector in Python tracker to isolate matrix from desktop UI, taskbars, and reflections. | M2 | ORIGINAL_REQUEST §R1 |
| 3 | R2: Direct Canonical Homography (H) | Map 4 anchor centers directly to canonical coordinates $(2.5/N, 2.5/N)$ to eliminate density extrapolation errors. | M2 | ORIGINAL_REQUEST §R2 |
| 4 | R2: 360° 4-Way Rotation Invariance | Test $0^\circ, 90^\circ, 180^\circ, 270^\circ$ orientations against CRC32 in Python desktop receiver and Web Worker. | M2 | ORIGINAL_REQUEST §R2 |
| 5 | R3: Web Worker Threading & Zero-Copy HUD | Multi-threaded background Web Worker for frame processing and live telemetry HUD with Pi-accurate progress (0.0000%). | M3 | ORIGINAL_REQUEST §R3 |
| 6 | R3: Offline HTML Worker Bundling | Inline `scanner_worker.js` as an in-memory Blob URL in `build_offline_html.py` and implement `processFrameInline` fallback in `web/receiver.js`. | M3 | ORIGINAL_REQUEST §R3 |
| 7 | R4: Adaptive Multi-Mode Encoding & Grandma Presets | Support 1-bit Potato, 2-bit Balanced, 3-bit Turbo modes with 5-point calibration swatches and auto-density sweeping (32, 48, 64). | M1, M3 | ORIGINAL_REQUEST §R4 |
| 8 | R5: Complete Loopback Test Suite | Automated end-to-end optical loopback tests in Python simulating homography, rotations, blur, noise, and lighting variations across all modes/densities. | M4 | ORIGINAL_REQUEST §R5 |
| 9 | R5: Acceptance Verification & Audit | 100% test pass rate, adversarial coverage hardening, and forensic integrity audit. | M5 | ORIGINAL_REQUEST §Acceptance |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Anchor Standard & Core Color Matrix | Standardize anchor cores to White in `core/color_matrix.py` and `web/matrix.js`; verify multi-mode color encoding and calibration swatches. | None | DONE |
| M2 | Python CV Tracker & 4-Way Homography | Implement `cv2.RETR_TREE` concentric anchor detection and 4-way rotation CRC32 validation in `desktop_receiver/tracker.py`, `desktop_receiver/receiver_gui.py`, and `desktop_app.py`. | M1 | DONE |
| M3 | Web Worker Inlining & Offline Bundler | Implement inline Blob Worker in `build_offline_html.py`, `processFrameInline` in `web/receiver.js`, and verify offline HTML runner. | M1 | DONE |
| M4 | Optical Loopback & E2E Test Suite | Implement `tests/test_optical_loopback.py` testing all 3 modes, 3 densities, 4 rotations, and optical perturbations. | M1, M2 | IN_PROGRESS |
| M5 | Final Acceptance Gate & Forensic Audit | Run 100% E2E test suite, adversarial challenge testing, and forensic integrity audit. | M1, M2, M3, M4 | PLANNED |

## Interface Contracts

### `core/color_matrix.py` ↔ `desktop_receiver/tracker.py`
- `ColorMatrixLayout(grid_size=N, color_mode=MODE, anchor_size=5)`:
  - `render_anchors(grid)`: Generates $5\times 5$ concentric anchors at four corners: outer border (black), middle ring (white), inner ring (black), center dot (white).
  - `anchor_centers`: List of 4 canonical floating point centroids $[(2.5/N, 2.5/N), (1-2.5/N, 2.5/N), (1-2.5/N, 1-2.5/N), (2.5/N, 1-2.5/N)]$.

### `desktop_receiver/tracker.py` ↔ `desktop_receiver/receiver_gui.py` / `desktop_app.py`
- `MatrixTracker.find_matrix(frame)`:
  - Returns `(warped_image, quad_points, status)` where `warped_image` is normalized canonical top-down matrix.
- `color_grid_to_bytes(grid, layout)` / `unpack_packet(raw_bytes)`:
  - Evaluates `rotations = [0, 90, 180, 270]` via `np.rot90(grid, k=-rot//90)` until `unpack_packet` returns valid `(header, payload)`.

### `build_offline_html.py` ↔ `web/scanner_worker.js`
- Offline bundler creates single self-contained HTML file where `scanner_worker.js` is embedded as a `<script id="scanner-worker-src" type="text/plain">` element and instantiated via `URL.createObjectURL(new Blob([src], {type: 'application/javascript'}))`.

## Code Layout
- `core/`: Python protocol, fountain code, and color matrix layout modules.
- `desktop_sender/`: Python desktop sender GUI and matrix rendering.
- `desktop_receiver/`: Python desktop receiver GUI, CV tracker, and color classifier.
- `web/`: JavaScript air-gap web application, Web Worker, vision engine, sender, receiver, and diagnostics.
- `tests/`: Automated unit tests, fountain tests, protocol tests, and optical loopback tests.
- `build_offline_html.py`: Self-contained single-file offline HTML compiler.
- `chromabeam_offline.html`: Generated offline air-gap web suite.
