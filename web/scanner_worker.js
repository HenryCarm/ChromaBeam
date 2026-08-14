/**
 * ChromaBeam Background Web Worker Decoder & Vision Engine
 * Offloads 100% of CV, homography warping, multi-orientation testing,
 * and fountain decoding from the main UI thread.
 */

// Import core scripts if running as dedicated worker
if (typeof importScripts === 'function') {
    importScripts('fountain.js', 'protocol.js', 'matrix.js', 'vision_engine.js');
}

const CANDIDATE_CONFIGS = [
    { grid: 32, mode: 0, label: '32×32 B&W (Potato)' },
    { grid: 48, mode: 0, label: '48×48 B&W' },
    { grid: 64, mode: 0, label: '64×64 B&W' },
    { grid: 32, mode: 1, label: '32×32 4-Color' },
    { grid: 48, mode: 1, label: '48×48 4-Color' },
    { grid: 48, mode: 2, label: '48×48 8-Color' },
    { grid: 64, mode: 2, label: '64×64 8-Color' },
];

const CACHED_LAYOUTS = {};
for (const cfg of CANDIDATE_CONFIGS) {
    CACHED_LAYOUTS[`${cfg.grid}_${cfg.mode}`] = new JSColorMatrixLayout(cfg.grid, cfg.mode);
}

let workerDecoder = null;
let workerCurrentFileId = null;
let workerPacketsCaught = 0;
let workerCRCErrors = 0;
let workerIsComplete = false;
let workerLockedConfig = null;

function resetWorkerSession() {
    workerDecoder = null;
    workerCurrentFileId = null;
    workerPacketsCaught = 0;
    workerCRCErrors = 0;
    workerIsComplete = false;
    workerLockedConfig = null;
}

self.onmessage = function(e) {
    const msg = e.data;
    if (msg.type === 'reset') {
        resetWorkerSession();
        self.postMessage({ type: 'resetAck' });
        return;
    }

    if (msg.type === 'processFrame') {
        const { width, height, guideRect } = msg;
        const imgData = {
            data: new Uint8ClampedArray(msg.buffer),
            width,
            height
        };

        if (workerIsComplete) {
            self.postMessage({
                type: 'frameResult',
                locked: false,
                caught: workerPacketsCaught,
                drops: workerCRCErrors,
                progress: 1.0,
                isComplete: true
            });
            return;
        }

        // 1. Detect 4-point quadrilateral in 3D camera space
        const quad = detectOpticalQuad(imgData, width, height, guideRect);

        let decodedResult = null;
        let matchedConfig = null;

        if (quad) {
            // Fast path: try locked config first
            if (workerLockedConfig) {
                const layout = CACHED_LAYOUTS[`${workerLockedConfig.grid}_${workerLockedConfig.mode}`];
                const sampledGrid = sampleQuadGrid(imgData, width, height, quad, layout);
                const res = decodeGridMultiOrientation(sampledGrid, layout);
                if (res) {
                    decodedResult = res;
                    matchedConfig = workerLockedConfig;
                } else {
                    workerLockedConfig = null; // lost lock
                }
            }

            // Sweep candidate configs if not locked
            if (!decodedResult) {
                for (const cfg of CANDIDATE_CONFIGS) {
                    const layout = CACHED_LAYOUTS[`${cfg.grid}_${cfg.mode}`];
                    const sampledGrid = sampleQuadGrid(imgData, width, height, quad, layout);
                    const res = decodeGridMultiOrientation(sampledGrid, layout);
                    if (res) {
                        decodedResult = res;
                        matchedConfig = cfg;
                        workerLockedConfig = cfg;
                        break;
                    }
                }
            }
        }

        let fileResult = null;

        if (decodedResult) {
            workerPacketsCaught++;
            const { packet, rotationDeg } = decodedResult;
            const { header, payload } = packet;

            if (!workerDecoder || workerCurrentFileId !== header.fileId) {
                workerCurrentFileId = header.fileId;
                workerDecoder = new LTDecoder(header.totalBlocks, header.blockSize, header.totalBlocks * header.blockSize);
                workerIsComplete = false;
            }

            const solved = workerDecoder.addDroplet(header.seed, payload);
            const progress = workerDecoder.getProgress();

            if (solved && !workerIsComplete) {
                workerIsComplete = true;
                const fullData = workerDecoder.reconstructData();
                if (fullData) {
                    const meta = unpackFileMetadata(fullData);
                    let filename = "chromabeam_received.bin";
                    let filePayload = fullData;
                    if (meta) {
                        filename = meta.filename;
                        filePayload = fullData.subarray(meta.metadataHeaderLen, meta.metadataHeaderLen + meta.filesize);
                    }
                    fileResult = {
                        filename,
                        filesize: filePayload.length,
                        payloadBuffer: filePayload.buffer
                    };
                }
            }

            self.postMessage({
                type: 'frameResult',
                locked: true,
                quad,
                caught: workerPacketsCaught,
                drops: workerCRCErrors,
                progress,
                configLabel: `${matchedConfig.label} (${rotationDeg}° rot)`,
                rotationDeg,
                isComplete: workerIsComplete,
                fileResult
            }, fileResult ? [fileResult.payloadBuffer] : []);

        } else {
            if (quad) workerCRCErrors++;
            self.postMessage({
                type: 'frameResult',
                locked: false,
                quad,
                caught: workerPacketsCaught,
                drops: workerCRCErrors,
                progress: workerDecoder ? workerDecoder.getProgress() : 0,
                isComplete: workerIsComplete,
                fileResult: null
            });
        }
    }
};
