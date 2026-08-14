const fs = require('fs');

const rawBuf = fs.readFileSync('tests/real_phone_screenshot.raw');
const width = 501;
const height = 1024;

const t0 = performance.now();

// 1. Grayscale
const gray = new Uint8Array(width * height);
for (let i = 0; i < width * height; i++) {
    const idx = i * 4;
    gray[i] = (rawBuf[idx] * 77 + rawBuf[idx + 1] * 150 + rawBuf[idx + 2] * 29) >> 8;
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

// 3. Fast Flat-Array Connected Component Labeling (Union-Find)
function findNestedBlobs(gray, w, h, T) {
    const labels = new Int32Array(w * h);
    const parent = new Int32Array(10000);
    const m00 = new Float64Array(10000);
    const m10 = new Float64Array(10000);
    const m01 = new Float64Array(10000);
    const color = new Uint8Array(10000);
    let nextLabel = 1;

    function find(i) {
        let root = i;
        while (parent[root] !== root) root = parent[root];
        let curr = i;
        while (curr !== root) {
            let nxt = parent[curr];
            parent[curr] = root;
            curr = nxt;
        }
        return root;
    }

    function union(i, j) {
        const rootI = find(i);
        const rootJ = find(j);
        if (rootI !== rootJ) {
            parent[rootJ] = rootI;
        }
    }

    // Downsample for speed if large
    const step = 2;
    const dw = Math.floor(w / step);
    const dh = Math.floor(h / step);

    for (let y = 0; y < dh; y++) {
        for (let x = 0; x < dw; x++) {
            const val = gray[(y * step) * w + (x * step)] > T ? 1 : 0;
            const idx = y * dw + x;

            let assignedLabel = 0;
            const topIdx = (y - 1) * dw + x;
            const leftIdx = y * dw + (x - 1);

            const hasTop = (y > 0) && (gray[((y - 1) * step) * w + (x * step)] > T ? 1 : 0) === val;
            const hasLeft = (x > 0) && (gray[(y * step) * w + ((x - 1) * step)] > T ? 1 : 0) === val;

            if (hasTop && hasLeft) {
                assignedLabel = labels[topIdx];
                const leftLabel = labels[leftIdx];
                if (assignedLabel !== leftLabel) {
                    union(assignedLabel, leftLabel);
                }
            } else if (hasTop) {
                assignedLabel = labels[topIdx];
            } else if (hasLeft) {
                assignedLabel = labels[leftIdx];
            } else {
                if (nextLabel < 9990) {
                    assignedLabel = nextLabel++;
                    parent[assignedLabel] = assignedLabel;
                    color[assignedLabel] = val;
                }
            }

            labels[idx] = assignedLabel;
        }
    }

    // Accumulate moments into roots
    for (let y = 0; y < dh; y++) {
        for (let x = 0; x < dw; x++) {
            const lbl = labels[y * dw + x];
            if (lbl > 0) {
                const root = find(lbl);
                m00[root] += 1;
                m10[root] += x * step;
                m01[root] += y * step;
            }
        }
    }

    const blobs = [];
    for (let i = 1; i < nextLabel; i++) {
        if (parent[i] === i && m00[i] >= 2) {
            const area = m00[i] * step * step;
            const cx = m10[i] / m00[i];
            const cy = m01[i] / m00[i];
            blobs.push({
                id: i,
                color: color[i],
                area,
                cx,
                cy
            });
        }
    }

    // Find nested pairs (White core inside Black ring sharing centroid)
    const nestedCandidates = [];
    for (let i = 0; i < blobs.length; i++) {
        const core = blobs[i];
        if (core.color !== 1) continue; // Core must be white

        for (let j = 0; j < blobs.length; j++) {
            if (i === j) continue;
            const ring = blobs[j];
            if (ring.color !== 0) continue; // Ring must be black

            if (core.area < 4 || ring.area < 15) continue;
            const ratio = core.area / ring.area;
            if (ratio < 0.03 || ratio > 0.25) continue;

            const dist = Math.hypot(core.cx - ring.cx, core.cy - ring.cy);
            if (dist < 4.5) {
                nestedCandidates.push({
                    cx: (core.cx + ring.cx) / 2,
                    cy: (core.cy + ring.cy) / 2,
                    area: ring.area,
                    coreArea: core.area
                });
            }
        }
    }

    return nestedCandidates;
}

const cands = findNestedBlobs(gray, width, height, threshold);
const elapsed = (performance.now() - t0).toFixed(2);

console.log(`⏱️ Fast Connected Component Search completed in ${elapsed} ms!`);
console.log(`Found ${cands.length} concentric nested anchor candidates:`);
cands.forEach((c, idx) => {
    console.log(`  Candidate ${idx+1}: (${c.cx.toFixed(1)}, ${c.cy.toFixed(1)}), ringArea=${c.area.toFixed(1)}, coreArea=${c.coreArea.toFixed(1)}`);
});
