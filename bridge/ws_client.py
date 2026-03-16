import asyncio
import json
import logging
from queue import Queue
from typing import Optional

import websockets
from websockets.exceptions import ConnectionClosed

from wechat.commander import CommandDispatcher

logger = logging.getLogger(__name__)


class WebSocketBridge:
    """
    Bi-directional WebSocket bridge replacing both ReplyServer and IngestClient.

    Upstream (agent → orchestrator): forward_message() queues messages to send.
    Downstream (orchestrator → agent): send_message → send_queue, command → dispatcher.
    """

    def __init__(
        self,
        ws_url: str,
        token: str,
        send_queue: Queue,
        commander: Optional[CommandDispatcher] = None,
        agent_id: str = "agent-1",
    ):
        self.ws_url = ws_url
        self.token = token
        self.send_queue = send_queue
        self.commander = commander
        self.agent_id = agent_id
        self._ws = None
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ingest_queue: Optional[asyncio.Queue] = None

    def forward_message(
        self,
        sender_id: str,
        conversation_id: str,
        msg_type: str = "text",
        content: str = "",
        **kwargs,
    ) -> bool:
        """Thread-safe: queue a message for upstream delivery."""
        if self._loop is None or self._ingest_queue is None:
            logger.warning("WebSocket not running, message dropped")
            return False

        envelope = {
            "type": "message",
            "data": {
                "sender_id": sender_id,
                "conversation_id": conversation_id,
                "msg_type": msg_type,
                "content": content,
                "origin": "wechat_pc",
            },
        }
        try:
            self._loop.call_soon_threadsafe(self._ingest_queue.put_nowait, envelope)
            return True
        except Exception as e:
            logger.error("Failed to queue message: %s", e)
            return False

    def health_check(self) -> bool:
        """Check if WebSocket is connected."""
        return self._ws is not None and self._ws.open

    async def run(self):
        """Main loop: connect, communicate, reconnect on failure."""
        self._running = True
        self._ingest_queue = asyncio.Queue()
        backoff = 1.0

        while self._running:
            try:
                url = f"{self.ws_url}?token={self.token}"
                logger.info("Connecting to %s", self.ws_url)
                async with websockets.connect(url) as ws:
                    self._ws = ws
                    backoff = 1.0

                    # Send register message
                    await ws.send(json.dumps({
                        "type": "register",
                        "data": {"agent_id": self.agent_id},
                    }))
                    logger.info("Registered as %s", self.agent_id)

                    # Run read and write pumps concurrently
                    await asyncio.gather(
                        self._read_pump(ws),
                        self._write_pump(ws),
                    )
            except (ConnectionClosed, ConnectionRefusedError, OSError) as e:
                logger.warning("WebSocket disconnected: %s, reconnecting in %.1fs", e, backoff)
            except Exception as e:
                logger.error("WebSocket error: %s, reconnecting in %.1fs", e, backoff)
            finally:
                self._ws = None

            if not self._running:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    async def _read_pump(self, ws):
        """Read downstream messages from orchestrator."""
        async for raw in ws:
            try:
                env = json.loads(raw)
            except json.JSONDecodeError:
                logger.error("Invalid JSON from orchestrator")
                continue

            msg_type = env.get("type", "")
            data = env.get("data", {})

            if msg_type == "send_message":
                self.send_queue.put({
                    "chat_name": data.get("touser", ""),
                    "content": data.get("content", ""),
                    "msgtype": "text",
                })
                logger.info("Queued send to %s", data.get("touser"))

            elif msg_type == "command":
                if self.commander:
                    action = data.get("action", "")
                    params = data.get("params", {})
                    result = self.commander.dispatch(action, params)
                    # Send result back
                    response = {
                        "type": "command_result",
                        "request_id": env.get("request_id", ""),
                        "data": result,
                    }
                    await ws.send(json.dumps(response))
                    logger.info("Command %s executed: %s", action, result.get("status"))
                else:
                    logger.warning("No commander, ignoring command: %s", data.get("action"))

    async def _write_pump(self, ws):
        """Send upstream messages to orchestrator."""
        while self._running:
            try:
                envelope = await asyncio.wait_for(self._ingest_queue.get(), timeout=1.0)
                await ws.send(json.dumps(envelope))
            except asyncio.TimeoutError:
                continue
            except ConnectionClosed:
                break

    def stop(self):
        """Signal the bridge to stop."""
        self._running = False
