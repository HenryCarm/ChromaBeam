/**
 * ChromaBeam JavaScript Optical Color Matrix Engine
 */

const JS_COLOR_PALETTE = [
    [0,   0,   0],    // 000: Black
    [0,   0,   255],  // 001: Blue
    [0,   255, 0],    // 010: Green
    [0,   255, 255],  // 011: Cyan
    [255, 0,   0],    // 100: Red
    [255, 0,   255],  // 101: Magenta
    [255, 255, 0],    // 110: Yellow
    [255, 255, 255]   // 111: White
];

const JS_ANCHOR_SIZE = 5;

class JSColorMatrixLayout {
    constructor(gridSize = 48) {
        this.gridSize = gridSize;
        this.anchorSize = JS_ANCHOR_SIZE;
        this.dataCoords = [];
        this.calCells = [];
        this.timingCells = [];

        const s = this.anchorSize;
        const N = this.gridSize;

        // 1. Calibration cells (Top row: s to s + 5)
        const calEnd = Math.min(N - s, s + 5);
        for (let c = s; c < calEnd; c++) {
            this.calCells.push({ r: 0, c });
        }

        // 2. Timing tracks
        // Top timing track (rest of top row)
        for (let c = calEnd; c < N - s; c++) {
            this.timingCells.push({ r: 0, c, colorIdx: (c % 2) * 7 });
        }
        // Bottom timing track
        for (let c = s; c < N - s; c++) {
            this.timingCells.push({ r: N - 1, c, colorIdx: (c % 2) * 7 });
        }

        // 3. Data cells
        for (let r = 0; r < N; r++) {
            for (let c = 0; c < N; c++) {
                const inTL = (r < s && c < s);
                const inTR = (r < s && c >= N - s);
                const inBL = (r >= N - s && c < s);
                const inBR = (r >= N - s && c >= N - s);
                const inTopBorder = (r === 0 && c >= s && c < N - s);
                const inBotBorder = (r === N - 1 && c >= s && c < N - s);

                if (!inTL && !inTR && !inBL && !inBR && !inTopBorder && !inBotBorder) {
                    this.dataCoords.push({ r, c });
                }
            }
        }

        this.numDataCells = this.dataCoords.length;
        this.maxPayloadBits = this.numDataCells * 3;
        this.maxPayloadBytes = Math.floor(this.maxPayloadBits / 8);
    }

    renderAnchors(grid2D) {
        const s = this.anchorSize;
        const N = this.gridSize;

        // TL: Concentric
        for (let r = 0; r < s; r++) for (let c = 0; c < s; c++) grid2D[r][c] = 7; // White
        for (let r = 1; r < s - 1; r++) for (let c = 1; c < s - 1; c++) grid2D[r][c] = 0; // Black
        for (let r = 2; r < s - 2; r++) for (let c = 2; c < s - 2; c++) grid2D[r][c] = 7; // Center dot

        // TR: White box with inner notch
        for (let r = 0; r < s; r++) for (let c = N - s; c < N; c++) grid2D[r][c] = 7;
        for (let r = 1; r < s - 1; r++) for (let c = N - s + 1; c < N - 1; c++) grid2D[r][c] = 0;
        grid2D[1][N - 2] = 7;

        // BR: Concentric with Red target
        for (let r = N - s; r < N; r++) for (let c = N - s; c < N; c++) grid2D[r][c] = 7;
        for (let r = N - s + 1; r < N - 1; r++) for (let c = N - s + 1; c < N - 1; c++) grid2D[r][c] = 0;
        for (let r = N - s + 2; r < N - 2; r++) for (let c = N - s + 2; c < N - 2; c++) grid2D[r][c] = 4; // Red center

        // BL: Crosshair
        for (let r = N - s; r < N; r++) for (let c = 0; c < s; c++) grid2D[r][c] = 7;
        for (let r = N - s + 1; r < N - 1; r++) for (let c = 1; c < s - 1; c++) grid2D[r][c] = 0;
        for (let r = N - s + 2; r < N - 2; r++) for (let c = 1; c < s - 1; c++) grid2D[r][c] = 7;
        for (let r = N - s + 1; r < N - 1; r++) for (let c = 2; c < s - 2; c++) grid2D[r][c] = 7;

        // Calibration Bar: K, R, G, B, W
        const calColors = [0, 4, 2, 1, 7];
        for (let i = 0; i < Math.min(this.calCells.length, calColors.length); i++) {
            const { r, c } = this.calCells[i];
            grid2D[r][c] = calColors[i];
        }

        // Timing Tracks
        for (const { r, c, colorIdx } of this.timingCells) {
            grid2D[r][c] = colorIdx;
        }
    }
}

function bytesToGridIndices(uint8Data, layout) {
    const N = layout.gridSize;
    const grid2D = Array.from({ length: N }, () => new Uint8Array(N));
    layout.renderAnchors(grid2D);

    // Unpack bits from bytes
    const bits = [];
    for (let i = 0; i < uint8Data.length; i++) {
        const b = uint8Data[i];
        for (let k = 7; k >= 0; k--) {
            bits.push((b >> k) & 1);
        }
    }

    // Pad to multiple of 3
    while (bits.length % 3 !== 0) bits.push(0);

    const numTriplets = Math.floor(bits.length / 3);
    const numToDraw = Math.min(numTriplets, layout.numDataCells);

    for (let i = 0; i < numToDraw; i++) {
        const b0 = bits[i * 3];
        const b1 = bits[i * 3 + 1];
        const b2 = bits[i * 3 + 2];
        const colorIdx = (b0 << 2) | (b1 << 1) | b2;
        const { r, c } = layout.dataCoords[i];
        grid2D[r][c] = colorIdx;
    }

    return grid2D;
}

function gridIndicesToBytes(grid2D, layout, rgbThreshold = 128) {
    const bits = [];
    for (let i = 0; i < layout.numDataCells; i++) {
        const { r, c } = layout.dataCoords[i];
        const colorIdx = grid2D[r][c];
        // 3 bits
        bits.push((colorIdx >> 2) & 1);
        bits.push((colorIdx >> 1) & 1);
        bits.push(colorIdx & 1);
    }

    const numBytes = Math.floor(bits.length / 8);
    const out = new Uint8Array(numBytes);
    for (let i = 0; i < numBytes; i++) {
        let b = 0;
        for (let k = 0; k < 8; k++) {
            b = (b << 1) | bits[i * 8 + k];
        }
        out[i] = b;
    }
    return out;
}
