from __future__ import annotations

import logging
from typing import Any

from wechat.session import WeChatSession
from wechat.contacts import ContactCollector

logger = logging.getLogger(__name__)


class CommandDispatcher:
    """
    Dispatches cloud-issued commands to the appropriate wxauto action.

    Supported actions:
      - search_contact: Search WeChat for a contact by name
      - send_message: Send a text message to a contact
      - send_file: Send a file to a contact
      - open_chat: Open a chat window
      - list_contacts: Get all sessions and friends
      - history_sync: Decrypt and sync historical messages to cloud
    """

    def __init__(self, session: WeChatSession):
        self.session = session
        self._history_sync_callback: Any | None = None

    def set_history_sync_callback(self, callback: Any) -> None:
        """Set callback for starting history sync. Called with (params,) -> dict."""
        self._history_sync_callback = callback

    def dispatch(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Route an action to the right handler. Returns result dict."""
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:
            return {"status": "error", "error": f"unknown action: {action}"}
        try:
            return handler(params)
        except Exception as e:
            logger.error("Command %s failed: %s", action, e)
            return {"status": "error", "error": str(e)}

    def _do_search_contact(self, params: dict) -> dict:
        name = params.get("name", "")
        if not name:
            return {"status": "error", "error": "missing 'name' param"}
        matches = self.session.search_contact(name)
        return {"status": "ok", "data": {"query": name, "matches": matches}}

    def _do_send_message(self, params: dict) -> dict:
        to = params.get("to", "")
        content = params.get("content", "")
        if not to or not content:
            return {"status": "error", "error": "missing 'to' or 'content'"}
        ok = self.session.send_text(to, content)
        return {"status": "ok" if ok else "error", "data": {"to": to, "sent": ok}}

    def _do_send_file(self, params: dict) -> dict:
        to = params.get("to", "")
        file_path = params.get("file_path", "")
        if not to or not file_path:
            return {"status": "error", "error": "missing 'to' or 'file_path'"}
        ok = self.session.send_file(to, file_path)
        return {"status": "ok" if ok else "error", "data": {"to": to, "sent": ok}}

    def _do_open_chat(self, params: dict) -> dict:
        name = params.get("name", "")
        if not name:
            return {"status": "error", "error": "missing 'name' param"}
        ok = self.session.open_chat(name)
        return {"status": "ok" if ok else "error", "data": {"name": name, "opened": ok}}

    def _do_list_contacts(self, params: dict) -> dict:
        collector = ContactCollector(self.session)
        result = collector.collect_all()
        return {"status": "ok", "data": result}

    def _do_history_sync(self, params: dict) -> dict:
        if not self._history_sync_callback:
            return {"status": "error", "error": "history sync not configured"}
        return self._history_sync_callback(params)

