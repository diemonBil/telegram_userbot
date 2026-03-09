"""
Orchestrator: manages the automated conversation loop for a single Telegram group.

Responsibilities:
  - Maintain the pool of Bot instances for this group
  - Pick the next bot to respond (random, never same as last)
  - Drive the autonomous conversation loop
  - Pause the loop when real-user activity is detected
  - Resume after real-user interactions are handled
"""

from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING, Optional

from loguru import logger

if TYPE_CHECKING:
    from src.bot import Bot
    from src.config import GroupConfig, AppConfig
    from src.context_manager import ContextManager


class Orchestrator:
    """
    Drives autonomous bot conversations in one Telegram group.

    The orchestrator runs a continuous async loop that:
      1. Picks a random bot (not the last one who spoke)
      2. Asks it to respond based on the current context
      3. Waits before the next round

    Real-user activity pauses the loop so reply_handler can take over,
    then resumes after a short cooldown.
    """

    def __init__(
        self,
        group_config: "GroupConfig",
        bots: list["Bot"],
        context: "ContextManager",
        app_config: "AppConfig",
    ) -> None:
        self._group_cfg = group_config
        self._bots = bots
        self._context = context
        self._app_cfg = app_config

        self._last_bot_name: Optional[str] = None
        self._running = False
        self._paused = False
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # Not paused initially

        # How many messages a bot can send in one "turn" before passing to another
        self._max_consecutive_messages = 2

        logger.info(
            f"Orchestrator ready for group '{group_config.name}' "
            f"with {len(bots)} bots"
        )

    def pick_next_bot(self) -> "Bot":
        """
        Select the next bot to respond.
        Ensures the same bot never sends two rounds in a row.
        """
        available = [b for b in self._bots if b.session_name != self._last_bot_name]
        if not available:
            # Fallback: only one bot, no choice
            available = self._bots
        chosen = random.choice(available)
        self._last_bot_name = chosen.session_name
        return chosen

    def pause(self, reason: str = "") -> None:
        """Pause the autonomous loop (e.g., real user is active)."""
        if not self._paused:
            self._paused = True
            self._pause_event.clear()
            logger.info(
                f"[{self._group_cfg.name}] Orchestrator paused"
                + (f": {reason}" if reason else "")
            )

    def resume(self, delay: float = 5.0) -> None:
        """Resume the autonomous loop after a short cooldown."""
        async def _resume_after_delay():
            await asyncio.sleep(delay)
            self._paused = False
            self._pause_event.set()
            logger.info(f"[{self._group_cfg.name}] Orchestrator resumed")

        asyncio.ensure_future(_resume_after_delay())

    async def run_loop(self) -> None:
        """
        Main autonomous conversation loop.
        Runs indefinitely until stop() is called.
        """
        self._running = True
        logger.info(f"[{self._group_cfg.name}] Starting orchestrator loop")

        while self._running:
            # Wait if paused (real user activity, startup, etc.)
            await self._pause_event.wait()

            if not self._running:
                break

            # Pick next bot and generate response
            bot = self.pick_next_bot()
            history = self._context.format_for_prompt()

            # Determine how many messages this bot will send this turn (1 or 2)
            turns = random.choices(
                [1, 2],
                weights=[1, 0],  # 100% chance of 1, 0% chance of 2
            )[0]

            for _ in range(turns):
                if not self._running or self._paused:
                    break

                await bot.respond(
                    chat_id=self._group_cfg.id,
                    context=self._context,
                    group_prompt=self._group_cfg.prompt,
                )
                print(self._context)
                # Short gap between consecutive messages from same bot
                if turns > 1:
                    await asyncio.sleep(random.uniform(2.0, 5.0))

            # Gap between bot "turns" — feels like others are reading
            inter_turn_delay = random.uniform(
                self._app_cfg.yaml.delay_min,
                self._app_cfg.yaml.delay_max,
            )
            
            # If we just resumed after a real user interaction, add extra delay
            if self._paused: # This check is tricky because _paused is set to False in resume()
                inter_turn_delay += 10.0

            logger.debug(
                f"[{self._group_cfg.name}] Next turn in {inter_turn_delay:.1f}s"
            )
            await asyncio.sleep(inter_turn_delay)

    def stop(self) -> None:
        """Stop the loop gracefully."""
        self._running = False
        self._pause_event.set()  # Unblock if waiting
        logger.info(f"[{self._group_cfg.name}] Orchestrator stopped")

    def notify_new_topic(self, topic: str) -> None:
        """Called by AdminHandler when a new topic starts."""
        self._context.set_topic(topic)
        logger.info(f"[{self._group_cfg.name}] New topic set: {topic[:60]}")
