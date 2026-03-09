"""
Reply Handler: monitors all group messages and detects when a real user
replies to a bot's message.

When detected:
  1. Identifies which bot was replied to
  2. Pauses the orchestrator
  3. Triggers that specific bot to respond in reply-thread format
  4. Resumes the orchestrator after the reply is sent
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional

from loguru import logger
from telethon import TelegramClient, events
from telethon.tl.types import User

if TYPE_CHECKING:
    from src.bot import Bot
    from src.config import GroupConfig
    from src.context_manager import ContextManager
    from src.orchestrator import Orchestrator


class ReplyHandler:
    """
    Listens to group messages via all bot clients.
    Routes real-user replies to the appropriate bot session.

    Note: We register the listener on ALL clients so that any one
    that receives the update first triggers the handler. A lock ensures
    only one bot responds per real-user message.
    """

    def __init__(
        self,
        bots: list["Bot"],
        group_config: "GroupConfig",
        context: "ContextManager",
        orchestrator: "Orchestrator",
    ) -> None:
        self._bots = bots
        self._bot_by_user_id: dict[int, "Bot"] = {}
        self._group_cfg = group_config
        self._context = context
        self._orchestrator = orchestrator
        self._response_lock = asyncio.Lock()
        self._handled_message_ids: set[int] = set()
        self._max_id_cache = 100

        # Register handlers for each bot client
        for bot in bots:
            bot.client.add_event_handler(
                self._on_group_message,
                events.NewMessage(
                    chats=[group_config.id],
                    incoming=True,
                ),
            )

        logger.info(
            f"ReplyHandler registered for group '{group_config.name}' "
            f"across {len(bots)} clients"
        )

    def register_bot_user_ids(self) -> None:
        """
        Build the user_id → Bot mapping.
        Must be called AFTER all bots have been initialized (tg_user_id set).
        """
        self._bot_by_user_id = {
            bot.tg_user_id: bot
            for bot in self._bots
            if bot.tg_user_id is not None
        }
        logger.debug(
            f"ReplyHandler: mapped {len(self._bot_by_user_id)} bot user IDs "
            f"in group '{self._group_cfg.name}'"
        )

    def _should_handle(self, msg_id: int) -> bool:
        """Check if this message has already been handled by another client."""
        if msg_id in self._handled_message_ids:
            return False
        
        # Add to cache and prune if too large
        self._handled_message_ids.add(msg_id)
        if len(self._handled_message_ids) > self._max_id_cache:
            # Remove the oldest (roughly, it's a set, but for small sizes it's fine)
            # Better: convert to list and remove first element
            ids = list(self._handled_message_ids)
            self._handled_message_ids = set(ids[-self._max_id_cache:])
            
        return True

    async def _on_group_message(self, event: events.NewMessage.Event) -> None:
        """Called for every incoming message in the group."""
        msg = event.message

        # Deduplicate: only one client should process this message ID
        if not self._should_handle(msg.id):
            return

        # We only care about messages that are replies
        if not msg.reply_to_msg_id:
            # Still: if a real user (not bot) sends a non-reply message, add it to context
            await self._handle_real_user_message(event)
            return

        # Check if it's a reply to one of our bots
        try:
            original_msg = await event.get_reply_message()
        except Exception as e:
            logger.debug(f"ReplyHandler: could not get reply message: {e}")
            return

        if original_msg is None:
            return

        # Is the original message from one of our bots?
        replied_to_bot = self._bot_by_user_id.get(original_msg.sender_id)
        if replied_to_bot is None:
            # Reply is to a real user or unknown — still update context
            await self._handle_real_user_message(event)
            return

        # Is the current message from a real user (not one of our bots)?
        sender_id = msg.sender_id
        if sender_id in self._bot_by_user_id:
            return  # Bot replying to bot — orchestrator handles this

        # At this point: real user replied to one of our bots
        sender: Optional[User] = await event.get_sender()
        sender_name = sender.first_name if sender else "Користувач"
        real_user_text = msg.text or ""

        if not real_user_text:
            return

        logger.info(
            f"ReplyHandler: real user '{sender_name}' replied to bot "
            f"'{replied_to_bot.session_name}' in '{self._group_cfg.name}'"
        )

        # Add real user's message to context
        self._context.add_message(
            sender_name=sender_name,
            text=real_user_text,
            is_bot=False,
            reply_to_sender=replied_to_bot.display_name,
        )

        # Use lock to prevent race conditions across multiple client listeners
        async with self._response_lock:
            self._orchestrator.pause("real user reply detected")

            await replied_to_bot.respond(
                chat_id=self._group_cfg.id,
                context=self._context,
                group_prompt=self._group_cfg.prompt,
                trigger_message=real_user_text,
                trigger_sender=sender_name,
                reply_to_msg_id=msg.id,
            )

            self._orchestrator.resume(delay=15.0)

    async def _handle_real_user_message(self, event: events.NewMessage.Event) -> None:
        """
        If a real user sends a non-reply message in the group,
        add it to context and briefly pause the orchestrator.
        """
        msg = event.message
        sender_id = msg.sender_id

        if sender_id in self._bot_by_user_id:
            return  # This is a bot message, orchestrator handles context update

        sender: Optional[User] = await event.get_sender()
        sender_name = sender.first_name if sender else "Користувач"
        text = msg.text or ""

        if not text:
            return

        logger.info(
            f"ReplyHandler: real user '{sender_name}' sent a message in "
            f"'{self._group_cfg.name}': {text[:60]}"
        )

        self._context.add_message(
            sender_name=sender_name,
            text=text,
            is_bot=False,
        )

        # Briefly pause so bots "read" the message before responding
        self._orchestrator.pause("real user message")
        self._orchestrator.resume(delay=6.0)

    def unregister(self) -> None:
        """Remove all event handlers."""
        for bot in self._bots:
            bot.client.remove_event_handler(self._on_group_message)
