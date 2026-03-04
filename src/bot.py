"""
Bot: wraps a single Telethon TelegramClient (one StringSession).

Responsible for:
  1. Asking AIClient to generate a response
  2. Simulating the typing indicator
  3. Waiting a random delay (feels human)
  4. Sending the message (optionally as a reply)
  5. Optionally sending media via MediaSender
  6. Adding the sent message to the ContextManager
"""

from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING, Optional

from loguru import logger
from telethon import TelegramClient

if TYPE_CHECKING:
    from src.ai_client import AIClient
    from src.config import SessionConfig, AppConfig
    from src.context_manager import ContextManager
    from src.media_sender import MediaSender


class Bot:
    """
    Represents a single user session acting as a chat participant.
    """

    def __init__(
        self,
        session_config: "SessionConfig",
        client: TelegramClient,
        ai_client: "AIClient",
        media_sender: "MediaSender",
        app_config: "AppConfig",
    ) -> None:
        self._cfg = session_config
        self.client = client
        self._ai = ai_client
        self._media = media_sender
        self._app_cfg = app_config

        # Will be set after connection
        self.tg_user_id: Optional[int] = None
        self.display_name: str = session_config.name

    @property
    def session_name(self) -> str:
        return self._cfg.name

    @property
    def is_admin(self) -> bool:
        return self._cfg.is_admin

    @property
    def persona(self) -> Optional[str]:
        return self._cfg.persona

    async def initialize(self) -> None:
        """Fetch and cache the Telegram user ID and display name."""
        me = await self.client.get_me()
        self.tg_user_id = me.id
        self.display_name = me.first_name or self._cfg.name
        logger.info(
            f"Bot '{self.session_name}' initialized as "
            f"'{self.display_name}' (id={self.tg_user_id})"
        )

    async def respond(
        self,
        chat_id: int,
        context: "ContextManager",
        group_prompt: str,
        trigger_message: Optional[str] = None,
        trigger_sender: Optional[str] = None,
        reply_to_msg_id: Optional[int] = None,
    ) -> Optional[int]:
        """
        Generate and send one response message in the group.

        Args:
            chat_id: Telegram group ID.
            context: The group's shared ContextManager.
            group_prompt: General topic/style prompt for this group.
            trigger_message: The latest message to respond to (optional).
            trigger_sender: Name of the last message sender (optional).
            reply_to_msg_id: If set, send as a reply to this message ID.

        Returns:
            The Telegram message ID of the sent message, or None if failed.
        """
        delay_min = self._app_cfg.yaml.delay_min
        delay_max = self._app_cfg.yaml.delay_max

        # 1. Generate AI response
        history_text = context.format_for_prompt()
        try:
            text = await self._ai.generate(
                group_prompt=group_prompt,
                history=history_text,
                persona=self.persona,
                trigger_message=trigger_message,
                sender_name=trigger_sender,
            )
        except Exception as e:
            logger.error(f"[{self.session_name}] AI generation failed: {e}")
            return None

        # 2. Simulate typing with a human-like delay
        typing_duration = random.uniform(delay_min, delay_max)
        logger.debug(
            f"[{self.session_name}] Typing for {typing_duration:.1f}s in chat {chat_id}"
        )

        try:
            async with self.client.action(chat_id, "typing"):
                await asyncio.sleep(typing_duration)
        except Exception as e:
            logger.warning(f"[{self.session_name}] Typing action failed: {e}")
            await asyncio.sleep(typing_duration)

        # 3. Send the message
        try:
            sent = await self.client.send_message(
                chat_id,
                text,
                reply_to=reply_to_msg_id,
            )
            logger.info(
                f"[{self.session_name}] Sent msg id={sent.id}: "
                f"{text[:60]}{'...' if len(text) > 60 else ''}"
            )
        except Exception as e:
            logger.error(f"[{self.session_name}] Failed to send message: {e}")
            return None

        # 4. Add to context
        context.add_message(
            sender_name=self.display_name,
            text=text,
            is_bot=True,
        )

        # 5. Optionally send media (emoji / GIF)
        await self._media.maybe_send_media(
            client=self.client,
            chat_id=chat_id,
            message_text=text,
            reply_to_msg_id=sent.id,
        )

        return sent.id

    def __repr__(self) -> str:
        return f"Bot(name={self.session_name!r}, admin={self.is_admin})"
