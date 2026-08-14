/**
 * ChromaBeam Background Web Worker Decoder & Vision Engine v4
 * Features:
 * - Hybrid QR Code & Optical Matrix Scanner
 * - 1:1:3:1:1 Hardware/jsQR Scanner for Ultra-Reliable B&W Potato Mode
 * - 3D Projective Homography for Multi-Color Matrix Modes
 * - Multi-Threaded Non-Blocking Fountain Solver
 */

if (typeof importScripts === 'function') {
    try {
        importScripts('jsQR.js', 'fountain.js', 'protocol.js', 'matrix.js', 'vision_engine.js');
    } catch (e) {
        self.postMessage({
            type: 'frameResult',
            locked: false, caught: 0, drops: 0,
            progress: 0, progressPctFormatted: "0.0000%",
            isComplete: false,
            logMsg: `[FATAL] importScripts FAILED: ${e.message}`,
            error: e.message
        });
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

let CACHED_LAYOUTS = {};
try {
    for (const cfg of CANDIDATE_CONFIGS) {
        CACHED_LAYOUTS[`${cfg.grid}_${cfg.mode}`] = new JSColorMatrixLayout(cfg.grid, cfg.mode);
    }
} catch (e) {
    // Handled in frame loop
}

let workerDecoder = null;
let workerCurrentFileId = null;
let workerPacketsCaught = 0;
let workerCRCErrors = 0;
let workerIsComplete = false;
let workerLockedConfig = null;
let workerFrameCount = 0;

function resetWorkerSession() {
    workerDecoder = null;
    workerCurrentFileId = null;
    workerPacketsCaught = 0;
    workerCRCErrors = 0;
    workerIsComplete = false;
    workerLockedConfig = null;
    workerFrameCount = 0;
}

function base64ToUint8Array(base64) {
    if (typeof atob === 'function') {
        const binaryString = atob(base64);
        const bytes = new Uint8Array(binaryString.length);
        for (let i = 0; i < binaryString.length; i++) {
            bytes[i] = binaryString.charCodeAt(i);
        }
        return bytes;
    }
    return null;
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
        workerFrameCount++;
        const frameNum = workerFrameCount;
        const logLines = [];

        function log(m) {
            logLines.push(m);
        }

        try {
            const { width, height, guideRect } = msg;

            if (!msg.buffer || msg.buffer.byteLength === 0) {
                log(`[F${frameNum}] Empty frame buffer received`);
                sendResult(logLines, startTime);
                return;
            }

            const imgData = {
                data: new Uint8ClampedArray(msg.buffer),
                width,
                height
            };

            const verbose = (frameNum <= 3) || (frameNum % 45 === 0);

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

            let decodedResult = null;
            let matchedConfigLabel = "";
            let quad = null;
            let detectMethod = "";
            let lastLumaMetrics = null;

            // =========================================================================
            // PASS 1: High-Speed Standard QR Code Detection (1:1:3:1:1 Finder Pattern)
            // =========================================================================
            if (typeof jsQR === 'function') {
                const qrRes = jsQR(imgData.data, width, height, {
                    inversionAttempts: "attemptBoth"
                });

                if (qrRes && qrRes.data) {
                    try {
                        const rawBytes = base64ToUint8Array(qrRes.data);
                        if (rawBytes) {
                            const packet = unpackPacket(rawBytes);
                            if (packet) {
                                decodedResult = {
                                    packet,
                                    rotationDeg: 0,
                                    rotationSteps: 0
                                };
                                matchedConfigLabel = "Standard QR (1-bit B&W)";
                                detectMethod = "1:1:3:1:1 QR Finder";
                                quad = [
                                    qrRes.location.topLeftCorner,
                                    qrRes.location.topRightCorner,
                                    qrRes.location.bottomRightCorner,
                                    qrRes.location.bottomLeftCorner
                                ];
                                if (verbose) {
                                    log(`[F${frameNum}] 🎯 jsQR locked! Seed #${packet.header.seed} fileId=${packet.header.fileId}`);
                                }
                            }
                        }
                    } catch (err) {
                        // Invalid QR payload, fall through to color matrix pass
                    }
                }
            }

            // =========================================================================
            // PASS 2: Custom Multi-Color Optical Matrix Detection (3D Homography)
            // =========================================================================
            if (!decodedResult) {
                const detectRes = detectOpticalQuad(imgData, width, height, guideRect);
                quad = detectRes.quad;
                detectMethod = detectRes.method;

                if (quad) {
                    const configsToTest = workerLockedConfig ? [workerLockedConfig] : CANDIDATE_CONFIGS;

                    for (const cfg of configsToTest) {
                        const layoutKey = `${cfg.grid}_${cfg.mode}`;
                        const layout = CACHED_LAYOUTS[layoutKey];
                        if (!layout) continue;

                        const sampleRes = sampleQuadGrid(imgData, width, height, quad, layout);
                        lastLumaMetrics = {
                            lumaThreshold: sampleRes.lumaThreshold,
                            minLuma: sampleRes.minLuma,
                            maxLuma: sampleRes.maxLuma,
                            contrast: sampleRes.contrast
                        };

                        let res = decodeGridMultiOrientation(sampleRes.grid2D, layout);

                        if (res) {
                            decodedResult = res;
                            matchedConfigLabel = `${cfg.label} (${res.rotationDeg}° rot)`;
                            workerLockedConfig = cfg;
                            break;
                        }
                    }

                    if (!decodedResult && workerLockedConfig) {
                        workerLockedConfig = null;
                    }
                }
            }

            // =========================================================================
            // PROCESS DECODED FOUNTAIN DROPLET
            // =========================================================================
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
                    log(`[F${frameNum}] 📦 Session Started: fileId=${header.fileId} K=${header.totalBlocks} (${header.totalBlocks * header.blockSize} bytes)`);
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
                        log(`[F${frameNum}] 🎉 FILE COMPLETE! ${filename} (${filePayload.length} bytes)`);
                    }
                }

                const allLogs = logLines.join('\n');
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
                    configLabel: matchedConfigLabel,
                    rotationDeg: rotationDeg || 0,
                    lumaMetrics: lastLumaMetrics,
                    latencyMs,
                    isComplete: workerIsComplete,
                    fileResult,
                    logMsg: `[DECODE] Droplet #${header.seed} solved: ${solvedCount}/${totalCount} (${progressPct})` + (allLogs ? '\n' + allLogs : '')
                }, fileResult ? [fileResult.payloadBuffer] : []);

            } else {
                if (quad) workerCRCErrors++;
                const progressRatio = workerDecoder ? workerDecoder.getProgress() : 0;
                const progressPct = (progressRatio * 100).toFixed(4) + "%";
                const allLogs = logLines.join('\n');

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
                    logMsg: allLogs.length > 0 ? allLogs : null
                });
            }

        } catch (err) {
            sendResult([`[F${workerFrameCount}] ERROR: ${err.message}`], startTime);
        }
    }
};

function sendResult(logLines, startTime) {
    const allLogs = logLines.join('\n');
    self.postMessage({
        type: 'frameResult',
        locked: false,
        caught: workerPacketsCaught,
        drops: workerCRCErrors,
        progress: 0,
        progressPctFormatted: "0.0000%",
        isComplete: false,
        latencyMs: (performance.now() - startTime).toFixed(1),
        logMsg: allLogs.length > 0 ? allLogs : null
    });
}
