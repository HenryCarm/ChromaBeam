/**
 * ChromaBeam Multi-Mode Optical Matrix Engine (JS)
 */

const PALETTES = {
    0: [ [0, 0, 0], [255, 255, 255] ], // 1-bit B&W
    1: [ [0, 0, 0], [255, 50, 50], [50, 255, 50], [255, 255, 255] ], // 2-bit 4-Color
    2: [ // 3-bit 8-Color RGB
        [0, 0, 0], [0, 0, 255], [0, 255, 0], [0, 255, 255],
        [255, 0, 0], [255, 0, 255], [255, 255, 0], [255, 255, 255]
    ]
};

const JS_ANCHOR_SIZE = 5;

class JSColorMatrixLayout {
    constructor(gridSize = 48, colorMode = 2) {
        this.gridSize = gridSize;
        this.colorMode = colorMode;
        this.anchorSize = JS_ANCHOR_SIZE;
        this.palette = PALETTES[colorMode] || PALETTES[2];
        this.bitsPerCell = (colorMode === 0) ? 1 : (colorMode === 1 ? 2 : 3);

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
        for (let c = calEnd; c < N - s; c++) {
            this.timingCells.push({ r: 0, c, colorIdx: (c % 2) ? (this.palette.length - 1) : 0 });
        }
        for (let c = s; c < N - s; c++) {
            this.timingCells.push({ r: N - 1, c, colorIdx: (c % 2) ? (this.palette.length - 1) : 0 });
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
        this.maxPayloadBits = this.numDataCells * this.bitsPerCell;
        this.maxPayloadBytes = Math.floor(this.maxPayloadBits / 8);
    }

    renderAnchors(grid2D) {
        const s = this.anchorSize;
        const N = this.gridSize;
        const white = this.palette.length - 1;
        const black = 0;

        // 1:1:1:1:1 Concentric square anchors
        // TL
        for (let r = 0; r < s; r++) for (let c = 0; c < s; c++) grid2D[r][c] = white;
        for (let r = 1; r < s - 1; r++) for (let c = 1; c < s - 1; c++) grid2D[r][c] = black;
        grid2D[2][2] = white;

        // TR
        for (let r = 0; r < s; r++) for (let c = N - s; c < N; c++) grid2D[r][c] = white;
        for (let r = 1; r < s - 1; r++) for (let c = N - s + 1; c < N - 1; c++) grid2D[r][c] = black;
        grid2D[2][N - 3] = (this.palette.length > 4) ? 4 : white; // Red dot if 8-color

        // BR
        for (let r = N - s; r < N; r++) for (let c = N - s; c < N; c++) grid2D[r][c] = white;
        for (let r = N - s + 1; r < N - 1; r++) for (let c = N - s + 1; c < N - 1; c++) grid2D[r][c] = black;
        grid2D[N - 3][N - 3] = (this.palette.length > 2) ? 2 : white; // Green dot

        // BL
        for (let r = N - s; r < N; r++) for (let c = 0; c < s; c++) grid2D[r][c] = white;
        for (let r = N - s + 1; r < N - 1; r++) for (let c = 1; c < s - 1; c++) grid2D[r][c] = black;
        grid2D[N - 3][2] = white;

        // Calibration swatches
        let calIdxs = (this.colorMode === 2) ? [0, 4, 2, 1, 7] : ((this.colorMode === 1) ? [0, 1, 2, 3] : [0, 1, 0, 1]);
        for (let i = 0; i < Math.min(this.calCells.length, calIdxs.length); i++) {
            const { r, c } = this.calCells[i];
            grid2D[r][c] = Math.min(calIdxs[i], this.palette.length - 1);
        }

        // Timing tracks
        for (const { r, c, colorIdx } of this.timingCells) {
            grid2D[r][c] = colorIdx;
        }
    }
}

function bytesToGridIndices(uint8Data, layout) {
    const N = layout.gridSize;
    const grid2D = Array.from({ length: N }, () => new Uint8Array(N));
    layout.renderAnchors(grid2D);

    const bits = [];
    for (let i = 0; i < uint8Data.length; i++) {
        const b = uint8Data[i];
        for (let k = 7; k >= 0; k--) bits.push((b >> k) & 1);
    }

    const bpc = layout.bitsPerCell;
    while (bits.length % bpc !== 0) bits.push(0);

    const numChunks = Math.floor(bits.length / bpc);
    const numToDraw = Math.min(numChunks, layout.numDataCells);

    for (let i = 0; i < numToDraw; i++) {
        let colorIdx = 0;
        if (bpc === 1) {
            colorIdx = bits[i];
        } else if (bpc === 2) {
            colorIdx = (bits[i * 2] << 1) | bits[i * 2 + 1];
        } else {
            colorIdx = (bits[i * 3] << 2) | (bits[i * 3 + 1] << 1) | bits[i * 3 + 2];
        }
        const { r, c } = layout.dataCoords[i];
        grid2D[r][c] = colorIdx;
    }

    return grid2D;
}

function gridIndicesToBytes(grid2D, layout) {
    const bits = [];
    const bpc = layout.bitsPerCell;

    for (let i = 0; i < layout.numDataCells; i++) {
        const { r, c } = layout.dataCoords[i];
        const colorIdx = grid2D[r][c];
        if (bpc === 1) {
            bits.push(colorIdx & 1);
        } else if (bpc === 2) {
            bits.push((colorIdx >> 1) & 1);
            bits.push(colorIdx & 1);
        } else {
            bits.push((colorIdx >> 2) & 1);
            bits.push((colorIdx >> 1) & 1);
            bits.push(colorIdx & 1);
        }
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
