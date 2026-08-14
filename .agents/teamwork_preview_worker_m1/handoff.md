# Milestone 1 Handoff Report: Anchor Standard & Core Color Matrix

## 1. Observation
- In `core/color_matrix.py` (lines 109–123) and `web/matrix.js` (lines 79–87), top-right and bottom-right anchor centers were previously rendered with mode-dependent color dots (`Red` / `Green` in 8-color mode). Grayscale binarization luminance for red ($Y \approx 111 < 128$) merges with the surrounding $3\times 3$ dark ring, corrupting the nested 3-level contour hierarchy.
- In `core/color_matrix.py`, `cal_end` was set to `min(N - s, s + 6)` while in `web/matrix.js` `calEnd` was `Math.min(N - s, s + 5)`. Top calibration swatches $[K, R, G, B, W]$ require exactly 5 cells at coordinates $(0, 5) \dots (0, 9)$, followed immediately by timing tracks.
- In `core/color_matrix.py` and `web/matrix.js`, normalized canonical floating-point anchor centroids $[(2.5/N, 2.5/N), (1-2.5/N, 2.5/N), (1-2.5/N, 1-2.5/N), (2.5/N, 1-2.5/N)]$ were not exposed via a standard `anchor_centers` property.

## 2. Logic Chain
1. *From Observation 1*: By standardizing all 4 corner anchor center dots ($1\times 1$ at $(2, 2)$, $(2, N-3)$, $(N-3, N-3)$, $(N-3, 2)$) to high-contrast White (`palette[-1]`), all 4 anchors now maintain the exact same $1:1:1:1:1$ concentric cross-section (White border, Black ring, White core) across all color modes (1-bit, 2-bit, 3-bit).
2. *From Observation 2*: Setting `cal_end = min(N - s, s + 5)` in `core/color_matrix.py` synchronizes the calibration cells $(0, 5) \dots (0, 9)$ and timing tracks $(0, 10) \dots (0, N-s-1)$ with `web/matrix.js`.
3. *From Observation 3*: Adding `anchor_centers` property in `core/color_matrix.py` and `anchorCenters` getter in `web/matrix.js` exposes the exact canonical centroids for direct 4-point DLT homography in M2.
4. *Cross-Language Compatibility*: Evaluated all 9 combinations of modes ($0, 1, 2$) and grid sizes ($32\times 32, 48\times 48, 64\times 64$) between Python and JavaScript. Both matrix generators produced 100% identical pixel grids and recovered payloads bit-for-bit.

## 3. Caveats
- This milestone standardizes the matrix generator engines in `core/color_matrix.py` and `web/matrix.js`. Computer vision anchor detection and 4-way rotation homography in `desktop_receiver/tracker.py` and `web/vision_engine.js` are scheduled for Milestone 2.

## 4. Conclusion
- Standardized all 4 anchor center dots to high-contrast White (`palette[-1]`) in both `core/color_matrix.py` and `web/matrix.js`.
- Verified nested $1:1:1:1:1$ concentric structure and cross-sections across all 4 corner anchors.
- Verified top calibration swatches $[K, R, G, B, W]$ at coordinates $(0, 5) \dots (0, 9)$ and timing tracks.
- Implemented `anchor_centers` / `anchorCenters` canonical centroid properties.
- Added automated unit tests `test_anchor_standard_and_calibration_swatches` and `test_python_js_cross_compatibility` to `tests/test_end_to_end.py`.
- Rebuilt `chromabeam_offline.html` using `build_offline_html.py`.
- 100% of unit tests pass (11/11).

## 5. Verification Method
Run the Python test suite:
```bash
/home/henry/Documents/Projects/Python/venv/bin/python -m unittest discover -s tests -v
```

Execute cross-language matrix compatibility check:
```bash
/home/henry/Documents/Projects/Python/venv/bin/python -c '
import os, json, subprocess
import numpy as np
from core.color_matrix import ColorMatrixLayout, bytes_to_color_grid, color_grid_to_bytes, MODE_1BIT_BW, MODE_2BIT_4COLOR, MODE_3BIT_8COLOR

for mode in [MODE_1BIT_BW, MODE_2BIT_4COLOR, MODE_3BIT_8COLOR]:
    for size in [32, 48, 64]:
        py_layout = ColorMatrixLayout(size, mode)
        test_payload = os.urandom(py_layout.max_payload_bytes)
        py_grid_rgb = bytes_to_color_grid(test_payload, py_layout)
        dists = np.sum((py_grid_rgb[:, :, np.newaxis, :] - py_layout.palette[np.newaxis, np.newaxis, :, :]) ** 2, axis=3)
        py_indices = np.argmin(dists, axis=2)
        
        js_code = f"""
        const {{ JSColorMatrixLayout, bytesToGridIndices, gridIndicesToBytes }} = require("./web/matrix.js");
        const layout = new JSColorMatrixLayout({size}, {mode});
        const inputBytes = new Uint8Array({list(test_payload)});
        const jsGrid = bytesToGridIndices(inputBytes, layout);
        const jsDecoded = gridIndicesToBytes(jsGrid, layout);
        const pyGrid = {json.dumps(py_indices.tolist())};
        let gridsMatch = true;
        for (let r = 0; r < {size}; r++) {{
            for (let c = 0; c < {size}; c++) {{
                if (jsGrid[r][c] !== pyGrid[r][c]) {{ gridsMatch = false; break; }}
            }}
            if (!gridsMatch) break;
        }}
        let bytesMatch = (jsDecoded.length === inputBytes.length);
        if (bytesMatch) {{
            for (let i = 0; i < inputBytes.length; i++) {{
                if (jsDecoded[i] !== inputBytes[i]) {{ bytesMatch = false; break; }}
            }}
        }}
        console.log(JSON.stringify({{ gridsMatch, bytesMatch }}));
        """
        res = subprocess.run(["node", "-e", js_code], capture_output=True, text=True, check=True)
        out = json.loads(res.stdout.strip().split("\n")[-1])
        assert out["gridsMatch"] and out["bytesMatch"]
        assert color_grid_to_bytes(py_grid_rgb, py_layout) == test_payload
print("ALL 9 MODES & DENSITIES: 100% BIT-FOR-BIT COMPATIBLE")
'
```
