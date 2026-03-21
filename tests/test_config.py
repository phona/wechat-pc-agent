import json
import os
import pytest
from unittest.mock import patch
from pathlib import Path

from config import AppConfig


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Override CONFIG_FILE for testing."""
    config_file = tmp_path / "config.json"
    with patch("config.CONFIG_FILE", config_file):
        yield tmp_path, config_file


def test_defaults():
    cfg = AppConfig()
    assert cfg.orchestrator_url == "http://localhost:8080"
    assert cfg.orchestrator_ws_url == "ws://localhost:8080/ws/agent"
    assert cfg.agent_token == ""
    assert cfg.max_history_days == 30
    assert cfg.sync_state_path == ""
    assert cfg.wechat_db_dir == ""
    assert cfg.decrypted_db_dir == ""
    assert cfg.wal_poll_interval_ms == 100
    assert cfg.db_sync_timestamp == 0


def test_resolved_paths_default_to_data_dir():
    cfg = AppConfig()
    # When empty, resolved paths use data_dir()
    assert cfg.resolved_sync_state_path.endswith("sync_state.json")
    assert cfg.resolved_decrypted_db_dir.endswith("decrypted")


def test_resolved_paths_use_explicit_values():
    cfg = AppConfig(sync_state_path="/custom/sync.json", decrypted_db_dir="/custom/dec")
    assert cfg.resolved_sync_state_path == "/custom/sync.json"
    assert cfg.resolved_decrypted_db_dir == "/custom/dec"


def test_save_and_load(tmp_config_dir):
    _, config_file = tmp_config_dir

    cfg = AppConfig(
        orchestrator_url="http://10.0.0.1:8080",
        orchestrator_ws_url="ws://10.0.0.1:8080/ws/agent",
        agent_token="my-secret",
    )
    cfg.save()

    assert config_file.exists()
    data = json.loads(config_file.read_text())
    assert data["orchestrator_url"] == "http://10.0.0.1:8080"
    assert data["orchestrator_ws_url"] == "ws://10.0.0.1:8080/ws/agent"
    assert data["agent_token"] == "my-secret"

    loaded = AppConfig.load()
    assert loaded.orchestrator_url == "http://10.0.0.1:8080"
    assert loaded.orchestrator_ws_url == "ws://10.0.0.1:8080/ws/agent"
    assert loaded.agent_token == "my-secret"


def test_load_from_env(tmp_config_dir):
    """When no config file exists, load from environment variables."""
    env = {
        "ORCHESTRATOR_URL": "http://env-host:8080",
        "ORCHESTRATOR_WS_URL": "ws://env-host:8080/ws/agent",
        "AGENT_TOKEN": "env-token",
        "MAX_HISTORY_DAYS": "60",
        "SYNC_STATE_PATH": "/tmp/sync.json",
    }
    with patch.dict(os.environ, env, clear=False):
        cfg = AppConfig.load()

    assert cfg.orchestrator_url == "http://env-host:8080"
    assert cfg.orchestrator_ws_url == "ws://env-host:8080/ws/agent"
    assert cfg.agent_token == "env-token"
    assert cfg.max_history_days == 60
    assert cfg.sync_state_path == "/tmp/sync.json"


def test_load_defaults_when_no_env(tmp_config_dir):
    """When no config file and no env vars, use defaults."""
    env_keys = [
        "ORCHESTRATOR_URL", "ORCHESTRATOR_WS_URL", "AGENT_TOKEN",
        "MAX_HISTORY_DAYS", "SYNC_STATE_PATH", "WECHAT_DB_DIR",
        "DECRYPTED_DB_DIR", "WAL_POLL_INTERVAL_MS", "DB_SYNC_TIMESTAMP",
    ]
    clean_env = {k: v for k, v in os.environ.items() if k not in env_keys}
    with patch.dict(os.environ, clean_env, clear=True):
        cfg = AppConfig.load()

    assert cfg.orchestrator_url == "http://localhost:8080"
    assert cfg.orchestrator_ws_url == "ws://localhost:8080/ws/agent"


def test_save_creates_directory(tmp_path):
    config_file = tmp_path / "subdir" / "config.json"
    with patch("config.CONFIG_FILE", config_file):
        cfg = AppConfig()
        cfg.save()
        assert config_file.exists()
