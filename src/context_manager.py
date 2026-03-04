"""
Context manager: maintains a sliding window of the group's conversation history.

Each group has its own ContextManager instance.
History is stored as a list of dicts and formatted into a prompt-friendly string.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Message:
    sender_name: str
    text: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    is_bot: bool = True
    reply_to_sender: Optional[str] = None  # name of the person being replied to


class ContextManager:
    """
    Maintains a bounded history of messages for a single Telegram group.
    Acts as the shared memory that all bots in the group read before generating responses.
    """

    def __init__(self, group_id: int, group_name: str, window_size: int = 30) -> None:
        self.group_id = group_id
        self.group_name = group_name
        self._window_size = window_size
        self._history: deque[Message] = deque(maxlen=window_size)
        self._current_topic: Optional[str] = None

    def add_message(
        self,
        sender_name: str,
        text: str,
        is_bot: bool = True,
        reply_to_sender: Optional[str] = None,
    ) -> None:
        """Add a new message to the context window."""
        msg = Message(
            sender_name=sender_name,
            text=text,
            is_bot=is_bot,
            reply_to_sender=reply_to_sender,
        )
        self._history.append(msg)

    def set_topic(self, topic: str) -> None:
        """Update the current conversation topic (triggered by admin DM)."""
        self._current_topic = topic

    @property
    def current_topic(self) -> Optional[str]:
        return self._current_topic

    def get_history(self) -> list[Message]:
        """Return the current history as a list (oldest first)."""
        return list(self._history)

    def format_for_prompt(self) -> str:
        """
        Format the conversation history into a human-readable string
        suitable for inclusion in an AI prompt.

        Example output:
            Олексій: Цікаво, що думаєте про React Server Components?
            Марія: Мені здається, це майбутнє фронтенду 🔥
            Дмитро (відповідає Марії): Погоджуюсь, але холодний старт все ще проблема
        """
        lines = []
        for msg in self._history:
            if msg.reply_to_sender:
                prefix = f"{msg.sender_name} (відповідає {msg.reply_to_sender})"
            else:
                prefix = msg.sender_name
            lines.append(f"{prefix}: {msg.text}")
        return "\n".join(lines)

    def clear(self) -> None:
        """Clear the history (e.g., when a completely new topic starts)."""
        self._history.clear()

    def __len__(self) -> int:
        return len(self._history)

    def __repr__(self) -> str:
        return (
            f"ContextManager(group={self.group_name!r}, "
            f"messages={len(self)}, topic={self._current_topic!r})"
        )
