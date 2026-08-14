const fs = require('fs');

const rawBuf = fs.readFileSync('tests/real_phone_screenshot.raw');
const width = 501;
const height = 1024;

const gray = new Uint8Array(width * height);
for (let i = 0; i < width * height; i++) {
    const r = rawBuf[i * 4];
    const g = rawBuf[i * 4 + 1];
    const b = rawBuf[i * 4 + 2];
    gray[i] = (r * 77 + g * 150 + b * 29) >> 8;
}

// Global Otsu
const hist = new Int32Array(256);
for (let i = 0; i < gray.length; i += 4) hist[gray[i]]++;
let sumTotal = 0;
for (let i = 0; i < 256; i++) sumTotal += i * hist[i];
let sumBg = 0, weightBg = 0, maxVar = 0, threshold = 128;
const totalCount = gray.length >> 2;

for (let t = 0; t < 256; t++) {
    weightBg += hist[t];
    if (weightBg === 0) continue;
    const weightFg = totalCount - weightBg;
    if (weightFg === 0) break;
    sumBg += t * hist[t];
    const meanBg = sumBg / weightBg;
    const meanFg = (sumTotal - sumBg) / weightFg;
    const variance = weightBg * weightFg * (meanBg - meanFg) * (meanBg - meanFg);
    if (variance > maxVar) {
        maxVar = variance;
        threshold = t;
    }
}

console.log(`Global threshold: ${threshold}`);

// 2D Template Verifier
// Checks if the 2D window around (cx, cy) of size `cellSize * 5` has:
// - Outer border (ring radius ~2 * cellSize): mostly WHITE
// - Inner ring (ring radius ~1 * cellSize): mostly BLACK
// - Center (radius ~0): WHITE
function verify2DAnchorTemplate(cx, cy, totalSize, T) {
    const cellSize = totalSize / 5.0;
    if (cellSize < 2.0) return false;

    // Check center (0, 0)
    const centerLuma = gray[Math.round(cy) * width + Math.round(cx)];
    if (centerLuma < T) return false; // Center MUST be white

    // Check 8 points on inner ring (radius = 1.0 * cellSize)
    let innerBlackCount = 0;
    const innerOffsets = [
        [-1, -1], [0, -1], [1, -1],
        [-1,  0],          [1,  0],
        [-1,  1], [0,  1], [1,  1]
    ];
    for (const [ox, oy] of innerOffsets) {
        const px = Math.round(cx + ox * cellSize);
        const py = Math.round(cy + oy * cellSize);
        if (px >= 0 && px < width && py >= 0 && py < height) {
            if (gray[py * width + px] <= T) innerBlackCount++;
        }
    }
    if (innerBlackCount < 6) return false; // At least 6 of 8 must be black

    // Check 16 points on outer ring (radius = 2.0 * cellSize)
    let outerWhiteCount = 0;
    const outerOffsets = [
        [-2, -2], [-1, -2], [0, -2], [1, -2], [2, -2],
        [-2, -1],                             [2, -1],
        [-2,  0],                             [2,  0],
        [-2,  1],                             [2,  1],
        [-2,  2], [-1,  2], [0,  2], [1,  2], [2,  2]
    ];
    for (const [ox, oy] of outerOffsets) {
        const px = Math.round(cx + ox * cellSize);
        const py = Math.round(cy + oy * cellSize);
        if (px >= 0 && px < width && py >= 0 && py < height) {
            if (gray[py * width + px] > T) outerWhiteCount++;
        }
    }
    if (outerWhiteCount < 10) return false; // At least 10 of 16 must be white

    return true;
}

// Find candidate anchors using 1D scanline + 2D Template Verification
const verifiedAnchors = [];
const stepY = 3;

for (let y = 15; y < height - 15; y += stepY) {
    let stateCount = [0, 0, 0, 0, 0];
    let currentState = 0;
    let lastColor = (gray[y * width + 10] > threshold) ? 1 : 0;

    for (let x = 10; x < width - 10; x++) {
        const color = (gray[y * width + x] > threshold) ? 1 : 0;
        if (color === lastColor) {
            stateCount[currentState]++;
        } else {
            if (currentState < 4) {
                currentState++;
                stateCount[currentState] = 1;
            } else {
                const total = stateCount[0] + stateCount[1] + stateCount[2] + stateCount[3] + stateCount[4];
                const avg = total / 5.0;
                let ratioOk = true;
                for (let i = 0; i < 5; i++) {
                    if (Math.abs(stateCount[i] - avg) > avg * 0.85 || stateCount[i] === 0) {
                        ratioOk = false;
                        break;
                    }
                }

                if (ratioOk && total >= 10 && total <= width * 0.40) {
                    const centerX = x - stateCount[4] - stateCount[3] - Math.floor(stateCount[2] / 2);
                    
                    // Verify with 2D Anchor Template!
                    if (verify2DAnchorTemplate(centerX, y, total, threshold)) {
                        verifiedAnchors.push({ x: centerX, y, size: total });
                    }
                }

                stateCount[0] = stateCount[2];
                stateCount[1] = stateCount[3];
                stateCount[2] = stateCount[4];
                stateCount[3] = 1;
                stateCount[4] = 0;
                currentState = 3;
            }
            lastColor = color;
        }
    }
}

console.log(`Found ${verifiedAnchors.length} 2D-verified anchor candidates!`);

// Cluster
const clusters = [];
for (const cand of verifiedAnchors) {
    let matched = false;
    for (const cl of clusters) {
        if (Math.hypot(cand.x - cl.x, cand.y - cl.y) < 15.0) {
            cl.x = (cl.x * cl.count + cand.x) / (cl.count + 1);
            cl.y = (cl.y * cl.count + cand.y) / (cl.count + 1);
            cl.size = (cl.size * cl.count + cand.size) / (cl.count + 1);
            cl.count++;
            matched = true;
            break;
        }
    }
    if (!matched) {
        clusters.push({ x: cand.x, y: cand.y, size: cand.size, count: 1 });
    }
}

console.log(`Clustered into ${clusters.length} unique 2D anchors:`);
clusters.forEach((c, i) => {
    console.log(`  Anchor ${i+1}: (${c.x.toFixed(1)}, ${c.y.toFixed(1)}), size=${c.size.toFixed(1)}px, votes=${c.count}`);
});
