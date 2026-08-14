/**
 * ChromaBeam JavaScript Protocol Serializer & CRC32
 */

const MAGIC_INT = 0x4342; // 'CB'
const HEADER_SIZE = 12;

// Standard CRC32 table
const CRC_TABLE = new Uint32Array(256);
for (let i = 0; i < 256; i++) {
    let c = i;
    for (let k = 0; k < 8; k++) {
        c = ((c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1));
    }
    CRC_TABLE[i] = c >>> 0;
}

function computeCRC32(uint8Array) {
    let crc = 0xFFFFFFFF;
    for (let i = 0; i < uint8Array.length; i++) {
        crc = (crc >>> 8) ^ CRC_TABLE[(crc ^ uint8Array[i]) & 0xFF];
    }
    return (crc ^ 0xFFFFFFFF) >>> 0;
}

function packPacket(fileId, totalBlocks, blockSize, seed, payloadUint8) {
    const packet = new Uint8Array(HEADER_SIZE + blockSize + 4);
    const view = new DataView(packet.buffer);

    view.setUint16(0, MAGIC_INT, false);
    view.setUint16(2, fileId & 0xFFFF, false);
    view.setUint16(4, totalBlocks & 0xFFFF, false);
    view.setUint16(6, blockSize & 0xFFFF, false);
    view.setUint32(8, seed >>> 0, false);

    packet.set(payloadUint8, HEADER_SIZE);

    const crc = computeCRC32(payloadUint8);
    view.setUint32(HEADER_SIZE + blockSize, crc, false);

    return packet;
}

function unpackPacket(rawUint8) {
    if (rawUint8.length < HEADER_SIZE + 4) return null;
    const view = new DataView(rawUint8.buffer, rawUint8.byteOffset, rawUint8.byteLength);

    const magic = view.getUint16(0, false);
    if (magic !== MAGIC_INT) return null;

    const fileId = view.getUint16(2, false);
    const totalBlocks = view.getUint16(4, false);
    const blockSize = view.getUint16(6, false);
    const seed = view.getUint32(8, false);

    if (rawUint8.length < HEADER_SIZE + blockSize + 4) return null;

    const payload = rawUint8.subarray(HEADER_SIZE, HEADER_SIZE + blockSize);
    const expectedCrc = view.getUint32(HEADER_SIZE + blockSize, false);

    const actualCrc = computeCRC32(payload);
    if (actualCrc !== expectedCrc) return null; // Corrupted frame

    return {
        header: { fileId, totalBlocks, blockSize, seed },
        payload
    };
}

function packFileMetadata(filename, filesize, mimeType = "application/octet-stream") {
    const enc = new TextEncoder();
    const nameBytes = enc.encode(filename).subarray(0, 255);
    const mimeBytes = enc.encode(mimeType).subarray(0, 64);

    const out = new Uint8Array(4 + 1 + nameBytes.length + 1 + mimeBytes.length);
    const view = new DataView(out.buffer);

    view.setUint32(0, filesize, false);
    out[4] = nameBytes.length;
    out.set(nameBytes, 5);
    const offset = 5 + nameBytes.length;
    out[offset] = mimeBytes.length;
    out.set(mimeBytes, offset + 1);

    return out;
}

function unpackFileMetadata(uint8Array) {
    if (uint8Array.length < 6) return null;
    const view = new DataView(uint8Array.buffer, uint8Array.byteOffset, uint8Array.byteLength);
    const filesize = view.getUint32(0, false);
    const nameLen = uint8Array[4];
    if (uint8Array.length < 5 + nameLen + 1) return null;

    const dec = new TextDecoder();
    const filename = dec.decode(uint8Array.subarray(5, 5 + nameLen));
    const offset = 5 + nameLen;
    const mimeLen = uint8Array[offset];
    if (uint8Array.length < offset + 1 + mimeLen) return null;

    const mimeType = dec.decode(uint8Array.subarray(offset + 1, offset + 1 + mimeLen));
    const metadataHeaderLen = offset + 1 + mimeLen;
    return { filename, filesize, mimeType, metadataHeaderLen };
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        MAGIC_INT,
        HEADER_SIZE,
        computeCRC32,
        packPacket,
        unpackPacket,
        packFileMetadata,
        unpackFileMetadata
    };
}
