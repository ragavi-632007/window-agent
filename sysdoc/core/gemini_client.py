"""Gemini direct-SDK client for the chat REPL and inline commands.

Fixes applied vs original:
  - Retry on ResourceExhausted (429) and ServiceUnavailable (503) with
    exponential backoff before falling to offline mock
  - Explicit request timeout on all generate_content() calls
  - temperature / max_output_tokens set per call type (structured vs chat)
  - Specific ResourceExhausted catch shown as rate-limit message, not generic error
  - Redundant isinstance(response, str) dead-code branch removed
  - Exception clause fixed: GoogleAPICallError caught before bare Exception
  - ask_for_command() now uses CommandPlan Pydantic model + native JSON mode
    (response_mime_type) instead of manual string parsing
  - explain_file_stream() truncates content to FILE_EXPLAIN_CHAR_LIMIT
  - _mock_response() uses user_input to tailor offline guidance
  - gitpilot model name sourced from config.MODEL (no more duplicate constant)
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import google.generativeai as genai
from google.api_core import exceptions
from google.generativeai import types as genai_types

from sysdoc.config import (
    MODEL,
    SYSTEM_PROMPT,
    STRUCTURED_TEMPERATURE,
    CHAT_TEMPERATURE,
    EXPLAIN_TEMPERATURE,
    MAX_TOKENS_STRUCTURED,
    MAX_TOKENS_CHAT,
    MAX_TOKENS_EXPLAIN,
    FILE_EXPLAIN_CHAR_LIMIT,
    GEMINI_TIMEOUT_BLOCKING,
    GEMINI_TIMEOUT_STREAMING,
)

# Retry policy for transient API errors
_MAX_RETRIES = 2
_RETRY_DELAY = 1.5  # seconds, doubles on each attempt


@dataclass
class GeminiChunk:
    text: str


def _make_generation_config(temperature: float, max_tokens: int) -> genai_types.GenerationConfig:
    return genai_types.GenerationConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
    )


def _is_retryable(exc: Exception) -> bool:
    """True for transient errors worth retrying (rate-limit, server overload)."""
    msg = str(exc)
    return (
        isinstance(exc, (exceptions.ResourceExhausted, exceptions.ServiceUnavailable))
        or "429" in msg
        or "503" in msg
        or "502" in msg
    )


def _generate_with_retry(model, prompt: str, *, stream: bool, generation_config, timeout: float | None = None) -> object:
    """Call model.generate_content with retry on transient errors."""
    delay = _RETRY_DELAY
    last_exc: Exception | None = None
    t_out = timeout if timeout is not None else (GEMINI_TIMEOUT_STREAMING if stream else GEMINI_TIMEOUT_BLOCKING)
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return model.generate_content(
                prompt,
                stream=stream,
                generation_config=generation_config,
                request_options={"timeout": t_out},
            )
        except exceptions.ResourceExhausted as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except exceptions.ServiceUnavailable as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except exceptions.GoogleAPICallError:
            raise
    raise last_exc  # should not be reached


class GeminiClient:
    def __init__(self) -> None:
        self.model_name = MODEL
        self.system_prompt = SYSTEM_PROMPT
        self._model = genai.GenerativeModel(MODEL, system_instruction=SYSTEM_PROMPT)
        # Separate model without system_instruction for structured / command tasks
        self._model_plain = genai.GenerativeModel(MODEL)

    def format_os_data(self, os_data: Dict[str, object]) -> str:
        return "\n".join(f"  {k}: {v}" for k, v in os_data.items())

    def _format_history(self, history: List[Dict[str, List[str]]]) -> str:
        lines: List[str] = []
        for entry in history[-12:]:
            role = entry.get("role", "unknown")
            for part in entry.get("parts", []):
                lines.append(f"{role}: {part}")
        return "\n".join(lines)

    def _build_prompt(
        self,
        user_input: str,
        os_data: Dict[str, object],
        history: List[Dict[str, List[str]]],
    ) -> str:
        # system_prompt is set as system_instruction on _model — do NOT prepend here
        history_text = self._format_history(history)
        if not os_data:
            message = user_input
        else:
            formatted_data = self.format_os_data(os_data)
            message = (
                f"User problem: {user_input}\n\n"
                f"Collected system data:\n{formatted_data}\n\n"
                "Give root cause and fix options."
            )
        parts: List[str] = []
        if history_text:
            parts += ["Previous exchange:", history_text, ""]
        parts.append(message)
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Offline fallback
    # ------------------------------------------------------------------

    def _mock_response(self, user_input: str, os_data: Dict[str, object]) -> str:
        if not os_data:
            return (
                "AI service is temporarily unavailable. "
                "Check your API key and network connection, then try again."
            )

        # Tailor the offline header to the user's query topic
        topic = user_input.lower() if user_input else ""
        if any(w in topic for w in ("network", "internet", "wifi", "dns", "slow internet")):
            header_hint = "Checking network metrics in offline mode..."
        elif any(w in topic for w in ("disk", "storage", "space", "full")):
            header_hint = "Checking storage metrics in offline mode..."
        elif any(w in topic for w in ("cpu", "ram", "memory", "slow pc")):
            header_hint = "Checking system resource metrics in offline mode..."
        else:
            header_hint = "Analyzing local system telemetry metrics for anomalies..."

        parts = [
            "\n  [bold red]OFFLINE FALLBACK[/bold red] [dim]— Gemini AI is currently unreachable[/dim]",
            f"  [dim]{header_hint}[/dim]",
            "",
        ]

        anomalies = 0

        cpu = os_data.get("cpu_percent", 0)
        if isinstance(cpu, (int, float)) and cpu > 80:
            parts.append(f"  [bold yellow]⚠[/bold yellow] [bold white]CPU Load High[/bold white] [dim]({cpu}%)[/dim]\n    [dim]↳ Close background tasks or check runaway processes.[/dim]")
            anomalies += 1
        else:
            parts.append(f"  [bold green]✓[/bold green] [dim]CPU utilization stable ({cpu}%)[/dim]")

        ram = os_data.get("ram_used_pct", 0)
        if isinstance(ram, (int, float)) and ram > 80:
            parts.append(f"  [bold yellow]⚠[/bold yellow] [bold white]RAM Exhaustion[/bold white] [dim]({ram}%)[/dim]\n    [dim]↳ Terminate memory-hungry programs.[/dim]")
            anomalies += 1
        else:
            parts.append(f"  [bold green]✓[/bold green] [dim]RAM utilization stable ({ram}%)[/dim]")

        drives = os_data.get("drives", [])
        disk_warning = False
        if isinstance(drives, list):
            for drive in drives:
                free = drive.get("free_gb", 999) if isinstance(drive, dict) else 999
                if isinstance(free, (int, float)) and free < 5:
                    device = drive.get("device", "Drive") if isinstance(drive, dict) else "Drive"
                    parts.append(
                        f"  [bold red]✗[/bold red] [bold white]Low Disk Space on {device}[/bold white] [dim]({free} GB free)[/dim]\n    [dim]↳ Execute storage cleanup protocol [c].[/dim]"
                    )
                    disk_warning = True
                    anomalies += 1
                    break
        if not disk_warning:
            parts.append("  [bold green]✓[/bold green] [dim]Storage levels secure.[/dim]")

        internet = os_data.get("internet")
        if internet is False or (isinstance(internet, str) and "unreachable" in internet.lower()):
            parts.append("  [bold red]✗[/bold red] [bold white]Internet Disconnected[/bold white]\n    [dim]↳ Try DNS flush [f] or adapter reset [r].[/dim]")
            anomalies += 1
        else:
            parts.append("  [bold green]✓[/bold green] [dim]Network connection established.[/dim]")

        dns = os_data.get("dns_status")
        if isinstance(dns, str) and "fail" in dns.lower():
            parts.append("  [bold red]✗[/bold red] [bold white]DNS Resolution Fail[/bold white]\n    [dim]↳ Flush local DNS resolver cache [f].[/dim]")
            anomalies += 1

        parts.append("")
        if anomalies == 0:
            parts.append("  [dim]System metrics look normal. Reconnect network to recover AI features.[/dim]")
        else:
            parts.append(f"  [dim]{anomalies} anomalies flagged in offline mode. Resolve issues to continue.[/dim]")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Blocking call (installer / scan)
    # ------------------------------------------------------------------

    def ask_gemini(
        self,
        user_input: str,
        os_data: Dict[str, object],
        history: List[Dict[str, List[str]]],
    ) -> str:
        prompt = self._build_prompt(user_input, os_data, history)
        cfg = _make_generation_config(CHAT_TEMPERATURE, MAX_TOKENS_CHAT)
        try:
            response = _generate_with_retry(self._model, prompt, stream=False, generation_config=cfg)
            if hasattr(response, "text") and response.text:
                return response.text.strip()
            if hasattr(response, "candidates") and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, "text") and candidate.text:
                    return candidate.text.strip()
                if isinstance(candidate, str) and candidate:
                    return candidate.strip()
            return "Gemini returned an empty response."
        except exceptions.ResourceExhausted:
            return (
                "[Rate limit] Gemini is temporarily throttled — please wait a moment and try again.\n"
                + self._mock_response(user_input, os_data)
            )
        except exceptions.GoogleAPICallError:
            return self._mock_response(user_input, os_data)
        except Exception:
            return self._mock_response(user_input, os_data)

    def generate(self, prompt: str) -> str:
        """Blocking, no-history call used by the installer and scan."""
        cfg = _make_generation_config(EXPLAIN_TEMPERATURE, MAX_TOKENS_EXPLAIN)
        try:
            response = _generate_with_retry(self._model_plain, prompt, stream=False, generation_config=cfg)
            return response.text.strip()
        except exceptions.ResourceExhausted:
            return "Gemini unavailable — rate limit reached"
        except Exception:
            return "Gemini unavailable — working offline"

    def generate_long(self, prompt: str, max_tokens: int = 4096, timeout: float = 120.0) -> str:
        """Blocking call with configurable token limit for detailed RAG explanations."""
        cfg = _make_generation_config(EXPLAIN_TEMPERATURE, max_tokens)
        try:
            response = _generate_with_retry(self._model_plain, prompt, stream=False, generation_config=cfg, timeout=timeout)
            return response.text.strip()
        except exceptions.ResourceExhausted:
            return "Gemini unavailable — rate limit reached"
        except Exception as exc:
            return f"Gemini error ({type(exc).__name__}): {exc}"

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def ask_gemini_stream(
        self,
        user_input: str,
        os_data: Dict[str, object],
        history: List[Dict[str, List[str]]],
    ) -> Iterable[GeminiChunk]:
        prompt = self._build_prompt(user_input, os_data, history)
        cfg = _make_generation_config(CHAT_TEMPERATURE, MAX_TOKENS_CHAT)
        try:
            response = _generate_with_retry(self._model, prompt, stream=True, generation_config=cfg)
            has_content = False
            for chunk in response:
                text = getattr(chunk, "text", None)
                if text:
                    has_content = True
                    yield GeminiChunk(text=text)
            if not has_content:
                yield GeminiChunk(text="Gemini returned an empty response.")
        except exceptions.ResourceExhausted:
            yield GeminiChunk(
                text="[Rate limit] Gemini is temporarily throttled — please wait a moment and try again.\n"
                + self._mock_response(user_input, os_data)
            )
        except (exceptions.GoogleAPICallError, Exception):
            yield GeminiChunk(text=self._mock_response(user_input, os_data))

    def ask_for_command(self, user_input: str) -> tuple[str | None, str]:
        """
        Ask for a single Windows terminal command that can answer user_input.
        Returns (command, reason) or (None, "") if a command is not appropriate.

        Uses native JSON mode (response_mime_type) for reliable structured output.
        Falls back to manual parsing if the model ignores the mime type.
        Groq fast-path is tried first via groq_client if available.
        """
        from sysdoc.core.groq_client import groq_client
        from sysdoc.agents.models import CommandPlan

        prompt = (
            f'User asked: "{user_input}"\n\n'
            f'Can ONE Windows terminal command (cmd.exe) answer this directly?\n\n'
            f'Respond with ONLY valid JSON — no markdown, no extra text:\n'
            f'If yes: {{"command": "the exact command", "reason": "one-line description"}}\n'
            f'If no:  {{"command": null, "reason": ""}}\n\n'
            f'Rules:\n'
            f'- For version checks on Windows: ALWAYS use winget list --name "AppName" '
            f'unless the app is a guaranteed-PATH tool (git, python, node, npm, pip, java, dotnet). '
            f'Most Windows GUI/server apps installed via winget are NOT in PATH.\n'
            f'- For guaranteed-PATH tools (git, python, node, npm, pip): use their own --version flag.\n'
            f'- For all other apps (mysql, mongodb, vscode, etc.): use winget list --name.\n'
            f'- Prefer cmd.exe; use powershell only when required.\n'
            f'- For chat/opinion/general questions: return null.\n\n'
            f'Examples:\n'
            f'  "mysql version"       -> {{"command": "winget list --name \\"MySQL\\"", "reason": "Shows installed MySQL version via winget"}}\n'
            f'  "python version"      -> {{"command": "python --version", "reason": "Python is a PATH tool"}}\n'
            f'  "git version"         -> {{"command": "git --version", "reason": "Git is a PATH tool"}}\n'
            f'  "my ip"               -> {{"command": "ipconfig", "reason": "Shows network adapter IP addresses"}}\n'
            f'  "disk space"          -> {{"command": "wmic logicaldisk get size,freespace,caption", "reason": "Shows disk usage"}}\n'
            f'  "tell me a joke"      -> {{"command": null, "reason": ""}}\n'
        )

        # Try Groq fast-path first
        if groq_client.available:
            data = groq_client.ask_json(prompt)
            if data is not None:
                try:
                    plan = CommandPlan(**data)
                    return plan.command or None, plan.reason or ""
                except Exception:
                    pass

        # Gemini fallback — use native JSON mode
        try:
            json_cfg = genai_types.GenerationConfig(
                temperature=STRUCTURED_TEMPERATURE,
                max_output_tokens=MAX_TOKENS_STRUCTURED,
                response_mime_type="application/json",
            )
            response = _generate_with_retry(
                self._model_plain, prompt, stream=False, generation_config=json_cfg
            )
            raw = response.text.strip() if hasattr(response, "text") else ""
            # Strip any markdown fences the model might still add
            if raw.startswith("```"):
                lines = raw.split("\n")
                raw = "\n".join(lines[1:])
                if raw.strip().endswith("```"):
                    raw = raw.strip()[:-3]
            data = json.loads(raw.strip())
            plan = CommandPlan(**data)
            return plan.command or None, plan.reason or ""
        except Exception:
            return None, ""

    def interpret_output(
        self,
        user_input: str,
        command: str,
        output: str,
    ) -> Iterable[GeminiChunk]:
        """Stream a plain-English interpretation of terminal command output."""
        prompt = (
            f'The user asked: "{user_input}"\n'
            f'We ran this Windows command: {command}\n'
            f'Output:\n{output or "(no output)"}\n\n'
            f'Explain the result in 1-3 plain sentences. No markdown. '
            f'Focus on what the user cares about.\n'
            f'If the output says "not recognized" AND a winget check shows the package IS installed, '
            f'say the app is installed but its bin directory is not in the system PATH — '
            f'do NOT say it might not be installed.\n'
            f'If the command failed and winget also shows nothing installed, say the app is not installed.\n'
            f'If the command succeeded, summarise the key info from the output.'
        )
        cfg = _make_generation_config(EXPLAIN_TEMPERATURE, MAX_TOKENS_EXPLAIN)
        try:
            response = _generate_with_retry(self._model_plain, prompt, stream=True, generation_config=cfg)
            has_content = False
            for chunk in response:
                text = getattr(chunk, "text", None)
                if text:
                    has_content = True
                    yield GeminiChunk(text=text)
            if not has_content:
                yield GeminiChunk(text=output.strip() or "Command returned no output.")
        except exceptions.ResourceExhausted:
            yield GeminiChunk(text="[Rate limit] Gemini throttled — showing raw output above.")
        except Exception:
            yield GeminiChunk(text=output.strip() or "Command returned no output.")

    def explain_file_stream(
        self,
        file_path: str,
        content: str,
    ) -> Iterable[GeminiChunk]:
        # Truncate to avoid token overflow on large files
        if len(content) > FILE_EXPLAIN_CHAR_LIMIT:
            content = content[:FILE_EXPLAIN_CHAR_LIMIT] + f"\n\n[... truncated at {FILE_EXPLAIN_CHAR_LIMIT} chars ...]"

        prompt = (
            f"You are a concise technical assistant. Read this file and give a SHORT, clear explanation.\n\n"
            f"File: {file_path}\n\n"
            f"=== FILE CONTENT ===\n{content}\n=== END ===\n\n"
            f"Respond with:\n\n"
            f"## What is this file?\n"
            f"2-3 sentences max — what it is and what it's for.\n\n"
            f"## Key Points\n"
            f"Bullet list of the most important things in the file (5-8 bullets max).\n"
            f"Use a table ONLY if the file has a clear list of fields, APIs, or steps — keep it small.\n\n"
            f"## Summary\n"
            f"One sentence takeaway.\n\n"
            f"Be brief. Do not explain every section. Focus on what matters most."
        )
        cfg = _make_generation_config(EXPLAIN_TEMPERATURE, MAX_TOKENS_EXPLAIN)
        try:
            response = _generate_with_retry(self._model_plain, prompt, stream=True, generation_config=cfg)
            has_content = False
            for chunk in response:
                text = getattr(chunk, "text", None)
                if text:
                    has_content = True
                    yield GeminiChunk(text=text)
            if not has_content:
                yield GeminiChunk(text="[No explanation returned by Gemini.]")
        except exceptions.ResourceExhausted:
            yield GeminiChunk(text="[Rate limit] Gemini throttled — cannot explain file right now.")
        except Exception:
            yield GeminiChunk(text="[Error] Could not analyze file — Gemini unavailable.")
