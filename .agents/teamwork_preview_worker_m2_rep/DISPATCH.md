## 2026-08-14T14:41:06Z
You are Worker 2 (Replacement) for Milestone 2 (M2: Python CV Tracker & 4-Way Homography) of ChromaBeam.

Working Directory: /home/henry/Documents/Projects/Python/QR ChromaBeam/.agents/teamwork_preview_worker_m2_rep
Original User Request: /home/henry/Documents/Projects/Python/QR ChromaBeam/.agents/ORIGINAL_REQUEST.md
Project Plan: /home/henry/Documents/Projects/Python/QR ChromaBeam/PROJECT.md
File Ownership: You exclusively own `desktop_receiver/tracker.py`, `desktop_receiver/receiver_gui.py`, and `desktop_app.py`.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

CRITICAL INSTRUCTION:
Ensure all loops in tracker, receiver, and test functions have explicit finite bounds and timeout guards. Never block on camera capture or `cv2.waitKey(0)`.

Your Mission:
1. In `desktop_receiver/tracker.py`:
   - Replace simplistic `cv2.RETR_EXTERNAL` with `cv2.RETR_TREE` hierarchical contour detection.
   - Match $1:1:1:1:1$ concentric finder pattern anchors using nested contour parent/child hierarchy, centroid distance $\Delta < 2.5\text{ px}$, and area ratio $\frac{\text{Area}(\text{Core})}{\text{Area}(\text{Ring})} \in [0.035, 0.160]$.
   - Filter and isolate the 4 anchor centroids from surrounding desktop UI text, taskbars, and reflections.
   - Order the 4 anchors into canonical order (Top-Left, Top-Right, Bottom-Right, Bottom-Left).
   - Compute the 3D projective homography matrix ($H$) mapping the 4 detected anchor centers directly to their canonical coordinates $(\frac{2.5}{N}, \frac{2.5}{N})$ from `layout.anchor_centers`.
   - Warp the camera frame into a normalized top-down canonical matrix grid.
2. In `desktop_receiver/receiver_gui.py` and `desktop_app.py`:
   - Implement 360° 4-way rotation invariance ($0^\circ, 90^\circ, 180^\circ, 270^\circ$) by testing all 4 orientations (`np.rot90(grid, k=-rot//90)`) against `unpack_packet(color_grid_to_bytes(grid, layout))` so frames held upright, sideways, or upside-down decode seamlessly.
   - Support auto-density sweeping across candidate configs (32x32 Potato, 48x48 Balanced, 64x64 Turbo) when receiver is searching.
3. Test your implementation using `/home/henry/Documents/Projects/Python/venv/bin/python -m unittest discover -s tests -v`. Ensure tests execute quickly without hanging.
4. Ensure all unit tests pass 100%.
