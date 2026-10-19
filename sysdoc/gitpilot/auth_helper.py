"""GitHub auth helper — avoids broken localhost OAuth when possible."""
from __future__ import annotations

import shutil
import subprocess
from typing import Tuple


def has_gh() -> bool:
    return shutil.which("gh") is not None


def gh_auth_status() -> Tuple[bool, str]:
    if not has_gh():
        return False, "GitHub CLI (gh) not installed."
    try:
        r = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        ok = r.returncode == 0 and "Logged in" in out
        return ok, out or f"exit {r.returncode}"
    except Exception as exc:
        return False, str(exc)


def login_with_web() -> Tuple[bool, str]:
    """Interactive gh auth login (keep terminal open)."""
    if not has_gh():
        return False, "Install GitHub CLI: https://cli.github.com/"
    try:
        r = subprocess.run(
            ["gh", "auth", "login", "-h", "github.com", "-p", "https", "-w"],
            timeout=300,
        )
        if r.returncode == 0:
            ok, msg = gh_auth_status()
            return ok, msg or "Login finished"
        return False, f"gh auth login exited {r.returncode}"
    except subprocess.TimeoutExpired:
        return False, "Timed out waiting for GitHub login."
    except Exception as exc:
        return False, str(exc)


def login_with_token(token: str) -> Tuple[bool, str]:
    token = (token or "").strip()
    if not token:
        return False, "Empty token"
    if not has_gh():
        return False, (
            "gh not installed. On next git push:\n"
            "  username = GitHub username\n"
            "  password = PAT (not GitHub password)"
        )
    try:
        r = subprocess.run(
            ["gh", "auth", "login", "--with-token"],
            input=token + "\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if r.returncode == 0:
            ok, msg = gh_auth_status()
            return ok, msg or "Token accepted"
        return False, (r.stderr or r.stdout or f"exit {r.returncode}").strip()
    except Exception as exc:
        return False, str(exc)


def ssh_setup_hint() -> str:
    return (
        "SSH setup (no browser callback):\n"
        "  1) ssh-keygen -t ed25519 -C \"you@email.com\"\n"
        "  2) Add ~/.ssh/id_ed25519.pub to GitHub → SSH keys\n"
        "  3) git remote set-url origin git@github.com:USER/REPO.git\n"
        "  4) git push"
    )


def pat_hint() -> str:
    return (
        "Create PAT: GitHub → Settings → Developer settings → Tokens\n"
        "Scope needed: repo\n"
        "Paste token below (or use as password on git push)."
    )


def run_auth_wizard(console=None) -> bool:
    """Menu for users when push auth fails."""
    def _p(msg: str) -> None:
        if console is not None:
            try:
                console.print(msg)
                return
            except Exception:
                pass
        print(msg)

    _p("")
    _p("  [GitHub Auth Helper]")
    _p("  Browser page 127.0.0.1 often fails after GitHub login.")
    _p("  Pick an easier method:")
    _p("")
    _p("    [1] GitHub CLI login (recommended)")
    _p("    [2] Paste Personal Access Token")
    _p("    [3] Show SSH instructions")
    _p("    [4] Check auth status")
    _p("    [5] Skip")
    _p("")

    try:
        choice = input("  Choose 1-5: ").strip()
    except Exception:
        choice = "5"

    if choice == "1":
        if not has_gh():
            _p("  Install gh: https://cli.github.com/  then retry [1]")
            return False
        _p("  Starting gh auth login — keep this window open...")
        ok, msg = login_with_web()
        _p(f"  {msg}")
        return ok

    if choice == "2":
        _p(pat_hint())
        try:
            token = input("  Paste PAT: ").strip()
        except Exception:
            token = ""
        ok, msg = login_with_token(token)
        _p(f"  {msg}")
        return ok

    if choice == "3":
        _p(ssh_setup_hint())
        return False

    if choice == "4":
        ok, msg = gh_auth_status()
        _p(f"  Logged in: {ok}")
        _p(f"  {msg}")
        return ok

    _p("  Skipped.")
    return False
