"""
Session Manager: loads and authenticates Telethon TelegramClient instances
from StringSession strings defined in config.yaml.

Each session corresponds to one real Telegram user account.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from telethon import TelegramClient
from telethon.sessions import StringSession

if TYPE_CHECKING:
    from src.config import AppConfig, SessionConfig


class SessionManager:
    """
    Manages the lifecycle of all Telethon client sessions.
    Creates clients from StringSession strings and provides them by name.
    """

    def __init__(self, config: "AppConfig") -> None:
        self._config = config
        self._clients: dict[str, TelegramClient] = {}

    def build_clients(self) -> dict[str, TelegramClient]:
        """
        Create TelegramClient instances for all configured sessions.
        Does NOT connect them — call connect_all() separately.
        """
        api_id = self._config.env.telegram_api_id
        api_hash = self._config.env.telegram_api_hash

        for session_cfg in self._config.yaml.sessions:
            client = TelegramClient(
                StringSession(session_cfg.string_session),
                api_id,
                api_hash,
            )
            self._clients[session_cfg.name] = client
            logger.info(f"Created client for session '{session_cfg.name}'")

        return self._clients

    async def connect_all(self) -> None:
        """Connect all clients to Telegram. Does not require re-authentication."""
        for name, client in self._clients.items():
            await client.connect()
            if not await client.is_user_authorized():
                raise RuntimeError(
                    f"Session '{name}' is not authorized. "
                    "Regenerate the StringSession for this account."
                )
            me = await client.get_me()
            logger.info(
                f"Session '{name}' connected as "
                f"{me.first_name} (@{me.username}, id={me.id})"
            )

    async def disconnect_all(self) -> None:
        """Gracefully disconnect all clients."""
        for name, client in self._clients.items():
            if client.is_connected():
                await client.disconnect()
                logger.info(f"Session '{name}' disconnected")

    def get(self, name: str) -> TelegramClient:
        """Get a client by session name."""
        if name not in self._clients:
            raise KeyError(f"No client found for session '{name}'")
        return self._clients[name]

    @property
    def all_clients(self) -> dict[str, TelegramClient]:
        return self._clients
