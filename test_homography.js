function solve8x8(A, b) {
    const n = 8;
    const M = Array.from({ length: n }, (_, i) => [...A[i], b[i]]);

    for (let i = 0; i < n; i++) {
        // Pivot
        let maxRow = i;
        for (let k = i + 1; k < n; k++) {
            if (Math.abs(M[k][i]) > Math.abs(M[maxRow][i])) maxRow = k;
        }
        [M[i], M[maxRow]] = [M[maxRow], M[i]];

        if (Math.abs(M[i][i]) < 1e-12) return null; // Singular

        for (let k = i + 1; k < n; k++) {
            const factor = M[k][i] / M[i][i];
            for (let j = i; j <= n; j++) {
                M[k][j] -= factor * M[i][j];
            }
        }
    }

    // Back substitution
    const x = new Float64Array(n);
    for (let i = n - 1; i >= 0; i--) {
        let sum = M[i][n];
        for (let j = i + 1; j < n; j++) sum -= M[i][j] * x[j];
        x[i] = sum / M[i][i];
    }
    return x;
}

class UniversalHomography {
    constructor(srcPts, dstPts) {
        // srcPts: [{u, v}], dstPts: [{x, y}] (4 points each)
        const A = [];
        const b = [];

        for (let i = 0; i < 4; i++) {
            const u = srcPts[i].u !== undefined ? srcPts[i].u : srcPts[i].x;
            const v = srcPts[i].v !== undefined ? srcPts[i].v : srcPts[i].y;
            const x = dstPts[i].x;
            const y = dstPts[i].y;

            // Row 1: [u, v, 1, 0, 0, 0, -x*u, -x*v] = x
            A.push([u, v, 1, 0, 0, 0, -x * u, -x * v]);
            b.push(x);

            // Row 2: [0, 0, 0, u, v, 1, -y*u, -y*v] = y
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

// Test mapping from canonical anchor centers directly to screen pixels!
const N = 32;
const c = 2.5 / N;
const canonicalAnchors = [
    { u: c, v: c },              // TL
    { u: 1 - c, v: c },          // TR
    { u: 1 - c, v: 1 - c },      // BR
    { u: c, v: 1 - c }           // BL
];

const screenAnchors = [
    { x: 100, y: 100 },
    { x: 400, y: 110 },
    { x: 390, y: 410 },
    { x: 90, y: 390 }
];

const H = new UniversalHomography(canonicalAnchors, screenAnchors);

console.log("Testing UniversalHomography mapping:");
canonicalAnchors.forEach((pt, i) => {
    const res = H.transform(pt.u, pt.v);
    console.log(`  Anchor ${i}: target=(${screenAnchors[i].x}, ${screenAnchors[i].y}) -> got=(${res.x.toFixed(2)}, ${res.y.toFixed(2)})`);
});

// Test sampling center cell (u=0.5, v=0.5)
const center = H.transform(0.5, 0.5);
console.log(`  Matrix Center (0.5, 0.5) maps to: (${center.x.toFixed(2)}, ${center.y.toFixed(2)})`);
