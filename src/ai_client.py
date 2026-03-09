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

Your persona: {persona}

Current group conversation:
{history}

Rules:
- Reply only on your own behalf, as a real person
- Do not use formal phrases and do not reveal that you are an AI
- Response length: {length_instruction}
- If there are emotions in the conversation, you can use a relevant emoji (max 1–2)
- Be logically consistent with previous messages
"""

_DEFAULT_LENGTH_INSTRUCTION = "1–4 sentences"
_DEFAULT_PERSONA = "A typical group participant. Communicates naturally and to the point."


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
        length_instruction: Optional[str] = None,
    ) -> str:
        """
        Generate a response for a bot in the group context.

        Args:
            group_prompt: The group's general conversation theme/rules.
            history: Formatted conversation history from ContextManager.
            persona: The bot's individual character description.
            trigger_message: The specific message this bot is responding to (optional).
            sender_name: Name of the person who sent the trigger message (optional).
            length_instruction: Specific instruction for the response length (optional).

        Returns:
            The generated text response.
        """
        system_prompt = _SYSTEM_TEMPLATE.format(
            group_prompt=group_prompt,
            persona=persona or _DEFAULT_PERSONA,
            history=history if history else "(розмова щойно почалась)",
            length_instruction=length_instruction or _DEFAULT_LENGTH_INSTRUCTION,
        )

        # Build user turn
        if trigger_message and sender_name:
            user_content = f"{sender_name}: {trigger_message}\n\nIt's your turn to reply."
        else:
            user_content = "It's your turn to write something in the group according to the theme."

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
