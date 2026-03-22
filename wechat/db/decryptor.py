"""High-level orchestrator for WeChat database decryption and reading."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .crypto import decrypt_database, verify_enc_key
from .reader import DBReader, DBMessage

logger = logging.getLogger(__name__)


class WeChatDBDecryptor:
    """Orchestrates database discovery, decryption, and reading.

    Caches decrypted files and re-decrypts only when source DB changes.

    Usage:
        decryptor = WeChatDBDecryptor(data_dir, output_dir)
        decrypted = decryptor.auto_decrypt()
        for db_path in decrypted:
            with DBReader(db_path) as reader:
                for table in reader.get_chat_tables():
                    messages = reader.get_messages(table)
    """

    _META_FILE = ".decrypt_meta.json"

    def __init__(
        self,
        wechat_data_dir: Path,
        output_dir: Path | None = None,
    ) -> None:
        self._data_dir = Path(wechat_data_dir)
        self._output_dir = output_dir or (self._data_dir / "decrypted")
        self._enc_key: bytes | None = None
        self._source_meta: dict[str, dict] = {}  # {name: {mtime, size}}

    @property
    def enc_key(self) -> bytes | None:
        return self._enc_key

    @enc_key.setter
    def enc_key(self, key: bytes) -> None:
        self._enc_key = key

    def find_msg_databases(self) -> list[Path]:
        """Find all encrypted message database files.

        WeChat stores messages in MSG0.db, MSG1.db, ... files under
        the Msg/Multi directory.
        """
        patterns = ["MSG*.db", "MicroMsg.db", "MediaMsg*.db"]
        databases = []

        search_dirs = [self._data_dir]
        multi_dir = self._data_dir / "Multi"
        if multi_dir.exists():
            search_dirs.append(multi_dir)

        for search_dir in search_dirs:
            for pattern in patterns:
                databases.extend(search_dir.glob(pattern))

        # Filter out already-decrypted files
        databases = [
            db for db in databases
            if db.exists() and db.stat().st_size >= 4096
        ]

        logger.info("Found %d database files in %s", len(databases), self._data_dir)
        return sorted(databases)

    def auto_decrypt(self, force: bool = False) -> list[Path]:
        """Auto-discover databases and decrypt all with the stored key.

        Uses cached decrypted files when source DB hasn't changed
        (same mtime + size). Pass ``force=True`` to re-decrypt everything.

        Returns:
            List of paths to decrypted database files.

        Raises:
            RuntimeError: If no encryption key is set.
        """
        if not self._enc_key:
            raise RuntimeError("Encryption key not set. Use key_extract or set enc_key.")

        databases = self.find_msg_databases()
        if not databases:
            logger.warning("No message databases found in %s", self._data_dir)
            return []

        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._load_meta()
        decrypted = []

        for db_path in databases:
            output = self._output_dir / db_path.name

            if not force and output.exists() and not self._source_changed(db_path):
                logger.info("Cache hit (unchanged): %s", db_path.name)
                decrypted.append(output)
                continue

            if not verify_enc_key(self._enc_key, db_path):
                logger.warning("Key verification failed for %s, skipping", db_path.name)
                continue

            try:
                decrypt_database(db_path, self._enc_key, output)
                self._record_meta(db_path)
                decrypted.append(output)
            except Exception as e:
                logger.error("Failed to decrypt %s: %s", db_path.name, e)

        self._save_meta()
        logger.info("Decrypted %d/%d databases", len(decrypted), len(databases))
        return decrypted

    def needs_re_decrypt(self) -> bool:
        """Check if any source DB has changed since last decryption."""
        self._load_meta()
        for db_path in self.find_msg_databases():
            if self._source_changed(db_path):
                return True
        return False

    # ── cache meta helpers ───────────────────────────────────

    def _meta_path(self) -> Path:
        return self._output_dir / self._META_FILE

    def _load_meta(self) -> None:
        mp = self._meta_path()
        if mp.exists():
            try:
                self._source_meta = json.loads(mp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._source_meta = {}

    def _save_meta(self) -> None:
        self._meta_path().write_text(
            json.dumps(self._source_meta, indent=2), encoding="utf-8",
        )

    def _record_meta(self, db_path: Path) -> None:
        stat = db_path.stat()
        self._source_meta[db_path.name] = {
            "mtime": stat.st_mtime,
            "size": stat.st_size,
        }

    def _source_changed(self, db_path: Path) -> bool:
        prev = self._source_meta.get(db_path.name)
        if not prev:
            return True
        stat = db_path.stat()
        return stat.st_mtime != prev["mtime"] or stat.st_size != prev["size"]

    def decrypt_single(self, db_path: Path) -> Path | None:
        """Decrypt a single database file."""
        if not self._enc_key:
            raise RuntimeError("Encryption key not set.")

        output = self._output_dir / db_path.name
        try:
            return decrypt_database(db_path, self._enc_key, output)
        except Exception as e:
            logger.error("Failed to decrypt %s: %s", db_path, e)
            return None
