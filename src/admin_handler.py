"""
Admin Handler: listens for private messages sent to the admin user account.

When a real user sends the admin a DM:
  1. The admin generates a topic-starting message using Grok (based on the DM)
  2. That message is posted in the configured group(s)
  3. The ContextManager is updated with the new topic
  4. The Orchestrator is notified to shift the conversation

This is the entry point for all topic changes in the system.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger
from telethon import TelegramClient, events
from telethon.tl.types import User

if TYPE_CHECKING:
    from src.ai_client import AIClient
    from src.config import AppConfig, GroupConfig
    from src.context_manager import ContextManager
    from src.orchestrator import Orchestrator


_TOPIC_STARTER_SYSTEM = """\
Ти адміністратор Telegram-групи. Тобі надходить нова тема для обговорення.
Сформуй природне, живе повідомлення для групи, щоб розпочати обговорення цієї теми.
Повідомлення має звучати як від живої людини, а не як оголошення.
Довжина: 1–3 речення. Не вказуй що це "нова тема" або "пропоную обговорити".
"""


class AdminHandler:
    """
    Handles incoming DMs to the admin account and converts them into
    group topic-starter messages.
    """

    def __init__(
        self,
        admin_client: TelegramClient,
        admin_display_name: str,
        ai_client: "AIClient",
        groups: list["GroupConfig"],
        contexts: dict[int, "ContextManager"],
        orchestrators: dict[int, "Orchestrator"],
        app_config: "AppConfig",
    ) -> None:
        self._client = admin_client
        self._admin_name = admin_display_name
        self._ai = ai_client
        self._groups = groups
        self._contexts = contexts           # group_id -> ContextManager
        self._orchestrators = orchestrators  # group_id -> Orchestrator
        self._app_cfg = app_config

        # Register the event handler
        self._client.add_event_handler(
            self._on_dm,
            events.NewMessage(incoming=True, func=lambda e: e.is_private),
        )
        logger.info(f"AdminHandler registered for account '{admin_display_name}'")

    async def _on_dm(self, event: events.NewMessage.Event) -> None:
        """Called when the admin receives a private message."""
        sender: User = await event.get_sender()
        dm_text = event.message.text

        if not dm_text:
            logger.debug("AdminHandler: received non-text DM, ignoring")
            return

        logger.info(
            f"AdminHandler: DM from {sender.first_name} (id={sender.id}): "
            f"{dm_text[:80]}"
        )

        # Generate a topic-starter message for each group
        for group in self._groups:
            context = self._contexts.get(group.id)
            orchestrator = self._orchestrators.get(group.id)
            if not context or not orchestrator:
                continue

            try:
                starter_msg = await self._ai.generate(
                    group_prompt=_TOPIC_STARTER_SYSTEM,
                    history="",
                    persona=self._app_cfg.sessions_by_name.get(
                        self._app_cfg.admin_session.name if self._app_cfg.admin_session else "", None
                    ) and self._app_cfg.admin_session.persona,
                    trigger_message=dm_text,
                    sender_name=sender.first_name,
                )
            except Exception as e:
                logger.error(f"AdminHandler: AI generation failed: {e}")
                continue

            # Pause orchestrator so bots don't fire while admin is typing
            orchestrator.pause("admin posting new topic")

            # Simulate admin typing
            try:
                async with self._client.action(group.id, "typing"):
                    await asyncio.sleep(3)
            except Exception:
                await asyncio.sleep(3)

            # Send the topic starter to the group
            try:
                sent = await self._client.send_message(group.id, starter_msg)
                logger.info(
                    f"AdminHandler: topic started in '{group.name}' "
                    f"(msg_id={sent.id}): {starter_msg[:60]}"
                )
            except Exception as e:
                logger.error(f"AdminHandler: failed to send to group {group.id}: {e}")
                orchestrator.resume()
                continue

            # Update context with new topic and the starter message
            context.set_topic(dm_text)
            context.add_message(
                sender_name=self._admin_name,
                text=starter_msg,
                is_bot=True,
            )

            # Let orchestrator resume bots after a short pause
            orchestrator.resume(delay=8.0)

    def unregister(self) -> None:
        """Remove the event handler."""
        self._client.remove_event_handler(self._on_dm)
