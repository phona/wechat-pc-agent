import json
import os
from pathlib import Path
from pydantic import BaseModel

from utils.paths import app_dir, data_dir


CONFIG_FILE = app_dir() / "config.json"


class AppConfig(BaseModel):
    orchestrator_url: str = "http://localhost:8080"
    orchestrator_ws_url: str = "ws://localhost:8080/ws/agent"
    agent_token: str = ""
    poll_interval: float = 1.0
    scroll_delay_ms: int = 800
    max_history_days: int = 30
    sync_state_path: str = ""
    wechat_db_dir: str = ""
    decrypted_db_dir: str = ""
    wal_poll_interval_ms: int = 100
    db_sync_timestamp: int = 0

    def _resolve_path(self, field: str, default_subpath: str) -> str:
        """Resolve a path field: if empty, use data_dir()/default_subpath."""
        val = getattr(self, field)
        if val:
            return val
        return str(data_dir() / default_subpath)

    @property
    def resolved_sync_state_path(self) -> str:
        return self._resolve_path("sync_state_path", "sync_state.json")

    @property
    def resolved_decrypted_db_dir(self) -> str:
        return self._resolve_path("decrypted_db_dir", "decrypted")

    def save(self) -> None:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self.model_dump(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls) -> "AppConfig":
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return cls(**data)
        # Fall back to environment variables.
        return cls(
            orchestrator_url=os.getenv("ORCHESTRATOR_URL", cls.model_fields["orchestrator_url"].default),
            orchestrator_ws_url=os.getenv("ORCHESTRATOR_WS_URL", cls.model_fields["orchestrator_ws_url"].default),
            agent_token=os.getenv("AGENT_TOKEN", ""),
            poll_interval=float(os.getenv("POLL_INTERVAL", str(cls.model_fields["poll_interval"].default))),
            scroll_delay_ms=int(os.getenv("SCROLL_DELAY_MS", str(cls.model_fields["scroll_delay_ms"].default))),
            max_history_days=int(os.getenv("MAX_HISTORY_DAYS", str(cls.model_fields["max_history_days"].default))),
            sync_state_path=os.getenv("SYNC_STATE_PATH", ""),
            wechat_db_dir=os.getenv("WECHAT_DB_DIR", ""),
            decrypted_db_dir=os.getenv("DECRYPTED_DB_DIR", ""),
            wal_poll_interval_ms=int(os.getenv("WAL_POLL_INTERVAL_MS", str(cls.model_fields["wal_poll_interval_ms"].default))),
            db_sync_timestamp=int(os.getenv("DB_SYNC_TIMESTAMP", str(cls.model_fields["db_sync_timestamp"].default))),
        )
