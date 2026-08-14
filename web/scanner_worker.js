/**
 * ChromaBeam Background Web Worker Decoder & Vision Engine v3
 * NOW WITH NUCLEAR VERBOSE LOGGING — every atom of action is logged.
 */

if (typeof importScripts === 'function') {
    try {
        importScripts('fountain.js', 'protocol.js', 'matrix.js', 'vision_engine.js');
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
    // Will be reported on first frame
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

        function log(msg) {
            logLines.push(msg);
        }

        try {
            const { width, height, guideRect } = msg;

            // Validate incoming data
            if (!msg.buffer || msg.buffer.byteLength === 0) {
                log(`[F${frameNum}] FATAL: Empty buffer received! byteLength=0`);
                sendResult(logLines, startTime);
                return;
            }

            const expectedBytes = width * height * 4;
            if (msg.buffer.byteLength !== expectedBytes) {
                log(`[F${frameNum}] FATAL: Buffer size mismatch! got=${msg.buffer.byteLength} expected=${expectedBytes} (${width}x${height}x4)`);
                sendResult(logLines, startTime);
                return;
            }

            const imgData = {
                data: new Uint8ClampedArray(msg.buffer),
                width,
                height
            };

            // Log every 30th frame to avoid flooding, but log FIRST 5 frames always
            const verbose = (frameNum <= 5) || (frameNum % 30 === 0);

            if (verbose) {
                log(`[F${frameNum}] Frame: ${width}x${height}, buffer=${msg.buffer.byteLength}B, guide=(${guideRect?.x},${guideRect?.y},${guideRect?.w},${guideRect?.h})`);
            }

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

            // Spot-check pixel data is real (not all zeros)
            if (verbose) {
                const d = imgData.data;
                const centerIdx = (Math.floor(height/2) * width + Math.floor(width/2)) * 4;
                log(`[F${frameNum}] Center pixel RGBA: (${d[centerIdx]},${d[centerIdx+1]},${d[centerIdx+2]},${d[centerIdx+3]})`);

                // Check if ALL pixels are zero (blank frame)
                let nonZero = 0;
                for (let i = 0; i < Math.min(d.length, 4000); i += 4) {
                    if (d[i] > 0 || d[i+1] > 0 || d[i+2] > 0) { nonZero++; break; }
                }
                if (nonZero === 0) {
                    log(`[F${frameNum}] WARNING: First 1000 pixels are ALL BLACK! Frame may be blank/corrupted.`);
                }
            }

            // 1. Detect 4-point quadrilateral
            const detectRes = detectOpticalQuad(imgData, width, height, guideRect);
            const quad = detectRes.quad;
            const detectMethod = detectRes.method;
            const confidence = detectRes.confidence;

            if (verbose) {
                if (quad) {
                    log(`[F${frameNum}] Quad: method=${detectMethod} conf=${confidence?.toFixed(2)} corners=[(${Math.round(quad[0].x)},${Math.round(quad[0].y)}),(${Math.round(quad[1].x)},${Math.round(quad[1].y)}),(${Math.round(quad[2].x)},${Math.round(quad[2].y)}),(${Math.round(quad[3].x)},${Math.round(quad[3].y)})]`);
                    
                    // Check quad size
                    const qw = Math.abs(quad[1].x - quad[0].x);
                    const qh = Math.abs(quad[3].y - quad[0].y);
                    log(`[F${frameNum}] Quad size: ~${Math.round(qw)}x${Math.round(qh)} px (image: ${width}x${height})`);
                } else {
                    log(`[F${frameNum}] Quad: NOT DETECTED (method=${detectMethod})`);
                }
            }

            let decodedResult = null;
            let matchedConfig = null;
            let lastLumaMetrics = null;

            if (quad) {
                const configsToTest = workerLockedConfig ? [workerLockedConfig] : CANDIDATE_CONFIGS;

                for (const cfg of configsToTest) {
                    const layoutKey = `${cfg.grid}_${cfg.mode}`;
                    const layout = CACHED_LAYOUTS[layoutKey];

                    if (!layout) {
                        log(`[F${frameNum}] ERROR: No cached layout for ${layoutKey}!`);
                        continue;
                    }

                    // Sample the grid
                    const sampleRes = sampleQuadGrid(imgData, width, height, quad, layout);
                    lastLumaMetrics = {
                        lumaThreshold: sampleRes.lumaThreshold,
                        minLuma: sampleRes.minLuma,
                        maxLuma: sampleRes.maxLuma,
                        contrast: sampleRes.contrast
                    };

                    if (verbose) {
                        log(`[F${frameNum}] Sample ${cfg.label}: thresh=${sampleRes.lumaThreshold} min=${sampleRes.minLuma} max=${sampleRes.maxLuma} contr=${sampleRes.contrast}`);
                    }

                    // Convert grid to bytes and check magic
                    const rawBytes = gridIndicesToBytes(sampleRes.grid2D, layout);

                    if (verbose) {
                        // Check the raw bytes for magic number
                        if (rawBytes.length >= 2) {
                            const magic = (rawBytes[0] << 8) | rawBytes[1];
                            log(`[F${frameNum}] ${cfg.label} raw[0:6]: ${Array.from(rawBytes.slice(0, 6)).map(b => '0x' + b.toString(16).padStart(2,'0')).join(' ')} magic=0x${magic.toString(16).padStart(4,'0')} (want 0x4342='CB')`);
                        }
                    }

                    // Try all 4 rotations
                    let res = decodeGridMultiOrientation(sampleRes.grid2D, layout);

                    if (verbose && !res) {
                        // Detailed rotation debug: check each rotation's magic
                        for (let rot = 0; rot < 4; rot++) {
                            const rotGrid = (rot === 0) ? sampleRes.grid2D : rotateGrid2D(sampleRes.grid2D, rot);
                            const rotBytes = gridIndicesToBytes(rotGrid, layout);
                            if (rotBytes.length >= 12) {
                                const m = (rotBytes[0] << 8) | rotBytes[1];
                                const fid = (rotBytes[2] << 8) | rotBytes[3];
                                const tb = (rotBytes[4] << 8) | rotBytes[5];
                                const bs = (rotBytes[6] << 8) | rotBytes[7];
                                log(`[F${frameNum}] ${cfg.label} rot${rot*90}°: magic=0x${m.toString(16).padStart(4,'0')} fid=${fid} blocks=${tb} bsize=${bs}`);
                            }
                        }
                    }

                    // Multi-threshold fallback for B&W mode
                    if (!res && cfg.mode === 0 && sampleRes.contrast > 30) {
                        const altThresholds = [sampleRes.lumaThreshold - 15, sampleRes.lumaThreshold + 15];
                        for (const altT of altThresholds) {
                            if (altT > 20 && altT < 240) {
                                const altSample = sampleQuadGrid(imgData, width, height, quad, layout, altT);
                                res = decodeGridMultiOrientation(altSample.grid2D, layout);
                                if (res) {
                                    log(`[F${frameNum}] ALT THRESHOLD ${altT} WORKED for ${cfg.label}!`);
                                    break;
                                }
                            }
                        }
                    }

                    if (res) {
                        decodedResult = res;
                        matchedConfig = cfg;
                        workerLockedConfig = cfg;
                        log(`[F${frameNum}] ✅ DECODED! ${cfg.label} rot=${res.rotationDeg}° seed=${res.packet.header.seed}`);
                        break;
                    }
                }

                if (!decodedResult && workerLockedConfig) {
                    workerLockedConfig = null;
                }

                if (!decodedResult && verbose) {
                    log(`[F${frameNum}] ❌ All configs failed. Tested ${configsToTest.length} configs × 4 rotations = ${configsToTest.length * 4} attempts.`);
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
                    log(`[F${frameNum}] New file session: fileId=${header.fileId} K=${header.totalBlocks} blockSize=${header.blockSize}`);
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
                    configLabel: `${matchedConfig.label} (${rotationDeg}° rot)`,
                    rotationDeg,
                    lumaMetrics: lastLumaMetrics,
                    latencyMs,
                    isComplete: workerIsComplete,
                    fileResult,
                    logMsg: `[DECODE] Seed #${header.seed} (K=${totalCount}) solved: ${solvedCount}/${totalCount} (${progressPct})` + (allLogs ? '\n' + allLogs : '')
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
                    // ALWAYS send logs for failed frames too!
                    logMsg: allLogs.length > 0 ? allLogs : null
                });
            }
        } catch (err) {
            const allLogs = logLines.join('\n');
            self.postMessage({
                type: 'frameResult',
                locked: false,
                caught: workerPacketsCaught,
                drops: workerCRCErrors + 1,
                progress: 0,
                progressPctFormatted: "0.0000%",
                error: err.message,
                logMsg: `[F${workerFrameCount}] EXCEPTION: ${err.message}\n${err.stack || ''}\n${allLogs}`
            });
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
