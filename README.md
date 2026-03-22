# WeChat PC Agent

Desktop agent for automating the Windows WeChat client and bridging messages to a remote orchestrator over WebSocket.

The app provides a PyQt6 GUI for:

- attaching to a running WeChat PC session via `wxauto`
- selecting chats to monitor
- forwarding inbound messages to an orchestrator
- receiving remote send/command requests
- collecting chat history by scrolling the UI
- decrypting WeChat message databases and tailing WAL updates for near real-time sync

## Runtime Model

This project is a Windows-targeted agent.

- Runtime automation depends on `wxauto`, `pyautogui`, and `wdecipher`
- the packaged app is built with PyInstaller
- the included manifest requests elevated privileges
- WeChat must already be running and logged in on the target machine

You can develop and run tests on non-Windows hosts, but the actual agent workflow and `.exe` packaging should be treated as Windows-only.

## Features

- GUI control panel for connect, start listening, collect history, stop, and settings
- WebSocket bridge for upstream message forwarding and downstream command handling
- event-driven chat listening through `wxauto.AddListenChat`
- history collection with local deduplication
- WeChat MSG database decryption and merged SQLite output
- WAL polling for incremental message detection after initial decrypt
- portable config and data paths for frozen builds

## Requirements

- Windows 10 or Windows 11
- desktop WeChat client installed and logged in
- Python 3.10+
- access to a WebSocket orchestrator endpoint
- administrator privileges recommended for stable WeChat/window automation

## Quick Start

### 1. Configure the agent

Create `config.json` in the project root, or next to the packaged `.exe`, using `config.example.json` as a starting point:

```json
{
  "orchestrator_ws_url": "ws://your-server:8080/ws/agent",
  "agent_token": "your-token-here",
  "poll_interval": 1.0,
  "wal_poll_interval_ms": 100
}
```

Additional supported keys:

- `scroll_delay_ms`: delay between scroll steps during history collection, default `800`
- `max_history_days`: max history window requested by the GUI, default `30`
- `sync_state_path`: optional path for history sync state JSON
- `decrypted_db_dir`: optional output directory for decrypted databases
- `db_sync_timestamp`: initial DB replay timestamp, default `0`

If `config.json` is missing, the app also reads these environment variables:

- `ORCHESTRATOR_URL`
- `ORCHESTRATOR_WS_URL`
- `AGENT_TOKEN`
- `POLL_INTERVAL`
- `SCROLL_DELAY_MS`
- `MAX_HISTORY_DAYS`
- `SYNC_STATE_PATH`
- `WECHAT_DB_DIR`
- `DECRYPTED_DB_DIR`
- `WAL_POLL_INTERVAL_MS`
- `DB_SYNC_TIMESTAMP`

### 2. Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install .[dev]
```

### 3. Run the GUI

```bash
python main.py
```

### 4. Use the app

1. Start WeChat on the same Windows machine and log in.
2. Launch the agent.
3. Click `Connect WeChat`.
4. Wait for the WebSocket bridge to connect.
5. Refresh and select chats.
6. Click `Start Listening` to stream live messages or `Collect History` to backfill older messages.

## WebSocket Behavior

The agent connects to `orchestrator_ws_url` with the token appended as a query parameter.

On connect it sends a registration envelope:

```json
{
  "type": "register",
  "data": {
    "agent_id": "agent-1"
  }
}
```

The bridge forwards inbound WeChat messages upstream as `type: "message"` envelopes and accepts downstream messages of these types:

- `send_message`
- `command`

Supported command actions:

- `search_contact`
- `send_message`
- `send_file`
- `open_chat`
- `list_contacts`
- `collect_history`

## Portable Data Layout

The app is designed to be portable in PyInstaller mode.

- `config.json` lives next to the executable
- `data/` is created next to the executable on first run
- decrypted databases default to `data/decrypted/`
- history sync state defaults to `data/sync_state.json`

## Build a Windows EXE

### Option 1: GitHub Actions

The repository includes a Windows workflow at `.github/workflows/build-exe.yml`.

1. Push your changes to GitHub.
2. Open the repository `Actions` tab.
3. Run `Build Windows EXE`.
4. Download the `WeChat-Agent-windows-x64` or `WeChat-Agent-portable` artifact.

### Option 2: Local Windows build

Run the included batch script from Windows:

```bat
build.bat
```

The output is written to:

- `release\WeChat-Agent\`

## Development

Run the test suite with:

```bash
pytest -q
```

Current local status in this repo:

- `140` tests passing

## Project Layout

```text
app/          PyQt6 GUI, widgets, worker threads
bridge/       WebSocket bridge to the orchestrator
wechat/       WeChat session, history reading, DB decrypt/reader logic
resources/    PyInstaller manifest and packaging assets
tests/        unit tests
main.py       GUI entry point
build.spec    PyInstaller spec
build.bat     Windows packaging script
```

## Notes

- This project automates a desktop messaging client. Test carefully in a non-critical environment before using it against a live account.
- Runtime success depends heavily on the target machine state: WeChat version, login state, desktop focus, permissions, and local security policy.
