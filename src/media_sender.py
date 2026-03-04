"""
Media Sender: decides whether to send media (emoji, GIF, sticker) alongside a message,
based on basic sentiment analysis of the generated text.

Keeps it simple: keyword matching is enough for natural feel.
Heavy ML sentiment analysis would be overkill here.
"""

from __future__ import annotations

import random
from typing import Optional

from loguru import logger
from telethon import TelegramClient
from telethon.tl.functions.messages import GetStickerSetRequest
from telethon.tl.types import InputStickerSetShortName


# Emoji that fit naturally after certain emotional tones
_POSITIVE_REACTIONS = ["😄", "🔥", "👍", "💯", "😎", "🚀", "✅", "💪"]
_FUNNY_REACTIONS = ["😂", "🤣", "💀", "😅", "🙈"]
_THOUGHTFUL_REACTIONS = ["🤔", "💭", "👀", "🧐"]
_AGREEMENT_REACTIONS = ["☝️", "+1", "💯", "саме так", "точно", "згоден"]

# Keywords that trigger different emotional reactions
_POSITIVE_KEYWORDS = [
    "круто", "чудово", "відмінно", "клас", "топ", "шикарно",
    "супер", "молодець", "excellent", "great", "nice", "cool",
]
_FUNNY_KEYWORDS = [
    "😂", "ха", "смішно", "жарт", "прикол", "lol", "хаха",
]
_QUESTION_KEYWORDS = ["?", "як ти думаєш", "як гадаєш", "що скажеш"]


def _detect_sentiment(text: str) -> str:
    """
    Rough sentiment detection based on keyword presence.
    Returns: 'positive', 'funny', 'thoughtful', or 'neutral'
    """
    lower = text.lower()
    if any(kw in lower for kw in _FUNNY_KEYWORDS):
        return "funny"
    if any(kw in lower for kw in _POSITIVE_KEYWORDS):
        return "positive"
    if any(kw in lower for kw in _QUESTION_KEYWORDS):
        return "thoughtful"
    return "neutral"


class MediaSender:
    """
    Optionally sends emoji or GIF after a bot message.
    Probability of sending media is configurable to avoid spam.
    """

    def __init__(self, emoji_probability: float = 0.3, gif_probability: float = 0.08) -> None:
        """
        Args:
            emoji_probability: Chance of appending an emoji-only reaction message.
            gif_probability: Chance of sending a GIF (low by default — feels more natural).
        """
        self.emoji_probability = emoji_probability
        self.gif_probability = gif_probability

    async def maybe_send_media(
        self,
        client: TelegramClient,
        chat_id: int,
        message_text: str,
        reply_to_msg_id: Optional[int] = None,
    ) -> bool:
        """
        Decide whether to send a media supplement after the main message.

        Returns True if media was sent, False otherwise.
        """
        sentiment = _detect_sentiment(message_text)

        # Try to send GIF first (rare, more impactful)
        if random.random() < self.gif_probability:
            sent = await self._send_gif(client, chat_id, sentiment, reply_to_msg_id)
            if sent:
                return True

        # Fallback: emoji reaction (more common)
        if random.random() < self.emoji_probability:
            await self._send_emoji(client, chat_id, sentiment, reply_to_msg_id)
            return True

        return False

    async def _send_emoji(
        self,
        client: TelegramClient,
        chat_id: int,
        sentiment: str,
        reply_to_msg_id: Optional[int],
    ) -> None:
        """Send a standalone emoji message matching the sentiment."""
        pool: list[str]
        if sentiment == "funny":
            pool = _FUNNY_REACTIONS
        elif sentiment == "positive":
            pool = _POSITIVE_REACTIONS
        elif sentiment == "thoughtful":
            pool = _THOUGHTFUL_REACTIONS
        else:
            # Neutral — skip standalone emoji, feels unnatural
            return

        emoji = random.choice(pool)
        try:
            await client.send_message(
                chat_id,
                emoji,
                reply_to=reply_to_msg_id,
            )
            logger.debug(f"Sent emoji '{emoji}' to chat {chat_id}")
        except Exception as e:
            logger.warning(f"Failed to send emoji: {e}")

    async def _send_gif(
        self,
        client: TelegramClient,
        chat_id: int,
        sentiment: str,
        reply_to_msg_id: Optional[int],
    ) -> bool:
        """
        Attempt to send a GIF via inline bot search (@gif).
        Falls back gracefully if it fails.
        """
        gif_queries = {
            "funny": ["haha", "lol", "laughing"],
            "positive": ["yes", "nice", "good job"],
            "thoughtful": ["thinking", "hmm"],
            "neutral": [],
        }
        queries = gif_queries.get(sentiment, [])
        if not queries:
            return False

        query = random.choice(queries)
        try:
            results = await client.inline_query("gif", query)
            if results:
                chosen = random.choice(results[:5])  # pick from top 5
                await chosen.click(chat_id, reply_to=reply_to_msg_id)
                logger.debug(f"Sent GIF (query='{query}') to chat {chat_id}")
                return True
        except Exception as e:
            logger.debug(f"GIF send failed (query='{query}'): {e}")

        return False
