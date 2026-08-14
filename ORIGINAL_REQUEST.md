# Original User Request

## Initial Request — 2026-08-14T13:26:55Z

ChromaBeam: Next-generation optical air-gapped file transfer suite with adaptive multi-mode encoding (High-Speed 3-bit RGB, Balanced 4-Color, and 1-bit Potato-Camera B&W), robust 1:1:1:1:1 nested-square finder pattern tracking, 360° 3D perspective homography, auto-density detection, and simplified Grandma-friendly presets.

Working directory: `/home/henry/Documents/Projects/Python/QR ChromaBeam`
Integrity mode: development

## Requirements

### R1. Robust 1:1:1:1:1 Concentric Finder Pattern & Dense QR Segmentation
Implement mathematical QR/Aztec-grade contour hierarchy and scanline finder pattern detection ($1:1:1:1:1$ ratio). Ensure the detector isolates the dense matrix square from surrounding desktop UI text, taskbars, and reflections so that only the valid matrix cells are warped into the canonical grid.

### R2. 360° 3D Projective Homography & 4-Way Rotation Invariance
Warp the 4 detected corners using projective transformation ($H$) into a top-down square grid. Evaluate all 4 rotations ($0^\circ, 90^\circ, 180^\circ, 270^\circ$) against CRC32 in the background worker so the receiver works flawlessly even when the phone is held sideways or upside-down.

### R3. Multi-Threaded Background Web Worker & Live Diagnostic HUD
Offload frame sampling, binarization, and fountain decoding to a dedicated Web Worker (`scanner_worker.js`) running in parallel with the 60 FPS main camera feed. Provide an on-screen live terminal log stream, Pi-accurate progress indicator ($0.0000\%$), and dynamic lighting contrast metrics.

### R4. Adaptive Multi-Mode Encoding & Grandma Presets
Support 3 distinct transmission modes selectable by presets or auto-negotiated:
1. **Potato Camera / Ultra-Reliable Mode (1-bit B&W)**: Pure black-and-white high-contrast matrix for budget cameras, dim lighting, and extreme angles.
2. **Balanced Mode (2-bit / 4-Color CMYK/RGB)**: High noise resilience with $2\times$ standard QR density.
3. **High-Speed Turbo Mode (3-bit / 8-Color JAB)**: Maximum optical throughput ($3\times$ speed) with 5-point calibration.

### R5. Complete PC & Mobile Loopback Validation
Automate full optical loopback testing for PC webcam receiver and mobile receiver across all densities (32x32, 48x48, 64x64) and color modes.

## Acceptance Criteria

### Detection & Decoding Verification
- [ ] 1:1:1:1:1 finder pattern and dense blob segmentation isolate matrix corners cleanly without capturing surrounding UI window text.
- [ ] 1-bit B&W Potato Mode successfully decodes on low-exposure, blurred, and budget mobile camera feeds.
- [ ] 360° 4-way rotation invariance decodes frames held upright, sideways, or upside-down.
- [ ] Auto-density detection decodes 32x32, 48x48, and 64x64 streams without manual user configuration.
- [ ] Real-time diagnostic logger streams worker events and droplet decodes without dropping main-thread frames.
- [ ] Automated end-to-end Python test suite passes 100% across all 3 color modes.
