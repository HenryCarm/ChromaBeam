## 2026-08-14T13:53:28Z
You are Worker 2 for Milestone 2 (M2: Python CV Tracker & 4-Way Homography) of ChromaBeam.

Working Directory: /home/henry/Documents/Projects/Python/QR ChromaBeam/.agents/teamwork_preview_worker_m2
Original User Request: /home/henry/Documents/Projects/Python/QR ChromaBeam/.agents/ORIGINAL_REQUEST.md
Project Plan: /home/henry/Documents/Projects/Python/QR ChromaBeam/PROJECT.md
File Ownership: You exclusively own `desktop_receiver/tracker.py`, `desktop_receiver/receiver_gui.py`, and `desktop_app.py`.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your Mission:
1. In `desktop_receiver/tracker.py`:
   - Replace the simplistic `cv2.RETR_EXTERNAL` polygon search with robust mathematical `cv2.RETR_TREE` hierarchical contour detection.
   - Detect $1:1:1:1:1$ concentric finder pattern anchors by finding nested contour pairs with matching centroids ($\Delta < 2.5\text{ px}$) and area ratio $\frac{\text{Area}(\text{Core})}{\text{Area}(\text{Ring})} \in [0.035, 0.160]$.
   - Filter and isolate the 4 anchor centroids from surrounding desktop UI text, taskbars, and reflections.
   - Sort the 4 anchors into canonical order (Top-Left, Top-Right, Bottom-Right, Bottom-Left).
   - Compute the 3D projective homography matrix ($H$) mapping the 4 detected anchor centers directly to their canonical coordinates $(\frac{2.5}{N}, \frac{2.5}{N})$ from `layout.anchor_centers`.
   - Warp the camera frame into a normalized top-down canonical matrix grid.
2. In `desktop_receiver/receiver_gui.py` and `desktop_app.py`:
   - Implement 360° 4-way rotation invariance ($0^\circ, 90^\circ, 180^\circ, 270^\circ$) by testing all 4 orientations (`np.rot90(grid, k=-rot//90)`) against `unpack_packet(color_grid_to_bytes(grid, layout))` so frames held upright, sideways, or upside-down decode seamlessly.
   - Support auto-density sweeping if grid size is not manually locked.
3. Test your implementation using `/home/henry/Documents/Projects/Python/venv/bin/python -m unittest discover -s tests -v`.
4. Ensure all existing and newly added unit tests pass 100%.

Rules:
- Python environment: strictly use `/home/henry/Documents/Projects/Python/venv/bin/python`. Never create local `.venv`.
- Safe file deletion: never use `rm` or `rm -rf`, move files to `/home/henry/Documents/Projects/OpenCode/tmp/Trash`.
- Write your completion findings and test execution results to `/home/henry/Documents/Projects/Python/QR ChromaBeam/.agents/teamwork_preview_worker_m2/handoff.md`.
- Send a completion message to parent when done with the path to your handoff.md.
