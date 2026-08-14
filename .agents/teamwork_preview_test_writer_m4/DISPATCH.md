## 2026-08-14T14:48:14Z
You are Test Writer for Milestone 4 (M4: Comprehensive Optical Loopback & E2E Test Suite) of ChromaBeam.

Working Directory: /home/henry/Documents/Projects/Python/QR ChromaBeam/.agents/teamwork_preview_test_writer_m4
Original User Request: /home/henry/Documents/Projects/Python/QR ChromaBeam/.agents/ORIGINAL_REQUEST.md
Project Plan: /home/henry/Documents/Projects/Python/QR ChromaBeam/PROJECT.md
Test Infrastructure Plan: /home/henry/Documents/Projects/Python/QR ChromaBeam/TEST_INFRA.md
File Ownership: You exclusively own `tests/test_optical_loopback.py`.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your Mission:
Implement a comprehensive, rigorous optical loopback test suite in `tests/test_optical_loopback.py` that verifies the entire end-to-end air-gapped file transfer pipeline across all required dimensions:

1. **Tier 1 — Feature & Mode Coverage (>= 5 per feature)**:
   - 1-bit Potato B&W Mode: 32x32, 48x48, 64x64 matrices.
   - 2-bit Balanced 4-Color Mode: 32x32, 48x48, 64x64 matrices.
   - 3-bit High-Speed Turbo 8-Color Mode: 32x32, 48x48, 64x64 matrices with 5-point calibration.
   - 1:1:1:1:1 concentric anchor detection and canonical quad ordering.

2. **Tier 2 — Boundary & Optical Perturbations (>= 5 per feature)**:
   - 360° 4-way rotation invariance: 0°, 90°, 180°, 270° orientation recovery against CRC32.
   - Arbitrary angle continuous rotations: 45°, 135°, 225°, 315°.
   - 3D perspective homography warping (perspective tilt up to 40°).
   - Gaussian blur ($\sigma = 1.0 \dots 2.5$) and Gaussian sensor noise ($\sigma = 10 \dots 35$).
   - Lighting exposure shifts ($\pm 40$) and non-uniform spatial illumination gradients (screen glare/reflections).
   - Surrounding desktop UI distraction: matrix embedded inside desktop window with surrounding code text, taskbars, and icons.

3. **Tier 3 — Cross-Feature Combinations (Pairwise)**:
   - Combinations of color mode x grid density x rotation angle x perspective distortion.
   - Auto-density sweeping without manual configuration.

4. **Tier 4 — Real-World Air-Gap Transmission Scenarios**:
   - Complete multi-frame file transfer: generate random test files (e.g. 5 KB, 20 KB binary payloads), split into fountain droplets with 30-40% simulated packet loss, warp frames through synthetic optical camera channel, decode through tracker & LTDecoder, and assert byte-for-byte exact SHA256/content match.

5. Run the complete test suite with `/home/henry/Documents/Projects/Python/venv/bin/python -m unittest discover -s tests -v` and verify all tests pass 100%.
