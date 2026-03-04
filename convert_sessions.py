"""
Convert Telethon SQLite .session files to StringSession strings.
Outputs the StringSession for each session file.
"""
import asyncio
import sys
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession, SQLiteSession

API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"

SESSIONS = {
    "amanda":  "sessions/amanda.session",
    "reggie":  "sessions/reggie.session",
    "steven":  "sessions/steven.session",
    "donnie":  "sessions/donnie.session",
}


async def convert(name: str, path: str) -> None:
    # Load existing SQLite session
    client = TelegramClient(path.replace(".session", ""), API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        print(f"[{name}] ❌ NOT AUTHORIZED — session may be expired")
        await client.disconnect()
        return

    me = await client.get_me()
    string = StringSession.save(client.session)
    print(f"\n[{name}] ✅ {me.first_name} {me.last_name or ''} (@{me.username}, id={me.id})")
    print(f"  string_session: {string}")
    await client.disconnect()


async def main():
    for name, path in SESSIONS.items():
        if not Path(path).exists():
            print(f"[{name}] File not found: {path}")
            continue
        await convert(name, path)


if __name__ == "__main__":
    asyncio.run(main())
