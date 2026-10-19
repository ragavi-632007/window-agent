"""GitPilot AI helpers.

Fast-path: Groq (llama-3.3-70b-versatile) — used for commit messages,
           command generation, error explanation (low-latency, low-cost).
Fallback:  Gemini (gemini-2.5-flash) — used when Groq is unavailable.

Model name is sourced from sysdoc/config.py (MODEL) — no duplicate constant.
"""
from __future__ import annotations

import time

import google.generativeai as genai
from rich.console import Console

from .config import get_api_key

console = Console()

_gemini_model = None

# Maximum retries on transient Gemini errors before giving up
_MAX_RETRIES = 1
_RETRY_DELAY = 2.0


def _get_gemini_model():
    global _gemini_model
    if _gemini_model is None:
        key = get_api_key()
        if key:
            genai.configure(api_key=key)
        from sysdoc.config import MODEL, STRUCTURED_TEMPERATURE
        import google.generativeai.types as _types
        _gemini_model = genai.GenerativeModel(
            MODEL,
            generation_config=_types.GenerationConfig(
                temperature=STRUCTURED_TEMPERATURE,
                max_output_tokens=512,
            ),
        )
    return _gemini_model


def _ask_groq(prompt: str, fallback: str = "") -> str | None:
    """Try Groq first. Returns text or None if unavailable."""
    try:
        from sysdoc.core.groq_client import groq_client
        if groq_client.available:
            result = groq_client.ask(prompt)
            return result  # may be None if Groq errors
    except Exception:
        pass
    return None


def _ask_gemini(prompt: str, fallback: str = "") -> str:
    """Gemini fallback with retry."""
    delay = _RETRY_DELAY
    for attempt in range(_MAX_RETRIES + 1):
        try:
            model = _get_gemini_model()
            response = model.generate_content(
                prompt,
                request_options={"timeout": 20},
            )
            return response.text.strip()
        except Exception as e:
            msg = str(e)
            is_transient = "429" in msg or "503" in msg or "502" in msg or "timeout" in msg.lower()
            if is_transient and attempt < _MAX_RETRIES:
                time.sleep(delay)
                delay *= 2
                continue
            _print_ai_error(e)
            return fallback or "AI unavailable"
    return fallback or "AI unavailable"


def _ask(prompt: str, fallback: str = "") -> str:
    """Try Groq, fall back to Gemini."""
    result = _ask_groq(prompt, fallback)
    if result is not None:
        return result.strip()
    return _ask_gemini(prompt, fallback)


def _print_ai_error(exc: Exception) -> None:
    """Print the AI error to the Rich console — never embed it in return values."""
    msg = str(exc)
    is_rate_limit = "429" in msg or "quota" in msg.lower() or "rate_limit" in msg.lower()
    if is_rate_limit:
        retry_hint = ""
        if "retry in" in msg.lower():
            try:
                part = msg.lower().split("retry in")[1].split("s")[0].strip()
                seconds = int(float(part))
                retry_hint = f"  [dim]Retry in ~{seconds}s, or wait a few minutes.[/dim]\n"
            except Exception:
                pass
        console.print(
            "\n  [bold yellow]⚠  AI rate limit reached[/bold yellow]  "
            "[dim](free tier quota)[/dim]\n"
            + retry_hint
            + "  [dim]The operation will continue — AI suggestions will be skipped.[/dim]\n"
        )
    else:
        console.print(f"\n  [dim red]⚠  AI error: {msg[:300]}[/dim red]\n")


# ── Commit messages ────────────────────────────────────────────────────────

def generate_commit_message(status: str, diff_names: str) -> str:
    prompt = f"""You are a Git commit message generator.

Generate ONE commit message using Conventional Commits format.
Rules:
- Start with: feat:, fix:, docs:, style:, refactor:, test:, chore:, etc.
- Be specific and clear. Max 72 characters.
- Return ONLY the commit message. No quotes. No explanation.

Changed files:
{diff_names[:800] if diff_names else "see status below"}

Git status:
{status[:600]}

Generate ONE commit message now:"""

    result = _ask(prompt, fallback="chore: update project files")
    return result.strip().strip('"').strip("'").strip("`")


# ── Error explanation ──────────────────────────────────────────────────────

def explain_error(error: str) -> str:
    prompt = f"""You are a friendly Git teacher helping a beginner.

Explain this Git error in simple English. Max 4 lines.
- Line 1: What went wrong (plain words)
- Line 2-3: Why it happened
- Line 4: How to fix it (simple step)

No jargon. No markdown. Be friendly.

Git error:
{error[:1000]}"""

    return _ask(prompt, fallback="Something went wrong with Git. Check your internet connection and try again.")


# ── Learning Q&A ───────────────────────────────────────────────────────────

def answer_git_question(question: str) -> str:
    prompt = f"""You are a friendly Git teacher for absolute beginners.

Answer this question simply. Max 5 lines.
Use everyday words. Give a real-world analogy if possible.
No markdown, no bullet points. Just plain conversational text.

Question: {question}"""

    return _ask(prompt, fallback="I couldn't get an answer right now. Please check your internet connection.")


# ── Free-text command generation ───────────────────────────────────────────

def generate_git_command(request: str, branch: str = "", repo_context: str = "") -> tuple[str, str]:
    """
    Convert a plain-English git request into a git command.
    Returns (command_string, plain_english_explanation).
    command_string starts with 'git ' or is 'UNCLEAR'.
    """
    prompt = f"""You are a Git expert assistant.

The user wants to perform this git operation:
"{request}"

Current branch: {branch or "unknown"}
{f"Repo context: {repo_context}" if repo_context else ""}

Respond with EXACTLY two lines — nothing else:
Line 1: The complete git command (must start with 'git ')
Line 2: One sentence explaining what it does in plain English

Rules:
- Single command only (no shell operators like && or ;)
- If the request needs a branch/file name but none was given, use a sensible placeholder like <branch-name> or <file>
- If the request is unclear or unsafe (e.g. force-push to main), write UNCLEAR on line 1 and explain why on line 2
- No markdown, no backticks, no extra lines

Examples:
git checkout -b feature-login
Creates a new branch called feature-login and switches to it

git stash
Temporarily saves your uncommitted changes so you can work on something else

git log --oneline -10
Shows the last 10 commits in a compact one-line format"""

    result = _ask(prompt, fallback="UNCLEAR\nCould not understand your request — please rephrase it.")
    lines = [l.strip() for l in result.strip().splitlines() if l.strip()]
    if len(lines) >= 2:
        return lines[0], " ".join(lines[1:])
    if lines:
        return lines[0], ""
    return "UNCLEAR", "Could not understand your request."


def interpret_git_output(request: str, command: str, output: str) -> str:
    """Explain what the git command output means in plain English."""
    prompt = f"""You are a friendly Git teacher.

User wanted: {request}
Command ran: {command}
Output:
{output[:800] if output else "(no output — command completed silently)"}

Explain in 2-3 plain sentences:
- What happened
- Whether it worked
- Any useful next step

No jargon. No markdown. Be brief and encouraging."""

    return _ask(prompt, fallback="The command ran. Check the output above for details.")
