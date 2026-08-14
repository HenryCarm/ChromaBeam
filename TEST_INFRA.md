# E2E Test Infra: ChromaBeam

## Test Philosophy
- Opaque-box, requirement-driven, empirical validation across all optical air-gap conditions.
- Methodology: Category-Partition + Boundary Value Analysis + Pairwise Combinations + Real-World Perturbations.

## Feature Inventory
| # | Feature | Source (requirement) | Tier 1 | Tier 2 | Tier 3 |
|---|---------|---------------------|:------:|:------:|:------:|
| 1 | 1-bit Potato B&W Mode | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 2 | 2-bit Balanced 4-Color Mode | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 3 | 3-bit Turbo 8-Color Mode | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 4 | 1:1:1:1:1 Concentric Anchor Detection | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ |
| 5 | UI Background / Text Segmentation | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ |
| 6 | 360° 3D Projective Homography Warp | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 7 | 4-Way Rotation Invariance (0°, 90°, 180°, 270°) | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 8 | Multi-Threaded Web Worker & Diagnostic HUD | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |
| 9 | Offline Bundled HTML & Blob Worker | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |
| 10 | Auto-Density Sweeping (32x32, 48x48, 64x64) | ORIGINAL_REQUEST §R4, R5 | 5 | 5 | ✓ |
| 11 | Luby Transform Fountain Packet Reconstruction | ORIGINAL_REQUEST §R5 | 5 | 5 | ✓ |

## Test Architecture
- Test Runner: Python `unittest` via `/home/henry/Documents/Projects/Python/venv/bin/python -m unittest discover -s tests -v`
- Synthetic Distortion Engine:
  - 3D Projective Warp (arbitrary tilt angles up to 45°)
  - Rotations (0°, 45°, 90°, 135°, 180°, 225°, 270°, 315°)
  - Gaussian blur ($\sigma = 1.0 \dots 2.5$)
  - Gaussian noise ($\sigma = 10 \dots 35$)
  - Brightness/Exposure shifts ($\pm 40$)
  - Spatial illumination gradient (simulating room glare/reflections)
  - UI Window distraction (matrix surrounded by code editor text, taskbars, buttons)

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Air-Gapped Key Transfer (1-bit Potato Mode, 32x32, rotated 90°, dim lighting) | F1, F4, F6, F7, F10, F11 | Medium |
| 2 | High-Speed Binary Payload Transfer (3-bit Turbo Mode, 64x64, 5-point calibration, 30° perspective tilt) | F3, F4, F6, F7, F10, F11 | High |
| 3 | Balanced Multi-Frame Document Transfer (2-bit Mode, 48x48, 180° upside-down, 30% packet erasure) | F2, F4, F6, F7, F10, F11 | High |
| 4 | Desktop UI Distraction Rejection (Matrix displayed inside code editor with active text cursor and window border) | F4, F5, F6, F7 | Medium |
| 5 | Offline Browser Single-File Air-Gap Receiver (Inline Blob Worker execution, zero network calls) | F8, F9, F11 | Medium |

## Coverage Thresholds
- Tier 1 (Feature Coverage): $\ge 5$ test cases per feature.
- Tier 2 (Boundary & Corner Cases): $\ge 5$ test cases per feature (extreme tilt, high noise, boundary sizes).
- Tier 3 (Cross-Feature Combinations): Pairwise combinations across all modes (1-bit, 2-bit, 3-bit), densities (32, 48, 64), and rotations (0°, 90°, 180°, 270°).
- Tier 4 (Real-World Application Scenarios): $\ge 5$ realistic air-gapped end-to-end transmissions.
- Acceptance Target: 100% pass rate across the complete test suite.
