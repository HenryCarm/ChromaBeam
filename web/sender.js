/**
 * ChromaBeam Web Sender Engine with Grandma Presets & Multi-Mode Support
 */

let senderGridSize = 32;
let senderColorMode = 0; // Default to Potato Mode (0: B&W) for instant bulletproof compatibility!
let senderLayout = new JSColorMatrixLayout(senderGridSize, senderColorMode);
let senderEncoder = null;
let senderFileBytes = null;
let senderFilename = "demo_sample.bin";
let senderFileId = Math.floor(Math.random() * 50000) + 1000;
let senderDropletSeed = 0;
let senderTotalSent = 0;
let senderStartTime = 0;
let senderIsStreaming = false;
let senderTargetFPS = 15;
let senderAnimationHandle = null;
let senderLastFrameTime = 0;

const senderCanvas = document.getElementById('senderCanvas');
const senderCtx = senderCanvas ? senderCanvas.getContext('2d', { alpha: false }) : null;

function initSender() {
    setupDragAndDrop();
    loadDemoSenderPayload();
    applyPreset('potato'); // Start with Potato Mode for 100% immediate out-of-the-box reliability!
    renderIdleSenderFrame();
}

function applyPreset(presetName) {
    document.querySelectorAll('.preset-card').forEach(c => c.classList.remove('active'));
    const card = document.getElementById(`preset_${presetName}`);
    if (card) card.classList.add('active');

    if (presetName === 'potato') {
        // Potato Camera: 1-bit Monochrome B&W, 32x32, 15 FPS
        senderColorMode = 0;
        senderGridSize = 32;
        senderTargetFPS = 15;
    } else if (presetName === 'balanced') {
        // Balanced: 2-bit 4-Color, 48x48, 25 FPS
        senderColorMode = 1;
        senderGridSize = 48;
        senderTargetFPS = 25;
    } else if (presetName === 'turbo') {
        // Turbo Speed: 3-bit 8-Color, 64x64, 45 FPS
        senderColorMode = 2;
        senderGridSize = 64;
        senderTargetFPS = 45;
    }

    // Sync Pro Mode controls
    const gridSel = document.getElementById('senderGridSelect');
    if (gridSel) gridSel.value = senderGridSize;
    const modeSel = document.getElementById('senderModeSelect');
    if (modeSel) modeSel.value = senderColorMode;
    const fpsRng = document.getElementById('senderFpsRange');
    if (fpsRng) {
        fpsRng.value = senderTargetFPS;
        document.getElementById('senderFpsLabel').textContent = `Frame Rate: ${senderTargetFPS} FPS`;
    }

    senderLayout = new JSColorMatrixLayout(senderGridSize, senderColorMode);
    if (senderFileBytes) {
        setSenderPayload(senderFileBytes, senderFilename);
    } else {
        renderIdleSenderFrame();
    }
}

function toggleProMode() {
    const proSection = document.getElementById('senderProSection');
    if (proSection) {
        const isHidden = proSection.style.display === 'none';
        proSection.style.display = isHidden ? 'flex' : 'none';
        document.getElementById('proToggleBtn').textContent = isHidden ? "▲ Hide Advanced Settings" : "⚙️ Advanced Settings (Pro)";
    }
}

function loadDemoSenderPayload() {
    const demoSize = 64 * 1024;
    const buf = new Uint8Array(demoSize);
    for (let i = 0; i < demoSize; i++) buf[i] = (i * 37) & 0xFF;
    setSenderPayload(buf, "chromabeam_sample_64kb.bin");
}

function setSenderPayload(uint8Bytes, filename) {
    senderFileBytes = uint8Bytes;
    senderFilename = filename;
    senderFileId = Math.floor(Math.random() * 50000) + 1000;

    const metaBytes = packFileMetadata(senderFilename, senderFileBytes.length);
    const fullPayload = new Uint8Array(metaBytes.length + senderFileBytes.length);
    fullPayload.set(metaBytes, 0);
    fullPayload.set(senderFileBytes, metaBytes.length);

    const blockSize = Math.max(24, senderLayout.maxPayloadBytes - 16);
    senderEncoder = new LTEncoder(fullPayload, blockSize);
    senderDropletSeed = 0;
    senderTotalSent = 0;

    const fLbl = document.getElementById('senderFileLabel');
    if (fLbl) fLbl.textContent = `File: ${senderFilename}`;
    const sLbl = document.getElementById('senderSizeLabel');
    if (sLbl) sLbl.textContent = `Size: ${(senderFileBytes.length / 1024).toFixed(1)} KB | Blocks K: ${senderEncoder.K} (Block: ${blockSize} B)`;
}

function renderIdleSenderFrame() {
    if (!senderCtx) return;
    const grid2D = Array.from({ length: senderLayout.gridSize }, () => new Uint8Array(senderLayout.gridSize));
    senderLayout.renderAnchors(grid2D);
    drawGridToCanvas(grid2D);
}

function uint8ArrayToBase64(uint8Array) {
    let binary = '';
    const len = uint8Array.byteLength;
    for (let i = 0; i < len; i++) {
        binary += String.fromCharCode(uint8Array[i]);
    }
    return btoa(binary);
}

function drawQRCodeToCanvas(packetBytes) {
    if (typeof qrcode !== 'function') {
        const grid2D = bytesToGridIndices(packetBytes, senderLayout);
        drawGridToCanvas(grid2D);
        return;
    }

    try {
        const b64 = uint8ArrayToBase64(packetBytes);
        const qr = qrcode(0, 'L');
        qr.addData(b64);
        qr.make();

        const moduleCount = qr.getModuleCount();
        const size = senderCanvas.width;
        const margin = Math.floor(size * 0.04);
        const drawSize = size - margin * 2;
        const cellSize = drawSize / moduleCount;

        senderCtx.fillStyle = '#FFFFFF';
        senderCtx.fillRect(0, 0, size, size);

        senderCtx.fillStyle = '#000000';
        for (let r = 0; r < moduleCount; r++) {
            for (let c = 0; c < moduleCount; c++) {
                if (qr.isDark(r, c)) {
                    senderCtx.fillRect(
                        Math.floor(margin + c * cellSize),
                        Math.floor(margin + r * cellSize),
                        Math.ceil(cellSize),
                        Math.ceil(cellSize)
                    );
                }
            }
        }
    } catch (e) {
        const grid2D = bytesToGridIndices(packetBytes, senderLayout);
        drawGridToCanvas(grid2D);
    }
}

function drawGridToCanvas(grid2D) {
    const N = senderLayout.gridSize;
    const size = senderCanvas.width;
    const cellSize = size / N;
    const palette = senderLayout.palette;

    senderCtx.fillStyle = '#000000';
    senderCtx.fillRect(0, 0, size, size);

    for (let r = 0; r < N; r++) {
        for (let c = 0; c < N; c++) {
            const colorIdx = grid2D[r][c];
            const [red, green, blue] = palette[colorIdx] || [0, 0, 0];
            senderCtx.fillStyle = `rgb(${red}, ${green}, ${blue})`;
            senderCtx.fillRect(Math.floor(c * cellSize), Math.floor(r * cellSize), Math.ceil(cellSize), Math.ceil(cellSize));
        }
    }
}

function toggleSenderStream() {
    senderIsStreaming = !senderIsStreaming;
    const btn = document.getElementById('senderStreamBtn');

    if (senderIsStreaming) {
        btn.textContent = "🛑 STOP OPTICAL BEAM";
        btn.classList.add('active');
        senderStartTime = performance.now();
        senderTotalSent = 0;
        senderLastFrameTime = performance.now();
        animateSenderStream();
    } else {
        btn.textContent = "🚀 START OPTICAL BEAM";
        btn.classList.remove('active');
        if (senderAnimationHandle) cancelAnimationFrame(senderAnimationHandle);
        document.getElementById('senderRateVal').textContent = "0.0 KB/s";
    }
}

function animateSenderStream(currentTime) {
    if (!senderIsStreaming) return;

    const interval = 1000 / senderTargetFPS;
    const delta = currentTime - senderLastFrameTime;

    if (!currentTime || delta >= interval) {
        senderLastFrameTime = currentTime ? (currentTime - (delta % interval)) : performance.now();

        if (senderEncoder) {
            const seed = senderDropletSeed++;
            senderTotalSent++;

            const { degree, indices, payload } = senderEncoder.generateDroplet(seed);
            const packet = packPacket(senderFileId, senderEncoder.K, senderEncoder.blockSize, seed, payload);

            if (senderColorMode === 0) {
                drawQRCodeToCanvas(packet);
            } else {
                const grid2D = bytesToGridIndices(packet, senderLayout);
                drawGridToCanvas(grid2D);
            }

            const elapsed = Math.max(0.001, (performance.now() - senderStartTime) / 1000.0);
            const kbSent = (senderTotalSent * packet.length) / 1024.0;
            const rate = kbSent / elapsed;
            const cycles = Math.floor(senderTotalSent / senderEncoder.K);

            document.getElementById('senderRateVal').textContent = `${rate.toFixed(1)} KB/s`;
            document.getElementById('senderDropletVal').textContent = `Droplets: ${senderTotalSent} (Seed #${seed})`;
            document.getElementById('senderCycleVal').textContent = `Cycles: ${cycles}x | Degree: ${degree}`;
        }
    }

}

function setupDragAndDrop() {
    const dropArea = document.getElementById('senderDropArea');
    const fileInput = document.getElementById('senderFileInput');
    if (!dropArea || !fileInput) return;

    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropArea.addEventListener(eventName, e => {
            e.preventDefault();
            e.stopPropagation();
        }, false);
    });

    ['dragenter', 'dragover'].forEach(eventName => {
        dropArea.addEventListener(eventName, () => dropArea.classList.add('drag-active'), false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropArea.addEventListener(eventName, () => dropArea.classList.remove('drag-active'), false);
    });

    dropArea.addEventListener('drop', e => {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files.length > 0) handleSelectedFile(files[0]);
    });

    fileInput.addEventListener('change', e => {
        if (e.target.files.length > 0) handleSelectedFile(e.target.files[0]);
    });
}

function handleSelectedFile(file) {
    const reader = new FileReader();
    reader.onload = function(e) {
        const uint8 = new Uint8Array(e.target.result);
        setSenderPayload(uint8, file.name);
    };
    reader.readAsArrayBuffer(file);
}

function updateSenderGridDensity(size) {
    senderGridSize = size;
    senderLayout = new JSColorMatrixLayout(senderGridSize, senderColorMode);
    if (senderFileBytes) setSenderPayload(senderFileBytes, senderFilename);
    else renderIdleSenderFrame();
}

function updateSenderColorMode(mode) {
    senderColorMode = mode;
    senderLayout = new JSColorMatrixLayout(senderGridSize, senderColorMode);
    if (senderFileBytes) setSenderPayload(senderFileBytes, senderFilename);
    else renderIdleSenderFrame();
}

function updateSenderFPS(fps) {
    senderTargetFPS = fps;
    document.getElementById('senderFpsLabel').textContent = `Frame Rate: ${fps} FPS`;
}

function toggleSenderFullscreen() {
    const container = document.getElementById('senderCanvasContainer');
    if (!document.fullscreenElement) {
        if (container.requestFullscreen) container.requestFullscreen();
    } else {
        if (document.exitFullscreen) document.exitFullscreen();
    }
}
