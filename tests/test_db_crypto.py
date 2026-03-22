"""Tests for wechat.db.crypto — SQLCipher 4 decryption functions."""

import hashlib
import hmac as hmac_mod
import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from wechat.db.crypto import (
    PAGE_SIZE,
    RESERVE_SIZE,
    SALT_SIZE,
    KEY_SIZE,
    HMAC_KEY_SIZE,
    HMAC_STORED_SIZE,
    IV_SIZE,
    PBKDF2_ITERATIONS,
    SALT_XOR_BYTE,
    SQLITE_HEADER,
    derive_mac_key,
    _compute_page_hmac,
    decrypt_page,
    verify_enc_key,
    decrypt_database,
)


# --- Test constants ---

TEST_ENC_KEY = b"\x01" * KEY_SIZE
TEST_SALT = b"\xaa" * SALT_SIZE


# --- derive_mac_key ---

class TestDeriveMacKey:
    def test_returns_32_bytes(self):
        result = derive_mac_key(TEST_ENC_KEY, TEST_SALT)
        assert len(result) == HMAC_KEY_SIZE

    def test_salt_is_xored(self):
        """Verify salt XOR 0x3A is applied before PBKDF2."""
        expected_salt = bytes(b ^ SALT_XOR_BYTE for b in TEST_SALT)
        expected = hashlib.pbkdf2_hmac(
            "sha512", TEST_ENC_KEY, expected_salt, PBKDF2_ITERATIONS, dklen=HMAC_KEY_SIZE,
        )
        assert derive_mac_key(TEST_ENC_KEY, TEST_SALT) == expected

    def test_different_keys_produce_different_mac_keys(self):
        k1 = derive_mac_key(b"\x01" * KEY_SIZE, TEST_SALT)
        k2 = derive_mac_key(b"\x02" * KEY_SIZE, TEST_SALT)
        assert k1 != k2

    def test_different_salts_produce_different_mac_keys(self):
        k1 = derive_mac_key(TEST_ENC_KEY, b"\xaa" * SALT_SIZE)
        k2 = derive_mac_key(TEST_ENC_KEY, b"\xbb" * SALT_SIZE)
        assert k1 != k2


# --- Helper to build a valid encrypted page ---

def _build_encrypted_page(enc_key: bytes, salt: bytes, page_num: int) -> bytes:
    """Build a fake encrypted page that passes HMAC verification.

    The 'encrypted' content is just random-looking bytes; we only need
    HMAC consistency, not real AES-CBC ciphertext that decrypts to valid data.
    """
    from Crypto.Cipher import AES

    mac_key = derive_mac_key(enc_key, salt)
    content_size = PAGE_SIZE - RESERVE_SIZE  # 4016 bytes

    # For page 1: first 16 bytes = salt (unencrypted), rest = AES-CBC encrypted
    if page_num == 1:
        plaintext = SQLITE_HEADER + b"\x00" * (content_size - SALT_SIZE)
        iv = b"\x00" * IV_SIZE
        cipher = AES.new(enc_key, AES.MODE_CBC, iv)
        encrypted_part = cipher.encrypt(plaintext)
        content = salt + encrypted_part[SALT_SIZE:]  # salt prefix + encrypted remainder
        # Actually we need to encrypt only the non-salt part
        plain_body = b"\x00" * (content_size - SALT_SIZE)
        cipher = AES.new(enc_key, AES.MODE_CBC, iv)
        encrypted_body = cipher.encrypt(plain_body)
        content = salt + encrypted_body
    else:
        iv = b"\x00" * IV_SIZE
        plaintext = b"\x00" * content_size
        from Crypto.Cipher import AES as AES2
        cipher = AES2.new(enc_key, AES2.MODE_CBC, iv)
        content = cipher.encrypt(plaintext)

    # Compute HMAC
    h = hmac_mod.new(mac_key, digestmod=hashlib.sha512)
    h.update(content)
    h.update(iv)
    h.update(struct.pack("<I", page_num))
    mac = h.digest()

    # Reserve: IV (16) + HMAC prefix (48) + padding (16)
    reserve = iv + mac[:HMAC_STORED_SIZE] + b"\x00" * 16
    assert len(reserve) == RESERVE_SIZE

    page = content + reserve
    assert len(page) == PAGE_SIZE
    return page


# --- _compute_page_hmac ---

class TestComputePageHmac:
    def test_deterministic(self):
        page = b"\x00" * PAGE_SIZE
        h1 = _compute_page_hmac(b"\x01" * HMAC_KEY_SIZE, page, 1)
        h2 = _compute_page_hmac(b"\x01" * HMAC_KEY_SIZE, page, 1)
        assert h1 == h2

    def test_different_page_num_different_hmac(self):
        page = b"\x00" * PAGE_SIZE
        mac_key = b"\x01" * HMAC_KEY_SIZE
        h1 = _compute_page_hmac(mac_key, page, 1)
        h2 = _compute_page_hmac(mac_key, page, 2)
        assert h1 != h2

    def test_returns_64_bytes(self):
        page = b"\x00" * PAGE_SIZE
        result = _compute_page_hmac(b"\x01" * HMAC_KEY_SIZE, page, 1)
        assert len(result) == 64


# --- decrypt_page ---

class TestDecryptPage:
    def test_wrong_page_size_raises(self):
        with pytest.raises(ValueError, match="Page size"):
            decrypt_page(b"\x00" * 100, 1, TEST_ENC_KEY, b"\x00" * HMAC_KEY_SIZE)

    def test_hmac_failure_raises(self):
        # Page with all zeros won't have valid HMAC
        page = b"\x00" * PAGE_SIZE
        mac_key = derive_mac_key(TEST_ENC_KEY, TEST_SALT)
        with pytest.raises(ValueError, match="HMAC verification failed"):
            decrypt_page(page, 1, TEST_ENC_KEY, mac_key)

    def test_valid_page_decrypts(self):
        page = _build_encrypted_page(TEST_ENC_KEY, TEST_SALT, 2)
        mac_key = derive_mac_key(TEST_ENC_KEY, TEST_SALT)
        result = decrypt_page(page, 2, TEST_ENC_KEY, mac_key)
        assert len(result) == PAGE_SIZE
        # Reserve area should be zeroed
        assert result[-RESERVE_SIZE:] == b"\x00" * RESERVE_SIZE

    def test_page1_has_sqlite_header(self):
        page = _build_encrypted_page(TEST_ENC_KEY, TEST_SALT, 1)
        mac_key = derive_mac_key(TEST_ENC_KEY, TEST_SALT)
        result = decrypt_page(page, 1, TEST_ENC_KEY, mac_key)
        assert result[:len(SQLITE_HEADER)] == SQLITE_HEADER


# --- verify_enc_key ---

class TestVerifyEncKey:
    def test_valid_key(self, tmp_path):
        db_file = tmp_path / "test.db"
        page = _build_encrypted_page(TEST_ENC_KEY, TEST_SALT, 1)
        db_file.write_bytes(page)
        assert verify_enc_key(TEST_ENC_KEY, db_file) is True

    def test_wrong_key(self, tmp_path):
        db_file = tmp_path / "test.db"
        page = _build_encrypted_page(TEST_ENC_KEY, TEST_SALT, 1)
        db_file.write_bytes(page)
        wrong_key = b"\xff" * KEY_SIZE
        assert verify_enc_key(wrong_key, db_file) is False

    def test_too_small_file(self, tmp_path):
        db_file = tmp_path / "small.db"
        db_file.write_bytes(b"\x00" * 100)
        assert verify_enc_key(TEST_ENC_KEY, db_file) is False

    def test_missing_file(self, tmp_path):
        assert verify_enc_key(TEST_ENC_KEY, tmp_path / "nope.db") is False


# --- decrypt_database ---

class TestDecryptDatabase:
    def test_decrypts_multi_page(self, tmp_path):
        pages = []
        for i in range(1, 4):
            pages.append(_build_encrypted_page(TEST_ENC_KEY, TEST_SALT, i))
        db_file = tmp_path / "encrypted.db"
        db_file.write_bytes(b"".join(pages))

        output = tmp_path / "decrypted.db"
        result = decrypt_database(db_file, TEST_ENC_KEY, output)

        assert result == output
        assert output.exists()
        data = output.read_bytes()
        assert len(data) == PAGE_SIZE * 3
        # First page starts with SQLite header
        assert data[:len(SQLITE_HEADER)] == SQLITE_HEADER

    def test_too_small_raises(self, tmp_path):
        db_file = tmp_path / "tiny.db"
        db_file.write_bytes(b"\x00" * 100)
        with pytest.raises(ValueError, match="too small"):
            decrypt_database(db_file, TEST_ENC_KEY, tmp_path / "out.db")

    def test_creates_output_directory(self, tmp_path):
        page = _build_encrypted_page(TEST_ENC_KEY, TEST_SALT, 1)
        db_file = tmp_path / "enc.db"
        db_file.write_bytes(page)

        output = tmp_path / "sub" / "dir" / "dec.db"
        decrypt_database(db_file, TEST_ENC_KEY, output)
        assert output.exists()
