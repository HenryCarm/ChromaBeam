# BRIEFING — 2026-08-14T13:46:00Z

## Mission
Map the existing ChromaBeam codebase, architecture, file layout, dependencies, and core fountain code / transmission structures.

## 🔒 My Identity
- Archetype: explorer
- Roles: codebase-survey, architecture-mapping
- Working directory: /home/henry/Documents/Projects/Python/QR ChromaBeam/.agents/teamwork_preview_explorer_survey_1_rep
- Original parent: c89bc45b-2100-41c5-80e9-59a68b919049
- Milestone: Survey Phase (ChromaBeam Codebase & Architecture Mapping)

## 🔒 Key Constraints
- Read-only investigation — do NOT implement or modify application source code
- Strictly use central venv `/home/henry/Documents/Projects/Python/venv/bin/python`
- Never create local `.venv` folders
- Never use `rm` directly (use safe trash if needed)
- Output analysis.md and handoff.md in working directory

## Current Parent
- Conversation ID: c89bc45b-2100-41c5-80e9-59a68b919049
- Updated: 2026-08-14T13:46:00Z

## Investigation State
- **Explored paths**:
  - `core/` (`protocol.py`, `fountain.py`, `color_matrix.py`, `__init__.py`)
  - `desktop_sender/` (`main.py`, `sender_gui.py`)
  - `desktop_receiver/` (`tracker.py`, `color_classifier.py`, `receiver_gui.py`)
  - `desktop_app.py`, `build_offline_html.py`, `chromabeam_offline.html`, `buildozer.spec`
  - `web/` (`index.html`, `style.css`, `protocol.js`, `fountain.js`, `matrix.js`, `vision_engine.js`, `scanner_worker.js`, `sender.js`, `receiver.js`, `server.py`, `diag.html`, `diag_cam.html`)
  - `tests/` (`test_fountain.py`, `test_protocol.py`, `test_end_to_end.py`)
  - `.github/workflows/build_and_release.yml`
- **Key findings**:
  - Fountain coding (LT with systematic K frames, Mulberry32 PRNG, Robust Soliton distribution, GF(2) incremental elimination) is 100% losslessly verified in Python and JS.
  - Multi-mode color matrix supports Potato B&W (1-bit), Balanced 4-color (2-bit), Turbo 8-color (3-bit) across 32x32, 48x48, 64x64 grids.
  - Web Worker receiver implements 360° 4-way rotation invariance, Otsu thresholding, AR reticles, live HUD, and diagnostic log terminal.
  - All 9 unit tests pass in 1.039s.
  - Gaps identified: Python OpenCV receiver lacks 4-way rotation checks against CRC32; Python tracker lacks 1:1:1:1:1 anchor scanline/contour hierarchy; `build_offline_html.py` needs inline Blob Worker.
- **Unexplored areas**: None. Entire codebase mapped and documented.

## Key Decisions Made
- Executed unit tests with `/home/henry/Documents/Projects/Python/venv/bin/python`.
- Comprehensive survey compiled into `analysis.md` and `handoff.md`.

## Artifact Index
- DISPATCH.md — Initial dispatch log
- progress.md — Liveness & task execution tracker
- analysis.md — Deep technical survey report (6 sections + recommendations)
- handoff.md — 5-component standardized handoff report
