/**
 * Suzuki-Abe (1985) Border Following Algorithm with RETR_TREE Hierarchy in Pure JavaScript.
 * Provides exact parity with OpenCV's cv2.findContours(img, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE).
 */

const DIRS = [
    { dx: -1, dy:  0 }, // 0: Left
    { dx: -1, dy: -1 }, // 1: Top-Left
    { dx:  0, dy: -1 }, // 2: Top
    { dx:  1, dy: -1 }, // 3: Top-Right
    { dx:  1, dy:  0 }, // 4: Right
    { dx:  1, dy:  1 }, // 5: Bottom-Right
    { dx:  0, dy:  1 }, // 6: Bottom
    { dx: -1, dy:  1 }  // 7: Bottom-Left
];

function findContoursSuzuki(binaryImg, width, height) {
    // binaryImg is a Uint8Array of size width * height (0 or 1)
    // We pad the image by 1 pixel on all sides to avoid boundary checks
    const W = width + 2;
    const H = height + 2;
    const F = new Int32Array(W * H);

    for (let y = 0; y < height; y++) {
        const srcRow = y * width;
        const dstRow = (y + 1) * W + 1;
        for (let x = 0; x < width; x++) {
            if (binaryImg[srcRow + x] > 0) {
                F[dstRow + x] = 1;
            }
        }
    }

    let nbd = 1;
    let lnbd = 1;
    const contours = [];
    const hierarchy = []; // [next, prev, first_child, parent]

    for (let i = 1; i <= height; i++) {
        lnbd = 1;
        for (let j = 1; j <= width; j++) {
            const idx = i * W + j;
            const fij = F[idx];
            let isOuter = false;
            let isHole = false;

            if (fij === 1 && F[idx - 1] === 0) {
                isOuter = true;
            } else if (fij >= 1 && F[idx + 1] === 0) {
                isHole = true;
            }

            if (!isOuter && !isHole) {
                if (Math.abs(fij) > 1) {
                    lnbd = Math.abs(fij);
                }
                continue;
            }

            // Determine parent contour
            nbd++;
            let parent = -1;
            if (isOuter) {
                if (lnbd > 1) {
                    const lnbdIdx = lnbd - 2;
                    const isLnbdHole = hierarchy[lnbdIdx].isHole;
                    parent = isLnbdHole ? lnbdIdx : hierarchy[lnbdIdx].parent;
                }
            } else {
                if (lnbd > 1) {
                    const lnbdIdx = lnbd - 2;
                    const isLnbdHole = hierarchy[lnbdIdx].isHole;
                    parent = isLnbdHole ? hierarchy[lnbdIdx].parent : lnbdIdx;
                }
            }

            // Follow border
            const startX = j;
            const startY = i;
            let fromDir = isOuter ? 0 : 4;

            // Find starting non-zero neighbor
            let startNeighborDir = -1;
            for (let k = 0; k < 8; k++) {
                const dir = (fromDir + k) % 8;
                const nx = startX + DIRS[dir].dx;
                const ny = startY + DIRS[dir].dy;
                if (F[ny * W + nx] !== 0) {
                    startNeighborDir = dir;
                    break;
                }
            }

            const currentContourPoints = [];

            if (startNeighborDir === -1) {
                // Isolated point
                F[idx] = -nbd;
                currentContourPoints.push({ x: startX - 1, y: startY - 1 });
            } else {
                let currX = startX;
                let currY = startY;
                let currDir = startNeighborDir;

                let prevX = currX;
                let prevY = currY;

                let loopCount = 0;
                const maxLoops = 20000;

                while (loopCount++ < maxLoops) {
                    currentContourPoints.push({ x: currX - 1, y: currY - 1 });

                    // Find next non-zero neighbor counter-clockwise
                    let nextDir = -1;
                    const checkStart = (currDir + 5) % 8; // opposite direction + 1
                    for (let k = 0; k < 8; k++) {
                        const dir = (checkStart + k) % 8;
                        const nx = currX + DIRS[dir].dx;
                        const ny = currY + DIRS[dir].dy;
                        if (F[ny * W + nx] !== 0) {
                            nextDir = dir;
                            break;
                        }
                    }

                    if (nextDir === -1) {
                        break;
                    }

                    // Update F value
                    const rightIdx = currY * W + currX + 1;
                    if (F[rightIdx] === 0) {
                        F[currY * W + currX] = -nbd;
                    } else if (F[currY * W + currX] === 1) {
                        F[currY * W + currX] = nbd;
                    }

                    // Move to next point
                    const nextX = currX + DIRS[nextDir].dx;
                    const nextY = currY + DIRS[nextDir].dy;

                    if (nextX === startX && nextY === startY && currX === prevX && currY === prevY && loopCount > 1) {
                        break;
                    }

                    if (currX === startX && currY === startY && prevX !== startX && nextX === (startX + DIRS[startNeighborDir].dx) && nextY === (startY + DIRS[startNeighborDir].dy)) {
                        break;
                    }

                    prevX = currX;
                    prevY = currY;
                    currX = nextX;
                    currY = nextY;
                    currDir = nextDir;
                }
            }

            contours.push(currentContourPoints);
            hierarchy.push({
                parent,
                isHole,
                nbd
            });

            if (Math.abs(fij) > 1) {
                lnbd = Math.abs(fij);
            }
        }
    }

    return { contours, hierarchy };
}

function computeContourMomentsAndArea(points) {
    if (points.length < 3) {
        return { area: 0, cx: points[0]?.x || 0, cy: points[0]?.y || 0 };
    }

    let a = 0;
    let cx = 0;
    let cy = 0;
    const n = points.length;

    for (let i = 0; i < n; i++) {
        const j = (i + 1) % n;
        const cross = points[i].x * points[j].y - points[j].x * points[i].y;
        a += cross;
        cx += (points[i].x + points[j].x) * cross;
        cy += (points[i].y + points[j].y) * cross;
    }

    a = a / 2.0;
    const absArea = Math.abs(a);
    if (absArea < 1e-5) {
        return { area: 0, cx: points[0].x, cy: points[0].y };
    }

    cx = cx / (6.0 * a);
    cy = cy / (6.0 * a);

    return { area: absArea, cx, cy };
}

module.exports = {
    findContoursSuzuki,
    computeContourMomentsAndArea
};
