## 2026-08-14T15:44:03Z
You are Worker for the Milestone 5 Remediation & Final Polish of ChromaBeam.

Working Directory: /home/henry/Documents/Projects/Python/QR ChromaBeam/.agents/teamwork_preview_worker_m5_remedy
Original User Request: /home/henry/Documents/Projects/Python/QR ChromaBeam/.agents/ORIGINAL_REQUEST.md
Project Plan: /home/henry/Documents/Projects/Python/QR ChromaBeam/PROJECT.md
File Ownership: `web/fountain.js`, `desktop_receiver/receiver_gui.py`, `desktop_app.py`, `build_offline_html.py`.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your Mission:
1. In `web/fountain.js` (line 15):
   - Fix the Mulberry32 typo: change `t = Math.imul(t ^ (t >>> 15), 61);` to `t = Math.imul(t ^ (t >>> 15), t | 61);` to perfectly match `core/fountain.py` (`t = imul(t ^ (t >> 15), t | 61)`).
2. In `desktop_receiver/receiver_gui.py` (line 188) and `desktop_app.py` (line 186):
   - Fix payload slicing: change `payload = data[len(data) - filesize:] if filesize ...` to `payload = data[:filesize] if filesize ...` so that payload bytes are extracted from the start, trimming any block padding zeros at the end.
   - Add empty filename fallback: `filename = filename.strip() if filename else "received_file.bin"` if filename is empty or contains only whitespace.
3. Rebuild `chromabeam_offline.html` using `/home/henry/Documents/Projects/Python/venv/bin/python build_offline_html.py`.
4. Run all unit tests: `/home/henry/Documents/Projects/Python/venv/bin/python -m unittest discover -s tests -v`.
5. Run cross-language fountain test in Node.js to verify bit-for-bit PRNG and LTDecoder recovery across Python and JS for both systematic and non-systematic droplets.
6. Write your report to `/home/henry/Documents/Projects/Python/QR ChromaBeam/.agents/teamwork_preview_worker_m5_remedy/handoff.md`.
