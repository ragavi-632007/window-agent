"""
Git Verification & Analysis Logic Module.
Analyzes outcome of Git actions (merge conflicts, missing upstreams, destructive flags, state checks).
"""

import re
from typing import Dict, List, Any, Tuple, Optional


class GitOutcomeStatus:
    SUCCESS = "SUCCESS"
    MERGE_CONFLICT = "MERGE_CONFLICT"
    REBASE_CONFLICT = "REBASE_CONFLICT"
    MISSING_UPSTREAM = "MISSING_UPSTREAM"
    UNCOMMITTED_CHANGES = "UNCOMMITTED_CHANGES"
    NOT_A_REPO = "NOT_A_REPO"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    DESTRUCTIVE_WARNING = "DESTRUCTIVE_WARNING"
    UNTRACKED_OVERWRITE = "UNTRACKED_OVERWRITE"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


DESTRUCTIVE_FLAGS = {
    "--hard",
    "-D",
    "--force",
    "-f",
    "--delete",
    "--purge",
    "-fdx",
    "-fd",
}


def is_destructive_command(cmd_args: List[str]) -> Tuple[bool, str]:
    """
    Analyzes command args for dangerous or destructive flags.
    Returns (is_destructive, reason_message).
    """
    lowered = [a.lower() for a in cmd_args]
    if "reset" in lowered and "--hard" in lowered:
        return True, "Destructive reset: 'git reset --hard' discards uncommitted changes permanently."
    if "clean" in lowered and any(f in lowered for f in ("-fdx", "-fd", "-f")):
        return True, "Destructive clean: removes untracked files and directories permanently."
    if "push" in lowered and any(f in lowered for f in ("--force", "-f", "--force-with-lease")):
        return True, "Destructive push: force-pushing may overwrite commits on remote branch."
    if "branch" in lowered and "-d" in lowered:
        return True, "Destructive branch delete: force-deleting branch -D."

    for arg in cmd_args:
        if arg in DESTRUCTIVE_FLAGS:
            return True, f"Command contains potentially destructive flag '{arg}'."

    return False, ""


def detect_merge_conflicts(output: str) -> List[str]:
    """Extract list of conflicting files from Git stdout/stderr output."""
    conflicts = []
    lines = output.splitlines()
    for line in lines:
        line_str = line.strip()
        if line_str.startswith("CONFLICT"):
            match = re.search(r"CONFLICT\s+\([^)]+\):\s+Merge conflict in\s+(.+)", line_str)
            if match:
                conflicts.append(match.group(1).strip())
            else:
                match_generic = re.search(r"in\s+([^\s]+)$", line_str)
                if match_generic:
                    conflicts.append(match_generic.group(1).strip())
        elif "both modified:" in line_str:
            parts = line_str.split("both modified:")
            if len(parts) == 2:
                conflicts.append(parts[1].strip())
    return sorted(list(set(conflicts)))


def analyze_git_outcome(
    command: str,
    stdout: str,
    stderr: str,
    returncode: int,
) -> Dict[str, Any]:
    """
    Parses and categorizes the result of a Git action.
    """
    combined = (stdout + "\n" + stderr).strip()

    if returncode == 0 and not ("CONFLICT" in combined or "error:" in combined.lower()):
        return {
            "status": GitOutcomeStatus.SUCCESS,
            "risk_level": "LOW",
            "message": "Git command executed successfully.",
            "conflicts": [],
            "suggestion": None,
        }

    # Check for specific failure patterns
    if "not a git repository" in combined.lower():
        return {
            "status": GitOutcomeStatus.NOT_A_REPO,
            "risk_level": "MEDIUM",
            "message": "Directory is not a Git repository.",
            "conflicts": [],
            "suggestion": "Run 'git init' to initialize a new repository.",
        }

    conflicts = detect_merge_conflicts(combined)
    if conflicts or "Automatic merge failed" in combined:
        return {
            "status": GitOutcomeStatus.MERGE_CONFLICT,
            "risk_level": "HIGH",
            "message": f"Merge conflict detected in {len(conflicts)} file(s).",
            "conflicts": conflicts,
            "suggestion": "Resolve markers (<<<<<<< / ======= / >>>>>>>) in conflicting files, then commit.",
        }

    if "no tracking information" in combined or "has no upstream branch" in combined:
        return {
            "status": GitOutcomeStatus.MISSING_UPSTREAM,
            "risk_level": "LOW",
            "message": "Current branch has no remote upstream set.",
            "conflicts": [],
            "suggestion": "Run 'git push -u origin <branch_name>' to publish branch.",
        }

    if "cannot pull with rebase: you have unstaged changes" in combined.lower() or "please commit your changes" in combined.lower():
        return {
            "status": GitOutcomeStatus.UNCOMMITTED_CHANGES,
            "risk_level": "MEDIUM",
            "message": "Uncommitted working tree changes preventing git action.",
            "conflicts": [],
            "suggestion": "Stash changes with 'git stash' or commit before proceeding.",
        }

    if "permission denied" in combined.lower() or "publickey" in combined.lower():
        return {
            "status": GitOutcomeStatus.PERMISSION_DENIED,
            "risk_level": "HIGH",
            "message": "Git SSH or HTTP authentication permission denied.",
            "conflicts": [],
            "suggestion": "Check SSH keys or remote URL permissions.",
        }

    return {
        "status": GitOutcomeStatus.UNKNOWN_ERROR if returncode != 0 else GitOutcomeStatus.SUCCESS,
        "risk_level": "MEDIUM" if returncode != 0 else "LOW",
        "message": stderr or stdout or "Git action completed with warnings.",
        "conflicts": conflicts,
        "suggestion": "Review error log or verify status with 'git status'.",
    }


def verify_git_state(path: str) -> Dict[str, Any]:
    """
    Performs full verification check of repository state.
    """
    from sysdoc.gitpilot import git_ops

    is_repo = git_ops.is_git_repo(path)
    if not is_repo:
        return {
            "is_repo": False,
            "branch": None,
            "has_commits": False,
            "is_clean": True,
            "has_conflicts": False,
            "staged_count": 0,
        }

    branch = git_ops.get_branch(path)
    commits = git_ops.has_commits(path)
    status_out, _, _ = git_ops.get_status_short(path)
    is_clean = not bool(status_out.strip())
    staged = git_ops.has_staged_changes(path)

    # Check for merge / rebase in progress
    git_dir_out, _, _ = git_ops.run_git(["rev-parse", "--git-path", "MERGE_HEAD"], cwd=path)
    git_dir = git_dir_out.strip()
    is_merging = bool(git_dir and os.path.exists(os.path.join(path, git_dir)))

    return {
        "is_repo": True,
        "branch": branch,
        "has_commits": commits,
        "is_clean": is_clean,
        "has_staged": staged,
        "is_merging": is_merging,
        "status_summary": status_out[:200] if status_out else "Clean",
    }


def run_unit_tests() -> bool:
    """Internal unit test suite for verification logic."""
    # Test merge conflict detection
    sample_conflict = (
        "Auto-merging main.py\n"
        "CONFLICT (content): Merge conflict in main.py\n"
        "Automatic merge failed; fix conflicts and then commit the result."
    )
    conflicts = detect_merge_conflicts(sample_conflict)
    assert "main.py" in conflicts, "Merge conflict parsing failed"

    # Test destructive check
    is_dest, _ = is_destructive_command(["git", "reset", "--hard"])
    assert is_dest, "Destructive command flag check failed"

    return True
