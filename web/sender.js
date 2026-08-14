/**
 * ChromaBeam Web Sender Engine
 */

let senderLayout = new JSColorMatrixLayout(48);
let senderEncoder = null;
let senderFileBytes = null;
let senderFilename = "demo_sample.bin";
let senderFileId = Math.floor(Math.random() * 50000) + 1000;
let senderDropletSeed = 0;
let senderTotalSent = 0;
let senderStartTime = 0;
let senderIsStreaming = false;
let senderTargetFPS = 45;
let senderAnimationHandle = null;
let senderLastFrameTime = 0;

const senderCanvas = document.getElementById('senderCanvas');
const senderCtx = senderCanvas ? senderCanvas.getContext('2d', { alpha: false }) : null;

function initSender() {
    setupDragAndDrop();
    loadDemoSenderPayload();
    renderIdleSenderFrame();
}

function loadDemoSenderPayload() {
    // Generate synthetic 128KB payload
    const demoSize = 128 * 1024;
    const buf = new Uint8Array(demoSize);
    for (let i = 0; i < demoSize; i++) buf[i] = (i * 37) & 0xFF;
    setSenderPayload(buf, "chromabeam_sample_128kb.bin");
}

function setSenderPayload(uint8Bytes, filename) {
    senderFileBytes = uint8Bytes;
    senderFilename = filename;
    senderFileId = Math.floor(Math.random() * 50000) + 1000;

    const metaBytes = packFileMetadata(senderFilename, senderFileBytes.length);
    const fullPayload = new Uint8Array(metaBytes.length + senderFileBytes.length);
    fullPayload.set(metaBytes, 0);
    fullPayload.set(senderFileBytes, metaBytes.length);

    const blockSize = Math.max(32, senderLayout.maxPayloadBytes - 16);
    senderEncoder = new LTEncoder(fullPayload, blockSize);
    senderDropletSeed = 0;
    senderTotalSent = 0;

    document.getElementById('senderFileLabel').textContent = `File: ${senderFilename}`;
    document.getElementById('senderSizeLabel').textContent = `Size: ${(senderFileBytes.length / 1024).toFixed(1)} KB | Blocks K: ${senderEncoder.K} (Block: ${blockSize} B)`;
}

function renderIdleSenderFrame() {
    if (!senderCtx) return;
    const grid2D = Array.from({ length: senderLayout.gridSize }, () => new Uint8Array(senderLayout.gridSize));
    senderLayout.renderAnchors(grid2D);
    drawGridToCanvas(grid2D);
}

function drawGridToCanvas(grid2D) {
    const N = senderLayout.gridSize;
    const size = senderCanvas.width;
    const cellSize = size / N;

    senderCtx.fillStyle = '#000000';
    senderCtx.fillRect(0, 0, size, size);

    for (let r = 0; r < N; r++) {
        for (let c = 0; c < N; c++) {
            const colorIdx = grid2D[r][c];
            const [red, green, blue] = JS_COLOR_PALETTE[colorIdx];
            senderCtx.fillStyle = `rgb(${red}, ${green}, ${blue})`;
            // Fill exact pixel cell (crisp integer bounds)
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
            const grid2D = bytesToGridIndices(packet, senderLayout);
            drawGridToCanvas(grid2D);

            // Update telemetry
            const elapsed = Math.max(0.001, (performance.now() - senderStartTime) / 1000.0);
            const kbSent = (senderTotalSent * packet.length) / 1024.0;
            const rate = kbSent / elapsed;
            const cycles = Math.floor(senderTotalSent / senderEncoder.K);

            document.getElementById('senderRateVal').textContent = `${rate.toFixed(1)} KB/s`;
            document.getElementById('senderDropletVal').textContent = `Droplets: ${senderTotalSent} (Seed #${seed})`;
            document.getElementById('senderCycleVal').textContent = `Stream Cycles: ${cycles}x | Degree: ${degree}`;
        }
    }

    senderAnimationHandle = requestAnimationFrame(animateSenderStream);
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
    senderLayout = new JSColorMatrixLayout(size);
    if (senderFileBytes) {
        setSenderPayload(senderFileBytes, senderFilename);
    } else {
        renderIdleSenderFrame();
    }
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
