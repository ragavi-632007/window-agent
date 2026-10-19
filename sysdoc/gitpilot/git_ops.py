import subprocess
import os
import shlex
from typing import Tuple


def find_git_binary() -> str:
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    for directory in path_dirs:
        if "GitPilot" in directory:
            continue
        for name in ["git.exe", "git.cmd", "git"]:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
    return "git"


GIT_BINARY = find_git_binary()


def run_git(args: list, cwd: str = None) -> Tuple[str, str, int]:
    try:
        result = subprocess.run(
            [GIT_BINARY] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except FileNotFoundError:
        return "", "Git is not installed. Download from https://git-scm.com", 1
    except Exception as e:
        return "", str(e), 1


def run_raw_command(path: str, raw_cmd: str) -> Tuple[str, str, int]:
    """Run a raw git command string. Strips leading 'git' if present."""
    try:
        parts = shlex.split(raw_cmd)
    except ValueError as e:
        return "", f"Could not parse command: {e}", 1
    if parts and parts[0].lower() == "git":
        parts = parts[1:]
    if not parts:
        return "", "Empty command.", 1
    return run_git(parts, cwd=path)


# ── Repo state ─────────────────────────────────────────────────────────────

def is_git_repo(path: str) -> bool:
    _, _, code = run_git(["rev-parse", "--git-dir"], cwd=path)
    return code == 0


def has_commits(path: str) -> bool:
    _, _, code = run_git(["rev-parse", "HEAD"], cwd=path)
    return code == 0


def has_staged_changes(path: str) -> bool:
    stdout, _, _ = run_git(["diff", "--cached", "--name-only"], cwd=path)
    return bool(stdout)


def get_branch(path: str) -> str:
    stdout, _, code = run_git(["branch", "--show-current"], cwd=path)
    if code == 0 and stdout:
        return stdout
    stdout, _, _ = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    return stdout or "main"


def get_commit_count(path: str) -> int:
    stdout, _, code = run_git(["rev-list", "--count", "HEAD"], cwd=path)
    if code == 0:
        try:
            return int(stdout)
        except ValueError:
            return 0
    return 0


def get_all_branches(path: str) -> list[str]:
    stdout, _, code = run_git(["branch", "-a", "--format=%(refname:short)"], cwd=path)
    if code != 0 or not stdout:
        return []
    return [b.strip() for b in stdout.splitlines() if b.strip()]


def get_local_branches(path: str) -> list[str]:
    stdout, _, code = run_git(["branch", "--format=%(refname:short)"], cwd=path)
    if code != 0 or not stdout:
        return []
    return [b.strip() for b in stdout.splitlines() if b.strip()]


# ── Basic operations ───────────────────────────────────────────────────────

def init_repo(path: str) -> Tuple[str, str, int]:
    return run_git(["init"], cwd=path)


def get_remote(path: str) -> Tuple[str, str, int]:
    return run_git(["remote", "-v"], cwd=path)


def add_remote(path: str, url: str) -> Tuple[str, str, int]:
    return run_git(["remote", "add", "origin", url], cwd=path)


def get_status(path: str) -> Tuple[str, str, int]:
    return run_git(["status"], cwd=path)


def get_status_short(path: str) -> Tuple[str, str, int]:
    return run_git(["status", "--short"], cwd=path)


def get_diff_names(path: str) -> Tuple[str, str, int]:
    return run_git(["diff", "--name-only"], cwd=path)


def stage_all(path: str) -> Tuple[str, str, int]:
    return run_git(["add", "."], cwd=path)


def commit(path: str, message: str) -> Tuple[str, str, int]:
    return run_git(["commit", "-m", message], cwd=path)


def push(path: str, branch: str, first_push: bool = False) -> Tuple[str, str, int]:
    if first_push:
        return run_git(["push", "-u", "origin", branch], cwd=path)
    return run_git(["push"], cwd=path)


def pull_rebase(path: str) -> Tuple[str, str, int]:
    return run_git(["pull", "--rebase"], cwd=path)


def get_log(path: str, n: int = 3) -> Tuple[str, str, int]:
    return run_git(["log", "--oneline", f"-n{n}"], cwd=path)


def get_log_graph(path: str, n: int = 20) -> Tuple[str, str, int]:
    return run_git(["log", "--oneline", "--graph", "--decorate", f"-n{n}"], cwd=path)


def clone_repo(url: str, dest: str) -> Tuple[str, str, int]:
    return run_git(["clone", url, dest])


def undo_last_commit(path: str) -> Tuple[str, str, int]:
    return run_git(["reset", "--soft", "HEAD~1"], cwd=path)


# ── Branch operations ──────────────────────────────────────────────────────

def create_branch(path: str, name: str) -> Tuple[str, str, int]:
    return run_git(["checkout", "-b", name], cwd=path)


def switch_branch(path: str, name: str) -> Tuple[str, str, int]:
    return run_git(["checkout", name], cwd=path)


def delete_branch(path: str, name: str, force: bool = False) -> Tuple[str, str, int]:
    flag = "-D" if force else "-d"
    return run_git(["branch", flag, name], cwd=path)


def rename_branch(path: str, old_name: str, new_name: str) -> Tuple[str, str, int]:
    return run_git(["branch", "-m", old_name, new_name], cwd=path)


def merge_branch(path: str, branch: str) -> Tuple[str, str, int]:
    return run_git(["merge", branch], cwd=path)


# ── Stash operations ───────────────────────────────────────────────────────

def stash_save(path: str, message: str = "") -> Tuple[str, str, int]:
    if message:
        return run_git(["stash", "push", "-m", message], cwd=path)
    return run_git(["stash"], cwd=path)


def stash_list(path: str) -> Tuple[str, str, int]:
    return run_git(["stash", "list"], cwd=path)


def stash_apply(path: str, index: int = 0) -> Tuple[str, str, int]:
    return run_git(["stash", "apply", f"stash@{{{index}}}"], cwd=path)


def stash_drop(path: str, index: int = 0) -> Tuple[str, str, int]:
    return run_git(["stash", "drop", f"stash@{{{index}}}"], cwd=path)


# ── Diff operations ────────────────────────────────────────────────────────

def get_diff_stat(path: str, staged: bool = False) -> Tuple[str, str, int]:
    args = ["diff", "--stat"]
    if staged:
        args.insert(1, "--cached")
    return run_git(args, cwd=path)


def get_diff_full(path: str, file: str = "", staged: bool = False) -> Tuple[str, str, int]:
    args = ["diff"]
    if staged:
        args.append("--cached")
    if file:
        args.append(file)
    return run_git(args, cwd=path)


# ── Tag operations ─────────────────────────────────────────────────────────

def list_tags(path: str) -> Tuple[str, str, int]:
    return run_git(["tag", "-l", "--sort=-version:refname"], cwd=path)


def create_tag(path: str, name: str, message: str = "") -> Tuple[str, str, int]:
    if message:
        return run_git(["tag", "-a", name, "-m", message], cwd=path)
    return run_git(["tag", name], cwd=path)


def delete_tag(path: str, name: str) -> Tuple[str, str, int]:
    return run_git(["tag", "-d", name], cwd=path)


def push_tag(path: str, name: str) -> Tuple[str, str, int]:
    return run_git(["push", "origin", name], cwd=path)
