const fs = require('fs');
const { findContoursSuzuki, computeContourMomentsAndArea } = require('./web/suzuki_contours.js');

const rawBuf = fs.readFileSync('tests/real_phone_screenshot.raw');
const width = 501;
const height = 1024;

// Compute grayscale
const gray = new Uint8Array(width * height);
for (let i = 0; i < width * height; i++) {
    const r = rawBuf[i * 4];
    const g = rawBuf[i * 4 + 1];
    const b = rawBuf[i * 4 + 2];
    gray[i] = Math.round(0.299 * r + 0.587 * g + 0.114 * b);
}

// Compute Otsu threshold
const hist = new Uint32Array(256);
for (let i = 0; i < gray.length; i++) hist[gray[i]]++;
let sumTotal = 0;
for (let i = 0; i < 256; i++) sumTotal += i * hist[i];
let sumBg = 0, weightBg = 0, maxVar = 0, otsuThresh = 128;
for (let t = 0; t < 256; t++) {
    weightBg += hist[t];
    if (weightBg === 0) continue;
    const weightFg = gray.length - weightBg;
    if (weightFg === 0) break;
    sumBg += t * hist[t];
    const meanBg = sumBg / weightBg;
    const meanFg = (sumTotal - sumBg) / weightFg;
    const variance = weightBg * weightFg * (meanBg - meanFg) ** 2;
    if (variance > maxVar) {
        maxVar = variance;
        otsuThresh = t;
    }
}

// Adaptive local threshold (Block Otsu / Local mean)
function localAdaptiveThreshold(gray, w, h, blockSize = 31, C = 4) {
    const out = new Uint8Array(w * h);
    const half = Math.floor(blockSize / 2);

    // Integral image for O(1) box sum
    const integral = new Float64Array((w + 1) * (h + 1));
    for (let y = 0; y < h; y++) {
        let rowSum = 0;
        for (let x = 0; x < w; x++) {
            rowSum += gray[y * w + x];
            integral[(y + 1) * (w + 1) + (x + 1)] = integral[y * (w + 1) + (x + 1)] + rowSum;
        }
    }

    for (let y = 0; y < h; y++) {
        const y0 = Math.max(0, y - half);
        const y1 = Math.min(h, y + half + 1);
        for (let x = 0; x < w; x++) {
            const x0 = Math.max(0, x - half);
            const x1 = Math.min(w, x + half + 1);
            const count = (x1 - x0) * (y1 - y0);
            const sum = integral[y1 * (w + 1) + x1] - integral[y0 * (w + 1) + x1] - integral[y1 * (w + 1) + x0] + integral[y0 * (w + 1) + x0];
            const mean = sum / count;
            out[y * w + x] = gray[y * w + x] > (mean - C) ? 1 : 0;
        }
    }
    return out;
}

const binAdaptive = localAdaptiveThreshold(gray, width, height, 31, 3);
const binAdaptiveInv = new Uint8Array(width * height);
for (let i = 0; i < width * height; i++) binAdaptiveInv[i] = binAdaptive[i] ? 0 : 1;

const binOtsu = new Uint8Array(width * height);
const binOtsuInv = new Uint8Array(width * height);
for (let i = 0; i < width * height; i++) {
    binOtsu[i] = gray[i] > otsuThresh ? 1 : 0;
    binOtsuInv[i] = gray[i] > otsuThresh ? 0 : 1;
}

const passes = [
    ['Adaptive', binAdaptive],
    ['AdaptiveInv', binAdaptiveInv],
    ['Otsu', binOtsu],
    ['OtsuInv', binOtsuInv]
];

const rawCandidates = [];

for (const [passName, binImg] of passes) {
    const { contours, hierarchy } = findContoursSuzuki(binImg, width, height);

    for (let i = 0; i < contours.length; i++) {
        const parentIdx = hierarchy[i].parent;
        if (parentIdx < 0 || parentIdx >= contours.length) continue;

        const grandParentIdx = hierarchy[parentIdx].parent;

        for (const ringIdx of [parentIdx, grandParentIdx]) {
            if (ringIdx < 0 || ringIdx >= contours.length) continue;

            const coreMom = computeContourMomentsAndArea(contours[i]);
            const ringMom = computeContourMomentsAndArea(contours[ringIdx]);

            // Area constraints for reasonable anchor size
            if (coreMom.area < 2.0 || ringMom.area < 15.0 || ringMom.area > (width * height * 0.05)) continue;

            const ratio = coreMom.area / ringMom.area;
            if (ratio < 0.030 || ratio > 0.180) continue;

            const delta = Math.hypot(coreMom.cx - ringMom.cx, coreMom.cy - ringMom.cy);
            if (delta >= 3.5) continue;

            rawCandidates.push({
                cx: coreMom.cx,
                cy: coreMom.cy,
                area: ringMom.area
            });
        }
    }
}

// Cluster candidates across passes
const clusters = [];
for (const cand of rawCandidates) {
    let matched = false;
    for (const cl of clusters) {
        if (Math.hypot(cand.cx - cl.cx, cand.cy - cl.cy) < 6.0) {
            cl.cx = (cl.cx * cl.count + cand.cx) / (cl.count + 1);
            cl.cy = (cl.cy * cl.count + cand.cy) / (cl.count + 1);
            cl.area = (cl.area * cl.count + cand.area) / (cl.count + 1);
            cl.count++;
            matched = true;
            break;
        }
    }
    if (!matched) {
        clusters.push({ cx: cand.cx, cy: cand.cy, area: cand.area, count: 1 });
    }
}

// Sort by cluster count (most confident)
clusters.sort((a, b) => b.count - a.count);
console.log(`Found ${clusters.length} unique anchor clusters after clustering!`);
clusters.slice(0, 10).forEach((c, idx) => {
    console.log(`  Cluster ${idx+1}: (${c.cx.toFixed(1)}, ${c.cy.toFixed(1)}), area=${c.area.toFixed(1)}, votes=${c.count}`);
});

// Quad search among candidates
function orderQuad(pts) {
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

function findBestQuad(pts) {
    if (pts.length < 4) return null;
    const N = Math.min(pts.length, 12);
    let bestQuad = null;
    let bestScore = -Infinity;

    for (let i = 0; i < N; i++) {
        for (let j = i + 1; j < N; j++) {
            for (let k = j + 1; k < N; k++) {
                for (let l = k + 1; l < N; l++) {
                    const combo = [
                        { x: pts[i].cx, y: pts[i].cy },
                        { x: pts[j].cx, y: pts[j].cy },
                        { x: pts[k].cx, y: pts[k].cy },
                        { x: pts[l].cx, y: pts[l].cy }
                    ];

                    const ordered = orderQuad(combo);
                    const d01 = Math.hypot(ordered[0].x - ordered[1].x, ordered[0].y - ordered[1].y);
                    const d12 = Math.hypot(ordered[1].x - ordered[2].x, ordered[1].y - ordered[2].y);
                    const d23 = Math.hypot(ordered[2].x - ordered[3].x, ordered[2].y - ordered[3].y);
                    const d30 = Math.hypot(ordered[3].x - ordered[0].x, ordered[3].y - ordered[0].y);

                    const minSide = Math.min(d01, d12, d23, d30);
                    const maxSide = Math.max(d01, d12, d23, d30);

                    if (minSide < 30) continue;
                    if (maxSide / minSide > 2.5) continue; // Aspect ratio check

                    // Diagonal check
                    const diag1 = Math.hypot(ordered[0].x - ordered[2].x, ordered[0].y - ordered[2].y);
                    const diag2 = Math.hypot(ordered[1].x - ordered[3].x, ordered[1].y - ordered[3].y);
                    if (Math.abs(diag1 - diag2) / Math.max(diag1, diag2) > 0.40) continue;

                    const score = (pts[i].count + pts[j].count + pts[k].count + pts[l].count) * 10.0 - (maxSide / minSide);
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

const foundQuad = findBestQuad(clusters);
if (foundQuad) {
    console.log("✅ SUCCESS! 4-Corner Quad Found by JavaScript on Real Phone Screenshot:");
    foundQuad.forEach((pt, i) => console.log(`  Corner ${i} (${['TL','TR','BR','BL'][i]}): (${pt.x.toFixed(1)}, ${pt.y.toFixed(1)})`));
} else {
    console.log("❌ No valid quad formed.");
}
