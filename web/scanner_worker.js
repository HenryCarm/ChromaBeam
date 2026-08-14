/**
 * ChromaBeam Background Web Worker Decoder & Vision Engine v2
 * Provides real-time diagnostic telemetry, multi-threshold decoding,
 * and high-precision fountain solver progress reporting.
 */

if (typeof importScripts === 'function') {
    try {
        importScripts('fountain.js', 'protocol.js', 'matrix.js', 'vision_engine.js');
    } catch (e) {
        console.error("[Worker] importScripts failed:", e);
    }
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
    const startTime = performance.now();
    const msg = e.data;

    if (msg.type === 'reset') {
        resetWorkerSession();
        self.postMessage({ type: 'resetAck' });
        return;
    }

    if (msg.type === 'processFrame') {
        try {
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
                    progressPctFormatted: "100.0000%",
                    isComplete: true,
                    latencyMs: (performance.now() - startTime).toFixed(1)
                });
                return;
            }

            // 1. Detect 4-point quadrilateral in 3D camera space
            const detectRes = detectOpticalQuad(imgData, width, height, guideRect);
            const quad = detectRes.quad;
            const detectMethod = detectRes.method;

            let decodedResult = null;
            let matchedConfig = null;
            let lastLumaMetrics = null;

            if (quad) {
                const configsToTest = workerLockedConfig ? [workerLockedConfig] : CANDIDATE_CONFIGS;

                for (const cfg of configsToTest) {
                    const layout = CACHED_LAYOUTS[`${cfg.grid}_${cfg.mode}`];
                    
                    // Primary sample pass
                    const sampleRes = sampleQuadGrid(imgData, width, height, quad, layout);
                    lastLumaMetrics = {
                        lumaThreshold: sampleRes.lumaThreshold,
                        minLuma: sampleRes.minLuma,
                        maxLuma: sampleRes.maxLuma,
                        contrast: sampleRes.contrast
                    };

                    let res = decodeGridMultiOrientation(sampleRes.grid2D, layout);

                    // Multi-threshold fallback for B&W mode (glare compensation)
                    if (!res && cfg.mode === 0 && sampleRes.contrast > 30) {
                        const altThresholds = [sampleRes.lumaThreshold - 15, sampleRes.lumaThreshold + 15];
                        for (const altT of altThresholds) {
                            if (altT > 20 && altT < 240) {
                                const altSample = sampleQuadGrid(imgData, width, height, quad, layout, altT);
                                res = decodeGridMultiOrientation(altSample.grid2D, layout);
                                if (res) break;
                            }
                        }
                    }

                    if (res) {
                        decodedResult = res;
                        matchedConfig = cfg;
                        workerLockedConfig = cfg;
                        break;
                    }
                }

                if (!decodedResult && workerLockedConfig) {
                    workerLockedConfig = null; // Lost lock, resume sweep next frame
                }
            }

            let fileResult = null;
            const latencyMs = (performance.now() - startTime).toFixed(1);

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
                const progressRatio = workerDecoder.getProgress();
                const solvedCount = workerDecoder.solvedBlocks.size;
                const totalCount = workerDecoder.K;
                const progressPct = (progressRatio * 100).toFixed(4) + "%";

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
                    detectMethod,
                    caught: workerPacketsCaught,
                    drops: workerCRCErrors,
                    progress: progressRatio,
                    progressPctFormatted: progressPct,
                    solvedBlocks: solvedCount,
                    totalBlocks: totalCount,
                    configLabel: `${matchedConfig.label} (${rotationDeg}° rot)`,
                    rotationDeg,
                    lumaMetrics: lastLumaMetrics,
                    latencyMs,
                    isComplete: workerIsComplete,
                    fileResult,
                    logMsg: `[DECODE] Droplet seed #${header.seed} (K=${totalCount}) solved: ${solvedCount}/${totalCount} (${progressPct})`
                }, fileResult ? [fileResult.payloadBuffer] : []);

            } else {
                if (quad) workerCRCErrors++;
                const progressRatio = workerDecoder ? workerDecoder.getProgress() : 0;
                const progressPct = (progressRatio * 100).toFixed(4) + "%";

                self.postMessage({
                    type: 'frameResult',
                    locked: false,
                    quad,
                    detectMethod,
                    caught: workerPacketsCaught,
                    drops: workerCRCErrors,
                    progress: progressRatio,
                    progressPctFormatted: progressPct,
                    solvedBlocks: workerDecoder ? workerDecoder.solvedBlocks.size : 0,
                    totalBlocks: workerDecoder ? workerDecoder.K : 0,
                    lumaMetrics: lastLumaMetrics,
                    latencyMs,
                    isComplete: workerIsComplete,
                    fileResult: null,
                    logMsg: null
                });
            }
        } catch (err) {
            console.error("[Worker] Frame processing exception:", err);
            self.postMessage({
                type: 'frameResult',
                locked: false,
                caught: workerPacketsCaught,
                drops: workerCRCErrors + 1,
                progress: 0,
                progressPctFormatted: "0.0000%",
                error: err.message,
                logMsg: `[ERROR] Worker Exception: ${err.message}`
            });
        }
    }
};
