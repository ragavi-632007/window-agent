"""Command Discovery Agent — NL app name → package ID + strategy chain.

Used before the INSTALL planner so "setup VS Code" becomes a concrete
winget/choco/scoop target with ordered fallback commands.
"""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any, Callable, Dict, List, Optional

from display.animations import agent_log, agent_log_ok, agent_log_step, agent_log_warn


DISCOVERY_SYSTEM = """You resolve Windows software install requests into concrete targets.

Return ONLY valid JSON (no markdown):
{
  "app_name": "Visual Studio Code",
  "winget_id": "Microsoft.VisualStudioCode",
  "choco_id": "vscode",
  "scoop_id": "vscode",
  "manager": "winget",
  "strategy_chain": [
    "install", "force_install", "accept_agreements",
    "choco_install", "scoop_install", "purge_reinstall"
  ],
  "reasoning": "short why"
}

Rules:
- Prefer official winget IDs when known (e.g. Microsoft.VisualStudioCode, Google.Chrome).
- manager is usually "winget"; use "pip"/"npm" only for libraries/CLIs.
- If unsure of winget_id, set it to "" — tools will search.
- strategy_chain must start with "install".
"""


def _run(cmd: list[str], timeout: int = 45) -> str:
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
        return (r.stdout or "") + "\n" + (r.stderr or "")
    except Exception as exc:
        return str(exc)


def winget_search(query: str, max_hits: int = 8) -> List[Dict[str, str]]:
    """Parse `winget search` into [{name, id, source}, ...]."""
    out = _run([
        "winget", "search", query,
        "--accept-source-agreements",
        "--disable-interactivity",
    ])
    hits: List[Dict[str, str]] = []
    for line in out.splitlines():
        line = line.rstrip()
        if not line or line.startswith("-") or "Name" in line and "Id" in line:
            continue
        # winget columns are space-padded; split on 2+ spaces
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) >= 2 and "." in parts[1]:
            hits.append({
                "name": parts[0],
                "id": parts[1],
                "source": parts[2] if len(parts) > 2 else "winget",
            })
        if len(hits) >= max_hits:
            break
    return hits


def _llm_json(prompt: str, system: str) -> dict:
    try:
        from core.gemini_client import GeminiClient
        raw = GeminiClient().generate(f"{system}\n\n{prompt}") or ""
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except Exception:
        pass
    return {}


def _heuristic_discovery(user_query: str) -> dict:
    """Offline fallback when LLM unavailable."""
    q = user_query.lower()
    # strip verbs
    for v in ("install", "setup", "download", "get", "grab", "add", "the", "a", "an"):
        q = re.sub(rf"\b{v}\b", " ", q)
    name = " ".join(q.split()).strip() or user_query.strip()

    known = {
        "vscode": ("Visual Studio Code", "Microsoft.VisualStudioCode", "vscode", "vscode"),
        "visual studio code": ("Visual Studio Code", "Microsoft.VisualStudioCode", "vscode", "vscode"),
        "vs code": ("Visual Studio Code", "Microsoft.VisualStudioCode", "vscode", "vscode"),
        "chrome": ("Google Chrome", "Google.Chrome", "googlechrome", "googlechrome"),
        "google chrome": ("Google Chrome", "Google.Chrome", "googlechrome", "googlechrome"),
        "firefox": ("Mozilla Firefox", "Mozilla.Firefox", "firefox", "firefox"),
        "discord": ("Discord", "Discord.Discord", "discord", "discord"),
        "notepad++": ("Notepad++", "Notepad++.Notepad++", "notepadplusplus", "notepadplusplus"),
        "git": ("Git", "Git.Git", "git", "git"),
        "python": ("Python 3", "Python.Python.3.12", "python", "python"),
        "node": ("Node.js", "OpenJS.NodeJS.LTS", "nodejs", "nodejs"),
        "nodejs": ("Node.js", "OpenJS.NodeJS.LTS", "nodejs", "nodejs"),
        "7zip": ("7-Zip", "7zip.7zip", "7zip", "7zip"),
        "vlc": ("VLC", "VideoLAN.VLC", "vlc", "vlc"),
    }
    key = name.lower()
    if key in known:
        app, wid, cid, sid = known[key]
    else:
        app, wid, cid, sid = name, "", "", ""

    return {
        "app_name": app,
        "winget_id": wid,
        "choco_id": cid,
        "scoop_id": sid,
        "manager": "winget",
        "strategy_chain": [
            "install", "force_install", "accept_agreements",
            "choco_install", "scoop_install", "purge_reinstall",
        ],
        "reasoning": "heuristic map" if wid else "needs winget search",
    }


def discover_package(user_query: str) -> Dict[str, Any]:
    """Full discovery: Gemini → winget search validation → best ID."""
    agent_log("discovery", f'Resolving install target for: "{user_query}"')

    data = _llm_json(
        f"User request: {user_query}\nReturn JSON package resolution.",
        DISCOVERY_SYSTEM,
    )
    if not data:
        data = _heuristic_discovery(user_query)

    app_name = str(data.get("app_name") or user_query).strip()
    winget_id = str(data.get("winget_id") or "").strip()
    search_q = app_name or user_query

    agent_log_step(f"Discovery  winget search '{search_q}'...")
    hits = winget_search(search_q)

    if winget_id and any(h["id"].lower() == winget_id.lower() for h in hits):
        chosen = next(h for h in hits if h["id"].lower() == winget_id.lower())
    elif hits:
        # Prefer winget source over msstore
        winget_hits = [h for h in hits if "msstore" not in h.get("source", "").lower()]
        chosen = (winget_hits or hits)[0]
        winget_id = chosen["id"]
        app_name = chosen.get("name") or app_name
    else:
        chosen = {}
        if not winget_id:
            agent_log_warn("Discovery  no winget hits — plan may escalate")

    chain = data.get("strategy_chain") or [
        "install", "force_install", "accept_agreements",
        "choco_install", "scoop_install", "purge_reinstall",
    ]
    # Ensure install is first
    if chain[0] != "install":
        chain = ["install"] + [s for s in chain if s != "install"]

    result = {
        "app_name": app_name,
        "winget_id": winget_id,
        "choco_id": str(data.get("choco_id") or ""),
        "scoop_id": str(data.get("scoop_id") or ""),
        "manager": str(data.get("manager") or "winget"),
        "strategy_chain": chain,
        "search_hits": hits[:5],
        "reasoning": str(data.get("reasoning") or ""),
        "confidence": 0.9 if winget_id else 0.4,
    }
    agent_log_ok(
        f"Discovery  {result['app_name']} → {result['winget_id'] or '(unresolved)'} "
        f"[{result['manager']}] conf={result['confidence']:.0%}"
    )
    if result["reasoning"]:
        agent_log("discovery", result["reasoning"][:200])
    return result


def make_command_discovery_node() -> Callable[[dict], dict]:
    """LangGraph node: fills discovery_result on state for INSTALL planner."""

    def command_discovery_node(state: dict) -> dict:
        # Prefer explicit user text from messages or user_query fields
        user_query = state.get("user_query") or ""
        if not user_query:
            msgs = state.get("messages") or []
            for m in reversed(msgs):
                content = getattr(m, "content", None) or (m.get("content") if isinstance(m, dict) else None)
                if content and isinstance(content, str) and content.strip():
                    user_query = content.strip()
                    break
        if not user_query:
            user_query = (state.get("action_plan") or {}).get("goal") or "install app"

        discovery = discover_package(user_query)
        return {
            "discovery_result": discovery,
            "user_query": user_query,
        }

    return command_discovery_node