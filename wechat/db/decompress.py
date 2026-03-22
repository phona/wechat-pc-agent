"""Message content decompression for WeChat databases.

WeChat uses zstandard compression for some message content (compress_type == 4).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# WeChat compression type constants
COMPRESS_NONE = 0
COMPRESS_ZSTD = 4


def decompress_message(data: bytes, compress_type: int = 0) -> str:
    """Decompress message content based on compression type.

    Args:
        data: Raw message bytes.
        compress_type: WeChat compression flag (0=none, 4=zstd).

    Returns:
        Decoded string content.
    """
    if not data:
        return ""

    if compress_type == COMPRESS_ZSTD:
        try:
            import zstandard as zstd
            decompressor = zstd.ZstdDecompressor()
            data = decompressor.decompress(data)
        except Exception as e:
            logger.warning("zstd decompression failed: %s", e)
            # Fall through to decode raw bytes

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")
