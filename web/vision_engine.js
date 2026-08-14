/**
 * ChromaBeam Pure JavaScript 3D Perspective & Computer Vision Engine v3
 * 
 * Features:
 * - Direct 4-Anchor 3D Homography (DLT Solver)
 * - 2D Cross-Checked 1:1:1:1:1 Scanline Locator (Horizontal + Vertical Verification)
 * - Multi-Thresholding Strategy (Adaptive Otsu + Delta sweeps)
 * - 360° 4-Way Rotation Invariance (0°, 90°, 180°, 270°)
 * - Subpixel Anti-Aliased Cell Sampling
 * - Zero Desktop UI Contamination (Locks strictly to matrix anchors)
 */

function solve8x8(A, b) {
    const n = 8;
    const M = Array.from({ length: n }, (_, i) => [...A[i], b[i]]);

    for (let i = 0; i < n; i++) {
        let maxRow = i;
        for (let k = i + 1; k < n; k++) {
            if (Math.abs(M[k][i]) > Math.abs(M[maxRow][i])) maxRow = k;
        }
        [M[i], M[maxRow]] = [M[maxRow], M[i]];

        if (Math.abs(M[i][i]) < 1e-12) return null;

        for (let k = i + 1; k < n; k++) {
            const factor = M[k][i] / M[i][i];
            for (let j = i; j <= n; j++) {
                M[k][j] -= factor * M[i][j];
            }
        }
    }

    const x = new Float64Array(n);
    for (let i = n - 1; i >= 0; i--) {
        let sum = M[i][n];
        for (let j = i + 1; j < n; j++) sum -= M[i][j] * x[j];
        x[i] = sum / M[i][i];
    }
    return x;
}

class ProjectiveTransform {
    constructor(srcPts, dstPts) {
        // If 4 arguments are passed (legacy: p0, p1, p2, p3), map unit square to quad
        if (arguments.length === 4) {
            const p0 = arguments[0], p1 = arguments[1], p2 = arguments[2], p3 = arguments[3];
            srcPts = [{ u: 0, v: 0 }, { u: 1, v: 0 }, { u: 1, v: 1 }, { u: 0, v: 1 }];
            dstPts = [p0, p1, p2, p3];
        }

        const A = [];
        const b = [];

        for (let i = 0; i < 4; i++) {
            const u = srcPts[i].u !== undefined ? srcPts[i].u : srcPts[i].x;
            const v = srcPts[i].v !== undefined ? srcPts[i].v : srcPts[i].y;
            const x = dstPts[i].x;
            const y = dstPts[i].y;

            A.push([u, v, 1, 0, 0, 0, -x * u, -x * v]);
            b.push(x);
            A.push([0, 0, 0, u, v, 1, -y * u, -y * v]);
            b.push(y);
        }

        const h = solve8x8(A, b);
        if (!h) {
            this.valid = false;
            return;
        }

        this.valid = true;
        this.h00 = h[0]; this.h01 = h[1]; this.h02 = h[2];
        this.h10 = h[3]; this.h11 = h[4]; this.h12 = h[5];
        this.h20 = h[6]; this.h21 = h[7];
    }

    transform(u, v) {
        if (!this.valid) return { x: 0, y: 0 };
        const W = this.h20 * u + this.h21 * v + 1.0;
        if (Math.abs(W) < 1e-9) return { x: 0, y: 0 };
        return {
            x: (this.h00 * u + this.h01 * v + this.h02) / W,
            y: (this.h10 * u + this.h11 * v + this.h12) / W
        };
    }
}

/**
 * Rotates a 2D array grid by 0, 90, 180, or 270 degrees clockwise.
 */
function rotateGrid2D(grid2D, rotationSteps) {
    const N = grid2D.length;
    const rot = (rotationSteps % 4 + 4) % 4;
    if (rot === 0) return grid2D;

    const out = Array.from({ length: N }, () => new Uint8Array(N));
    for (let r = 0; r < N; r++) {
        for (let c = 0; c < N; c++) {
            if (rot === 1) {
                out[c][N - 1 - r] = grid2D[r][c]; // 90 deg clockwise
            } else if (rot === 2) {
                out[N - 1 - r][N - 1 - c] = grid2D[r][c]; // 180 deg upside-down
            } else if (rot === 3) {
                out[N - 1 - c][r] = grid2D[r][c]; // 270 deg clockwise
            }
        }
    }
    return out;
}

/**
 * Samples a grid using projective homography mapping.
 * If quad.isAnchorCenters is true, maps canonical layout.anchorCenters directly to the 4 corners.
 */
function sampleQuadGrid(imgData, w, h, quad, layout, customThreshold = null) {
    const N = layout.gridSize;
    const colorMode = layout.colorMode;
    const palette = layout.palette;
    const data = imgData.data;

    let transform;
    if (quad.isAnchorCenters && layout.anchorCenters) {
        transform = new ProjectiveTransform(layout.anchorCenters, quad);
    } else {
        transform = new ProjectiveTransform(
            [{ u: 0, v: 0 }, { u: 1, v: 0 }, { u: 1, v: 1 }, { u: 0, v: 1 }],
            quad
        );
    }

    const grid2D = Array.from({ length: N }, () => new Uint8Array(N));

    let minLuma = 255;
    let maxLuma = 0;
    let lumaThreshold = 128;

    // Fast sampling pass to compute luminance distribution & Otsu threshold
    if (colorMode === 0) {
        if (customThreshold !== null) {
            lumaThreshold = customThreshold;
        } else {
            const samples = [];
            const step = Math.max(1, Math.floor(N / 8));
            for (let r = 0; r < N; r += step) {
                for (let c = 0; c < N; c += step) {
                    const pt = transform.transform((c + 0.5) / N, (r + 0.5) / N);
                    const px = Math.floor(pt.x);
                    const py = Math.floor(pt.y);
                    if (px >= 0 && px < w && py >= 0 && py < h) {
                        const idx = (py * w + px) * 4;
                        const luma = 0.299 * data[idx] + 0.587 * data[idx + 1] + 0.114 * data[idx + 2];
                        samples.push(luma);
                        if (luma < minLuma) minLuma = luma;
                        if (luma > maxLuma) maxLuma = luma;
                    }
                }
            }
            if (samples.length > 10) {
                lumaThreshold = calculateOtsuFromLumaArray(samples);
            }
        }
    }

    // Main cell sampling pass
    for (let r = 0; r < N; r++) {
        const v = (r + 0.5) / N;
        for (let c = 0; c < N; c++) {
            const u = (c + 0.5) / N;

            const pt = transform.transform(u, v);
            const cx = pt.x;
            const cy = pt.y;

            const ptRight = transform.transform((c + 1.0) / N, v);
            const cellRadius = Math.max(1.0, Math.hypot(ptRight.x - cx, ptRight.y - cy) * 0.22);

            let avgR = 0, avgG = 0, avgB = 0, count = 0;
            const offsets = [-cellRadius, 0, cellRadius];

            for (const dy of offsets) {
                for (const dx of offsets) {
                    const px = Math.floor(cx + dx);
                    const py = Math.floor(cy + dy);
                    if (px >= 0 && px < w && py >= 0 && py < h) {
                        const idx = (py * w + px) * 4;
                        avgR += data[idx];
                        avgG += data[idx + 1];
                        avgB += data[idx + 2];
                        count++;
                    }
                }
            }

            if (count > 0) {
                avgR /= count;
                avgG /= count;
                avgB /= count;
            }

            if (colorMode === 0) {
                const luma = 0.299 * avgR + 0.587 * avgG + 0.114 * avgB;
                grid2D[r][c] = (luma > lumaThreshold) ? 1 : 0;
            } else {
                let bestIdx = 0;
                let minDist = Infinity;
                for (let k = 0; k < palette.length; k++) {
                    const [pr, pg, pb] = palette[k];
                    const dist = (avgR - pr) ** 2 + (avgG - pg) ** 2 + (avgB - pb) ** 2;
                    if (dist < minDist) {
                        minDist = dist;
                        bestIdx = k;
                    }
                }
                grid2D[r][c] = bestIdx;
            }
        }
    }

    return {
        grid2D,
        lumaThreshold,
        minLuma: Math.round(minLuma),
        maxLuma: Math.round(maxLuma),
        contrast: Math.max(0, Math.round(maxLuma - minLuma))
    };
}

function calculateOtsuFromLumaArray(samples) {
    const histogram = new Uint32Array(256);
    for (let i = 0; i < samples.length; i++) {
        histogram[Math.min(255, Math.max(0, Math.floor(samples[i])))]++;
    }

    let sumTotal = 0;
    for (let i = 0; i < 256; i++) sumTotal += i * histogram[i];

    let sumBg = 0, weightBg = 0, maxVariance = 0, threshold = 128;
    const totalCount = samples.length;

    for (let t = 0; t < 256; t++) {
        weightBg += histogram[t];
        if (weightBg === 0) continue;
        const weightFg = totalCount - weightBg;
        if (weightFg === 0) break;

        sumBg += t * histogram[t];
        const meanBg = sumBg / weightBg;
        const meanFg = (sumTotal - sumBg) / weightFg;
        const variance = weightBg * weightFg * (meanBg - meanFg) ** 2;

        if (variance > maxVariance) {
            maxVariance = variance;
            threshold = t;
        }
    }

    return threshold;
}

/**
 * Universal Quad & Finder Pattern Detector.
 * Returns { quad, method, confidence }
 */
function detectOpticalQuad(imgData, w, h, guideRect) {
    const data = imgData.data;

    // 1. Primary Pass: 2D Cross-Checked 1:1:1:1:1 Finder Pattern Detection
    const anchors = find2DAnchorQuad(data, w, h);
    if (anchors && anchors.length === 4) {
        anchors.isAnchorCenters = true;
        return { quad: anchors, method: '4-Anchor 3D Homography', confidence: 0.98 };
    }

    // 2. Fallback: Guide Region Quad
    const gx = guideRect ? guideRect.x : Math.floor(w * 0.1);
    const gy = guideRect ? guideRect.y : Math.floor(h * 0.1);
    const gw = guideRect ? guideRect.w : Math.floor(w * 0.8);
    const gh = guideRect ? guideRect.h : Math.floor(h * 0.8);

    const defaultQuad = [
        { x: gx, y: gy },
        { x: gx + gw, y: gy },
        { x: gx + gw, y: gy + gh },
        { x: gx, y: gy + gh }
    ];
    defaultQuad.isAnchorCenters = false;
    return { quad: defaultQuad, method: 'Viewfinder ROI', confidence: 0.40 };
}

function find2DAnchorQuad(data, w, h) {
    // 1. Fast Grayscale Conversion
    const gray = new Uint8Array(w * h);
    for (let i = 0; i < w * h; i++) {
        const idx = i * 4;
        gray[i] = (data[idx] * 77 + data[idx + 1] * 150 + data[idx + 2] * 29) >> 8;
    }

    // 2. Sample 2D Otsu Threshold
    const hist = new Int32Array(256);
    let sampleCount = 0;
    for (let y = 0; y < h; y += 4) {
        for (let x = 0; x < w; x += 4) {
            hist[gray[y * w + x]]++;
            sampleCount++;
        }
    }

    let sumTotal = 0;
    for (let i = 0; i < 256; i++) sumTotal += i * hist[i];
    let sumBg = 0, weightBg = 0, maxVar = 0, globalThresh = 128;

    for (let t = 0; t < 256; t++) {
        weightBg += hist[t];
        if (weightBg === 0) continue;
        const weightFg = sampleCount - weightBg;
        if (weightFg === 0) break;

        sumBg += t * hist[t];
        const meanBg = sumBg / weightBg;
        const meanFg = (sumTotal - sumBg) / weightFg;
        const variance = weightBg * weightFg * (meanBg - meanFg) * (meanBg - meanFg);
        if (variance > maxVar) {
            maxVar = variance;
            globalThresh = t;
        }
    }

    const thresholdsToTry = [
        globalThresh,
        Math.max(20, globalThresh - 25),
        Math.min(235, globalThresh + 25)
    ];

    const allCandidates = [];

    // 3. Scanline Search with 2D Vertical Verification
    for (const T of thresholdsToTry) {
        const stepY = 3;
        for (let y = 10; y < h - 10; y += stepY) {
            let stateCount = [0, 0, 0, 0, 0];
            let currentState = 0;
            let lastColor = (gray[y * w + 10] > T) ? 1 : 0;

            for (let x = 10; x < w - 10; x++) {
                const color = (gray[y * w + x] > T) ? 1 : 0;
                if (color === lastColor) {
                    stateCount[currentState]++;
                } else {
                    if (currentState < 4) {
                        currentState++;
                        stateCount[currentState] = 1;
                    } else {
                        // Check 1:1:1:1:1 ratio
                        if (checkRatio11111(stateCount, w)) {
                            const totalW = stateCount[0] + stateCount[1] + stateCount[2] + stateCount[3] + stateCount[4];
                            const centerX = x - stateCount[4] - stateCount[3] - Math.floor(stateCount[2] / 2);

                            // Cross-validate vertically
                            const vertRes = checkVerticalCrossSection(gray, w, h, centerX, y, T, totalW);
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

    if (allCandidates.length < 4) return null;

    // 4. Cluster Anchor Points
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
    return findBestAnchorQuad(clusters, w, h);
}

function checkRatio11111(counts, maxW) {
    const total = counts[0] + counts[1] + counts[2] + counts[3] + counts[4];
    if (total < 8 || total > maxW * 0.45) return false;
    const avg = total / 5.0;
    const maxVar = avg * 0.90;
    for (let i = 0; i < 5; i++) {
        if (Math.abs(counts[i] - avg) > maxVar || counts[i] === 0) return false;
    }
    return true;
}

function checkVerticalCrossSection(gray, w, h, cx, startY, T, expectedW) {
    const span = Math.min(h - 1 - startY, startY, Math.floor(expectedW * 1.6));
    if (span < 6) return null;

    let stateCount = [0, 0, 0, 0, 0];
    const topY = Math.max(0, startY - span);
    const botY = Math.min(h - 1, startY + span);

    let currentState = 0;
    let lastColor = (gray[topY * w + cx] > T) ? 1 : 0;

    for (let y = topY; y <= botY; y++) {
        const color = (gray[y * w + cx] > T) ? 1 : 0;
        if (color === lastColor) {
            stateCount[currentState]++;
        } else {
            if (currentState < 4) {
                currentState++;
                stateCount[currentState] = 1;
            } else {
                if (checkRatio11111(stateCount, w)) {
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
    const minQuadArea = (imgW * imgH) * 0.005; // At least 0.5% of camera frame
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

                    // 5. Score = Area * side_regularity * diag_regularity * sqrt(size_uniformity)
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

/**
 * Fast Multi-Orientation Decoder.
 * Tries 0°, 90°, 180°, 270° rotations of the sampled grid.
 */
function decodeGridMultiOrientation(sampledGrid, layout) {
    for (let rot = 0; rot < 4; rot++) {
        const rotGrid = (rot === 0) ? sampledGrid : rotateGrid2D(sampledGrid, rot);
        const rawBytes = gridIndicesToBytes(rotGrid, layout);
        const packet = unpackPacket(rawBytes);
        if (packet) {
            return {
                packet,
                rotationDeg: rot * 90,
                rotationSteps: rot
            };
        }
    }
    return null;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        ProjectiveTransform,
        rotateGrid2D,
        sampleQuadGrid,
        detectOpticalQuad,
        decodeGridMultiOrientation,
        find2DAnchorQuad,
        calculateOtsuFromLumaArray
    };
}
