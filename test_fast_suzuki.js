const fs = require('fs');
const { findContoursSuzuki, computeContourMomentsAndArea } = require('./web/suzuki_contours.js');

const rawBuf = fs.readFileSync('tests/real_phone_screenshot.raw');
const origW = 501;
const origH = 1024;

// 1. Fast downsample by 2x for quad detection: (250 x 512)
const scale = 2;
const w = Math.floor(origW / scale);
const h = Math.floor(origH / scale);

const t0 = performance.now();

const gray = new Uint8Array(w * h);
for (let y = 0; y < h; y++) {
    const srcY = y * scale;
    for (let x = 0; x < w; x++) {
        const srcX = x * scale;
        const idx = (srcY * origW + srcX) * 4;
        gray[y * w + x] = Math.round(0.299 * rawBuf[idx] + 0.587 * rawBuf[idx + 1] + 0.114 * rawBuf[idx + 2]);
    }
}

// 2. Fast Block-Otsu / Multi-Otsu
// Global Otsu
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

// Fast binary images
const binNormal = new Uint8Array(w * h);
const binInv = new Uint8Array(w * h);
const binHigh = new Uint8Array(w * h);
const binLow = new Uint8Array(w * h);

const highT = Math.min(240, otsuThresh + 20);
const lowT = Math.max(15, otsuThresh - 20);

for (let i = 0; i < gray.length; i++) {
    const g = gray[i];
    binNormal[i] = g > otsuThresh ? 1 : 0;
    binInv[i] = g > otsuThresh ? 0 : 1;
    binHigh[i] = g > highT ? 1 : 0;
    binLow[i] = g > lowT ? 1 : 0;
}

const rawCandidates = [];

for (const binImg of [binNormal, binInv, binHigh, binLow]) {
    const { contours, hierarchy } = findContoursSuzuki(binImg, w, h);

    for (let i = 0; i < contours.length; i++) {
        const parentIdx = hierarchy[i].parent;
        if (parentIdx < 0 || parentIdx >= contours.length) continue;

        const grandParentIdx = hierarchy[parentIdx].parent;

        for (const ringIdx of [parentIdx, grandParentIdx]) {
            if (ringIdx < 0 || ringIdx >= contours.length) continue;

            const coreMom = computeContourMomentsAndArea(contours[i]);
            const ringMom = computeContourMomentsAndArea(contours[ringIdx]);

            if (coreMom.area < 1.0 || ringMom.area < 4.0 || ringMom.area > (w * h * 0.10)) continue;

            const ratio = coreMom.area / ringMom.area;
            if (ratio < 0.025 || ratio > 0.200) continue;

            const delta = Math.hypot(coreMom.cx - ringMom.cx, coreMom.cy - ringMom.cy);
            if (delta >= 2.5) continue;

            // Scale coordinates back to original image space
            rawCandidates.push({
                cx: coreMom.cx * scale,
                cy: coreMom.cy * scale,
                area: ringMom.area * scale * scale
            });
        }
    }
}

// Cluster candidates
const clusters = [];
for (const cand of rawCandidates) {
    let matched = false;
    for (const cl of clusters) {
        if (Math.hypot(cand.cx - cl.cx, cand.cy - cl.cy) < 10.0) {
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

clusters.sort((a, b) => b.count - a.count);

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
    const N = Math.min(pts.length, 8);
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

                    if (minSide < 40) continue;
                    if (maxSide / minSide > 2.2) continue;

                    const diag1 = Math.hypot(ordered[0].x - ordered[2].x, ordered[0].y - ordered[2].y);
                    const diag2 = Math.hypot(ordered[1].x - ordered[3].x, ordered[1].y - ordered[3].y);
                    if (Math.abs(diag1 - diag2) / Math.max(diag1, diag2) > 0.35) continue;

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
const elapsed = (performance.now() - t0).toFixed(1);

console.log(`⏱️ Total Processing Time: ${elapsed} ms`);
console.log(`Found ${clusters.length} unique anchor clusters:`);
clusters.slice(0, 6).forEach((c, idx) => {
    console.log(`  Cluster ${idx+1}: (${c.cx.toFixed(1)}, ${c.cy.toFixed(1)}), votes=${c.count}`);
});

if (foundQuad) {
    console.log("✅ SUCCESS! 4-Corner Quad Found by JavaScript on Real Phone Screenshot:");
    foundQuad.forEach((pt, i) => console.log(`  Corner ${i} (${['TL','TR','BR','BL'][i]}): (${pt.x.toFixed(1)}, ${pt.y.toFixed(1)})`));
} else {
    console.log("❌ No valid quad formed.");
}
