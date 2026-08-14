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
let workerLastLockedQuad = null;
let workerLockStreak = 0;

function resetWorkerSession() {
    workerDecoder = null;
    workerCurrentFileId = null;
    workerPacketsCaught = 0;
    workerCRCErrors = 0;
    workerIsComplete = false;
    workerLockedConfig = null;
    workerFrameCount = 0;
    workerLastLockedQuad = null;
    workerLockStreak = 0;
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

function scanCroppedQR(fullBuffer, imgW, imgH, rx, ry, rw, rh) {
    rx = Math.max(0, Math.floor(rx));
    ry = Math.max(0, Math.floor(ry));
    rw = Math.min(imgW - rx, Math.floor(rw));
    rh = Math.min(imgH - ry, Math.floor(rh));
    if (rw < 50 || rh < 50) return null;

    const cropBuf = new Uint8ClampedArray(rw * rh * 4);
    for (let y = 0; y < rh; y++) {
        const srcOffset = ((ry + y) * imgW + rx) * 4;
        const dstOffset = (y * rw) * 4;
        cropBuf.set(fullBuffer.subarray(srcOffset, srcOffset + rw * 4), dstOffset);
    }

    const res = jsQR(cropBuf, rw, rh, { inversionAttempts: "attemptBoth" });
    if (res && res.data) {
        return {
            data: res.data,
            location: {
                topLeftCorner: { x: res.location.topLeftCorner.x + rx, y: res.location.topLeftCorner.y + ry },
                topRightCorner: { x: res.location.topRightCorner.x + rx, y: res.location.topRightCorner.y + ry },
                bottomRightCorner: { x: res.location.bottomRightCorner.x + rx, y: res.location.bottomRightCorner.y + ry },
                bottomLeftCorner: { x: res.location.bottomLeftCorner.x + rx, y: res.location.bottomLeftCorner.y + ry }
            }
        };
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
            // PASS 1: High-Speed Scandit-Style Multi-Tier QR Detection
            // =========================================================================
            if (typeof jsQR === 'function') {
                let qrRes = null;

                // Tier 1: Locked Tracking ROI (Tight 25% padding around last known quad)
                if (workerLastLockedQuad) {
                    const xs = workerLastLockedQuad.map(p => p.x);
                    const ys = workerLastLockedQuad.map(p => p.y);
                    const minX = Math.min(...xs);
                    const maxX = Math.max(...xs);
                    const minY = Math.min(...ys);
                    const maxY = Math.max(...ys);
                    const padX = (maxX - minX) * 0.25;
                    const padY = (maxY - minY) * 0.25;

                    qrRes = scanCroppedQR(
                        imgData.data, width, height,
                        minX - padX, minY - padY,
                        (maxX - minX) + padX * 2, (maxY - minY) + padY * 2
                    );
                    if (qrRes) detectMethod = "1:1:3:1:1 QR (Track Lock)";
                }

                // Tier 2: Viewfinder ROI (The green guide box)
                if (!qrRes && guideRect && guideRect.w > 50 && guideRect.h > 50) {
                    const pad = guideRect.w * 0.10;
                    qrRes = scanCroppedQR(
                        imgData.data, width, height,
                        guideRect.x - pad, guideRect.y - pad,
                        guideRect.w + pad * 2, guideRect.h + pad * 2
                    );
                    if (qrRes) detectMethod = "1:1:3:1:1 QR (Viewfinder ROI)";
                }

                // Tier 3: Full Frame Fallback
                if (!qrRes) {
                    qrRes = jsQR(imgData.data, width, height, {
                        inversionAttempts: "attemptBoth"
                    });
                    if (qrRes) detectMethod = "1:1:3:1:1 QR (Full Frame)";
                }

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
                                quad = [
                                    qrRes.location.topLeftCorner,
                                    qrRes.location.topRightCorner,
                                    qrRes.location.bottomRightCorner,
                                    qrRes.location.bottomLeftCorner
                                ];
                                workerLastLockedQuad = quad;
                                workerLockStreak++;
                                if (verbose) {
                                    log(`[F${frameNum}] 🎯 jsQR locked! Seed #${packet.header.seed} fileId=${packet.header.fileId}`);
                                }
                            }
                        }
                    } catch (err) {
                        // Invalid QR payload
                    }
                } else {
                    // Missed frame: degrade lock streak
                    if (workerLastLockedQuad) {
                        workerLockStreak--;
                        if (workerLockStreak <= 0) workerLastLockedQuad = null;
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
