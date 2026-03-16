"""Tests for DBDecryptor with mocked wdecipher imports."""
import os
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_wdecipher():
    """Provide mock wdecipher functions."""
    get_wx_infos = MagicMock()
    get_wx_dbs = MagicMock()
    batch_decrypt_wx_db = MagicMock()
    return get_wx_infos, get_wx_dbs, batch_decrypt_wx_db


@pytest.fixture
def decryptor(tmp_path):
    from wechat.db_decrypt import DBDecryptor
    return DBDecryptor(out_dir=str(tmp_path / "decrypted"))


class TestDecrypt:
    def test_decrypt_success(self, decryptor, mock_wdecipher, tmp_path):
        get_wx_infos, get_wx_dbs, batch_decrypt_wx_db = mock_wdecipher

        get_wx_infos.return_value = [{"db_key": "secret123", "wx_dir": "/fake/wechat"}]
        get_wx_dbs.return_value = {"MSG": ["/fake/wechat/MSG0.db", "/fake/wechat/MSG1.db"]}
        batch_decrypt_wx_db.return_value = True

        # Create the expected merged DB file
        out_dir = tmp_path / "decrypted"
        out_dir.mkdir(parents=True, exist_ok=True)
        merged = out_dir / "MSG_ALL.db"
        merged.write_text("fake")

        with patch("wechat.db_decrypt._import_wdecipher", return_value=mock_wdecipher):
            result = decryptor.decrypt()

        assert result == str(merged)
        assert decryptor.merged_path == str(merged)
        assert decryptor.wx_dir == "/fake/wechat"
        get_wx_dbs.assert_called_once_with("/fake/wechat", db_types=["MSG"])
        batch_decrypt_wx_db.assert_called_once_with(
            "secret123", ["/fake/wechat/MSG0.db", "/fake/wechat/MSG1.db"],
            str(out_dir), merge_db=True,
        )

    def test_decrypt_merge_msg_all_name(self, decryptor, mock_wdecipher, tmp_path):
        """Finds merge_MSG_ALL.db if MSG_ALL.db doesn't exist."""
        get_wx_infos, get_wx_dbs, batch_decrypt_wx_db = mock_wdecipher
        get_wx_infos.return_value = [{"db_key": "k", "wx_dir": "/wd"}]
        get_wx_dbs.return_value = {"MSG": ["/wd/MSG0.db"]}
        batch_decrypt_wx_db.return_value = True

        out_dir = tmp_path / "decrypted"
        out_dir.mkdir(parents=True, exist_ok=True)
        merged = out_dir / "merge_MSG_ALL.db"
        merged.write_text("fake")

        with patch("wechat.db_decrypt._import_wdecipher", return_value=mock_wdecipher):
            result = decryptor.decrypt()

        assert result == str(merged)

    def test_decrypt_result_is_path(self, decryptor, mock_wdecipher, tmp_path):
        """Falls back to batch_decrypt result when it's a valid path string."""
        get_wx_infos, get_wx_dbs, batch_decrypt_wx_db = mock_wdecipher
        get_wx_infos.return_value = [{"db_key": "k", "wx_dir": "/wd"}]
        get_wx_dbs.return_value = {"MSG": ["/wd/MSG0.db"]}

        out_dir = tmp_path / "decrypted"
        out_dir.mkdir(parents=True, exist_ok=True)
        custom = out_dir / "custom_merged.db"
        custom.write_text("fake")
        batch_decrypt_wx_db.return_value = str(custom)

        with patch("wechat.db_decrypt._import_wdecipher", return_value=mock_wdecipher):
            result = decryptor.decrypt()

        assert result == str(custom)

    def test_decrypt_no_wechat_running(self, decryptor, mock_wdecipher):
        get_wx_infos, _, _ = mock_wdecipher
        get_wx_infos.return_value = []

        with patch("wechat.db_decrypt._import_wdecipher", return_value=mock_wdecipher):
            with pytest.raises(RuntimeError, match="WeChat not running"):
                decryptor.decrypt()

    def test_decrypt_no_db_key(self, decryptor, mock_wdecipher):
        get_wx_infos, _, _ = mock_wdecipher
        get_wx_infos.return_value = [{"db_key": None, "wx_dir": "/wd"}]

        with patch("wechat.db_decrypt._import_wdecipher", return_value=mock_wdecipher):
            with pytest.raises(RuntimeError, match="Cannot extract db_key"):
                decryptor.decrypt()

    def test_decrypt_no_msg_dbs(self, decryptor, mock_wdecipher):
        get_wx_infos, get_wx_dbs, _ = mock_wdecipher
        get_wx_infos.return_value = [{"db_key": "k", "wx_dir": "/wd"}]
        get_wx_dbs.return_value = {"MSG": []}

        with patch("wechat.db_decrypt._import_wdecipher", return_value=mock_wdecipher):
            with pytest.raises(RuntimeError, match="No MSG databases"):
                decryptor.decrypt()

    def test_decrypt_empty_result(self, decryptor, mock_wdecipher):
        get_wx_infos, get_wx_dbs, batch_decrypt_wx_db = mock_wdecipher
        get_wx_infos.return_value = [{"db_key": "k", "wx_dir": "/wd"}]
        get_wx_dbs.return_value = {"MSG": ["/wd/MSG0.db"]}
        batch_decrypt_wx_db.return_value = None

        with patch("wechat.db_decrypt._import_wdecipher", return_value=mock_wdecipher):
            with pytest.raises(RuntimeError, match="batch_decrypt_wx_db returned empty"):
                decryptor.decrypt()

    def test_decrypt_merged_not_found(self, decryptor, mock_wdecipher):
        get_wx_infos, get_wx_dbs, batch_decrypt_wx_db = mock_wdecipher
        get_wx_infos.return_value = [{"db_key": "k", "wx_dir": "/wd"}]
        get_wx_dbs.return_value = {"MSG": ["/wd/MSG0.db"]}
        batch_decrypt_wx_db.return_value = True  # not a path

        with patch("wechat.db_decrypt._import_wdecipher", return_value=mock_wdecipher):
            with pytest.raises(RuntimeError, match="Could not locate merged DB"):
                decryptor.decrypt()

    def test_decrypt_uses_alt_key_names(self, decryptor, mock_wdecipher, tmp_path):
        """Supports 'key' and 'filePath' as alternate field names."""
        get_wx_infos, get_wx_dbs, batch_decrypt_wx_db = mock_wdecipher
        get_wx_infos.return_value = [{"key": "alt_key", "filePath": "/alt/path"}]
        get_wx_dbs.return_value = {"MSG": ["/alt/path/MSG0.db"]}
        batch_decrypt_wx_db.return_value = True

        out_dir = tmp_path / "decrypted"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "MSG_ALL.db").write_text("fake")

        with patch("wechat.db_decrypt._import_wdecipher", return_value=mock_wdecipher):
            decryptor.decrypt()

        assert decryptor.wx_dir == "/alt/path"


class TestRefresh:
    def test_refresh_reuses_key(self, decryptor, mock_wdecipher, tmp_path):
        """refresh() re-decrypts without calling get_wx_infos again."""
        get_wx_infos, get_wx_dbs, batch_decrypt_wx_db = mock_wdecipher

        # Set up internal state as if decrypt() already ran
        decryptor._key = "cached_key"
        decryptor._wx_dir = "/cached/dir"
        out_dir = tmp_path / "decrypted"
        out_dir.mkdir(parents=True, exist_ok=True)
        merged = out_dir / "MSG_ALL.db"
        merged.write_text("fake")
        decryptor._merged_path = str(merged)

        get_wx_dbs.return_value = {"MSG": ["/cached/dir/MSG0.db"]}
        batch_decrypt_wx_db.return_value = True

        with patch("wechat.db_decrypt._import_wdecipher", return_value=mock_wdecipher):
            result = decryptor.refresh()

        assert result == str(merged)
        get_wx_infos.assert_not_called()  # key cached, no need to re-read

    def test_refresh_falls_back_to_decrypt(self, decryptor, mock_wdecipher, tmp_path):
        """refresh() calls decrypt() when no key is cached."""
        get_wx_infos, get_wx_dbs, batch_decrypt_wx_db = mock_wdecipher
        get_wx_infos.return_value = [{"db_key": "k", "wx_dir": "/wd"}]
        get_wx_dbs.return_value = {"MSG": ["/wd/MSG0.db"]}
        batch_decrypt_wx_db.return_value = True

        out_dir = tmp_path / "decrypted"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "MSG_ALL.db").write_text("fake")

        with patch("wechat.db_decrypt._import_wdecipher", return_value=mock_wdecipher):
            result = decryptor.refresh()

        get_wx_infos.assert_called_once()  # had to do full decrypt

    def test_refresh_no_msg_dbs(self, decryptor, mock_wdecipher):
        """refresh() raises when no MSG DBs found."""
        _, get_wx_dbs, _ = mock_wdecipher
        decryptor._key = "k"
        decryptor._wx_dir = "/wd"
        get_wx_dbs.return_value = {"MSG": []}

        with patch("wechat.db_decrypt._import_wdecipher", return_value=mock_wdecipher):
            with pytest.raises(RuntimeError, match="No MSG databases on refresh"):
                decryptor.refresh()

    def test_refresh_merged_gone_falls_back(self, decryptor, mock_wdecipher, tmp_path):
        """refresh() falls back to decrypt() if merged path no longer exists."""
        get_wx_infos, get_wx_dbs, batch_decrypt_wx_db = mock_wdecipher

        decryptor._key = "k"
        decryptor._wx_dir = "/wd"
        decryptor._merged_path = "/nonexistent/MSG_ALL.db"

        get_wx_dbs.return_value = {"MSG": ["/wd/MSG0.db"]}
        batch_decrypt_wx_db.return_value = True

        # decrypt() fallback will need these
        get_wx_infos.return_value = [{"db_key": "k", "wx_dir": "/wd"}]

        out_dir = tmp_path / "decrypted"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "MSG_ALL.db").write_text("fake")

        with patch("wechat.db_decrypt._import_wdecipher", return_value=mock_wdecipher):
            result = decryptor.refresh()

        assert "MSG_ALL.db" in result
