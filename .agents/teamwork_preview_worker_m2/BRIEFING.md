# BRIEFING — 2026-08-14T13:54:00Z

## Mission
Implement robust hierarchical 1:1:1:1:1 concentric anchor tracking, direct 4-point homography warping, 360° 4-way rotation invariance, and auto-density sweeping in Python desktop receiver for Milestone 2.

## 🔒 My Identity
- Archetype: implementer
- Roles: implementer, qa, specialist
- Working directory: /home/henry/Documents/Projects/Python/QR ChromaBeam/.agents/teamwork_preview_worker_m2
- Original parent: c89bc45b-2100-41c5-80e9-59a68b919049
- Milestone: M2 - Python CV Tracker & 4-Way Homography

## 🔒 Key Constraints
- Strictly use `/home/henry/Documents/Projects/Python/venv/bin/python`. Never create local `.venv`.
- Safe file deletion: never use `rm` or `rm -rf`, move to `/home/henry/Documents/Projects/OpenCode/tmp/Trash`.
- Only modify owned files: `desktop_receiver/tracker.py`, `desktop_receiver/receiver_gui.py`, `desktop_app.py`, plus tests if needed.
- No dummy/facade implementations or hardcoded values; real mathematical algorithms only.

## Current Parent
- Conversation ID: c89bc45b-2100-41c5-80e9-59a68b919049
- Updated: not yet

## Task Summary
- **What to build**:
  1. `desktop_receiver/tracker.py`: `cv2.RETR_TREE` concentric anchor hierarchy detector, finding nested contour pairs with centroid delta < 2.5 px and area ratio in [0.035, 0.160], quad grouping, anchor sorting (TL, TR, BR, BL), 3D homography matrix mapping to canonical anchor centers $(2.5/N, 2.5/N)$, and warp to canonical grid.
  2. `desktop_receiver/receiver_gui.py` and `desktop_app.py`: 360° 4-way rotation invariance ($0^\circ, 90^\circ, 180^\circ, 270^\circ$) against CRC32 packet validation, and auto-density sweeping across grid sizes (32, 48, 64) if density not locked.
  3. Ensure 100% unit tests pass using `/home/henry/Documents/Projects/Python/venv/bin/python -m unittest discover -s tests -v`.
- **Success criteria**: 100% pass on all unit tests, robust detection of 4 anchors under perspective, noise, rotation, and lighting variations, clean UI segmentation.
- **Interface contracts**: `/home/henry/Documents/Projects/Python/QR ChromaBeam/PROJECT.md` § Interface Contracts
- **Code layout**: `/home/henry/Documents/Projects/Python/QR ChromaBeam/PROJECT.md` § Code Layout

## Key Decisions Made
- [TBD]

## Artifact Index
- `.agents/teamwork_preview_worker_m2/DISPATCH.md` — Assignment instructions
- `.agents/teamwork_preview_worker_m2/BRIEFING.md` — Agent state and situational awareness
- `.agents/teamwork_preview_worker_m2/progress.md` — Liveness and progress heartbeat
- `.agents/teamwork_preview_worker_m2/handoff.md` — Final handoff report

## Change Tracker
- **Files modified**: None yet
- **Build status**: Untested
- **Pending issues**: None

## Quality Status
- **Build/test result**: Pending
- **Lint status**: Pending
- **Tests added/modified**: None yet

## Loaded Skills
- None
