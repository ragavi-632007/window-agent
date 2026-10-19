"""
Git Mock Objects & Environment Simulation Testing Module.
Provides mock git repositories, command interceptors, and simulated environments.
"""

import os
import shutil
import tempfile
from typing import Dict, List, Tuple, Optional, Any


class MockGitRepo:
    """
    In-memory / isolated temporary Git repository for simulation testing.
    """

    def __init__(self, repo_name: str = "mock_repo"):
        self.repo_name = repo_name
        self.temp_dir = tempfile.mkdtemp(prefix=f"git_mock_{repo_name}_")
        self.branches = ["main"]
        self.current_branch = "main"
        self.commits: List[Dict[str, str]] = []
        self.staged_files: List[str] = []
        self.untracked_files: List[str] = []
        self.remotes: Dict[str, str] = {}
        self._initialize_mock_files()

    def _initialize_mock_files(self) -> None:
        """Create sample mock repository files."""
        readme = os.path.join(self.temp_dir, "README.md")
        with open(readme, "w", encoding="utf-8") as f:
            f.write(f"# {self.repo_name}\nSimulated test repository.\n")
        self.untracked_files.append("README.md")

    def stage_file(self, filename: str) -> None:
        if filename in self.untracked_files:
            self.untracked_files.remove(filename)
        if filename not in self.staged_files:
            self.staged_files.append(filename)

    def create_commit(self, message: str) -> str:
        commit_hash = f"a{len(self.commits)+1:06d}"
        commit_obj = {
            "hash": commit_hash,
            "message": message,
            "branch": self.current_branch,
            "files": list(self.staged_files),
        }
        self.commits.append(commit_obj)
        self.staged_files.clear()
        return commit_hash

    def mock_run_git(self, args: List[str]) -> Tuple[str, str, int]:
        """Simulate git command execution."""
        if not args:
            return "", "Empty command", 1

        subcmd = args[0].lower()

        if subcmd == "status":
            staged_str = "\n".join([f"  staged: {f}" for f in self.staged_files])
            untracked_str = "\n".join([f"  untracked: {f}" for f in self.untracked_files])
            out = f"On branch {self.current_branch}\n{staged_str}\n{untracked_str}".strip()
            return out, "", 0

        elif subcmd == "branch":
            if len(args) > 1 and not args[1].startswith("-"):
                new_branch = args[1]
                if new_branch not in self.branches:
                    self.branches.append(new_branch)
                return f"Created branch {new_branch}", "", 0
            branch_list = "\n".join(
                [f"* {b}" if b == self.current_branch else f"  {b}" for b in self.branches]
            )
            return branch_list, "", 0

        elif subcmd == "checkout":
            if len(args) > 1:
                target = args[-1]
                if target in self.branches:
                    self.current_branch = target
                    return f"Switched to branch '{target}'", "", 0
                elif "-b" in args:
                    self.branches.append(target)
                    self.current_branch = target
                    return f"Switched to a new branch '{target}'", "", 0
            return "", f"error: pathspec '{args[-1]}' did not match any file(s)", 1

        elif subcmd == "log":
            if not self.commits:
                return "", "fatal: your current branch does not have any commits yet", 128
            lines = [f"{c['hash']} {c['message']}" for c in reversed(self.commits)]
            return "\n".join(lines), "", 0

        elif subcmd == "add":
            if "." in args:
                self.staged_files.extend(self.untracked_files)
                self.untracked_files.clear()
            return "", "", 0

        elif subcmd == "commit":
            msg_idx = args.index("-m") + 1 if "-m" in args else -1
            msg = args[msg_idx] if msg_idx > 0 and msg_idx < len(args) else "Mock commit"
            h = self.create_commit(msg)
            return f"[{self.current_branch} {h}] {msg}", "", 0

        return "", f"Mock runner: git command '{' '.join(args)}' simulated.", 0

    def cleanup(self) -> None:
        """Remove temporary mock folder."""
        if os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            except Exception:
                pass


def create_mock_repo_environment() -> MockGitRepo:
    """Factory helper to build a pre-populated mock environment."""
    mock = MockGitRepo()
    mock.stage_file("README.md")
    mock.create_commit("Initial commit")
    mock.branches.append("feature/login")
    return mock


def fake_push_no_upstream(path, branch, first_push=False):
    return (
        "",
        "fatal: The current branch main has no upstream branch.\n"
        "To push the current branch and set the remote as upstream, use\n"
        "    git push --set-upstream origin main\n",
        1,
    )


def fake_push_ok(path, branch, first_push=False):
    return ("Everything up-to-date\n", "", 0)
