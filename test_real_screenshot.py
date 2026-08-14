#!/usr/bin/env python3
"""
Test finding the ChromaBeam matrix directly on Henny's real phone screenshot!
"""
import sys, os
import cv2
import numpy as np

screenshot_path = "/home/henry/.gemini/antigravity/brain/30e7d299-434e-4b52-8e68-be03941a5dab/.user_uploaded/media_1786713734549.jpg"

if not os.path.exists(screenshot_path):
    print(f"Screenshot not found at {screenshot_path}")
    sys.exit(1)

img = cv2.imread(screenshot_path)
h, w = img.shape[:2]
print(f"Loaded real phone screenshot: {w}x{h}")

# The phone screenshot has the camera viewfinder in the upper half.
# Let's crop out just the camera viewfinder region.
# In the screenshot, the viewfinder is around y in [50, 450]
cv2.imwrite("tests/real_phone_screenshot.png", img)

# Let's run tracker.py on this screenshot
sys.path.insert(0, os.path.abspath("."))
from desktop_receiver.tracker import OpticalTracker, find_nested_anchor_centers

tracker = OpticalTracker()
centers = find_nested_anchor_centers(img)
print(f"find_nested_anchor_centers on real phone screenshot found: {len(centers)} candidates")
for c in centers:
    print(f"  Center: ({c[0]:.1f}, {c[1]:.1f}), area={c[2]:.1f}")

quad = tracker.find_matrix_quad(img)
if quad is not None:
    print(f"✅ find_matrix_quad SUCCESS! Quad corners:")
    for pt in quad:
        print(f"  ({pt[0]:.1f}, {pt[1]:.1f})")
else:
    print(f"❌ find_matrix_quad returned None on real screenshot.")
