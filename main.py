"""
Main entry point for the Telegram Userbot system.

Bootstrap order:
  1. Load and validate config (.env + config.yaml)
  2. Initialize logging
  3. Create and connect all Telegram sessions (SessionManager)
  4. Initialize Bot instances
  5. Create AIClient and MediaSender (shared across bots)
  6. Create ContextManagers (one per group)
  7. Create Orchestrators (one per group)
  8. Register AdminHandler on admin session
  9. Register ReplyHandlers (one per group)
 10. Start all orchestrator loops + run until interrupted
"""

from __future__ import annotations

import asyncio
import sys

from loguru import logger

from src.admin_handler import AdminHandler
from src.ai_client import AIClient
from src.bot import Bot
from src.config import load_config
from src.context_manager import ContextManager
from src.media_sender import MediaSender
from src.orchestrator import Orchestrator
from src.reply_handler import ReplyHandler
from src.session_manager import SessionManager


def setup_logging(log_level: str) -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> — <level>{message}</level>"
        ),
        colorize=True,
    )
    logger.add(
        "logs/userbot.log",
        level="DEBUG",
        rotation="10 MB",
        retention="7 days",
        compression="zip",
        encoding="utf-8",
    )


async def main() -> None:
    # ── 1. Config ─────────────────────────────────────────────────────────────
    try:
        config = load_config("config.yaml")
    except (FileNotFoundError, ValueError) as e:
        print(f"[ERROR] Configuration failed: {e}")
        sys.exit(1)

    setup_logging(config.env.log_level)
    logger.info("Configuration loaded successfully")

    # ── 2. Session Manager ────────────────────────────────────────────────────
    session_mgr = SessionManager(config)
    session_mgr.build_clients()

    try:
        await session_mgr.connect_all()
        # Join groups by username to ensure entity mapping exists
        await session_mgr.join_groups()
    except RuntimeError as e:
        logger.error(f"Session connection failed: {e}")
        sys.exit(1)

    # ── 3. Shared AI + Media ──────────────────────────────────────────────────
    ai_client = AIClient(
        api_key=config.env.grok_api_key,
        base_url=config.env.grok_api_base_url,
        model=config.env.grok_model,
    )
    media_sender = MediaSender(emoji_probability=0.1, gif_probability=0.08)

    # ── 4. Build Bot instances ────────────────────────────────────────────────
    bots_by_name: dict[str, Bot] = {}
    for session_cfg in config.yaml.sessions:
        client = session_mgr.get(session_cfg.name)
        bot = Bot(
            session_config=session_cfg,
            client=client,
            ai_client=ai_client,
            media_sender=media_sender,
            app_config=config,
        )
        await bot.initialize()
        bots_by_name[session_cfg.name] = bot

    logger.info(f"Initialized {len(bots_by_name)} bot(s)")

    # ── 5. Per-group setup ────────────────────────────────────────────────────
    contexts: dict[int, ContextManager] = {}
    orchestrators: dict[int, Orchestrator] = {}
    orchestrator_tasks: list[asyncio.Task] = []

    for group_cfg in config.yaml.groups:
        # Bots for this group
        group_bots = [
            bots_by_name[name]
            for name in group_cfg.participants
            if name in bots_by_name
        ]
        if not group_bots:
            logger.warning(f"Group '{group_cfg.name}': no valid bots, skipping")
            continue

        # Context
        ctx = ContextManager(
            group_id=group_cfg.id,
            group_name=group_cfg.name,
            window_size=config.yaml.context_window,
        )
        contexts[group_cfg.id] = ctx

        # Orchestrator
        orchestrator = Orchestrator(
            group_config=group_cfg,
            bots=group_bots,
            context=ctx,
            app_config=config,
        )
        orchestrators[group_cfg.id] = orchestrator

        # Reply Handler
        reply_handler = ReplyHandler(
            bots=group_bots,
            group_config=group_cfg,
            context=ctx,
            orchestrator=orchestrator,
        )
        reply_handler.register_bot_user_ids()

        # Start orchestrator loop
        task = asyncio.create_task(
            orchestrator.run_loop(),
            name=f"orchestrator-{group_cfg.name}",
        )
        orchestrator_tasks.append(task)
        logger.info(f"Group '{group_cfg.name}' started ({len(group_bots)} bots)")

    # ── 6. Admin Handler ──────────────────────────────────────────────────────
    admin_session_cfg = config.admin_session
    if admin_session_cfg and admin_session_cfg.name in bots_by_name:
        admin_bot = bots_by_name[admin_session_cfg.name]
        AdminHandler(
            admin_client=admin_bot.client,
            admin_display_name=admin_bot.display_name,
            ai_client=ai_client,
            groups=config.yaml.groups,
            contexts=contexts,
            orchestrators=orchestrators,
            app_config=config,
        )
        logger.info(f"Admin handler active on session '{admin_session_cfg.name}'")
    else:
        logger.warning(
            "No admin session configured or admin session not found. "
            "Topic changes via DM will not work."
        )

    # ── 7. Run ────────────────────────────────────────────────────────────────
    logger.info("Userbot system is running. Press Ctrl+C to stop.")
    try:
        await asyncio.gather(*orchestrator_tasks)
    except asyncio.CancelledError:
        logger.info("Shutdown signal received")
    finally:
        for orchestrator in orchestrators.values():
            orchestrator.stop()
        await ai_client.close()
        await session_mgr.disconnect_all()
        logger.info("Userbot stopped cleanly")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user.")
