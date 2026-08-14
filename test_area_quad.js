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

// 2. Global Otsu
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

const thresholdsToTry = [threshold, Math.max(20, threshold - 25), Math.min(235, threshold + 25)];
const allCandidates = [];

for (const T of thresholdsToTry) {
    const stepY = 3;
    for (let y = 10; y < height - 10; y += stepY) {
        let stateCount = [0, 0, 0, 0, 0];
        let currentState = 0;
        let lastColor = (gray[y * width + 10] > T) ? 1 : 0;

        for (let x = 10; x < width - 10; x++) {
            const color = (gray[y * width + x] > T) ? 1 : 0;
            if (color === lastColor) {
                stateCount[currentState]++;
            } else {
                if (currentState < 4) {
                    currentState++;
                    stateCount[currentState] = 1;
                } else {
                    if (checkRatio(stateCount)) {
                        const totalW = stateCount[0] + stateCount[1] + stateCount[2] + stateCount[3] + stateCount[4];
                        const centerX = x - stateCount[4] - stateCount[3] - Math.floor(stateCount[2] / 2);

                        const vertRes = checkVertical(centerX, y, T, totalW);
                        if (vertRes) {
                            allCandidates.push({
                                x: centerX,
                                y: vertRes.centerY,
                                size: (totalW + vertRes.totalH) / 2
                            });
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
}

function checkRatio(counts) {
    const total = counts[0] + counts[1] + counts[2] + counts[3] + counts[4];
    if (total < 8 || total > width * 0.45) return false;
    const avg = total / 5.0;
    const maxVar = avg * 0.90;
    for (let i = 0; i < 5; i++) {
        if (Math.abs(counts[i] - avg) > maxVar || counts[i] === 0) return false;
    }
    return true;
}

function checkVertical(cx, startY, T, expectedW) {
    const span = Math.min(height - 1 - startY, startY, Math.floor(expectedW * 1.6));
    if (span < 6) return null;

    let stateCount = [0, 0, 0, 0, 0];
    const topY = Math.max(0, startY - span);
    const botY = Math.min(height - 1, startY + span);

    let currentState = 0;
    let lastColor = (gray[topY * width + cx] > T) ? 1 : 0;

    for (let y = topY; y <= botY; y++) {
        const color = (gray[y * width + cx] > T) ? 1 : 0;
        if (color === lastColor) {
            stateCount[currentState]++;
        } else {
            if (currentState < 4) {
                currentState++;
                stateCount[currentState] = 1;
            } else {
                if (checkRatio(stateCount)) {
                    const totalH = stateCount[0] + stateCount[1] + stateCount[2] + stateCount[3] + stateCount[4];
                    if (Math.abs(totalH - expectedW) / Math.max(totalH, expectedW) < 0.70) {
                        const centerY = y - stateCount[4] - stateCount[3] - Math.floor(stateCount[2] / 2);
                        if (Math.abs(centerY - startY) < expectedW * 0.7) {
                            return { centerY, totalH };
                        }
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
    return null;
}

// Cluster candidates
const clusters = [];
for (const cand of allCandidates) {
    let matched = false;
    for (const cl of clusters) {
        if (Math.hypot(cand.x - cl.x, cand.y - cl.y) < 16.0) {
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

clusters.sort((a, b) => b.count - a.count);

function orderQuadPointsClockwise(pts) {
    const cx = (pts[0].x + pts[1].x + pts[2].x + pts[3].x) / 4;
    const cy = (pts[0].y + pts[1].y + pts[2].y + pts[3].y) / 4;

    const sorted = pts.slice().sort((a, b) => {
        return Math.atan2(a.y - cy, a.x - cx) - Math.atan2(b.y - cy, b.x - cx);
    });

    let tlIdx = 0, minSum = Infinity;
    for (let i = 0; i < 4; i++) {
        const s = sorted[i].x + sorted[i].y;
        if (s < minSum) { minSum = s; tlIdx = i; }
    }

    return [
        sorted[tlIdx],
        sorted[(tlIdx + 1) % 4],
        sorted[(tlIdx + 2) % 4],
        sorted[(tlIdx + 3) % 4]
    ];
}

function findBestAnchorQuad(clusters, imgW, imgH) {
    if (clusters.length < 4) return null;
    const minQuadArea = (imgW * imgH) * 0.01; // At least 1% of frame
    const N = Math.min(clusters.length, 16);
    let bestQuad = null;
    let bestScore = -1.0;

    for (let i = 0; i < N; i++) {
        for (let j = i + 1; j < N; j++) {
            for (let k = j + 1; k < N; k++) {
                for (let l = k + 1; l < N; l++) {
                    const combo = [
                        { x: clusters[i].x, y: clusters[i].y, size: clusters[i].size },
                        { x: clusters[j].x, y: clusters[j].y, size: clusters[j].size },
                        { x: clusters[k].x, y: clusters[k].y, size: clusters[k].size },
                        { x: clusters[l].x, y: clusters[l].y, size: clusters[l].size }
                    ];

                    const ordered = orderQuadPointsClockwise(combo);

                    // 1. Calculate Quad Area (Shoelace formula)
                    const area = 0.5 * Math.abs(
                        (ordered[0].x * ordered[1].y - ordered[1].x * ordered[0].y) +
                        (ordered[1].x * ordered[2].y - ordered[2].x * ordered[1].y) +
                        (ordered[2].x * ordered[3].y - ordered[3].x * ordered[2].y) +
                        (ordered[3].x * ordered[0].y - ordered[0].x * ordered[3].y)
                    );

                    if (area < minQuadArea) continue;

                    // 2. Check side lengths
                    const d0 = Math.hypot(ordered[0].x - ordered[1].x, ordered[0].y - ordered[1].y);
                    const d1 = Math.hypot(ordered[1].x - ordered[2].x, ordered[1].y - ordered[2].y);
                    const d2 = Math.hypot(ordered[2].x - ordered[3].x, ordered[2].y - ordered[3].y);
                    const d3 = Math.hypot(ordered[3].x - ordered[0].x, ordered[3].y - ordered[0].y);

                    const sides = [d0, d1, d2, d3];
                    const sMin = Math.min(...sides);
                    const sMax = Math.max(...sides);
                    if (sMax === 0 || (sMin / sMax) < 0.25) continue;

                    // 3. Check diagonals
                    const diag1 = Math.hypot(ordered[0].x - ordered[2].x, ordered[0].y - ordered[2].y);
                    const diag2 = Math.hypot(ordered[1].x - ordered[3].x, ordered[1].y - ordered[3].y);
                    const dMin = Math.min(diag1, diag2);
                    const dMax = Math.max(diag1, diag2);
                    if (dMax === 0 || (dMin / dMax) < 0.35) continue;

                    // 4. Check anchor size uniformity
                    const sizes = [combo[0].size, combo[1].size, combo[2].size, combo[3].size];
                    const szMin = Math.min(...sizes);
                    const szMax = Math.max(...sizes);
                    if (szMax === 0 || (szMin / szMax) < 0.15) continue;

                    // 5. Score = Area * side_regularity * diag_regularity * size_uniformity
                    const score = area * (sMin / sMax) * (dMin / dMax) * Math.sqrt(szMin / szMax);

                    if (score > bestScore) {
                        bestScore = score;
                        bestQuad = ordered;
                    }
                }
            }
        }
    }
    return bestQuad;
}

const foundQuad = findBestAnchorQuad(clusters, width, height);

if (foundQuad) {
    console.log("✅ SUCCESS! Area-Weighted 4-Corner Quad Found:");
    foundQuad.forEach((pt, i) => console.log(`  Corner ${i} (${['TL','TR','BR','BL'][i]}): (${pt.x.toFixed(1)}, ${pt.y.toFixed(1)})`));
    const area = 0.5 * Math.abs(
        (foundQuad[0].x * foundQuad[1].y - foundQuad[1].x * foundQuad[0].y) +
        (foundQuad[1].x * foundQuad[2].y - foundQuad[2].x * foundQuad[1].y) +
        (foundQuad[2].x * foundQuad[3].y - foundQuad[3].x * foundQuad[2].y) +
        (foundQuad[3].x * foundQuad[0].y - foundQuad[0].x * foundQuad[3].y)
    );
    console.log(`  Quad Area: ${area.toFixed(0)} px² (${(area / (width * height) * 100).toFixed(1)}% of frame)`);
} else {
    console.log("❌ No valid quad formed.");
}
