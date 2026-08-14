import cv2

img = cv2.imread('tests/real_phone_screenshot.png')
# Draw circles at the Python detected quad
pts = [(50, 407), (403, 464), (324, 919), (86, 731)]

for p in pts:
    cv2.circle(img, p, 10, (0, 255, 0), -1)

cv2.imwrite('tests/debug_detected_corners.png', img)
print("Saved tests/debug_detected_corners.png")
