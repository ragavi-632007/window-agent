"""Groq fast-path client.

Used for low-latency, low-cost tasks where a full reasoning model is overkill:
  - Command classification (ask_for_command)
  - Intent disambiguation (DomainGuess when IntentEngine returns GENERAL)
  - GitPilot suggestions

Falls back to None gracefully when GROQ_API_KEY is not set, so callers can
do:
    result = groq_client.ask(prompt) if groq_client.available else None
    if result is None:
        result = gemini_fallback()
"""
from __future__ import annotations

import json
import time
from typing import Optional

from sysdoc.config import GROQ_API_KEY, GROQ_MODEL, STRUCTURED_TEMPERATURE, MAX_TOKENS_STRUCTURED

# Maximum retries on transient errors (429 rate-limit, 503 unavailable)
_MAX_RETRIES = 2
_RETRY_DELAY = 2.0  # seconds, doubles on each retry


class GroqClient:
    def __init__(self) -> None:
        self._client = None
        self.available = False

        if not GROQ_API_KEY:
            return

        try:
            from groq import Groq
            self._client = Groq(api_key=GROQ_API_KEY)
            self.available = True
        except ImportError:
            # groq package not installed — degrade silently
            pass
        except Exception:
            pass

    # ── Core blocking call ────────────────────────────────────────────────

    def ask(
        self,
        prompt: str,
        system: str = "You are a helpful assistant. Be concise.",
        temperature: float = STRUCTURED_TEMPERATURE,
        max_tokens: int = MAX_TOKENS_STRUCTURED,
    ) -> Optional[str]:
        """Blocking call to Groq. Returns text or None on failure."""
        if not self.available or self._client is None:
            return None

        delay = _RETRY_DELAY
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = self._client.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=15,
                )
                return resp.choices[0].message.content.strip()
            except Exception as exc:
                msg = str(exc)
                is_rate_limit = "429" in msg or "rate" in msg.lower()
                is_transient = "503" in msg or "502" in msg or "timeout" in msg.lower()
                if (is_rate_limit or is_transient) and attempt < _MAX_RETRIES:
                    time.sleep(delay)
                    delay *= 2
                    continue
                # Non-retriable or exhausted retries
                return None

    # ── Structured JSON call ──────────────────────────────────────────────

    def ask_json(
        self,
        prompt: str,
        system: str = "Respond ONLY with valid JSON. No markdown, no extra text.",
        temperature: float = STRUCTURED_TEMPERATURE,
        max_tokens: int = MAX_TOKENS_STRUCTURED,
    ) -> Optional[dict]:
        """Ask Groq for a JSON response. Returns parsed dict or None."""
        raw = self.ask(prompt, system=system, temperature=temperature, max_tokens=max_tokens)
        if raw is None:
            return None
        # Strip markdown fences if model added them anyway
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.strip().endswith("```"):
                text = text.strip()[:-3]
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            return None


# Module-level singleton — created once, reused everywhere
groq_client = GroqClient()
