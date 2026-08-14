"""
ChromaBeam Core Package
"""
from .protocol import (
    MAGIC_BYTES,
    MAGIC_INT,
    HEADER_SIZE,
    PacketHeader,
    pack_packet,
    unpack_packet,
    pack_file_metadata,
    unpack_file_metadata
)
from .fountain import (
    LTEncoder,
    LTDecoder,
    Mulberry32,
    get_droplet_indices,
    get_robust_soliton_cdf
)
from .color_matrix import (
    ColorMatrixLayout,
    COLOR_PALETTE,
    bytes_to_color_grid,
    color_grid_to_bytes,
    upscale_grid_for_display
)
