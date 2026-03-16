"""Decrypt WeChat MSG databases using wdecipher."""

import logging
import os

logger = logging.getLogger(__name__)


def _import_wdecipher():
    """Lazy import wdecipher (Windows-only, requires WeChat)."""
    from wdecipher import get_wx_infos, get_wx_dbs, batch_decrypt_wx_db
    return get_wx_infos, get_wx_dbs, batch_decrypt_wx_db


class DBDecryptor:
    """Decrypt WeChat MSG databases into a single merged SQLite file."""

    def __init__(self, out_dir: str = "./data/decrypted"):
        self.out_dir = out_dir
        self._key: str | None = None
        self._wx_dir: str | None = None
        self._merged_path: str | None = None

    def decrypt(self) -> str:
        """Decrypt MSG databases. Returns path to merged DB."""
        os.makedirs(self.out_dir, exist_ok=True)
        get_wx_infos, get_wx_dbs, batch_decrypt_wx_db = _import_wdecipher()

        infos = get_wx_infos()
        if not infos:
            raise RuntimeError("WeChat not running or wdecipher cannot read process info")

        info = infos[0]
        self._key = info.get("db_key") or info.get("key")
        self._wx_dir = info.get("wx_dir") or info.get("filePath")

        if not self._key or not self._wx_dir:
            raise RuntimeError(f"Cannot extract db_key/wx_dir: {info}")

        logger.info("WeChat data dir: %s", self._wx_dir)

        dbs = get_wx_dbs(self._wx_dir, db_types=["MSG"])
        msg_db_paths = dbs.get("MSG", [])
        if not msg_db_paths:
            raise RuntimeError(f"No MSG databases found in {self._wx_dir}")

        logger.info("Found %d MSG database files", len(msg_db_paths))

        result = batch_decrypt_wx_db(self._key, msg_db_paths, self.out_dir, merge_db=True)
        if not result:
            raise RuntimeError("batch_decrypt_wx_db returned empty result")

        for name in ("MSG_ALL.db", "merge_MSG_ALL.db"):
            path = os.path.join(self.out_dir, name)
            if os.path.exists(path):
                self._merged_path = path
                return self._merged_path

        if isinstance(result, str) and os.path.exists(result):
            self._merged_path = result
            return self._merged_path

        raise RuntimeError(f"Could not locate merged DB in {self.out_dir}")

    def refresh(self) -> str:
        """Re-decrypt to pick up WAL changes. Returns merged DB path."""
        if not self._key or not self._wx_dir:
            return self.decrypt()

        _, get_wx_dbs, batch_decrypt_wx_db = _import_wdecipher()
        dbs = get_wx_dbs(self._wx_dir, db_types=["MSG"])
        msg_db_paths = dbs.get("MSG", [])
        if not msg_db_paths:
            raise RuntimeError("No MSG databases on refresh")

        batch_decrypt_wx_db(self._key, msg_db_paths, self.out_dir, merge_db=True)

        if self._merged_path and os.path.exists(self._merged_path):
            return self._merged_path
        return self.decrypt()

    @property
    def wx_dir(self) -> str | None:
        return self._wx_dir

    @property
    def merged_path(self) -> str | None:
        return self._merged_path
