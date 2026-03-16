"""Tests for the WebSocket bridge client."""
import asyncio
import json
import pytest
from queue import Queue
from unittest.mock import AsyncMock, MagicMock, patch

from websockets.exceptions import ConnectionClosed

from bridge.ws_client import WebSocketBridge


@pytest.fixture
def bridge():
    q = Queue()
    commander = MagicMock()
    b = WebSocketBridge(
        ws_url="ws://localhost:8080/ws/agent",
        token="test-token",
        send_queue=q,
        commander=commander,
        agent_id="agent-test",
    )
    return b


class TestForwardMessage:
    def test_returns_false_when_not_running(self, bridge):
        """forward_message returns False when loop/queue not initialized."""
        assert bridge.forward_message("sender1", "conv1", "text", "hello") is False

    def test_queues_message_when_running(self, bridge):
        """forward_message puts envelope on the ingest queue."""
        loop = asyncio.new_event_loop()
        bridge._loop = loop
        bridge._ingest_queue = asyncio.Queue()

        result = bridge.forward_message("sender1", "conv1", "text", "hello")
        assert result is True

        # Run pending callbacks so call_soon_threadsafe fires
        loop.run_until_complete(asyncio.sleep(0))

        # Check the queued envelope
        envelope = bridge._ingest_queue.get_nowait()
        assert envelope["type"] == "message"
        assert envelope["data"]["sender_id"] == "sender1"
        assert envelope["data"]["conversation_id"] == "conv1"
        assert envelope["data"]["content"] == "hello"
        assert envelope["data"]["origin"] == "wechat_pc"
        loop.close()


class TestHealthCheck:
    def test_not_connected(self, bridge):
        assert bridge.health_check() is False

    def test_connected(self, bridge):
        mock_ws = MagicMock()
        mock_ws.open = True
        bridge._ws = mock_ws
        assert bridge.health_check() is True

    def test_disconnected_ws(self, bridge):
        mock_ws = MagicMock()
        mock_ws.open = False
        bridge._ws = mock_ws
        assert bridge.health_check() is False


class TestStop:
    def test_stop_sets_flag(self, bridge):
        bridge._running = True
        bridge.stop()
        assert bridge._running is False


class TestReadPump:
    @pytest.mark.asyncio
    async def test_routes_send_message(self, bridge):
        """Downstream send_message goes into send_queue."""
        msg = json.dumps({"type": "send_message", "data": {"touser": "GroupA", "content": "hi"}})
        mock_ws = AsyncMock()
        mock_ws.__aiter__ = lambda self: self
        mock_ws.__anext__ = AsyncMock(side_effect=[msg, StopAsyncIteration])

        await bridge._read_pump(mock_ws)

        item = bridge.send_queue.get_nowait()
        assert item["chat_name"] == "GroupA"
        assert item["content"] == "hi"

    @pytest.mark.asyncio
    async def test_routes_command(self, bridge):
        """Downstream command is dispatched and result sent back."""
        bridge.commander.dispatch.return_value = {"status": "ok"}
        msg = json.dumps({
            "type": "command",
            "request_id": "req-123",
            "data": {"action": "search_contact", "params": {"name": "Alice"}},
        })
        mock_ws = AsyncMock()
        mock_ws.__aiter__ = lambda self: self
        mock_ws.__anext__ = AsyncMock(side_effect=[msg, StopAsyncIteration])

        await bridge._read_pump(mock_ws)

        bridge.commander.dispatch.assert_called_once_with("search_contact", {"name": "Alice"})
        # Verify response was sent
        sent = mock_ws.send.call_args[0][0]
        parsed = json.loads(sent)
        assert parsed["type"] == "command_result"
        assert parsed["request_id"] == "req-123"
        assert parsed["data"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_ignores_invalid_json(self, bridge):
        """Invalid JSON is skipped without error."""
        mock_ws = AsyncMock()
        mock_ws.__aiter__ = lambda self: self
        mock_ws.__anext__ = AsyncMock(side_effect=["not-json", StopAsyncIteration])

        await bridge._read_pump(mock_ws)
        # No exception raised


class TestWritePump:
    @pytest.mark.asyncio
    async def test_sends_queued_messages(self, bridge):
        """Write pump sends envelopes from the ingest queue."""
        bridge._running = True
        bridge._ingest_queue = asyncio.Queue()
        envelope = {"type": "message", "data": {"content": "test"}}
        await bridge._ingest_queue.put(envelope)

        mock_ws = AsyncMock()

        # Stop after first message
        async def stop_after_send(*args):
            bridge._running = False

        mock_ws.send.side_effect = stop_after_send

        await bridge._write_pump(mock_ws)

        sent = mock_ws.send.call_args[0][0]
        parsed = json.loads(sent)
        assert parsed["type"] == "message"
        assert parsed["data"]["content"] == "test"

    @pytest.mark.asyncio
    async def test_write_pump_stops_on_connection_closed(self, bridge):
        """Write pump exits when ws.send raises ConnectionClosed."""
        from websockets.exceptions import ConnectionClosed
        from websockets.frames import Close

        bridge._running = True
        bridge._ingest_queue = asyncio.Queue()
        await bridge._ingest_queue.put({"type": "message", "data": {}})

        mock_ws = AsyncMock()
        mock_ws.send.side_effect = ConnectionClosed(Close(1000, "bye"), None)

        await bridge._write_pump(mock_ws)
        # Should exit cleanly without raising


class TestRunLoop:
    @pytest.mark.asyncio
    async def test_run_registers_and_calls_pumps(self, bridge):
        """run() connects, sends register, and runs read/write pumps."""
        mock_ws = AsyncMock()
        mock_ws.open = True

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_ws)
        cm.__aexit__ = AsyncMock(return_value=False)

        original_gather = asyncio.gather
        async def fake_gather(*coros):
            bridge._running = False
            for c in coros:
                c.close()

        with patch("websockets.connect", return_value=cm), \
             patch.object(asyncio, "gather", side_effect=fake_gather):
            await bridge.run()

        register_call = mock_ws.send.call_args_list[0][0][0]
        parsed = json.loads(register_call)
        assert parsed["type"] == "register"
        assert parsed["data"]["agent_id"] == "agent-test"

    @pytest.mark.asyncio
    async def test_run_reconnects_on_connection_closed(self, bridge):
        """run() reconnects with backoff after ConnectionClosed."""
        from websockets.frames import Close

        attempt = 0

        def fake_connect(*args, **kwargs):
            nonlocal attempt
            attempt += 1
            if attempt >= 2:
                bridge._running = False
            raise ConnectionClosed(Close(1000, "bye"), None)

        with patch("websockets.connect", side_effect=fake_connect), \
             patch.object(asyncio, "sleep", new_callable=AsyncMock) as mock_sleep:
            await bridge.run()

        assert attempt == 2
        mock_sleep.assert_called_with(1.0)

    @pytest.mark.asyncio
    async def test_run_exponential_backoff(self, bridge):
        """Backoff doubles after each failure."""
        from websockets.frames import Close

        attempt = 0
        backoffs = []

        def fake_connect(*args, **kwargs):
            nonlocal attempt
            attempt += 1
            if attempt > 4:
                bridge._running = False
            raise ConnectionClosed(Close(1000, "bye"), None)

        async def capture_sleep(t):
            backoffs.append(t)

        with patch("websockets.connect", side_effect=fake_connect), \
             patch.object(asyncio, "sleep", side_effect=capture_sleep):
            await bridge.run()

        assert backoffs == [1.0, 2.0, 4.0, 8.0]

    @pytest.mark.asyncio
    async def test_run_resets_backoff_on_success(self, bridge):
        """Backoff resets to 1.0 after a successful connection."""
        from websockets.frames import Close

        attempt = 0
        backoffs = []

        cm = AsyncMock()
        mock_ws = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_ws)
        cm.__aexit__ = AsyncMock(return_value=False)

        def fake_connect(*args, **kwargs):
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise ConnectionRefusedError("refused")
            if attempt == 3:
                bridge._running = False
                raise ConnectionRefusedError("refused")
            return cm  # attempt 2 succeeds

        async def fake_gather(*coros):
            for c in coros:
                c.close()
            raise ConnectionClosed(Close(1000, "bye"), None)

        async def capture_sleep(t):
            backoffs.append(t)

        with patch("websockets.connect", side_effect=fake_connect), \
             patch.object(asyncio, "gather", side_effect=fake_gather), \
             patch.object(asyncio, "sleep", side_effect=capture_sleep):
            await bridge.run()

        # First fail: backoff 1.0, success resets, second fail: backoff 1.0 again
        assert backoffs == [1.0, 1.0]

    @pytest.mark.asyncio
    async def test_run_clears_ws_on_disconnect(self, bridge):
        """_ws is set to None in the finally block after disconnect."""
        cm = AsyncMock()
        mock_ws = AsyncMock()
        mock_ws.open = True
        cm.__aenter__ = AsyncMock(return_value=mock_ws)
        cm.__aexit__ = AsyncMock(return_value=False)

        async def fake_gather(*coros):
            for c in coros:
                c.close()
            bridge._running = False

        with patch("websockets.connect", return_value=cm), \
             patch.object(asyncio, "gather", side_effect=fake_gather):
            await bridge.run()

        assert bridge._ws is None


class TestReadPumpEdgeCases:
    @pytest.mark.asyncio
    async def test_command_without_commander(self, bridge):
        """Command is ignored when no commander is set."""
        bridge.commander = None
        msg = json.dumps({"type": "command", "data": {"action": "test"}})
        mock_ws = AsyncMock()
        mock_ws.__aiter__ = lambda self: self
        mock_ws.__anext__ = AsyncMock(side_effect=[msg, StopAsyncIteration])

        await bridge._read_pump(mock_ws)
        # No exception, no send call
        mock_ws.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_message_type_is_ignored(self, bridge):
        """Unknown message types don't cause errors."""
        msg = json.dumps({"type": "unknown_type", "data": {}})
        mock_ws = AsyncMock()
        mock_ws.__aiter__ = lambda self: self
        mock_ws.__anext__ = AsyncMock(side_effect=[msg, StopAsyncIteration])

        await bridge._read_pump(mock_ws)
        bridge.send_queue.empty()
