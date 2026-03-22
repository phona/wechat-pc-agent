"""SQLCipher 4 database decryption for WeChat local databases.

WeChat uses SQLCipher 4 with custom parameters:
  - AES-256-CBC encryption
  - HMAC-SHA512 page authentication
  - PBKDF2-SHA512 key derivation (2 iterations)
  - 4096-byte pages, 80-byte reserve per page (16 IV + 48 HMAC + 16 pad)
  - Salt XOR 0x3A for MAC key derivation
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import struct
from pathlib import Path

from Crypto.Cipher import AES

logger = logging.getLogger(__name__)

# SQLCipher 4 constants (WeChat configuration)
PAGE_SIZE = 4096
RESERVE_SIZE = 80  # 16 IV + 48 HMAC-SHA512 prefix + 16 padding
SALT_SIZE = 16
KEY_SIZE = 32
HMAC_KEY_SIZE = 32
PBKDF2_ITERATIONS = 2
SALT_XOR_BYTE = 0x3A
IV_SIZE = 16
HMAC_SIZE = 64  # SHA-512 output
HMAC_STORED_SIZE = 48  # only first 48 bytes stored in reserve

# SQLite header
SQLITE_HEADER = b"SQLite format 3\x00"
SQLITE_HEADER_SIZE = len(SQLITE_HEADER)

# WAL constants
WAL_HEADER_SIZE = 32
WAL_FRAME_HEADER_SIZE = 24


def derive_mac_key(enc_key: bytes, salt: bytes) -> bytes:
    """Derive HMAC key from encryption key using PBKDF2-SHA512.

    Salt is XORed with 0x3A per SQLCipher 4 spec.
    """
    mac_salt = bytes(b ^ SALT_XOR_BYTE for b in salt)
    return hashlib.pbkdf2_hmac(
        "sha512", enc_key, mac_salt, PBKDF2_ITERATIONS, dklen=HMAC_KEY_SIZE,
    )


def _compute_page_hmac(
    mac_key: bytes, page_data: bytes, page_num: int,
) -> bytes:
    """Compute HMAC-SHA512 for a page.

    HMAC covers: encrypted content (excluding reserve) + page number (LE u32).
    """
    content_end = PAGE_SIZE - RESERVE_SIZE
    h = hmac.new(mac_key, digestmod=hashlib.sha512)
    h.update(page_data[:content_end])
    h.update(page_data[content_end:content_end + IV_SIZE])  # IV is part of HMAC input
    h.update(struct.pack("<I", page_num))
    return h.digest()


def decrypt_page(
    page_data: bytes, page_num: int, enc_key: bytes, mac_key: bytes,
) -> bytes:
    """Decrypt a single database page.

    Args:
        page_data: Raw encrypted page (PAGE_SIZE bytes).
        page_num: 1-based page number.
        enc_key: 32-byte encryption key.
        mac_key: 32-byte HMAC key.

    Returns:
        Decrypted page content (PAGE_SIZE bytes with reserve zeroed).

    Raises:
        ValueError: If HMAC verification fails.
    """
    if len(page_data) != PAGE_SIZE:
        raise ValueError(f"Page size {len(page_data)} != {PAGE_SIZE}")

    content_end = PAGE_SIZE - RESERVE_SIZE
    iv = page_data[content_end:content_end + IV_SIZE]
    stored_hmac = page_data[content_end + IV_SIZE:content_end + IV_SIZE + HMAC_STORED_SIZE]

    # Verify HMAC
    computed = _compute_page_hmac(mac_key, page_data, page_num)
    if not hmac.compare_digest(computed[:HMAC_STORED_SIZE], stored_hmac):
        raise ValueError(f"HMAC verification failed for page {page_num}")

    # Decrypt
    encrypted = page_data[:content_end]

    # Page 1 special: first 16 bytes are the salt (unencrypted)
    if page_num == 1:
        prefix = encrypted[:SALT_SIZE]
        encrypted = encrypted[SALT_SIZE:]
        cipher = AES.new(enc_key, AES.MODE_CBC, iv)
        decrypted = prefix + cipher.decrypt(encrypted)
        # Replace salt with SQLite header
        decrypted = SQLITE_HEADER + decrypted[SQLITE_HEADER_SIZE:]
    else:
        cipher = AES.new(enc_key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(encrypted)

    # Zero out reserve area
    return decrypted + b"\x00" * RESERVE_SIZE


def verify_enc_key(enc_key: bytes, db_path: Path) -> bool:
    """Verify an encryption key against a database file.

    Reads the first page and checks HMAC. Returns True if key is valid.
    """
    try:
        with open(db_path, "rb") as f:
            first_page = f.read(PAGE_SIZE)

        if len(first_page) < PAGE_SIZE:
            return False

        salt = first_page[:SALT_SIZE]
        mac_key = derive_mac_key(enc_key, salt)
        decrypt_page(first_page, 1, enc_key, mac_key)
        return True
    except (ValueError, OSError):
        return False


def decrypt_database(db_path: Path, enc_key: bytes, output_path: Path) -> Path:
    """Decrypt an entire SQLCipher 4 database file.

    Args:
        db_path: Path to encrypted database.
        enc_key: 32-byte encryption key.
        output_path: Path to write decrypted database.

    Returns:
        Path to the decrypted database file.

    Raises:
        ValueError: If key verification fails on page 1.
        OSError: If file I/O fails.
    """
    with open(db_path, "rb") as f:
        data = f.read()

    if len(data) < PAGE_SIZE:
        raise ValueError(f"Database too small: {len(data)} bytes")

    salt = data[:SALT_SIZE]
    mac_key = derive_mac_key(enc_key, salt)

    total_pages = len(data) // PAGE_SIZE
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "wb") as out:
        for i in range(total_pages):
            page_num = i + 1  # 1-based
            page_data = data[i * PAGE_SIZE:(i + 1) * PAGE_SIZE]
            try:
                decrypted = decrypt_page(page_data, page_num, enc_key, mac_key)
                out.write(decrypted)
            except ValueError:
                logger.warning("Page %d HMAC failed, writing zeros", page_num)
                out.write(b"\x00" * PAGE_SIZE)

    # Handle WAL file if present
    wal_path = db_path.parent / (db_path.name + "-wal")
    if wal_path.exists():
        _decrypt_wal(wal_path, enc_key, salt, output_path)

    logger.info("Decrypted %d pages from %s → %s", total_pages, db_path, output_path)
    return output_path


def _decrypt_wal(
    wal_path: Path, enc_key: bytes, salt: bytes, output_db: Path,
) -> None:
    """Decrypt and apply WAL (Write-Ahead Log) frames to the output database."""
    with open(wal_path, "rb") as f:
        wal_data = f.read()

    if len(wal_data) <= WAL_HEADER_SIZE:
        return

    mac_key = derive_mac_key(enc_key, salt)
    frame_size = WAL_FRAME_HEADER_SIZE + PAGE_SIZE
    offset = WAL_HEADER_SIZE

    with open(output_db, "r+b") as out:
        while offset + frame_size <= len(wal_data):
            frame_header = wal_data[offset:offset + WAL_FRAME_HEADER_SIZE]
            page_num = struct.unpack(">I", frame_header[:4])[0]
            page_data = wal_data[offset + WAL_FRAME_HEADER_SIZE:offset + frame_size]

            if len(page_data) == PAGE_SIZE:
                try:
                    decrypted = decrypt_page(page_data, page_num, enc_key, mac_key)
                    out.seek((page_num - 1) * PAGE_SIZE)
                    out.write(decrypted)
                except ValueError:
                    logger.debug("WAL frame page %d HMAC failed, skipping", page_num)

            offset += frame_size

    logger.info("Applied WAL frames from %s", wal_path)
