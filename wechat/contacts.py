import logging
from wechat.session import WeChatSession

logger = logging.getLogger(__name__)


class ContactCollector:
    """Collects contacts and group members from WeChat PC."""

    def __init__(self, session: WeChatSession):
        self.session = session

    def collect_sessions(self) -> list[str]:
        """Collect and store active session/chat names."""
        sessions = self.session.get_session_list()
        logger.info("Collected %d sessions", len(sessions))
        return sessions

    def collect_friends(self) -> list[str]:
        """Collect visible chats as the friend/contact list (VLM-based)."""
        return self.collect_sessions()

    def collect_all(self) -> dict:
        """Collect all available contact information."""
        sessions = self.collect_sessions()
        friends = self.collect_friends()
        return {
            "sessions": sessions,
            "friends": friends,
        }
