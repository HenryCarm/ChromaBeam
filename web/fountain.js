/**
 * ChromaBeam JavaScript Luby Transform (LT) Fountain Code Implementation
 * Matches Python Mulberry32 PRNG, Robust Soliton distribution, and peeling/GF(2) solver.
 */

class Mulberry32 {
    constructor(seed) {
        this.state = seed >>> 0;
    }

    nextUint32() {
        this.state = (this.state + 0x6D2B79F5) >>> 0;
        let t = this.state;
        t = Math.imul(t ^ (t >>> 15), t | 1) >>> 0;
        t ^= (t + Math.imul(t ^ (t >>> 7), 61)) >>> 0;
        return (t ^ (t >>> 14)) >>> 0;
    }

    nextFloat() {
        return this.nextUint32() / 4294967296.0;
    }

    randInt(low, high) {
        if (low >= high) return low;
        return low + (this.nextUint32() % (high - low + 1));
    }
}

function getRobustSolitonCDF(K, c = 0.1, delta = 0.05) {
    if (K === 1) return [1.0];

    const rho = new Float64Array(K + 1);
    rho[1] = 1.0 / K;
    for (let d = 2; d <= K; d++) {
        rho[d] = 1.0 / (d * (d - 1));
    }

    const R = c * Math.log(K / delta) * Math.sqrt(K);
    const tau = new Float64Array(K + 1);
    const kOverR = R > 0 ? Math.round(K / R) : K;

    for (let d = 1; d <= K; d++) {
        if (d < kOverR) {
            tau[d] = R / (d * K);
        } else if (d === kOverR) {
            tau[d] = (R * Math.log(R / delta)) / K;
        } else {
            tau[d] = 0.0;
        }
    }

    const mu = new Float64Array(K + 1);
    let total = 0.0;
    for (let d = 1; d <= K; d++) {
        mu[d] = rho[d] + tau[d];
        total += mu[d];
    }
    if (total <= 0) total = 1.0;

    const cdf = new Float64Array(K + 1);
    let cum = 0.0;
    for (let d = 1; d <= K; d++) {
        cum += mu[d] / total;
        cdf[d] = cum;
    }
    cdf[K] = 1.0;
    return cdf;
}

function sampleDegree(prng, cdf, K) {
    if (K <= 1) return 1;
    const r = prng.nextFloat();
    for (let d = 1; d <= K; d++) {
        if (r <= cdf[d]) return d;
    }
    return K;
}

function getDropletIndices(seed, K) {
    if (K <= 1) return { degree: 1, indices: [0] };
    if (seed < K) return { degree: 1, indices: [seed] };

    const prng = new Mulberry32(seed);
    const cdf = getRobustSolitonCDF(K);
    const degree = sampleDegree(prng, cdf, K);

    const indicesSet = new Set();
    while (indicesSet.size < degree) {
        const idx = prng.randInt(0, K - 1);
        indicesSet.add(idx);
    }
    return { degree, indices: Array.from(indicesSet).sort((a, b) => a - b) };
}

class LTEncoder {
    constructor(uint8Data, blockSize = 256) {
        this.rawData = uint8Data;
        this.blockSize = blockSize;
        this.totalSize = uint8Data.length;
        this.K = Math.max(1, Math.ceil(this.totalSize / this.blockSize));

        this.blocks = [];
        for (let i = 0; i < this.K; i++) {
            const chunk = new Uint8Array(this.blockSize);
            const start = i * this.blockSize;
            const end = Math.min(start + this.blockSize, this.totalSize);
            chunk.set(this.rawData.subarray(start, end));
            this.blocks.push(chunk);
        }
    }

    generateDroplet(seed) {
        const { degree, indices } = getDropletIndices(seed, this.K);
        const payload = new Uint8Array(this.blockSize);
        payload.set(this.blocks[indices[0]]);

        for (let k = 1; k < indices.length; k++) {
            const other = this.blocks[indices[k]];
            for (let j = 0; j < this.blockSize; j++) {
                payload[j] ^= other[j];
            }
        }
        return { degree, indices, payload };
    }
}

class LTDecoder {
    constructor(K, blockSize, totalFilesize) {
        this.K = K;
        this.blockSize = blockSize;
        this.totalFilesize = totalFilesize;
        this.solvedBlocks = new Map(); // idx -> Uint8Array
        this.basis = new Map();        // pivot -> { indices: Set, data: Uint8Array }
        this.receivedCount = 0;
        this.isComplete = false;
    }

    addDroplet(seed, payloadUint8) {
        if (this.isComplete) return true;
        if (payloadUint8.length !== this.blockSize) return false;

        this.receivedCount++;
        const { degree, indices } = getDropletIndices(seed, this.K);
        let curIndices = new Set(indices);
        let curData = new Uint8Array(payloadUint8);

        // 1. Reduce with already solved singletons
        for (const [solvedIdx, solvedData] of this.solvedBlocks) {
            if (curIndices.has(solvedIdx)) {
                curIndices.delete(solvedIdx);
                for (let j = 0; j < this.blockSize; j++) curData[j] ^= solvedData[j];
            }
        }

        if (curIndices.size === 0) return this._checkComplete();

        // 2. Incremental GF(2) elimination into basis
        while (curIndices.size > 0) {
            let pivot = Math.min(...curIndices);
            if (this.basis.has(pivot)) {
                const basisRow = this.basis.get(pivot);
                // Symmetric difference
                const newIndices = new Set();
                for (const elem of curIndices) if (!basisRow.indices.has(elem)) newIndices.add(elem);
                for (const elem of basisRow.indices) if (!curIndices.has(elem)) newIndices.add(elem);
                curIndices = newIndices;

                for (let j = 0; j < this.blockSize; j++) curData[j] ^= basisRow.data[j];
            } else {
                this.basis.set(pivot, { indices: curIndices, data: curData });
                break;
            }
        }

        // 3. Back-substitute and extract newly solved singletons
        this._reduceBasis();
        return this._checkComplete();
    }

    _reduceBasis() {
        let changed = true;
        while (changed) {
            changed = false;
            for (const [pivot, row] of Array.from(this.basis.entries())) {
                for (const solvedIdx of Array.from(row.indices)) {
                    if (this.solvedBlocks.has(solvedIdx)) {
                        row.indices.delete(solvedIdx);
                        const solvedData = this.solvedBlocks.get(solvedIdx);
                        for (let j = 0; j < this.blockSize; j++) row.data[j] ^= solvedData[j];
                        changed = true;
                    }
                }

                if (row.indices.size === 0) {
                    this.basis.delete(pivot);
                } else if (row.indices.size === 1) {
                    const singleIdx = row.indices.values().next().value;
                    if (!this.solvedBlocks.has(singleIdx)) {
                        this.solvedBlocks.set(singleIdx, new Uint8Array(row.data));
                        this.basis.delete(pivot);
                        changed = true;
                    }
                }
            }
        }
    }

    _checkComplete() {
        if (this.solvedBlocks.size >= this.K) {
            this.isComplete = true;
            return true;
        }
        return false;
    }

    getProgress() {
        return this.solvedBlocks.size / this.K;
    }

    reconstructData() {
        if (this.solvedBlocks.size < this.K) return null;
        const out = new Uint8Array(this.K * this.blockSize);
        for (let i = 0; i < this.K; i++) {
            if (!this.solvedBlocks.has(i)) return null;
            out.set(this.solvedBlocks.get(i), i * this.blockSize);
        }
        return out.subarray(0, this.totalFilesize);
    }
}
