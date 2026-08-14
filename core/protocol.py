"""
ChromaBeam Core Protocol Specification
Encapsulates frame headers, metadata, CRC32 validation, and binary packing.
"""

import struct
import zlib
from typing import Optional, Tuple, NamedTuple

# Protocol Magic Bytes: 'CB' -> 0x43, 0x42
MAGIC_BYTES = b'\x43\x42'
MAGIC_INT = 0x4342

# Header format:
# Magic: 2 bytes (0x43, 0x42)
# File ID: 2 bytes (uint16_be)
# Total Blocks (K): 2 bytes (uint16_be)
# Block Size (B): 2 bytes (uint16_be)
# Seed / Droplet ID: 4 bytes (uint32_be)
# Total Header Size = 12 bytes
HEADER_FORMAT = ">HHHHI"
HEADER_SIZE = 12


class PacketHeader(NamedTuple):
    file_id: int
    total_blocks: int
    block_size: int
    seed: int


def pack_packet(file_id: int, total_blocks: int, block_size: int, seed: int, payload: bytes) -> bytes:
    """
    Packs a fountain droplet into a binary frame with CRC32 integrity check.
    
    Packet structure:
    [Header (12B)] [Payload (block_size B)] [CRC32 (4B)]
    """
    header = struct.pack(HEADER_FORMAT, MAGIC_INT, file_id & 0xFFFF, total_blocks & 0xFFFF, block_size & 0xFFFF, seed & 0xFFFFFFFF)
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    crc_bytes = struct.pack(">I", crc)
    return header + payload + crc_bytes


def unpack_packet(raw_bytes: bytes) -> Optional[Tuple[PacketHeader, bytes]]:
    """
    Unpacks and validates a binary frame.
    Returns (PacketHeader, payload_bytes) if valid, None if corrupt or invalid magic/CRC.
    """
    min_size = HEADER_SIZE + 4  # Header + CRC
    if len(raw_bytes) < min_size:
        return None
    
    magic, file_id, total_blocks, block_size, seed = struct.unpack_from(HEADER_FORMAT, raw_bytes, 0)
    if magic != MAGIC_INT:
        return None
    
    expected_payload_len = block_size
    if len(raw_bytes) < HEADER_SIZE + expected_payload_len + 4:
        return None
    
    payload = raw_bytes[HEADER_SIZE:HEADER_SIZE + expected_payload_len]
    expected_crc = struct.unpack_from(">I", raw_bytes, HEADER_SIZE + expected_payload_len)[0]
    
    actual_crc = zlib.crc32(payload) & 0xFFFFFFFF
    if actual_crc != expected_crc:
        return None  # Frame corrupted by camera noise or motion blur
    
    header = PacketHeader(
        file_id=file_id,
        total_blocks=total_blocks,
        block_size=block_size,
        seed=seed
    )
    return header, payload


def pack_file_metadata(filename: str, filesize: int, mime_type: str = "application/octet-stream") -> bytes:
    """
    Encodes file metadata (filename, size, mime) into a compact binary block.
    Format: [FileSize (4B)] [NameLen (1B)] [Filename] [MimeLen (1B)] [MimeType]
    """
    name_bytes = filename.encode('utf-8')[:255]
    mime_bytes = mime_type.encode('utf-8')[:64]
    header = struct.pack(">IB", filesize, len(name_bytes))
    return header + name_bytes + struct.pack("B", len(mime_bytes)) + mime_bytes


def unpack_file_metadata(data: bytes) -> Optional[Tuple[str, int, str]]:
    """
    Unpacks file metadata. Returns (filename, filesize, mime_type).
    """
    if len(data) < 6:
        return None
    filesize, name_len = struct.unpack_from(">IB", data, 0)
    offset = 5
    if len(data) < offset + name_len + 1:
        return None
    filename = data[offset:offset + name_len].decode('utf-8', errors='replace')
    offset += name_len
    mime_len = data[offset]
    offset += 1
    if len(data) < offset + mime_len:
        return None
    mime_type = data[offset:offset + mime_len].decode('utf-8', errors='replace')
    return filename, filesize, mime_type
