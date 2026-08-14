/**
 * ChromaBeam Pure JavaScript 3D Perspective & Computer Vision Engine
 * Supports 4-point Projective Transform (Homography), 360° 4-Way Rotation Invariance,
 * Finder Pattern Detection, Multi-Pixel Bilinear Sampling, and Adaptive Thresholding.
 */

class ProjectiveTransform {
    constructor(p0, p1, p2, p3) {
        // Maps unit square (0,0)-(1,0)-(1,1)-(0,1) to quad (p0, p1, p2, p3)
        // p0: TL, p1: TR, p2: BR, p3: BL
        const x0 = p0.x, y0 = p0.y;
        const x1 = p1.x, y1 = p1.y;
        const x2 = p2.x, y2 = p2.y;
        const x3 = p3.x, y3 = p3.y;

        const dx1 = x1 - x2;
        const dx2 = x3 - x2;
        const sx = x0 - x1 + x2 - x3;
        const dy1 = y1 - y2;
        const dy2 = y3 - y2;
        const sy = y0 - y1 + y2 - y3;

        if (Math.abs(sx) < 1e-6 && Math.abs(sy) < 1e-6) {
            // Affine transform
            this.a = x1 - x0;
            this.b = x3 - x0;
            this.c = x0;
            this.d = y1 - y0;
            this.e = y3 - y0;
            this.f = y0;
            this.g = 0;
            this.h = 0;
        } else {
            // Perspective transform
            const det = dx1 * dy2 - dx2 * dy1;
            if (Math.abs(det) < 1e-7) {
                // Degenerate quad fallback to affine
                this.a = x1 - x0; this.b = x3 - x0; this.c = x0;
                this.d = y1 - y0; this.e = y3 - y0; this.f = y0;
                this.g = 0; this.h = 0;
            } else {
                this.g = (sx * dy2 - dx2 * sy) / det;
                this.h = (dx1 * sy - sx * dy1) / det;
                this.a = x1 - x0 + this.g * x1;
                this.b = x3 - x0 + this.h * x3;
                this.c = x0;
                this.d = y1 - y0 + this.g * y1;
                this.e = y3 - y0 + this.h * y3;
                this.f = y0;
            }
        }
    }

    transform(u, v) {
        const W = this.g * u + this.h * v + 1.0;
        if (Math.abs(W) < 1e-7) return { x: this.c, y: this.f };
        return {
            x: (this.a * u + this.b * v + this.c) / W,
            y: (this.d * u + this.e * v + this.f) / W
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
                // 90 deg clockwise
                out[c][N - 1 - r] = grid2D[r][c];
            } else if (rot === 2) {
                // 180 deg upside-down
                out[N - 1 - r][N - 1 - c] = grid2D[r][c];
            } else if (rot === 3) {
                // 270 deg clockwise (90 deg counter-clockwise)
                out[N - 1 - c][r] = grid2D[r][c];
            }
        }
    }
    return out;
}

/**
 * Samples a grid from an arbitrary 4-point quadrilateral using 3D perspective mapping.
 * Uses 3x3 multi-pixel bilinear subpixel averaging to eliminate moire and camera noise.
 */
function sampleQuadGrid(imgData, w, h, quad, layout) {
    const N = layout.gridSize;
    const colorMode = layout.colorMode;
    const palette = layout.palette;
    const data = imgData.data;

    const transform = new ProjectiveTransform(quad[0], quad[1], quad[2], quad[3]);
    const grid2D = Array.from({ length: N }, () => new Uint8Array(N));

    // Sample pixels across grid to compute Otsu threshold for B&W
    let lumaThreshold = 128;
    if (colorMode === 0) {
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
                }
            }
        }
        if (samples.length > 20) {
            lumaThreshold = calculateOtsuFromLumaArray(samples);
        }
    }

    for (let r = 0; r < N; r++) {
        const v = (r + 0.5) / N;
        for (let c = 0; c < N; c++) {
            const u = (c + 0.5) / N;
            
            // Center point
            const pt = transform.transform(u, v);
            const cx = pt.x;
            const cy = pt.y;

            // Approximate cell radius in camera pixels
            const ptRight = transform.transform((c + 1.0) / N, v);
            const cellRadius = Math.max(1.0, Math.hypot(ptRight.x - cx, ptRight.y - cy) * 0.25);

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

    return grid2D;
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
 * Searches the camera frame for:
 * 1. Full 4-Anchor Pattern Finder (concentric square anchors 1:1:1:1:1)
 * 2. High-contrast square boundaries
 * 3. Guide region fallback
 */
function detectOpticalQuad(imgData, w, h, guideRect) {
    const data = imgData.data;

    // Fast pass: scan for 4 corner anchor clusters
    const anchorClusters = findAnchorClusters(data, w, h);
    if (anchorClusters && anchorClusters.length === 4) {
        const orderedAnchors = orderQuadPointsClockwise(anchorClusters);
        // Expand from anchor centers to outer grid corners
        // Anchors are 5x5 cells centered at (2.5, 2.5) cells in an N-grid
        // Outer corners are extrapolated slightly (~6%) outward
        const cx = (orderedAnchors[0].x + orderedAnchors[1].x + orderedAnchors[2].x + orderedAnchors[3].x) / 4;
        const cy = (orderedAnchors[0].y + orderedAnchors[1].y + orderedAnchors[2].y + orderedAnchors[3].y) / 4;
        const scale = 1.08; // extrapolate to outer edge of the anchors

        return orderedAnchors.map(pt => ({
            x: Math.max(0, Math.min(w - 1, cx + (pt.x - cx) * scale)),
            y: Math.max(0, Math.min(h - 1, cy + (pt.y - cy) * scale))
        }));
    }

    // Secondary pass: Detect high contrast bounds within / around guide
    const gx = guideRect ? guideRect.x : Math.floor(w * 0.1);
    const gy = guideRect ? guideRect.y : Math.floor(h * 0.1);
    const gw = guideRect ? guideRect.w : Math.floor(w * 0.8);
    const gh = guideRect ? guideRect.h : Math.floor(h * 0.8);

    const bounds = detectHighContrastBounds(data, w, h, gx, gy, gw, gh);
    if (bounds) {
        return [
            { x: bounds.x, y: bounds.y },                          // TL
            { x: bounds.x + bounds.w, y: bounds.y },              // TR
            { x: bounds.x + bounds.w, y: bounds.y + bounds.h },   // BR
            { x: bounds.x, y: bounds.y + bounds.h }               // BL
        ];
    }

    // Default guide quad
    return [
        { x: gx, y: gy },
        { x: gx + gw, y: gy },
        { x: gx + gw, y: gy + gh },
        { x: gx, y: gy + gh }
    ];
}

/**
 * Searches for concentric anchor patterns across scan lines
 */
function findAnchorClusters(data, w, h) {
    const candidates = [];
    const stepY = Math.max(4, Math.floor(h / 80));

    // Scan horizontal lines for 1:1:1:1:1 or 1:3:1 white/black/white transitions
    for (let y = 10; y < h - 10; y += stepY) {
        let state = 0;
        let counts = [0, 0, 0, 0, 0];
        let lastColor = 0; // 0: black, 1: white

        for (let x = 10; x < w - 10; x += 2) {
            const idx = (y * w + x) * 4;
            const luma = 0.299 * data[idx] + 0.587 * data[idx + 1] + 0.114 * data[idx + 2];
            const color = (luma > 140) ? 1 : 0;

            if (x === 10) {
                lastColor = color;
                counts[0] = 1;
                state = 0;
                continue;
            }

            if (color === lastColor) {
                counts[state]++;
            } else {
                if (state < 4) {
                    state++;
                    counts[state] = 1;
                } else {
                    // Check if counts match white:black:white:black:white (1:1:1:1:1)
                    if (counts[0] > 2 && counts[1] > 2 && counts[2] > 2 && counts[3] > 2 && counts[4] > 2) {
                        const total = counts[0] + counts[1] + counts[2] + counts[3] + counts[4];
                        const avg = total / 5.0;
                        const maxDiff = Math.max(...counts.map(c => Math.abs(c - avg)));
                        if (maxDiff < avg * 1.5 && total >= 15 && total < w * 0.4) {
                            const centerX = x - (counts[4] + counts[3] + counts[2] / 2);
                            candidates.push({ x: centerX, y });
                        }
                    }
                    counts[0] = counts[2];
                    counts[1] = counts[3];
                    counts[2] = counts[4];
                    counts[3] = 1;
                    counts[4] = 0;
                    state = 3;
                }
                lastColor = color;
            }
        }
    }

    if (candidates.length < 4) return null;

    // Cluster nearby candidates
    const clusters = [];
    const radius = Math.min(w, h) * 0.08;

    for (const pt of candidates) {
        let found = false;
        for (const cl of clusters) {
            if (Math.hypot(cl.x - pt.x, cl.y - pt.y) < radius) {
                cl.x = (cl.x * cl.count + pt.x) / (cl.count + 1);
                cl.y = (cl.y * cl.count + pt.y) / (cl.count + 1);
                cl.count++;
                found = true;
                break;
            }
        }
        if (!found) {
            clusters.push({ x: pt.x, y: pt.y, count: 1 });
        }
    }

    // Sort by count descending and take top 4 clusters if separated
    clusters.sort((a, b) => b.count - a.count);
    if (clusters.length >= 4) {
        const top4 = clusters.slice(0, 4);
        // Verify they form a convex quadrilateral
        const minDistance = Math.min(w, h) * 0.15;
        for (let i = 0; i < 4; i++) {
            for (let j = i + 1; j < 4; j++) {
                if (Math.hypot(top4[i].x - top4[j].x, top4[i].y - top4[j].y) < minDistance) {
                    return null; // too close, degenerate
                }
            }
        }
        return top4;
    }

    return null;
}

/**
 * Orders 4 points clockwise starting with Top-Left
 */
function orderQuadPointsClockwise(pts) {
    const cx = (pts[0].x + pts[1].x + pts[2].x + pts[3].x) / 4;
    const cy = (pts[0].y + pts[1].y + pts[2].y + pts[3].y) / 4;

    const sorted = pts.slice().sort((a, b) => {
        const angleA = Math.atan2(a.y - cy, a.x - cx);
        const angleB = Math.atan2(b.y - cy, b.x - cx);
        return angleA - angleB;
    });

    // Find the one closest to top-left (-3*PI/4)
    let tlIdx = 0;
    let minSum = Infinity;
    for (let i = 0; i < 4; i++) {
        const sum = sorted[i].x + sorted[i].y;
        if (sum < minSum) {
            minSum = sum;
            tlIdx = i;
        }
    }

    return [
        sorted[tlIdx],
        sorted[(tlIdx + 1) % 4],
        sorted[(tlIdx + 2) % 4],
        sorted[(tlIdx + 3) % 4]
    ];
}

function detectHighContrastBounds(data, imgW, imgH, gx, gy, gw, gh) {
    const BRIGHT_THRESHOLD = 150;
    const MIN_BRIGHT = 3;
    let top = -1, bottom = -1, left = -1, right = -1;

    for (let y = gy; y < gy + gh; y += 2) {
        let bCount = 0;
        for (let x = gx; x < gx + gw; x += 3) {
            const idx = (y * imgW + x) * 4;
            const luma = 0.299 * data[idx] + 0.587 * data[idx + 1] + 0.114 * data[idx + 2];
            if (luma > BRIGHT_THRESHOLD) bCount++;
        }
        if (bCount >= MIN_BRIGHT) { top = y; break; }
    }

    for (let y = gy + gh - 1; y >= gy; y -= 2) {
        let bCount = 0;
        for (let x = gx; x < gx + gw; x += 3) {
            const idx = (y * imgW + x) * 4;
            const luma = 0.299 * data[idx] + 0.587 * data[idx + 1] + 0.114 * data[idx + 2];
            if (luma > BRIGHT_THRESHOLD) bCount++;
        }
        if (bCount >= MIN_BRIGHT) { bottom = y; break; }
    }

    for (let x = gx; x < gx + gw; x += 2) {
        let bCount = 0;
        for (let y = gy; y < gy + gh; y += 3) {
            const idx = (y * imgW + x) * 4;
            const luma = 0.299 * data[idx] + 0.587 * data[idx + 1] + 0.114 * data[idx + 2];
            if (luma > BRIGHT_THRESHOLD) bCount++;
        }
        if (bCount >= MIN_BRIGHT) { left = x; break; }
    }

    for (let x = gx + gw - 1; x >= gx; x -= 2) {
        let bCount = 0;
        for (let y = gy; y < gy + gh; y += 3) {
            const idx = (y * imgW + x) * 4;
            const luma = 0.299 * data[idx] + 0.587 * data[idx + 1] + 0.114 * data[idx + 2];
            if (luma > BRIGHT_THRESHOLD) bCount++;
        }
        if (bCount >= MIN_BRIGHT) { right = x; break; }
    }

    if (top < 0 || bottom < 0 || left < 0 || right < 0) return null;
    if (right <= left + 20 || bottom <= top + 20) return null;

    const w = right - left;
    const h = bottom - top;
    const side = Math.min(w, h);
    const cx = left + w / 2;
    const cy = top + h / 2;

    return {
        x: Math.floor(cx - side / 2),
        y: Math.floor(cy - side / 2),
        w: Math.floor(side),
        h: Math.floor(side)
    };
}

/**
 * Fast Multi-Orientation Decoder.
 * Tries 0°, 90°, 180°, 270° rotations of the sampled grid and returns the valid packet + rotation angle.
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
