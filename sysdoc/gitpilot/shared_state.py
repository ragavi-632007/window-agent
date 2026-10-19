"""Shared state between FixBot REPL, Git Action Graph, and fixgit coach UI."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

_STATE_DIR = Path.home() / ".gitpilot"
_STATE_FILE = _STATE_DIR / "session_state.json"


def _load() -> dict:
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save(data: dict) -> None:
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_last_repo_path() -> Optional[str]:
    path = _load().get("last_repo_path")
    if path and os.path.isdir(path):
        return path
    return None


def set_last_repo_path(path: str) -> None:
    data = _load()
    data["last_repo_path"] = os.path.abspath(os.path.expanduser(path))
    _save(data)


def get_last_branch() -> Optional[str]:
    return _load().get("last_branch")


def set_last_branch(branch: str) -> None:
    data = _load()
    data["last_branch"] = branch
    _save(data)


def update_from_inspect(repo_path: str, inspect: dict[str, Any]) -> None:
    set_last_repo_path(repo_path)
    if inspect.get("branch"):
        set_last_branch(str(inspect["branch"]))
