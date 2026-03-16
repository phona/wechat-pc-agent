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
        """Collect the friend list."""
        try:
            friends = self.session.wx.GetAllFriends()
            names = []
            if friends:
                for f in friends:
                    name = str(f) if isinstance(f, str) else getattr(f, "name", str(f))
                    names.append(name)
            logger.info("Collected %d friends", len(names))
            return names
        except Exception as e:
            logger.error("Failed to collect friends: %s", e)
            return []

    def collect_all(self) -> dict:
        """Collect all available contact information."""
        sessions = self.collect_sessions()
        friends = self.collect_friends()
        return {
            "sessions": sessions,
            "friends": friends,
        }
