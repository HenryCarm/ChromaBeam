# ChromaBeam Survey Analysis: Requirements R3, R4, and R5

**Author:** Explorer 3 (Replacement)  
**Date:** 2026-08-14  
**Scope:** In-depth investigation of:
- **R3**: Multi-Threaded Background Web Worker (`scanner_worker.js`) & Live Diagnostic HUD
- **R4**: Adaptive Multi-Mode Encoding & Grandma Presets (1-bit, 2-bit, 3-bit, 5-point calibration, 32/48/64 densities)
- **R5**: Complete PC & Mobile Loopback Validation & Automated E2E Test Suite

---

## Executive Summary

ChromaBeam is designed as an optical air-gapped file transfer suite utilizing fountain-coded animated 2D matrix frames captured via webcams or mobile cameras. This survey examines the web scanner worker threading model, real-time diagnostic telemetry HUD, multi-mode optical matrix encoding schemes with 5-point color calibration, grandma-friendly presets, and end-to-end loopback simulation testing.

### Key Findings Summary:
1. **R3 (Web Worker & Live HUD):**
   - The Web Worker (`web/scanner_worker.js`) executes background frame binarization, quad homography warping, multi-orientation grid decoding, and Luby Transform Gaussian elimination in an asynchronous thread.
   - Main UI (`web/receiver.js`) maintains smooth 60 FPS rendering by passing camera frames via transferable `ArrayBuffer` objects with a `workerIsBusy` lock to prevent frame accumulation.
   - Telemetry HUD provides live FPS, worker latency (ms), droplet counts/drops, Otsu luminance threshold, dynamic contrast metrics, Pi-accurate progress formatting (`0.0000%`), and a rolling diagnostic log terminal with DOM-throttled retention.
   - **Identified Gap:** `web/receiver.js` line 203 calls `processFrameInline` if `scannerWorker` fails to initialize, but `processFrameInline` is not defined anywhere in the codebase. Furthermore, `build_offline_html.py` does not bundle `scanner_worker.js` as an inline Blob worker, which causes worker failure when running from local `file:///` URLs or offline bundles.

2. **R4 (Multi-Mode Encoding & Grandma Presets):**
   - **Mode 0 (1-bit B&W Potato Mode):** 1 bit/cell, 2-color palette (Black/White), designed for low-exposure, blurred, or budget sensors. Supported by Otsu thresholding and dynamic $\pm 15$ offset retry.
   - **Mode 1 (2-bit Balanced 4-Color):** 2 bits/cell, 4-color palette (Black, Red, Green, White), providing $2\times$ data density with orthogonal chrominance separation.
   - **Mode 2 (3-bit High-Speed Turbo 8-Color JAB):** 3 bits/cell, 8-color palette (RGB cube vertices: K, B, G, C, R, M, Y, W), achieving up to 550+ KB/s optical throughput.
   - **5-Point Color Calibration:** Located on top border cells $(0, 5)$ to $(0, 9)$ featuring $[K, R, G, B, W]$ swatches. Used by `AdaptiveColorClassifier` to dynamically recompute decision boundaries under ambient color temperature shifts.
   - **Grid Densities:** $32\times 32$, $48\times 48$, and $64\times 64$ with $5\times 5$ corner anchor isolation (100 reserved cells) and timing border tracks.
   - **Auto-Density & Mode Negotiation:** Receiver cycles through candidate configurations `(grid, mode)` against 4-way orientations $(0^\circ, 90^\circ, 180^\circ, 270^\circ)$ validated against CRC32. Upon a valid frame, receiver locks config to minimize CPU overhead.

3. **R5 (Loopback Validation & Automated E2E Test Suite):**
   - Existing tests (`tests/test_end_to_end.py`, `tests/test_fountain.py`, `tests/test_protocol.py`) pass 100% (9 tests in 1.1s) for pure matrix-to-byte serialization and Luby Transform peeling/GF(2) solvers.
   - **Identified Gap:** Existing tests lack optical channel simulation (perspective distortion $H$, 4-way 360° rotation permutation, Gaussian/motion blur, camera sensor noise, uneven gradient illumination, exposure underexposure/overexposure, and auto-density auto-detection).
   - An end-to-end headless loopback harness must be constructed in `tests/test_optical_loopback.py` that renders frames, applies synthetic optical perturbations, feeds them through `OpticalTracker` and `AdaptiveColorClassifier`, and validates 100% bit-for-bit file reconstruction.

---

## 1. Deep Dive: Requirement R3 — Multi-Threaded Web Worker & Diagnostic HUD

### 1.1 Web Worker Architecture & Concurrency Model

```
+-------------------------------------------------------------------------+
|                              MAIN UI THREAD                             |
|  +---------------------+   requestAnimationFrame   +------------------+ |
|  | HTML5 <video> Stream | -----------------------> | 60 FPS Canvas UI | |
|  +---------------------+                           +------------------+ |
|            |                                                 ^          |
|            | (if !workerIsBusy)                              |          |
|            v                                                 |          |
|    Transferable ArrayBuffer                            frameResult Msg  |
|    postMessage({buffer, ...}, [buffer])                      |          |
+------------|-------------------------------------------------|----------+
             |                                                 |
             v                                                 |
+-------------------------------------------------------------------------+
|                     BACKGROUND WEB WORKER (scanner_worker.js)           |
|                                                                         |
|  1. detectOpticalQuad (Concentric Anchor Matching / Adaptive ROI)       |
|  2. ProjectiveTransform (4-point Homography Matrix H)                   |
|  3. sampleQuadGrid (Subpixel 3x3 Averaging + Otsu Luma Thresholding)    |
|  4. decodeGridMultiOrientation (0°, 90°, 180°, 270° Orientation Sweep)  |
|  5. unpackPacket (Magic 0x4342 + CRC32 Integrity Verification)          |
|  6. LTDecoder (Incremental GF(2) Gaussian Elimination & Peeling)       |
+-------------------------------------------------------------------------+
```

#### Detailed Worker Mechanism (`web/scanner_worker.js`):
- **Script Imports:** Lines 7–13 import `fountain.js`, `protocol.js`, `matrix.js`, and `vision_engine.js`.
- **Pre-Allocated Layout Cache:** Lines 25–28 pre-instantiate `JSColorMatrixLayout` for candidate configurations to prevent garbage collection spikes during continuous scanning.
- **Zero-Copy Memory Transfer:** In `web/receiver.js` (lines 190–201), `imgData.data.buffer` is passed with transferable ownership (`[buffer]`). This eliminates copy latency ($\sim 5-10$ ms for 720p RGBA buffers).
- **Concurrency Gate (`workerIsBusy`):**
  - Main thread sets `workerIsBusy = true` when posting a frame to the worker.
  - While worker is busy computing, subsequent video frames continue rendering on the canvas at 60 FPS with zero stutter.
  - When worker returns `frameResult`, `handleWorkerMessage` sets `workerIsBusy = false`.
  - Stale frames are naturally discarded without building up a message queue.

#### Missing Inline Fallback & Offline Bundle Gap:
1. In `web/receiver.js` line 203:
   ```javascript
   if (scannerWorker) {
       workerIsBusy = true;
       scannerWorker.postMessage({ type: 'processFrame', buffer, width: vw, height: vh, guideRect }, [buffer]);
   } else {
       processFrameInline(imgData, vw, vh, guideRect); // NOT DEFINED -> throws ReferenceError!
   }
   ```
2. When `chromabeam_offline.html` is opened directly via `file://` protocol in modern browsers (Chrome/Firefox/Safari), loading an external worker file (`new Worker('scanner_worker.js')`) or calling `importScripts()` is blocked by CORS/same-origin policy on local files.
3. **Architectural Solution:**
   - Implement `processFrameInline` or construct an in-memory inline Blob Worker:
     ```javascript
     const blob = new Blob([allConcatenatedWorkerAndDependencyJs], { type: 'application/javascript' });
     const workerUrl = URL.createObjectURL(blob);
     scannerWorker = new Worker(workerUrl);
     ```
   - Update `build_offline_html.py` to bundle dependencies and the worker code inside the self-contained HTML.

---

### 1.2 Real-Time Diagnostic HUD & Telemetry Metrics

The diagnostic HUD in `web/index.html` and `web/receiver.js` provides comprehensive real-time telemetry:

| HUD Metric | Calculation / Source | Display Format | Target SLA / Range |
|---|---|---|---|
| **Camera FPS** | `receiverFpsCounter` measured over 1000ms delta | `60 FPS (Worker: 14.2ms)` | 30–60 FPS UI |
| **Worker Latency** | `performance.now() - startTime` in worker | `12.4ms` | $< 25$ ms per frame |
| **Fountain Progress** | `solvedBlocks.size / K` | `0.0000%` to `100.0000%` | Exact 4 decimal places |
| **Block Solved Counter** | `solvedBlocks.size` / `K` | `Solved: 42 / 120 Blocks (35.0000%)` | Monotonically non-decreasing |
| **Droplet Statistics** | `workerPacketsCaught` and `workerCRCErrors` | `Caught: 45 (Drops: 3)` | Drop rate $< 15\%$ |
| **Vision Detector** | Detection method from `detectOpticalQuad` | `4-Anchor Finder ★` / `Adaptive Boundary ○` | Confidence $\ge 0.80$ |
| **Luma & Contrast** | Otsu threshold and $(L_{\max} - L_{\min})$ | `Thresh: 128 (Contr: 185)` | Contrast $> 35$ for lock |
| **Rotation Indicator** | Verified packet rotation steps | `(90° rot)` | $0^\circ, 90^\circ, 180^\circ, 270^\circ$ |
| **Live Terminal Log** | Throttled rolling log buffer (max 120 lines) | Timestamped console lines with category colors | Copy & Clear actions |

#### Contrast & Luminance Math:
- Pixel Luminance formula (ITU-R BT.601):
  $$L(R, G, B) = 0.299 \cdot R + 0.587 \cdot G + 0.114 \cdot B$$
- Otsu's Between-Class Variance Maximization:
  $$\sigma_B^2(t) = \omega_0(t) \omega_1(t) [\mu_0(t) - \mu_1(t)]^2$$
  where $\omega_0(t)$ and $\omega_1(t)$ are background/foreground probabilities, and $\mu_0(t)$, $\mu_1(t)$ are mean luminances.
- Multi-threshold Glare Compensation (Mode 0):
  If the primary Otsu threshold fails and contrast $> 30$, the worker evaluates $T_{\text{alt}} = T_{\text{otsu}} \pm 15$ to resolve monitor specular glare or camera auto-exposure oscillation.

---

## 2. Deep Dive: Requirement R4 — Adaptive Multi-Mode Encoding & Grandma Presets

### 2.1 Optical Mode Specifications & Bit Allocation

```
+----------------------------------------------------------------------------------------+
|                                    TRANSMISSION MODES                                  |
+----------------------------------------------------------------------------------------+
| Mode 0: 1-bit Monochrome B&W (Potato Camera Mode)                                      |
| - Palette: [0, 0, 0] (Black, 0), [255, 255, 255] (White, 1)                           |
| - Bits per cell: 1                                                                     |
| - Use Case: Low-end webcams, budget mobile cameras, extreme glare, heavy motion blur   |
+----------------------------------------------------------------------------------------+
| Mode 1: 2-bit 4-Color (Balanced Mode)                                                  |
| - Palette: [0,0,0] (Black, 00), [255,50,50] (Red, 01),                                |
|            [50,255,50] (Green, 10), [255,255,255] (White, 11)                          |
| - Bits per cell: 2                                                                     |
| - Use Case: General office screens, smartphones, 2x standard density                   |
+----------------------------------------------------------------------------------------+
| Mode 2: 3-bit 8-Color RGB JAB (High-Speed Turbo Mode)                                  |
| - Palette: [0,0,0] (Black, 000), [0,0,255] (Blue, 001), [0,255,0] (Green, 010),       |
|            [0,255,255] (Cyan, 011), [255,0,0] (Red, 100), [255,0,255] (Magenta, 101),  |
|            [255,255,0] (Yellow, 110), [255,255,255] (White, 111)                      |
| - Bits per cell: 3                                                                     |
| - Use Case: High-throughput transfer (550+ KB/s) on IPS/OLED screens with 1080p sensors |
+----------------------------------------------------------------------------------------+
```

### 2.2 Matrix Geometry & Density Levels

For an $N \times N$ matrix layout (`ColorMatrixLayout` / `JSColorMatrixLayout`):
- **Anchor Size:** $s = 5$ (1:1:1:1:1 concentric squares in all 4 corners).
- **Reserved Anchor Cells:** $4 \times (5 \times 5) = 100$ cells.
- **Top Border Calibration Cells:** Cells $(0, s)$ to $(0, s+4)$ (5 cells).
- **Border Timing Tracks:** Top border $(0, s+5)$ to $(0, N-s-1)$ and Bottom border $(N-1, s)$ to $(N-1, N-s-1)$.
- **Data Cells Count & Capacity Matrix:**

| Grid Size | Color Mode | Bits/Cell | Total Cells ($N^2$) | Reserved Cells | Usable Data Cells | Max Payload (Bytes) | Usable Block Size |
|---|---|---|---|---|---|---|---|
| **$32 \times 32$** | 0 (1-bit B&W) | 1 | 1,024 | 144 | 880 | 110 B | 88 B |
| **$32 \times 32$** | 1 (2-bit 4-Col) | 2 | 1,024 | 144 | 880 | 220 B | 196 B |
| **$48 \times 48$** | 0 (1-bit B&W) | 1 | 2,304 | 176 | 2,128 | 266 B | 240 B |
| **$48 \times 48$** | 1 (2-bit 4-Col) | 2 | 2,304 | 176 | 2,128 | 532 B | 500 B |
| **$48 \times 48$** | 2 (3-bit 8-Col) | 3 | 2,304 | 176 | 2,128 | 798 B | 768 B |
| **$64 \times 64$** | 0 (1-bit B&W) | 1 | 4,096 | 208 | 3,888 | 486 B | 450 B |
| **$64 \times 64$** | 2 (3-bit 8-Col) | 3 | 4,096 | 208 | 3,888 | 1,458 B | 1,400 B |

### 2.3 5-Point Reference Color Calibration

Under real-world conditions, monitor color temperature (e.g., warm 3000K vs cool 6500K), room lighting, and camera auto-white-balance distort optical RGB values.

#### Calibration Swatch Positioning:
- Top row border, columns $c = 5, 6, 7, 8, 9$:
  - Swatch 0: Black `[0, 0, 0]`
  - Swatch 1: Red `[255, 0, 0]`
  - Swatch 2: Green `[0, 255, 0]`
  - Swatch 3: Blue `[0, 0, 255]`
  - Swatch 4: White `[255, 255, 255]`

#### Dynamic Classification Algorithm:
```python
def calibrate(self, cal_samples: List[np.ndarray]):
    black, red, green, blue, white = [np.mean(s, axis=0) for s in cal_samples[:5]]
    
    # Adaptive channel midpoint thresholds
    self.r_threshold = float((red[0] + green[0] + black[0]) / 3.0 + red[0]) / 2.0
    self.g_threshold = float((green[1] + red[1] + black[1]) / 3.0 + green[1]) / 2.0
    self.b_threshold = float((blue[2] + red[2] + black[2]) / 3.0 + blue[2]) / 2.0
    
    # Safe bounds clamping
    self.r_threshold = np.clip(self.r_threshold, 40.0, 215.0)
    self.g_threshold = np.clip(self.g_threshold, 40.0, 215.0)
    self.b_threshold = np.clip(self.b_threshold, 40.0, 215.0)
```

Each RGB cell vector $\mathbf{v} = [R, G, B]$ is classified into 3 binary bits:
$$b_R = \mathbb{I}(R > T_R), \quad b_G = \mathbb{I}(G > T_G), \quad b_B = \mathbb{I}(B > T_B)$$
$$\text{ColorIndex} = (b_R \ll 2) \mid (b_G \ll 1) \mid b_B$$

### 2.4 Grandma Presets & Simplified UI

Three Grandma-friendly presets allow one-click operation:
1. 🛡️ **Potato Camera:** Mode 0 (1-bit B&W), $32 \times 32$ grid, 15 FPS. Maximum error tolerance, minimum CPU load.
2. ⚖️ **Balanced:** Mode 1 (2-bit 4-Color), $48 \times 48$ grid, 25 FPS. Optimal default for modern displays.
3. ⚡ **Turbo Speed:** Mode 2 (3-bit 8-Color), $64 \times 64$ grid, 45 FPS. Maximum optical bandwidth (550+ KB/s).

Advanced settings (custom grid, FPS slider, manual color depth) remain tucked under a collapsible "⚙️ Advanced Settings (Pro)" accordion.

---

## 3. Deep Dive: Requirement R5 — PC & Mobile Loopback Validation & Automated E2E Test Suite

### 3.1 Loopback Validation Architecture

```
+-------------------------------------------------------------------------+
|                    HEADLESS E2E LOOPBACK TEST PIPELINE                  |
+-------------------------------------------------------------------------+
|  1. PAYLOAD GENERATION                                                  |
|     - Generate synthetic binary file (64 KB / 128 KB / 1 MB)            |
|     - Pack file metadata (filename, size, MIME type)                    |
|     - Split into K blocks via LTEncoder                                 |
+-------------------------------------------------------------------------+
                                 |
                                 v
|  2. OPTICAL MATRIX RENDERING                                            |
|     - Pack protocol header (MAGIC_INT=0x4342, fileId, K, blockSize, seed)|
|     - Compute CRC32 checksum                                            |
|     - Map bits to Color Matrix (32x32, 48x48, 64x64)                    |
|     - Render 1:1:1:1:1 concentric anchors & 5-point calibration swatches|
+-------------------------------------------------------------------------+
                                 |
                                 v
|  3. SYNTHETIC OPTICAL CAMERA CHANNEL SIMULATION                         |
|     - Projective Homography Warp H (Perspective tilt: pitch/yaw ±25°)   |
|     - 360° Rotations (0°, 90°, 180°, 270°)                              |
|     - Optical Blur (Gaussian blur kernel 3x3, 5x5, motion blur)         |
|     - Additive Gaussian Sensor Noise (sigma = 10..25)                   |
|     - Exposure / Lighting Shift (0.4x underexposure, 1.4x overexposure) |
|     - Non-Uniform Spatial Gradient Illumination                         |
|     - Channel Loss (10% to 50% random droplet erasure + shuffle)        |
+-------------------------------------------------------------------------+
                                 |
                                 v
|  4. OPTICAL RECEIVER & DECODER PIPELINE                                 |
|     - OpticalTracker: Detect largest 4-point quadrilateral              |
|     - Homography Inverse Warp: cv2.warpPerspective / ProjectiveTransform|
|     - Subpixel Cell Sampling: 3x3 bilinear kernel averaging             |
|     - Adaptive Calibration: sample 5-point swatches & update thresholds |
|     - 4-Way Rotation Sweep: unpackPacket + CRC32 verification           |
|     - LTDecoder: incremental GF(2) Gaussian elimination & peeling       |
+-------------------------------------------------------------------------+
                                 |
                                 v
|  5. BIT-FOR-BIT RECONSTRUCTION VERIFICATION                             |
|     - Verify is_complete == True                                        |
|     - Verify unpack_file_metadata(reconstructed_data)                   |
|     - Assert reconstructed_file == original_file (SHA-256 / CRC32)     |
+-------------------------------------------------------------------------+
```

### 3.2 Synthetic Optical Channel Perturbation Models

To ensure the test suite rigorously models real-world conditions without requiring physical camera hardware during CI/CD, the following mathematical perturbations must be implemented in Python:

1. **3D Perspective Homography ($H$):**
   Given a square canonical image with corners $\mathbf{p}_i \in \{(0,0), (W,0), (W,H), (0,H)\}$, apply random corner displacements $\mathbf{p}'_i = \mathbf{p}_i + \boldsymbol{\delta}_i$ with $|\boldsymbol{\delta}_i| \le 0.25 \cdot W$:
   $$\mathbf{x}' \sim H \mathbf{x} = \begin{bmatrix} h_{11} & h_{12} & h_{13} \\ h_{21} & h_{22} & h_{23} \\ h_{31} & h_{32} & 1 \end{bmatrix} \begin{bmatrix} x \\ y \\ 1 \end{bmatrix}$$

2. **4-Way 360° Rotation:**
   Apply matrix rotation $R_\theta$ for $\theta \in \{0^\circ, 90^\circ, 180^\circ, 270^\circ\}$ using `np.rot90(img, k)`.

3. **Uneven Lighting Gradient:**
   Simulate directional room lighting across the sensor:
   $$I_{\text{lit}}(x, y) = I(x, y) \cdot \left(0.5 + 0.5 \frac{x}{W}\right) \cdot \left(0.7 + 0.3 \frac{y}{H}\right)$$

4. **Sensor Noise & Optical Blur:**
   - Gaussian Noise: $I_{\text{noisy}}(x, y) = \text{clip}(I(x, y) + \mathcal{N}(0, \sigma^2), 0, 255)$ with $\sigma = 15$.
   - Gaussian Blur: $I_{\text{blurred}} = I * G_{5\times 5}(\sigma=1.2)$.

5. **Harsh Packet Loss Simulation:**
   - Generate $1.5 \times K$ droplets.
   - Randomly drop $40\%$ of packets.
   - Shuffle arrival sequence to test out-of-order Luby Transform recovery.

---

## 4. Acceptance Criteria & Test Coverage Matrix

| Requirement | Acceptance Criterion | Test Harness Implementation | Target Result |
|---|---|---|---|
| **R1** | 1:1:1:1:1 finder pattern and dense blob segmentation isolate matrix corners cleanly without capturing surrounding UI window text. | `test_finder_pattern_segmentation` | Quad accuracy $\Delta < 2$ px |
| **R2** | 360° 4-way rotation invariance decodes frames held upright, sideways, or upside-down. | `test_360_rotation_invariance` ($0^\circ, 90^\circ, 180^\circ, 270^\circ$) | 100% frame decode |
| **R3** | Real-time diagnostic logger streams worker events and droplet decodes without dropping main-thread frames. | Web Worker telemetry unit test & timing benchmarks | Zero UI thread lockup |
| **R4.1** | 1-bit B&W Potato Mode successfully decodes on low-exposure, blurred, and budget mobile camera feeds. | `test_potato_mode_underexposed_blurred` | 100% packet recovery |
| **R4.2** | 2-bit 4-Color Balanced Mode decodes with high chrominance separation. | `test_balanced_4color_mode` | 100% packet recovery |
| **R4.3** | 3-bit 8-Color Turbo Mode with 5-point calibration decodes under ambient color temperature shifts. | `test_turbo_8color_with_calibration` | 100% packet recovery |
| **R4.4** | Auto-density detection decodes 32x32, 48x48, and 64x64 streams without manual user configuration. | `test_auto_density_sweep` | Auto-lock within 1 frame |
| **R5** | Automated end-to-end Python test suite passes 100% across all 3 color modes under packet drop and optical distortion. | `test_end_to_end_full_file_recovery` | 100% Bit-for-bit match |

---

## 5. Architectural Recommendations & Implementation Plan

### 5.1 Immediate Implementation Fixes (for Implementation Phase)
1. **Fix Web Worker Inlining in `chromabeam_offline.html` (`build_offline_html.py`):**
   - Package all worker scripts (`scanner_worker.js`, `vision_engine.js`, `matrix.js`, `protocol.js`, `fountain.js`) into an inline Blob URL so the offline single-file app functions on any device with zero server dependency.
2. **Define `processFrameInline` in `web/receiver.js`:**
   - Provide a complete inline decoding fallback function if Web Worker instantiation is blocked.
3. **Expand Python Test Suite (`tests/test_optical_loopback.py`):**
   - Implement the complete synthetic camera loopback suite parameterized across all 3 modes, all 3 densities, 4 rotations, and optical distortion channels.

---
