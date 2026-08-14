# Handoff Report: Optical Detection (R1) & Homography Rotation Invariance (R2)

**Agent:** Explorer 2 (`teamwork_preview_explorer_survey_2`)  
**Mission:** Survey and investigate requirements R1 & R2 in depth  
**Date:** 2026-08-14  

---

## 1. Observation

1. **Python Quad Detection Vulnerability (`desktop_receiver/tracker.py:47-69`):**
   ```python
   contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
   ...
   for cnt in contours:
       peri = cv2.arcLength(cnt, True)
       approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
       if len(approx) == 4 and cv2.isContourConvex(approx):
   ```
   `RETR_EXTERNAL` searches only for outermost boundaries. When a matrix is rendered inside an OS window, browser, or camera view with ambient screen bezels, the external contour encompasses the entire screen or window frame instead of the matrix. Furthermore, it completely ignores the 4 corner $5\times 5$ concentric finder patterns.

2. **Python Rotation Invariance Absence (`desktop_receiver/receiver_gui.py:72-73`, `desktop_app.py:122-125`):**
   ```python
   raw_bytes = color_grid_to_bytes(sampled_grid, self.layout)
   packet_data = unpack_packet(raw_bytes)
   ```
   The Python receiver only tests rotation $0^\circ$. If the phone is held at $90^\circ, 180^\circ$, or $270^\circ$, `unpack_packet` returns `None` due to CRC32/Magic mismatch, causing $100\%$ frame drops.

3. **Anchor Core Color Binarization Flaw (`core/color_matrix.py:109-123` & `web/matrix.js:80-87`):**
   In `core/color_matrix.py`:
   - Top-Right anchor center dot: `self.palette[min(4, len(self.palette)-1)]` (Red in 8-color mode).
   - Bottom-Right anchor center dot: `self.palette[min(2, len(self.palette)-1)]` (Green in 8-color/4-color mode).
   In grayscale conversion, Red ($Y = 0.299 \times 255 \approx 76 < 128$) becomes dark, merging with the surrounding $3\times 3$ black ring into a solid black block. This destroys the 3-level nested contour hierarchy in 2 of the 4 corners during binarization.

4. **JavaScript Vision Engine Density Misalignment (`web/vision_engine.js:247-251`):**
   ```javascript
   const scale = 1.08;
   const quad = orderedAnchors.map(pt => ({
       x: Math.max(0, Math.min(w - 1, cx + (pt.x - cx) * scale)),
       y: Math.max(0, Math.min(h - 1, cy + (pt.y - cy) * scale))
   }));
   ```
   A static `scale = 1.08` is used to extrapolate matrix outer corners from anchor centers across all densities. However, the exact geometric ratio is $\frac{N}{N - 5}$: for $N=32$, $\frac{32}{27} \approx 1.185$; for $N=48$, $\frac{48}{43} \approx 1.116$; for $N=64$, $\frac{64}{59} \approx 1.085$. The fixed $1.08$ causes corner clipping on $32\times 32$ and $48\times 48$ grids.

5. **Empirical Validation of Direct Anchor Homography & 4-Way Rotation Invariance:**
   We tested direct anchor-to-canonical homography $H$ and 4-way rotation CRC32 checking across 8 test angles ($0^\circ, 45^\circ, 90^\circ, 135^\circ, 180^\circ, 225^\circ, 270^\circ, 315^\circ$) under 3D perspective distortion:
   ```
   Angle   0° -> SUCCESS! Decoded @   0° CW
   Angle  45° -> SUCCESS! Decoded @   0° CW
   Angle  90° -> SUCCESS! Decoded @  90° CW
   Angle 135° -> SUCCESS! Decoded @  90° CW
   Angle 180° -> SUCCESS! Decoded @ 180° CW
   Angle 225° -> SUCCESS! Decoded @ 180° CW
   Angle 270° -> SUCCESS! Decoded @ 270° CW
   Angle 315° -> SUCCESS! Decoded @ 270° CW
   ```
   Decoding achieved 100% accuracy with zero false-positives.

---

## 2. Logic Chain

1. **Premise 1 (R1 Segmentation):** High-density matrices must be segmented from surrounding desktop text, browser controls, and room reflections without requiring manual ROI boxes.
2. **Inference 1.1:** Surrounding text and window borders lack multi-level concentric nested contours. By using `cv2.findContours(thresh, cv2.RETR_TREE)` and checking for concentric pairs with centroid distance $\Delta < 2.5\text{ px}$ and area ratio $\frac{\text{Area}(\text{Core})}{\text{Area}(\text{Ring})} \in [0.035, 0.160]$, all background elements are filtered out, isolating the exact 4 anchor centroids.
3. **Inference 1.2:** Setting all 4 anchor center dots to high-contrast White (`palette[-1]`) guarantees that binarization retains the 3-level contour tree across all 3 color modes (1-bit, 2-bit, 3-bit).
4. **Premise 2 (R2 Homography):** The 3D camera view of the matrix undergoes non-affine projective perspective distortion.
5. **Inference 2.1:** Extrapolating to outer corners with 2D Euclidean centroid vectors creates perspective distortion error because the 2D centroid shifts under perspective foreshortening.
6. **Inference 2.2:** Mapping the 4 detected anchor centers $(x_i, y_i)$ directly to their known canonical coordinates $(P_0, P_1, P_2, P_3) = \left(\frac{2.5}{N}, \frac{2.5}{N}\right), \left(\frac{N-2.5}{N}, \frac{2.5}{N}\right), \left(\frac{N-2.5}{N}, \frac{N-2.5}{N}\right), \left(\frac{2.5}{N}, \frac{N-2.5}{N}\right)$ produces the exact 8-parameter homography matrix $H$ with zero extrapolation error.
7. **Premise 3 (R2 Rotation Invariance):** The camera/phone can be held at any arbitrary angle ($0^\circ \dots 360^\circ$).
8. **Inference 3.1:** Evaluating the 4 cardinal grid rotations ($k \in \{0, 1, 2, 3\}$) against CRC32 provides 360° rotation invariance. Because CRC32 has a collision probability of $2^{-32} \approx 2.3 \times 10^{-10}$, the risk of an accidental false decode across 12 candidates is $< 2.79 \times 10^{-9}$ (zero false positives).

---

## 3. Caveats

1. **Extreme Low-Light / Severe Motion Blur:** If motion blur exceeds $2\times$ module size, the $1\times 1$ core may merge into the $3\times 3$ black ring. In potato mode, a fallback to outer anchor contour bounding or contrast-guided ROI should remain available.
2. **Extreme Perspective Grazing Angles ($>65^\circ$ Tilt):** At angles beyond $65^\circ$, severe trapezoidal compression reduces distant cells below the Nyquist sampling limit of low-resolution webcams ($640\times 480$). A minimum recommended capture resolution of $1280\times 720$ or $1080\text{p}$ is recommended for $64\times 64$ matrices.

---

## 4. Conclusion

1. **R1 Solution:** Replace `RETR_EXTERNAL` with `cv2.RETR_TREE` hierarchical concentric anchor detection in `desktop_receiver/tracker.py`, and standardize all 4 anchor cores to White in `core/color_matrix.py` and `web/matrix.js`.
2. **R2 Solution:** Compute homography $H$ directly from anchor centroids mapped to canonical coordinates $\left(\frac{2.5}{N}, \frac{2.5}{N}\right)$ to eliminate density and perspective extrapolation error. Implement 4-way rotation evaluation ($0^\circ, 90^\circ, 180^\circ, 270^\circ$) against CRC32 in Python and Web Worker.
3. **Artifact Location:** Detailed architectural diagrams, pseudocode, and mathematical formulas are documented in `/home/henry/Documents/Projects/Python/QR ChromaBeam/.agents/teamwork_preview_explorer_survey_2/analysis.md`.

---

## 5. Verification Method

To independently verify the mathematical models and rotation invariance findings:
```bash
/home/henry/Documents/Projects/Python/venv/bin/python -c "
import cv2, numpy as np
from core.color_matrix import ColorMatrixLayout, bytes_to_color_grid, color_grid_to_bytes, MODE_2BIT_4COLOR
from core.protocol import pack_packet, unpack_packet

N = 48
layout = ColorMatrixLayout(grid_size=N, color_mode=MODE_2BIT_4COLOR)
payload = b'Verification payload for ChromaBeam R1/R2 Handoff'
packet = pack_packet(file_id=77, total_blocks=4, block_size=len(payload), seed=1, payload=payload)
grid = bytes_to_color_grid(packet, layout)

# Standardize cores to white
white = layout.palette[-1]
s = layout.anchor_size
grid[2:s-2, 2:s-2] = white
grid[2:s-2, N-s+2:N-2] = white
grid[N-s+2:N-2, N-s+2:N-2] = white
grid[N-s+2:N-2, 2:s-2] = white

# Test 4 rotations
for rot in [0, 90, 180, 270]:
    rot_grid = np.rot90(grid, k=-rot//90)
    for test_rot in range(4):
        unrot = np.rot90(rot_grid, k=-test_rot)
        res = unpack_packet(color_grid_to_bytes(unrot, layout))
        if res:
            print(f'Input Rot: {rot:>3} deg -> Decoded @ {test_rot*90:>3} deg -> Match: {res[1] == payload}')
            break
"
```
Expected output:
```
Input Rot:   0 deg -> Decoded @   0 deg -> Match: True
Input Rot:  90 deg -> Decoded @ 270 deg -> Match: True
Input Rot: 180 deg -> Decoded @ 180 deg -> Match: True
Input Rot: 270 deg -> Decoded @  90 deg -> Match: True
```
