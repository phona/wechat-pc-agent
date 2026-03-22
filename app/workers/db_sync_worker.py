"""DB sync worker — initial history pull + periodic reconciliation."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from wechat.db import WeChatDBDecryptor, DBReader, SyncState

logger = logging.getLogger(__name__)

BATCH_SIZE = 200


class DBSyncWorker(QThread):
    """Dual-purpose worker: full history sync + periodic DB reconciliation.

    Lifecycle:
        1. Decrypt databases (cached if unchanged)
        2. Sync all unsent messages (first run = full history)
        3. Sleep for ``interval_hours``
        4. Re-check DB for new messages, forward any that vision missed
        5. Repeat from 3
    """

    progress = pyqtSignal(str, int, int)   # table, done, total
    finished = pyqtSignal(dict)             # summary (emitted each cycle)
    log_message = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        decryptor: WeChatDBDecryptor,
        bridge,  # WebSocketBridge
        sync_state: SyncState,
        interval_hours: float = 4.0,
        conversations: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._decryptor = decryptor
        self._bridge = bridge
        self._sync_state = sync_state
        self._interval = interval_hours * 3600
        self._conversations = conversations
        self._running = True
        self._force_requested = False

    def stop(self) -> None:
        self._running = False

    def force_sync(self, conversations: list[str] | None = None) -> None:
        """Request an immediate sync cycle (e.g. from cloud command)."""
        self._conversations = conversations
        self._force_requested = True

    def run(self) -> None:
        self.log_message.emit("DB sync worker started")

        while self._running:
            stats = self._run_cycle()
            self.finished.emit(stats)

            # Wait for next cycle, checking stop/force every second
            waited = 0.0
            while self._running and waited < self._interval:
                if self._force_requested:
                    self._force_requested = False
                    break
                time.sleep(1.0)
                waited += 1.0

        self.log_message.emit("DB sync worker stopped")

    def _run_cycle(self) -> dict:
        """Run one sync cycle: decrypt if needed, then sync messages."""
        stats = {"databases": 0, "tables": 0, "messages": 0, "skipped": 0, "errors": 0}

        try:
            # Decrypt (uses cache unless source changed)
            self.log_message.emit("Checking databases...")
            decrypted = self._decryptor.auto_decrypt()
            stats["databases"] = len(decrypted)

            if not decrypted:
                self.log_message.emit("No databases available")
                return stats

            for db_path in decrypted:
                if not self._running:
                    break
                self._sync_database(db_path, stats)

            self._sync_state.save()

        except Exception as e:
            logger.exception("DB sync cycle failed")
            self.error_occurred.emit(f"DB sync failed: {e}")
            stats["errors"] += 1

        self.log_message.emit(
            f"DB sync cycle: {stats['messages']} new, "
            f"{stats['skipped']} skipped (already synced by vision)"
        )
        return stats

    def _sync_database(self, db_path: Path, stats: dict) -> None:
        try:
            with DBReader(db_path) as reader:
                tables = reader.get_chat_tables()
                if self._conversations:
                    tables = [t for t in tables if t in self._conversations]

                for table in tables:
                    if not self._running:
                        return
                    new, skipped = self._sync_table(reader, table)
                    stats["tables"] += 1
                    stats["messages"] += new
                    stats["skipped"] += skipped

        except Exception as e:
            logger.error("Failed to read database %s: %s", db_path, e)
            self.error_occurred.emit(f"Database error: {db_path.name}: {e}")
            stats["errors"] += 1

    def _sync_table(self, reader: DBReader, table_name: str) -> tuple[int, int]:
        """Sync one table. Returns (new_count, skipped_count)."""
        last_ts = self._sync_state.get_db_last_timestamp(table_name)
        total = reader.get_message_count(table_name)
        new_count = 0
        skipped = 0

        while self._running:
            messages = reader.get_messages(
                table_name, after_timestamp=last_ts, limit=BATCH_SIZE,
            )
            if not messages:
                break

            batch_new = 0
            for msg in messages:
                if not self._running:
                    break

                msg_id = f"{table_name}:{msg.msg_id}"

                # Dedup: skip if vision already forwarded this message
                if self._sync_state.is_msg_synced(msg_id):
                    skipped += 1
                    last_ts = msg.timestamp
                    continue

                if self._bridge:
                    try:
                        self._bridge.forward_message(
                            sender_id=msg.sender,
                            conversation_id=msg.conversation_id,
                            msg_type=msg.type_name,
                            content=msg.content,
                        )
                    except Exception as e:
                        logger.debug("Forward failed: %s", e)

                last_ts = msg.timestamp
                new_count += 1
                batch_new += 1

            self._sync_state.update_db_sync(table_name, last_ts, batch_new)
            self.progress.emit(table_name, new_count, total)

            if len(messages) == BATCH_SIZE:
                time.sleep(0.1)

        if new_count > 0:
            self.log_message.emit(
                f"{table_name}: {new_count} new, {skipped} skipped"
            )

        return new_count, skipped
