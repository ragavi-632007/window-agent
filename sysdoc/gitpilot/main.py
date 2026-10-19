import sys
import os
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.rule import Rule
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box
from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.styles import Style as PtStyle

from .config import get_api_key, save_api_key
from . import git_ops as git
from .ai_helper import (
    generate_commit_message,
    explain_error,
    answer_git_question,
    generate_git_command,
    interpret_git_output,
)

console = Console()


# ── UI helpers ─────────────────────────────────────────────────────────────

import re


def sanitize_remote_url(raw: str) -> str:
    if not raw:
        return ""
    return re.sub(r'https://[^@]+@github\.com', 'https://***@github.com', raw)


def stream_header(title: str):
    console.print()
    console.print(Rule(f"[bold cyan]🚀  {title}[/bold cyan]", style="cyan"))


def stream_step(text: str):
    console.print(f"  [dim]•[/dim]  {text}")


def stream_divider():
    console.print(Rule(style="dim"))


def stream_run(text: str):
    console.print(f"\n  [bold cyan]►[/bold cyan]  {text}")


def stream_ok(msg: str):
    ok(msg)


def stream_warn(msg: str):
    warn(msg)


def stream_err(msg: str):
    err(msg)


def stream_tip(text: str):
    console.print(f"  [dim]💡 {text}[/dim]")


class LiveJob:
    def __init__(self, label: str):
        self.label = label
        self._progress = None
        self._task = None

    def __enter__(self):
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn(f"[bold cyan]{self.label}[/bold cyan]"),
            console=console,
            transient=True,
        )
        self._progress.__enter__()
        self._task = self._progress.add_task("", total=None)
        return self

    def finish(self, ok: bool = True, detail: str = ""):
        if self._progress:
            try:
                self._progress.__exit__(None, None, None)
            except Exception:
                pass
        if ok:
            console.print(f"  [bold green]✓[/bold green]  [dim]{self.label}[/dim] {f'([dim]{detail[:60]}[/dim])' if detail else ''}")
        else:
            console.print(f"  [bold red]✗[/bold red]  [dim]{self.label}[/dim] {f'([red]{detail[:60]}[/red])' if detail else ''}")

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._progress:
            try:
                self._progress.__exit__(exc_type, exc_val, exc_tb)
            except Exception:
                pass


def show_banner():
    console.clear()
    console.print(Panel(
        Text.from_markup(
            "[bold cyan]  ██████╗ ██╗████████╗██████╗ ██╗██╗      ██████╗ ████████╗\n"
            " ██╔════╝ ██║╚══██╔══╝██╔══██╗██║██║     ██╔═══██╗╚══██╔══╝\n"
            " ██║  ███╗██║   ██║   ██████╔╝██║██║     ██║   ██║   ██║   \n"
            " ██║   ██║██║   ██║   ██╔═══╝ ██║██║     ██║   ██║   ██║   \n"
            " ╚██████╔╝██║   ██║   ██║     ██║███████╗╚██████╔╝   ██║   \n"
            "  ╚═════╝ ╚═╝   ╚═╝   ╚═╝     ╚═╝╚══════╝ ╚═════╝    ╚═╝  [/bold cyan]\n\n"
            "[bold white]        AI-Powered Git Assistant for Beginners[/bold white]\n"
            "[dim]        Powered by Google Gemini 2.5 Flash  •  Type \\fixgit inside Fixbot[/dim]"
        ),
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()


def step_panel(num: int, total: int, title: str, command: str = "", tip: str = ""):
    cmd_part = f"  [dim]({command})[/dim]" if command else ""
    console.print(f"\n  [dim][{num}/{total}][/dim]  [bold white]{title}[/bold white]{cmd_part}")
    if tip:
        console.print(f"  [dim]    {tip}[/dim]")


def teach_panel(text: str):
    console.print(f"\n  [dim]💡 {text}[/dim]\n")


def ok(msg: str):
    first, *rest = msg.splitlines()
    console.print(f"\n  [bold green]✓[/bold green]  {first}")
    for line in rest:
        if line.strip():
            console.print(f"  [dim]   {line}[/dim]")
    console.print()


def err(msg: str):
    first, *rest = msg.splitlines()
    console.print(f"\n  [bold red]✗[/bold red]  {first}")
    for line in rest:
        if line.strip():
            console.print(f"  [dim]   {line}[/dim]")
    console.print()


def warn(msg: str):
    first, *rest = msg.splitlines()
    console.print(f"\n  [bold yellow]![/bold yellow]  {first}")
    for line in rest:
        if line.strip():
            console.print(f"  [dim]   {line}[/dim]")
    console.print()


def info_box(title: str, body: str):
    console.print(f"\n  [bold white]{title}[/bold white]")
    console.print(f"  [dim]{'─' * 50}[/dim]")
    for line in body.splitlines()[:30]:
        console.print(f"  [white]{line}[/white]", highlight=False)
    lines = body.splitlines()
    if len(lines) > 30:
        console.print(f"  [dim]  ... {len(lines) - 30} more lines[/dim]")
    console.print()


def spinner(label: str, fn, *args, **kwargs):
    with Progress(SpinnerColumn(), TextColumn(f"[bold cyan]{label}[/bold cyan]"),
                  console=console, transient=True) as p:
        p.add_task("", total=None)
        return fn(*args, **kwargs)


def ask_path(prompt_text: str = "Project folder path") -> str:
    cwd = os.getcwd()
    _style = PtStyle.from_dict({"prompt": "#00d7ff bold"})
    console.print(
        f"  [dim]{prompt_text}[/dim]  [dim](Ctrl+V or right-click to paste  •  Enter = current folder)[/dim]"
    )
    console.print(f"  [dim]Current: {cwd}[/dim]")
    try:
        result = pt_prompt("  ❯ Path: ", style=_style).strip()
    except (KeyboardInterrupt, EOFError):
        return cwd
    return result if result else cwd


def pause():
    try:
        input("\n  Press Enter to continue...")
    except (KeyboardInterrupt, EOFError):
        pass


_PT_STYLE = PtStyle.from_dict({"prompt": "#00d7ff bold"})


def _pick(prompt_text: str = "", default: str = "") -> str:
    """Single-line input using prompt_toolkit (supports paste)."""
    label = f"  ❯ {prompt_text}: " if prompt_text else "  ❯ "
    try:
        return pt_prompt(label, default=default, style=_PT_STYLE).strip()
    except (KeyboardInterrupt, EOFError):
        return "q"


def _confirm(question: str, default: bool = True) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    console.print(f"\n  [dim]{question} {hint}[/dim]")
    ans = _pick().lower()
    if not ans:
        return default
    return ans.startswith("y")


def _sub_menu(title: str, items: list, back: str = "← Back") -> int | None:
    """
    Print a numbered sub-menu. Returns 0-based index or None for back/cancel.
    Accepts a number or partial text match.
    """
    console.print(f"\n  [bold white]{title}[/bold white]\n")
    for i, item in enumerate(items, 1):
        console.print(f"  [cyan][{i}][/cyan]  {item}")
    console.print(f"  [dim][q][/dim]  {back}\n")
    raw = _pick().lower()
    if raw in ("q", "b", "back", ""):
        return None
    try:
        n = int(raw)
        if 1 <= n <= len(items):
            return n - 1
        warn(f"Enter a number between 1 and {len(items)}.")
        return None
    except ValueError:
        for i, item in enumerate(items):
            if raw in item.lower():
                return i
        return None


def show_home():
    """Clean main menu — simple numbered list, no heavy panels."""
    console.clear()
    console.print(
        "\n  [bold cyan]GitPilot[/bold cyan]  "
        "[dim]AI-Powered Git Assistant[/dim]\n"
        f"  [dim]{'─' * 50}[/dim]\n"
    )
    console.print("  [bold white]Hi! What do you want to do?[/bold white]\n")
    for i, (label, _) in enumerate(_GROUPED_MENU, 1):
        console.print(f"  [cyan][{i}][/cyan]  {label}")
    console.print(f"\n  [dim][q][/dim]  Exit to Fixbot\n")


def _require_repo(path: str) -> bool:
    if not git.is_git_repo(path):
        err("This folder is not a Git project.")
        return False
    return True


# ── First-time setup ───────────────────────────────────────────────────────

def setup_api_key():
    console.print(Panel(
        "[bold yellow]🔑 First Time Setup — Gemini API Key[/bold yellow]\n\n"
        "GitPilot uses Google Gemini AI to write commit messages,\n"
        "explain errors, and answer any Git question.\n\n"
        "[bold white]Get your FREE key (no credit card needed):[/bold white]\n"
        "[bold cyan]  https://aistudio.google.com[/bold cyan]\n\n"
        "[dim]Click 'Get API Key' → Create → Copy the key → Paste below.[/dim]",
        border_style="yellow",
        padding=(1, 2),
    ))
    _s = PtStyle.from_dict({"prompt": "#ffff00 bold"})
    console.print("  [dim](Ctrl+V or right-click to paste your key)[/dim]")
    try:
        key = pt_prompt("  ❯ API Key: ", style=_s).strip()
    except (KeyboardInterrupt, EOFError):
        return None
    if key:
        save_api_key(key)
        ok("API Key saved — You're ready!")
        return key
    return None


def handle_conflicts(path: str, conflict_type: str = "rebase") -> bool:
    """
    Guides the user step-by-step to resolve conflicts.
    conflict_type can be 'rebase' or 'merge'.
    Returns True if resolved successfully, False if aborted or failed.
    """
    console.print()
    console.print(Panel(
        "[bold red]⚠️  Conflict Detected![/bold red]\n\n"
        "Git tried to combine changes but found that the same lines were modified differently.\n"
        "[bold white]Don't panic! This is completely normal and easy to fix.[/bold white]",
        border_style="red",
    ))

    # Let's find conflicted files
    # git diff --name-only --diff-filter=U
    out, _, _ = git.run_git(["diff", "--name-only", "--diff-filter=U"], cwd=path)
    conflicted_files = [f.strip() for f in out.splitlines() if f.strip()]
    
    if conflicted_files:
        console.print("\n  [bold white]Conflicted Files:[/bold white]")
        for f in conflicted_files:
            console.print(f"  [red]• {f}[/red]")
    else:
        # Fallback to status check
        console.print("\n  [yellow]Please check the files below for conflicts.[/yellow]")

    teach_panel(
        "Here is what you need to do:\n"
        "1. Open the conflicted files in your editor.\n"
        "2. Look for markers like <<<<<<<, =======, and >>>>>>>.\n"
        "3. Edit the file to keep the changes you want, and delete all of those markers.\n"
        "4. Save the files."
    )

    while True:
        console.print("\n  [bold white]What would you like to do now?[/bold white]\n")
        items = [
            "I have edited and resolved all conflicts. Let's continue!",
            "Show me which files still have conflict markers",
            "Abort this action and go back to safety (no data will be lost)"
        ]
        choice = _sub_menu("Conflict Resolution Menu", items)
        
        if choice is None:
            continue
            
        if choice == 0:
            # Let's check if conflict markers still exist in the files
            markers_found = []
            for f in conflicted_files:
                full_p = Path(path) / f
                if full_p.exists():
                    try:
                        content = full_p.read_text(encoding="utf-8", errors="ignore")
                        if "<<<<<<<" in content or "=======" in content or ">>>>>>>" in content:
                            markers_found.append(f)
                    except Exception:
                        pass
            
            if markers_found:
                err("We still found conflict markers in these files:")
                for f in markers_found:
                    console.print(f"  [red]• {f}[/red]")
                console.print("  [dim]Please open them, remove all markers (<<<<<<<, =======, >>>>>>>), save, and try again.[/dim]")
                continue
                
            # Stage all changes
            console.print("  [dim]Staging resolved files (git add .)...[/dim]")
            git.stage_all(path)
            
            # Continue the rebase or merge
            if conflict_type == "rebase":
                out, errmsg, code = spinner("Continuing rebase", git.run_git, ["rebase", "--continue"], cwd=path)
                # If git rebase --continue succeeds or says "No changes"
                if code == 0:
                    ok("Conflicts resolved and rebase completed successfully!")
                    return True
                elif "no changes" in (out + errmsg).lower():
                    # We can skip
                    git.run_git(["rebase", "--skip"], cwd=path)
                    ok("Conflicts skipped / completed!")
                    return True
                else:
                    err(f"Rebase continue failed:\n{errmsg}")
                    # If we still have conflicts, loop again
                    if "conflict" in (out + errmsg).lower():
                        continue
                    return False
            else: # merge
                out, errmsg, code = spinner("Finishing merge", git.run_git, ["commit", "--no-edit"], cwd=path)
                if code == 0:
                    ok("Conflicts resolved and merge completed successfully!")
                    return True
                else:
                    err(f"Merge commit failed:\n{errmsg}")
                    return False
                    
        elif choice == 1:
            # Show which files still have markers
            markers_found = []
            for f in conflicted_files:
                full_p = Path(path) / f
                if full_p.exists():
                    try:
                        content = full_p.read_text(encoding="utf-8", errors="ignore")
                        if "<<<<<<<" in content:
                            markers_found.append(f)
                    except Exception:
                        pass
            if markers_found:
                console.print("\n  [yellow]These files still have conflict markers:[/yellow]")
                for f in markers_found:
                    console.print(f"  [red]• {f}[/red]")
            else:
                ok("No conflict markers found! You're ready to continue.")
                
        elif choice == 2:
            # Abort
            if conflict_type == "rebase":
                spinner("Aborting rebase", git.run_git, ["rebase", "--abort"], cwd=path)
            else:
                spinner("Aborting merge", git.run_git, ["merge", "--abort"], cwd=path)
            warn("Action aborted. Returned your project back to its original state.")
            return False


# ══════════════════════════════════════════════════════════════════════════
# FLOW 1 — SMART PUSH
# ══════════════════════════════════════════════════════════════════════════

def flow_push():
    from gitpilot import git_ops as git
    from gitpilot.ai_helper import generate_commit_message, explain_error

    console.print()
    stream_header("Smart Push")
    stream_step("Upload your folder to GitHub in a few clear steps")
    stream_divider()

    path = ask_path()
    if not path or not Path(path).exists():
        stream_err(f"Folder not found: {path}")
        return

    # ── 1. Repo ──────────────────────────────────────────
    stream_header("1 · Project")
    stream_run("Checking if this folder is a Git project…")
    with LiveJob("Checking git status…") as job:
        is_repo = git.is_git_repo(path)
        job.finish(ok=True, detail="git repo" if is_repo else "not a repo")

    if not is_repo:
        stream_run("Creating Git project (git init)…")
        with LiveJob("git init…") as job:
            out, err_msg, code = git.init_repo(path)
            job.finish(ok=code == 0, detail=err_msg or out)
        if code != 0:
            stream_err(err_msg or "git init failed")
            return
        stream_ok("New Git project ready")
    else:
        stream_ok(f"Git project found\n{path}")

    # ── 2. Remote (NEVER show raw PAT) ───────────────────
    stream_header("2 · GitHub link")
    stream_run("Checking remote…")
    remote_out, _, _ = git.get_remote(path)
    safe_remote = sanitize_remote_url(remote_out or "")

    if not (remote_out or "").strip():
        stream_warn("No GitHub URL yet")
        stream_tip("Paste your repo URL, e.g. https://github.com/USER/REPO.git")
        console.print("  [dim]Paste your GitHub repository URL (e.g. https://github.com/you/project.git)[/dim]")
        _url_s = PtStyle.from_dict({"prompt": "#00d7ff bold"})
        try:
            repo_url = pt_prompt("  ❯ URL: ", style=_url_s).strip()
        except (KeyboardInterrupt, EOFError):
            return
        if not repo_url:
            stream_err("No URL provided.")
            return
        with LiveJob("Connecting to GitHub…") as job:
            out, err_msg, code = git.add_remote(path, repo_url.strip())
            job.finish(ok=code == 0 or "already exists" in (err_msg or ""), detail=sanitize_remote_url(repo_url))
        if code != 0 and "already exists" not in (err_msg or ""):
            stream_err(f"Could not connect:\n{err_msg}")
            return
        stream_ok(f"GitHub connected!\n{sanitize_remote_url(repo_url)}")
    else:
        stream_ok("Already linked to GitHub")
        for line in safe_remote.splitlines():
            if line.strip():
                stream_step(line.strip())

    # ── 3. Changes ───────────────────────────────────────
    stream_header("3 · Your changes")
    stream_run("Looking for new or edited files…")
    with LiveJob("Scanning…") as job:
        short_out, _, _ = git.get_status_short(path)
        status_out, _, _ = git.get_status(path)
        diff_names, _, _ = git.get_diff_names(path)
        job.finish(ok=True, detail=f"{len((short_out or '').splitlines())} file(s)")

    if not (short_out or "").strip() and not git.has_staged_changes(path):
        stream_warn("Nothing new to upload — GitHub already matches this folder")
        log_out, _, _ = git.get_log(path, n=5)
        if log_out:
            stream_step("Recent commits:")
            for line in log_out.splitlines()[:5]:
                stream_step(line)
        return

    stream_ok("Files to upload")
    for line in (short_out or "").splitlines()[:20]:
        stream_step(line)

    # ── 4. Commit ────────────────────────────────────────
    stream_header("4 · Save snapshot")
    stream_run("AI writing a short commit message…")
    with LiveJob("AI commit message…") as job:
        commit_msg = generate_commit_message(status_out, diff_names or short_out)
        job.finish(ok=True, detail=(commit_msg or "")[:50])

    stream_ok(f"Message: {commit_msg}")
    console.print("  [dim]Press Enter to use it, or type your own:[/dim]")
    _cm_s = PtStyle.from_dict({"prompt": "#00ff87 bold"})
    try:
        final_msg = pt_prompt("  ❯ Message: ", default=commit_msg or "Update project files", style=_cm_s).strip()
    except (KeyboardInterrupt, EOFError):
        final_msg = commit_msg or "Update project files"
    final_msg = final_msg or commit_msg or "Update project files"

    stream_run("Staging + committing…")
    with LiveJob("git add + commit…") as job:
        git.stage_all(path)
        out, err_msg, code = git.commit(path, final_msg)
        job.finish(ok=code == 0 or "nothing to commit" in (out + (err_msg or "")).lower(), detail=err_msg or "committed")
    if code != 0 and "nothing to commit" not in (out + (err_msg or "")).lower():
        stream_err(err_msg or out or "commit failed")
        return
    stream_ok("Snapshot saved on this PC")

    # ── 5. Push ──────────────────────────────────────────
    stream_header("5 · Upload")
    branch = git.get_branch(path) or "main"
    stream_run(f"Uploading branch [bold]{branch}[/bold]…")
    with LiveJob(f"git push → {branch}…") as job:
        out, err_msg, code = git.push(path, branch, first_push=True)
        job.finish(ok=code == 0, detail=sanitize_remote_url(err_msg or out or ""))

    if code != 0:
        stream_err(err_msg or out or "push failed")
        low = ((err_msg or "") + " " + (out or "")).lower()
        if "auth" in low or "permission" in low or "403" in low or "denied" in low:
            stream_tip("Open Auth Helper for easy login (no broken localhost page)")
            try:
                from gitpilot.auth_helper import run_auth_wizard
                if run_auth_wizard(console):
                    stream_run("Retrying push…")
                    with LiveJob("git push retry…") as job:
                        out, err_msg, code = git.push(path, branch, first_push=True)
                        job.finish(ok=code == 0, detail=err_msg or out or "")
            except Exception:
                pass
        if code != 0:
            return

    stream_divider()
    stream_header("Done")
    stream_ok(f"Code is on GitHub · branch {branch}")
    stream_tip("Open the repo in browser to confirm")
    pause()


# ══════════════════════════════════════════════════════════════════════════
# FLOW 2 — PULL
# ══════════════════════════════════════════════════════════════════════════

def flow_pull():
    console.print()
    console.print(Rule("[bold cyan]⬇️   Pull Latest Changes from GitHub[/bold cyan]", style="cyan"))
    console.print()
    path = ask_path()
    if not _require_repo(path):
        return
    teach_panel("'Pulling' downloads the latest version from GitHub. Always pull before starting work.")
    out, errmsg, code = spinner("Pulling latest changes", git.pull_rebase, path)
    if code != 0:
        err(f"Pull failed:\n{errmsg}")
        teach_panel(spinner("AI analyzing error", explain_error, errmsg))
    else:
        ok(f"Up to date!\n{out or 'Already up to date.'}")


# ══════════════════════════════════════════════════════════════════════════
# FLOW 3 — CLONE
# ══════════════════════════════════════════════════════════════════════════

def flow_clone():
    console.print()
    console.print(Rule("[bold cyan]📥  Clone — Download a Project from GitHub[/bold cyan]", style="cyan"))
    console.print()
    teach_panel("'Cloning' downloads an entire GitHub project to your computer — history and all.")
    console.print("  [dim]Paste the GitHub repository URL to clone:[/dim]")
    console.print("  [dim](Ctrl+V or right-click to paste)[/dim]")
    _cl_s = PtStyle.from_dict({"prompt": "#00d7ff bold"})
    try:
        url = pt_prompt("  ❯ URL: ", style=_cl_s).strip()
    except (KeyboardInterrupt, EOFError):
        return
    if not url:
        err("No URL provided.")
        return
    dest = ask_path("Where to save it (folder path)")
    out, errmsg, code = spinner("Cloning repository", git.clone_repo, url.strip(), dest)
    if code != 0:
        err(f"Clone failed:\n{errmsg}")
        teach_panel(spinner("AI analyzing error", explain_error, errmsg))
    else:
        ok(f"Repository cloned!\nSaved to: {dest}")


# ══════════════════════════════════════════════════════════════════════════
# FLOW 4 — STATUS
# ══════════════════════════════════════════════════════════════════════════

def flow_status():
    console.print()
    console.print(Rule("[bold cyan]📊  Git Status[/bold cyan]", style="cyan"))
    console.print()
    path = ask_path()
    if not _require_repo(path):
        return
    teach_panel("'git status' shows which files changed, which are staged, and which are new.")
    branch = git.get_branch(path)
    status_out, _, _ = git.get_status(path)
    log_out, _, _ = git.get_log(path, 5)
    commit_count = git.get_commit_count(path)
    remote_out, _, _ = git.get_remote(path)

    console.print(f"\n  [bold white]Project Info[/bold white]")
    console.print(f"  [dim]{'─' * 50}[/dim]")
    console.print(f"  [cyan]Path[/cyan]          {path}")
    console.print(f"  [cyan]Branch[/cyan]        {branch}")
    console.print(f"  [cyan]Commits[/cyan]       {commit_count}")
    console.print(f"  [cyan]Remote[/cyan]        {'Connected ✓' if remote_out else 'Not connected ⚠'}")
    console.print()
    info_box("Git Status", status_out)
    if log_out:
        info_box("Recent Commits", log_out)


# ══════════════════════════════════════════════════════════════════════════
# FLOW 5 — BRANCH MANAGER
# ══════════════════════════════════════════════════════════════════════════

def flow_branch():
    console.print()
    console.print(Rule("[bold cyan]🌿  Branch Manager[/bold cyan]", style="cyan"))
    console.print()
    path = ask_path()
    if not _require_repo(path):
        return

    teach_panel("A 'branch' is like a parallel copy of your project. "
                "You work on a branch without touching the main code until you're ready.")

    _ITEMS = ["List all branches", "Create new branch", "Switch to branch",
              "Delete a branch", "Rename a branch"]

    while True:
        current = git.get_branch(path)
        console.print(f"  [dim]Current branch:[/dim] [bold cyan]{current}[/bold cyan]")

        idx = _sub_menu("Branch Manager", _ITEMS)
        if idx is None:
            break

        action = _ITEMS[idx]

        if action == "List all branches":
            branches = git.get_all_branches(path)
            if branches:
                console.print()
                for b in branches:
                    marker = "  [bold green]← current[/bold green]" if b == current else ""
                    console.print(f"  [cyan]{b}[/cyan]{marker}")
                console.print()
            else:
                warn("No branches found.")

        elif action == "Create new branch":
            name = _pick("New branch name")
            if not name:
                warn("No name entered.")
                continue
            out, errmsg, code = spinner(f"Creating branch '{name}'", git.create_branch, path, name)
            if code != 0:
                err(f"Failed:\n{errmsg}")
                teach_panel(spinner("AI analyzing error", explain_error, errmsg))
            else:
                ok(f"Created and switched to branch '{name}'!")

        elif action == "Switch to branch":
            branches = git.get_local_branches(path)
            others = [b for b in branches if b != current]
            if not others:
                warn("No other local branches to switch to.")
                continue
            bidx = _sub_menu("Switch to:", others)
            if bidx is None:
                continue
            target = others[bidx]
            out, errmsg, code = spinner(f"Switching to '{target}'", git.switch_branch, path, target)
            if code != 0:
                err(f"Failed:\n{errmsg}")
                teach_panel(spinner("AI analyzing error", explain_error, errmsg))
            else:
                ok(f"Switched to '{target}'!")

        elif action == "Delete a branch":
            branches = git.get_local_branches(path)
            others = [b for b in branches if b != current]
            if not others:
                warn("No other branches to delete.")
                continue
            bidx = _sub_menu("Delete which branch?", others)
            if bidx is None:
                continue
            target = others[bidx]
            if not _confirm(f"Delete branch '{target}'? (unmerged changes will be lost)", default=False):
                warn("Cancelled.")
                continue
            out, errmsg, code = spinner(f"Deleting '{target}'", git.delete_branch, path, target)
            if code != 0:
                if not _confirm("Branch has unmerged changes. Force delete anyway?", default=False):
                    continue
                out, errmsg, code = spinner(f"Force deleting '{target}'",
                                            git.delete_branch, path, target, force=True)
            if code == 0:
                ok(f"Branch '{target}' deleted.")
            else:
                err(f"Failed:\n{errmsg}")

        elif action == "Rename a branch":
            branches = git.get_local_branches(path)
            if not branches:
                warn("No branches to rename.")
                continue
            bidx = _sub_menu("Rename which branch?", branches)
            if bidx is None:
                continue
            target = branches[bidx]
            new_name = _pick(f"New name for '{target}'")
            if not new_name:
                warn("No name entered.")
                continue
            out, errmsg, code = spinner("Renaming branch", git.rename_branch, path, target, new_name)
            if code == 0:
                ok(f"Renamed '{target}' → '{new_name}'!")
            else:
                err(f"Failed:\n{errmsg}")

        console.print()


# ══════════════════════════════════════════════════════════════════════════
# FLOW 6 — MERGE
# ══════════════════════════════════════════════════════════════════════════

def flow_merge():
    console.print()
    console.print(Rule("[bold cyan]🔀  Merge Branch[/bold cyan]", style="cyan"))
    console.print()
    path = ask_path()
    if not _require_repo(path):
        return

    teach_panel("'Merging' combines work from one branch into another. "
                "Think of it as combining two document drafts into one final version.")

    current = git.get_branch(path)
    branches = git.get_local_branches(path)
    others = [b for b in branches if b != current]

    if not others:
        warn("No other branches to merge from.")
        return

    console.print(f"\n  [dim]You are on:[/dim] [bold cyan]{current}[/bold cyan]")
    console.print(f"  [dim]Merge INTO {current} FROM:[/dim]")

    idx = _sub_menu("Which branch to merge in?", others)
    if idx is None:
        return
    source = others[idx]

    if not _confirm(f"Merge '{source}' into '{current}'?"):
        warn("Cancelled.")
        return

    out, errmsg, code = spinner(f"Merging '{source}' → '{current}'", git.merge_branch, path, source)

    if code != 0:
        if "CONFLICT" in out or "CONFLICT" in errmsg:
            err("Merge conflict detected!")
            info_box("Conflicts", out)
            teach_panel(
                "A merge conflict means two branches changed the same lines differently. "
                "Open the conflicting files, look for <<<<<<< markers, edit them to keep what you want, "
                "then run 'git add .' and 'git commit' to finish the merge."
            )
        else:
            err(f"Merge failed:\n{errmsg}")
            teach_panel(spinner("AI analyzing error", explain_error, errmsg))
    else:
        ok(f"Merged '{source}' into '{current}' successfully!")
        if out:
            info_box("Merge result", out)


# ══════════════════════════════════════════════════════════════════════════
# FLOW 7 — STASH
# ══════════════════════════════════════════════════════════════════════════

def flow_stash():
    console.print()
    console.print(Rule("[bold cyan]📦  Stash — Save Work Temporarily[/bold cyan]", style="cyan"))
    console.print()
    path = ask_path()
    if not _require_repo(path):
        return

    teach_panel("'Stash' is like putting your half-done work in a drawer. "
                "You can come back later and pull it out exactly as you left it.")

    _ITEMS = ["Save current changes to stash", "List stashes", "Apply a stash", "Drop a stash"]

    while True:
        idx = _sub_menu("Stash", _ITEMS)
        if idx is None:
            break

        action = _ITEMS[idx]

        if action == "Save current changes to stash":
            msg = _pick("Stash label (optional, Enter to skip)")
            out, errmsg, code = spinner("Stashing changes", git.stash_save, path, msg)
            if code != 0:
                err(f"Stash failed:\n{errmsg}")
            else:
                ok(f"Changes stashed!\n{out}")

        elif action == "List stashes":
            out, _, _ = git.stash_list(path)
            if out:
                info_box("Stash List", out)
            else:
                warn("No stashes found.")

        elif action == "Apply a stash":
            stash_out, _, _ = git.stash_list(path)
            if not stash_out:
                warn("No stashes to apply.")
                continue
            stashes = stash_out.splitlines()
            sidx = _sub_menu("Apply which stash?", stashes)
            if sidx is None:
                continue
            out, errmsg, code = spinner(f"Applying stash@{{{sidx}}}", git.stash_apply, path, sidx)
            if code != 0:
                err(f"Apply failed:\n{errmsg}")
            else:
                ok(f"Stash applied!\n{out}")

        elif action == "Drop a stash":
            stash_out, _, _ = git.stash_list(path)
            if not stash_out:
                warn("No stashes to drop.")
                continue
            stashes = stash_out.splitlines()
            sidx = _sub_menu("Drop which stash?", stashes)
            if sidx is None:
                continue
            if not _confirm(f"Drop stash@{{{sidx}}}?", default=False):
                continue
            out, errmsg, code = spinner(f"Dropping stash@{{{sidx}}}", git.stash_drop, path, sidx)
            if code == 0:
                ok("Stash dropped.")
            else:
                err(f"Failed:\n{errmsg}")

        console.print()


# ══════════════════════════════════════════════════════════════════════════
# FLOW 8 — DIFF VIEWER
# ══════════════════════════════════════════════════════════════════════════

def flow_diff():
    console.print()
    console.print(Rule("[bold cyan]🔍  View Diff — What Changed[/bold cyan]", style="cyan"))
    console.print()
    path = ask_path()
    if not _require_repo(path):
        return

    teach_panel("'diff' shows exactly what lines you added (+) or removed (-) since the last commit.")

    _ITEMS = [
        "Unstaged changes (not yet added)",
        "Staged changes (already added, not committed)",
        "Stats only (which files changed)",
    ]
    idx = _sub_menu("Which diff to view?", _ITEMS)
    if idx is None:
        return

    staged = idx == 1
    stats_only = idx == 2

    if stats_only:
        out, _, _ = spinner("Getting diff stats", git.get_diff_stat, path, staged=False)
        staged_out, _, _ = git.get_diff_stat(path, staged=True)
        combined = "\n".join(filter(None, [out, staged_out]))
        if combined:
            info_box("Changed Files (stats)", combined)
        else:
            ok("No changes to show.")
        return

    out, errmsg, code = spinner("Getting diff", git.get_diff_full, path, staged=staged)

    if not out:
        ok("No changes to show." if staged else "No unstaged changes.")
        return

    lines = out.splitlines()
    if len(lines) > 80:
        display = "\n".join(lines[:80]) + f"\n... ({len(lines) - 80} more lines)"
    else:
        display = out

    console.print(Panel(
        f"[white]{display}[/white]",
        title=f"[bold]{'Staged' if staged else 'Unstaged'} Diff[/bold]",
        border_style="yellow",
    ))


# ══════════════════════════════════════════════════════════════════════════
# FLOW 9 — FULL LOG
# ══════════════════════════════════════════════════════════════════════════

def flow_log():
    console.print()
    console.print(Rule("[bold cyan]📋  Commit Log[/bold cyan]", style="cyan"))
    console.print()
    path = ask_path()
    if not _require_repo(path):
        return
    if not git.has_commits(path):
        warn("No commits yet.")
        return

    teach_panel("The log shows every save point (commit) you've made — who made it, when, and what changed.")

    _COUNTS = ["Last 10 commits", "Last 20 commits", "Last 50 commits"]
    idx = _sub_menu("How many commits to show?", _COUNTS)
    count = [10, 20, 50][idx] if idx is not None else 10

    out, errmsg, code = spinner("Loading log", git.get_log_graph, path, count)

    if code != 0 or not out:
        warn("No commit history to show.")
        return

    console.print(Panel(f"[cyan]{out}[/cyan]", title="[bold]Commit History[/bold]",
                        border_style="dim", padding=(0, 2)))


# ══════════════════════════════════════════════════════════════════════════
# FLOW 10 — TAGS
# ══════════════════════════════════════════════════════════════════════════

def flow_tags():
    console.print()
    console.print(Rule("[bold cyan]🏷️   Tag Manager[/bold cyan]", style="cyan"))
    console.print()
    path = ask_path()
    if not _require_repo(path):
        return

    teach_panel("'Tags' mark specific commits as important — like 'v1.0' or 'release-2024'. "
                "They're used for versioning and releases.")

    _ITEMS = ["List all tags", "Create a tag", "Delete a tag", "Push tag to GitHub"]

    while True:
        idx = _sub_menu("Tag Manager", _ITEMS)
        if idx is None:
            break

        action = _ITEMS[idx]

        if action == "List all tags":
            out, _, _ = git.list_tags(path)
            if out:
                info_box("Tags", out)
            else:
                warn("No tags found.")

        elif action == "Create a tag":
            name = _pick("Tag name (e.g. v1.0.0)")
            if not name:
                warn("No name entered.")
                continue
            msg = _pick("Tag message (optional, Enter to skip)")
            out, errmsg, code = spinner(f"Creating tag '{name}'", git.create_tag, path, name, msg)
            if code == 0:
                ok(f"Tag '{name}' created!")
            else:
                err(f"Failed:\n{errmsg}")

        elif action == "Delete a tag":
            tags_out, _, _ = git.list_tags(path)
            if not tags_out:
                warn("No tags to delete.")
                continue
            tags = tags_out.splitlines()
            tidx = _sub_menu("Delete which tag?", tags)
            if tidx is None:
                continue
            tag = tags[tidx]
            if not _confirm(f"Delete tag '{tag}'?", default=False):
                continue
            out, errmsg, code = spinner(f"Deleting tag '{tag}'", git.delete_tag, path, tag)
            if code == 0:
                ok(f"Tag '{tag}' deleted.")
            else:
                err(f"Failed:\n{errmsg}")

        elif action == "Push tag to GitHub":
            tags_out, _, _ = git.list_tags(path)
            if not tags_out:
                warn("No tags to push.")
                continue
            tags = tags_out.splitlines()
            tidx = _sub_menu("Push which tag to GitHub?", tags)
            if tidx is None:
                continue
            tag = tags[tidx]
            out, errmsg, code = spinner(f"Pushing tag '{tag}'", git.push_tag, path, tag)
            if code == 0:
                ok(f"Tag '{tag}' pushed to GitHub!")
            else:
                err(f"Failed:\n{errmsg}")

        console.print()


# ══════════════════════════════════════════════════════════════════════════
# FLOW 11 — FIX GIT ERROR
# ══════════════════════════════════════════════════════════════════════════

def flow_fix():
    console.print()
    console.print(Rule("[bold cyan]🔧  Fix Git Error with AI[/bold cyan]", style="cyan"))
    console.print()
    console.print("  [dim]Paste the Git error you're seeing and Gemini will explain it.[/dim]")
    console.print("  [dim](Ctrl+V or right-click to paste in CMD)[/dim]\n")

    _err_style = PtStyle.from_dict({"prompt": "#00d7ff bold"})
    try:
        error_msg = pt_prompt("  ❯ Error: ", style=_err_style).strip()
    except (KeyboardInterrupt, EOFError):
        return
    if not error_msg:
        err("No error provided.")
        return

    explanation = spinner("Gemini analyzing error", explain_error, error_msg.strip())

    console.print(f"\n  [bold white]Your Error:[/bold white]")
    console.print(f"  [dim red]{error_msg.strip()[:300]}[/dim red]")
    console.print(f"\n  [bold white]What it means and how to fix it:[/bold white]\n")
    for line in explanation.splitlines():
        console.print(f"  [cyan]{line}[/cyan]")
    console.print()


# ══════════════════════════════════════════════════════════════════════════
# FLOW 12 — UNDO LAST COMMIT
# ══════════════════════════════════════════════════════════════════════════

def flow_undo():
    console.print()
    console.print(Rule("[bold cyan]↩️   Undo Last Commit[/bold cyan]", style="cyan"))
    console.print()
    path = ask_path()
    if not _require_repo(path):
        return
    if not git.has_commits(path):
        err("No commits to undo.")
        return

    log_out, _, _ = git.get_log(path, 3)
    info_box("Recent Commits", log_out)

    teach_panel("This will UNDO your last commit but KEEP your file changes — like removing the save label "
                "without deleting your work. Only affects commits not yet pushed to GitHub.")

    if not _confirm("Undo the last commit? (files will NOT be deleted)", default=False):
        warn("Cancelled.")
        return

    _, errmsg, code = spinner("Undoing last commit", git.undo_last_commit, path)
    if code != 0:
        err(f"Could not undo:\n{errmsg}")
        teach_panel(spinner("AI analyzing error", explain_error, errmsg))
    else:
        ok("Last commit undone! Your files are safe.")


# ══════════════════════════════════════════════════════════════════════════
# FLOW 13 — LEARN GIT
# ══════════════════════════════════════════════════════════════════════════

LEARN_TOPICS = [
    "What is Git?",
    "What is GitHub?",
    "What is a commit?",
    "What is a branch?",
    "What is push and pull?",
    "What is a merge conflict?",
    "What is .gitignore?",
    "What is git init?",
    "What is git clone?",
    "What is git add?",
    "What is git stash?",
    "What is git rebase?",
    "What is a tag?",
    "Ask my own question",
]


def flow_learn():
    console.print()
    console.print(Rule("[bold cyan]📚  Learn Git — Powered by Gemini AI[/bold cyan]", style="cyan"))
    console.print()
    console.print("  [dim]Pick a topic or ask your own question. Gemini answers in plain English.[/dim]\n")

    while True:
        idx = _sub_menu("Git Topics", LEARN_TOPICS)
        if idx is None:
            break

        topic = LEARN_TOPICS[idx]

        if topic == "Ask my own question":
            question = _pick("Your question")
            if not question:
                continue
        else:
            question = topic

        answer = spinner("Gemini thinking", answer_git_question, question)

        console.print(f"\n  [bold white]Q:[/bold white] {question}")
        console.print(f"  [dim]{'─' * 50}[/dim]")
        for line in answer.splitlines():
            console.print(f"  [cyan]{line}[/cyan]")
        console.print()


# ══════════════════════════════════════════════════════════════════════════
# FLOW 14 — SETUP GITHUB AUTH
# ══════════════════════════════════════════════════════════════════════════

def flow_setup_auth():
    console.print()
    console.print(Rule("[bold cyan]🔑  Setup GitHub Authentication[/bold cyan]", style="cyan"))
    console.print()

    console.print(
        "\n  [bold white]Why does Git ask for a token?[/bold white]\n\n"
        "  In 2021, GitHub stopped accepting your account [bold red]password[/bold red] for Git.\n"
        "  Now it requires a [bold cyan]Personal Access Token (PAT)[/bold cyan] — a special\n"
        "  key generated inside your GitHub account settings.\n\n"
        "  Think of it like a key card: your regular password gets you\n"
        "  into the GitHub website, but pushing/pulling code needs\n"
        "  this separate key card instead.\n"
    )

    _AUTH_ITEMS = [
        "How to create a GitHub PAT (step-by-step guide)",
        "Save my PAT so Git never asks again",
        "Check / fix my credential helper",
        "Test my GitHub connection",
    ]

    while True:
        idx = _sub_menu("GitHub Auth", _AUTH_ITEMS)
        if idx is None:
            break

        action = _AUTH_ITEMS[idx]
        console.print()

        # ── How to create a PAT ───────────────────────────────────────────
        if "How to create" in action:
            console.print("  [bold white]Steps to create a GitHub Personal Access Token:[/bold white]\n")
            steps = [
                "Open:  https://github.com/settings/tokens",
                "Click  'Generate new token (classic)'",
                "Give it a name (e.g.  my-laptop)",
                "Set expiration  →  90 days recommended",
                "Check the  'repo'  scope  (full repo access)",
                "Scroll down, click  'Generate token'",
                "Copy it immediately — GitHub shows it only once!",
            ]
            for i, s in enumerate(steps, 1):
                console.print(f"  [dim]{i}.[/dim]  {s}")
            console.print(
                "\n  [dim]When Git asks for your password during push/pull,\n"
                "  paste this token instead of your account password.[/dim]\n"
            )

        # ── Save PAT ──────────────────────────────────────────────────────
        elif "Save my PAT" in action:
            import subprocess as _sp

            _s = PtStyle.from_dict({"prompt": "#00d7ff bold"})

            console.print("  [dim]Your GitHub username (not email — your @handle):[/dim]")
            try:
                username = pt_prompt("  ❯ Username: ", style=_s).strip()
            except (KeyboardInterrupt, EOFError):
                console.print()
                continue
            if not username:
                warn("No username entered.")
                continue

            console.print("  [dim]Paste your Personal Access Token (Ctrl+V  •  input is hidden):[/dim]")
            try:
                token = pt_prompt("  ❯ Token: ", style=_s, is_password=True).strip()
            except (KeyboardInterrupt, EOFError):
                console.print()
                continue
            if not token:
                warn("No token entered.")
                continue

            # Ensure a credential helper is configured
            helper_out, _, _ = git.run_raw_command(".", "git config --global credential.helper")
            if not helper_out.strip():
                git.run_raw_command(".", "git config --global credential.helper manager")
                helper_out, _, _ = git.run_raw_command(".", "git config --global credential.helper")
                if not helper_out.strip():
                    git.run_raw_command(".", "git config --global credential.helper store")

            cred = (
                f"protocol=https\n"
                f"host=github.com\n"
                f"username={username}\n"
                f"password={token}\n"
            )
            try:
                result = _sp.run(
                    [git.GIT_BINARY, "credential", "approve"],
                    input=cred,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                if result.returncode == 0:
                    ok(
                        "PAT saved!\n"
                        "Git will no longer ask for credentials on github.com.\n"
                        "The token is stored securely in your system's credential manager."
                    )
                else:
                    err(f"Could not save credential:\n{result.stderr}")
            except Exception as exc:
                err(f"Error: {exc}")

        # ── Check / fix credential helper ─────────────────────────────────
        elif "Check" in action:
            helper_out, _, _ = git.run_raw_command(".", "git config --global credential.helper")
            helper = helper_out.strip()

            if helper:
                ok(f"Credential helper is set: {helper}")
                if "manager" in helper.lower():
                    console.print(
                        "  [dim]Git Credential Manager is active — tokens are stored\n"
                        "  securely in the Windows Credential Manager.[/dim]\n"
                    )
                elif "store" in helper.lower():
                    console.print(
                        "  [dim]Credentials are stored in ~/.git-credentials (plaintext).\n"
                        "  Works fine, but the file is not encrypted.[/dim]\n"
                    )
            else:
                warn(
                    "No credential helper configured.\n"
                    "Git will ask for your token on every push/pull."
                )
                if _confirm("Set up Git Credential Manager now? (recommended)"):
                    _, errmsg, code = git.run_raw_command(
                        ".", "git config --global credential.helper manager"
                    )
                    if code != 0:
                        _, errmsg, code = git.run_raw_command(
                            ".", "git config --global credential.helper manager-core"
                        )
                    if code == 0:
                        ok(
                            "Git Credential Manager enabled!\n"
                            "Enter your PAT once on next push — it'll be saved forever."
                        )
                    else:
                        _, _, code2 = git.run_raw_command(
                            ".", "git config --global credential.helper store"
                        )
                        if code2 == 0:
                            ok("Credential store (plaintext) enabled.")
                        else:
                            err(f"Could not set any credential helper:\n{errmsg}")

        # ── Test connection ───────────────────────────────────────────────
        elif "Test" in action:
            path = ask_path("Path to your git project")
            if not git.is_git_repo(path):
                err("Not a git project.")
                console.print()
                continue
            remote_out, _, _ = git.get_remote(path)
            if not remote_out:
                err("No remote configured — nothing to test.")
                console.print()
                continue

            out, errmsg, code = spinner(
                "Testing connection to GitHub",
                git.run_raw_command,
                path,
                "git ls-remote --heads origin",
            )

            if code == 0:
                ok(
                    "GitHub connection works!\n"
                    "Authentication is set up correctly — no token prompt needed."
                )
            else:
                combined = (out + " " + errmsg).lower()
                if "authentication" in combined or "403" in combined or "401" in combined or "token" in combined:
                    err(
                        "Authentication failed.\n"
                        "Your PAT may be expired or missing the 'repo' scope."
                    )
                    teach_panel(
                        "Create a new PAT at github.com/settings/tokens with the 'repo' scope checked. "
                        "Then use 'Save my PAT' in this menu to store it."
                    )
                else:
                    err(f"Connection failed:\n{errmsg}")

        console.print()


# ══════════════════════════════════════════════════════════════════════════
# FLOW 15 — ASK ANYTHING  (free-text AI Git assistant)
# ══════════════════════════════════════════════════════════════════════════

def flow_ask_anything():
    console.print()
    console.print(Rule("[bold cyan]💬  Ask Anything — AI Git Assistant[/bold cyan]", style="cyan"))
    console.print()
    console.print("  [dim]Type any git operation in plain English. Gemini will generate and run the command.[/dim]\n")
    console.print("  [dim]Examples:  'create a branch called hotfix'  •  'show last 5 commits'  •  "
                  "'add a remote called upstream'[/dim]\n")

    path = ask_path()
    if not Path(path).exists():
        err(f"Folder not found:\n{path}")
        return

    is_repo = git.is_git_repo(path)
    branch = git.get_branch(path) if is_repo else ""
    repo_context = f"Is git repo: {is_repo}, Branch: {branch}" if is_repo else "Not a git repo yet"

    _req_style = PtStyle.from_dict({"prompt": "#00d7ff bold"})
    while True:
        console.print("  [dim]What git operation do you want?  (Ctrl+V to paste  •  Enter alone to exit)[/dim]")
        try:
            request = pt_prompt("  ❯ ", style=_req_style).strip()
        except (KeyboardInterrupt, EOFError):
            break

        if not request:
            break

        command, explanation = spinner(
            "Gemini generating command",
            generate_git_command,
            request,
            branch,
            repo_context,
        )

        if command.upper() == "UNCLEAR" or not command.lower().startswith("git "):
            console.print()
            console.print(f"\n  [bold yellow]❓ Need more info:[/bold yellow]  {explanation}")
            console.print("  [dim]Please add the missing details to your request:[/dim]")
            try:
                request = pt_prompt("  ❯ ", default=request, style=_req_style).strip()
            except (KeyboardInterrupt, EOFError):
                break
            if not request:
                break
            command, explanation = spinner("Gemini retrying", generate_git_command,
                                           request, branch, repo_context)
            if command.upper() == "UNCLEAR" or not command.lower().startswith("git "):
                warn("Still unclear. Try describing it differently.")
                continue

        # Fill in any remaining placeholders interactively
        import re as _re
        placeholders = _re.findall(r"<([^>]+)>", command)
        if placeholders:
            console.print()
            console.print("  [dim]The command needs a few details:[/dim]")
            for ph in placeholders:
                _ph_s = PtStyle.from_dict({"prompt": "#00ff87 bold"})
                try:
                    value = pt_prompt(f"  ❯ {ph}: ", style=_ph_s).strip()
                except (KeyboardInterrupt, EOFError):
                    value = ""
                if value:
                    command = command.replace(f"<{ph}>", value, 1)
                else:
                    warn(f"No value for <{ph}> — skipping.")
                    command = ""
                    break
            if not command:
                continue

        # Show command + explanation for confirmation
        console.print(f"\n  [bold white]Your request:[/bold white] [dim]{request}[/dim]")
        console.print(f"  [bold yellow]Command:[/bold yellow]  [bold cyan]{command}[/bold cyan]")
        console.print(f"  [dim]{explanation}[/dim]\n")

        if not _confirm("Run this command?"):
            warn("Skipped.")
            if not _confirm("Try another operation?"):
                break
            continue

        out, errmsg, code = spinner(f"Running: {command}", git.run_raw_command, path, command)

        raw_output = "\n".join(filter(None, [out, errmsg])).strip()

        console.print()
        if raw_output:
            info_box(f"Output: {command}", raw_output[:1200])
        else:
            console.print("  [dim](command completed with no output)[/dim]")

        interpretation = spinner(
            "Gemini interpreting result",
            interpret_git_output,
            request,
            command,
            raw_output,
        )

        if code == 0:
            ok(f"Done!\n{interpretation}")
        else:
            console.print(f"\n  [bold red]✗[/bold red]  Command exited with an error.")
            for line in interpretation.splitlines():
                console.print(f"  [cyan]{line}[/cyan]")
            console.print()

        if is_repo:
            branch = git.get_branch(path)
            repo_context = f"Is git repo: True, Branch: {branch}"

        console.print()
        if not _confirm("Try another operation?"):
            break
        console.print()


def flow_run_mas_tests():
    from .test_terminal_mas import run_terminal_mas_tests
    run_terminal_mas_tests()


# ══════════════════════════════════════════════════════════════════════════
# MAIN MENU
# ══════════════════════════════════════════════════════════════════════════

_GROUPED_MENU = [
    ("Upload my code to GitHub",    flow_push),
    ("Download / get latest code",  None),
    ("See what changed",            None),
    ("Manage branches & tags",      None),
    ("Fix a problem",               None),
    ("Learn Git",                   None),
    ("Run Git Telemetry & MAS Tests", flow_run_mas_tests),
]

_SUB_ITEMS = {
    2: ["Pull latest changes",        "Clone a repository"],
    3: ["Check status",               "View diff",           "Commit log"],
    4: ["Branch manager",             "Merge branch",        "Stash",       "Tags"],
    5: ["Fix a Git error (AI)",       "Undo last commit",    "Setup GitHub auth"],
    6: ["Learn Git topics",           "Ask anything (AI)"],
}

_SUB_TITLES = {
    2: "Download / Get Latest Code",
    3: "See What Changed",
    4: "Manage Branches & Tags",
    5: "Fix a Problem",
    6: "Learn Git",
}

_SUB_FLOWS = {
    2: [flow_pull,        flow_clone],
    3: [flow_status,      flow_diff,         flow_log],
    4: [flow_branch,      flow_merge,        flow_stash,    flow_tags],
    5: [flow_fix,         flow_undo,         flow_setup_auth],
    6: [flow_learn,       flow_ask_anything],
}


def main():
    api_key = get_api_key()
    if not api_key:
        show_banner()
        api_key = setup_api_key()
        if not api_key:
            console.print("\n  [red]No API key provided. Returning to Fixbot.[/red]\n")
            return

    while True:
        try:
            show_home()
            raw = _pick()

            if raw.lower() in ("q", "exit", "quit", ""):
                console.print(f"\n  [bold cyan]Returning to Fixbot![/bold cyan]  [dim]Happy coding.[/dim]\n")
                break

            try:
                n = int(raw)
            except ValueError:
                warn("Enter a number from the menu.")
                continue

            if not (1 <= n <= len(_GROUPED_MENU)):
                warn(f"Enter a number between 1 and {len(_GROUPED_MENU)}.")
                continue

            label, direct_fn = _GROUPED_MENU[n - 1]

            if direct_fn is not None:
                direct_fn()
                pause()
            else:
                sidx = _sub_menu(_SUB_TITLES[n], _SUB_ITEMS[n])
                if sidx is None:
                    continue
                flow_fn = _SUB_FLOWS[n][sidx]
                flow_fn()
                pause()

        except KeyboardInterrupt:
            console.print(f"\n  [bold cyan]Returning to Fixbot![/bold cyan]\n")
            break
