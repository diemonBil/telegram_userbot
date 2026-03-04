"""
AI Client: wrapper around the Grok API for generating bot responses.

Builds a full system prompt from:
  - group prompt (defines the topic/style)
  - bot persona (per-session character description)
  - current conversation history (from ContextManager)
  - the triggering message (what to respond to)

Uses aiohttp for async HTTP requests.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import aiohttp
from loguru import logger


_SYSTEM_TEMPLATE = """\
{group_prompt}

Твоя особистість: {persona}

Поточна розмова в групі:
{history}

Правила:
- Відповідай виключно від свого імені, як жива людина
- Не використовуй формальні фрази та не розкривай що ти AI
- Довжина відповіді: 1–4 речення
- Якщо в розмові є емоції — можеш використати відповідне емодзі (не більше 1–2)
- Будь логічно послідовним до попередніх повідомлень
"""

_DEFAULT_PERSONA = "Звичайний учасник групи. Спілкується природно і по суті."


class AIClient:
    """
    Async client for the Grok API.
    Generates a contextually appropriate response for a given bot in a given group.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.x.ai/v1",
        model: str = "grok-3-latest",
        max_retries: int = 3,
        timeout: int = 30,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._max_retries = max_retries
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
        return self._session

    async def generate(
        self,
        group_prompt: str,
        history: str,
        persona: Optional[str] = None,
        trigger_message: Optional[str] = None,
        sender_name: Optional[str] = None,
    ) -> str:
        """
        Generate a response for a bot in the group context.

        Args:
            group_prompt: The group's general conversation theme/rules.
            history: Formatted conversation history from ContextManager.
            persona: The bot's individual character description.
            trigger_message: The specific message this bot is responding to (optional).
            sender_name: Name of the person who sent the trigger message (optional).

        Returns:
            The generated text response.
        """
        system_prompt = _SYSTEM_TEMPLATE.format(
            group_prompt=group_prompt,
            persona=persona or _DEFAULT_PERSONA,
            history=history if history else "(розмова щойно почалась)",
        )

        # Build user turn
        if trigger_message and sender_name:
            user_content = f"{sender_name}: {trigger_message}\n\nТвоя черга відповісти."
        else:
            user_content = "Твоя черга написати щось у групі відповідно до теми."

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": 200,
            "temperature": 0.85,   # High enough for natural variety, not too random
        }

        for attempt in range(1, self._max_retries + 1):
            try:
                session = await self._get_session()
                async with session.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning(
                            f"Grok API error {resp.status} (attempt {attempt}): {body}"
                        )
                        if attempt < self._max_retries:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        raise RuntimeError(f"Grok API returned {resp.status}: {body}")

                    data = await resp.json()
                    text = data["choices"][0]["message"]["content"].strip()
                    logger.debug(f"Generated response ({len(text)} chars)")
                    return text

            except aiohttp.ClientError as e:
                logger.warning(f"Network error on attempt {attempt}: {e}")
                if attempt < self._max_retries:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise

        raise RuntimeError("AI generation failed after all retries")

    async def close(self) -> None:
        """Close the underlying aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
