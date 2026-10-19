"""
Git Tool Registry — sole allowlist for Git Action Graph executor.
"""
from __future__ import annotations

import subprocess
import time
from typing import Any, Callable, Dict, List, Optional, Tuple


class GitTool:
    def __init__(
        self,
        name: str,
        description: str,
        handler: Callable[..., Tuple[str, str, int]],
        args_schema: Optional[Dict[str, Any]] = None,
        is_destructive: bool = False,
    ):
        self.name = name
        self.description = description
        self.handler = handler
        self.args_schema = args_schema or {}
        self.is_destructive = is_destructive

    def execute(self, *args, **kwargs) -> Tuple[str, str, int]:
        return self.handler(*args, **kwargs)


class GitToolRegistry:
    def __init__(self):
        self._tools: Dict[str, GitTool] = {}
        self._register_default_tools()

    def register(self, tool: GitTool) -> None:
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[GitTool]:
        return self._tools.get(name)

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "is_destructive": t.is_destructive,
                "args_schema": t.args_schema,
            }
            for t in self._tools.values()
        ]

    def _register_default_tools(self) -> None:
        # Prefer package-relative import (sysdoc on path)
        try:
            from gitpilot import git_ops
        except ImportError:
            from sysdoc.gitpilot import git_ops  # type: ignore

        self.register(
            GitTool("git_status", "Working tree status", git_ops.get_status)
        )
        self.register(
            GitTool("git_log", "Recent commit history", git_ops.get_log)
        )
        self.register(
            GitTool("git_diff", "Show diffs", git_ops.get_diff_full)
        )
        self.register(
            GitTool("git_remote", "Show remotes", git_ops.get_remote)
        )
        self.register(
            GitTool("git_stage_all", "Stage all changes", git_ops.stage_all)
        )
        self.register(
            GitTool("git_commit", "Create commit", git_ops.commit)
        )
        self.register(
            GitTool(
                "git_push",
                "Push to remote",
                lambda path, branch="main", **kw: git_ops.push(
                    path, branch, first_push=False
                ),
            )
        )
        self.register(
            GitTool(
                "git_push_upstream",
                "Push and set upstream",
                lambda path, branch="main", **kw: git_ops.push(
                    path, branch, first_push=True
                ),
            )
        )
        self.register(
            GitTool("git_pull", "Pull with rebase", git_ops.pull_rebase)
        )
        self.register(
            GitTool(
                "git_branch",
                "Create branch",
                lambda path, name="feature", **kw: git_ops.create_branch(path, name),
            )
        )
        self.register(
            GitTool(
                "git_checkout",
                "Switch branch",
                lambda path, name="main", **kw: git_ops.switch_branch(path, name),
            )
        )
        self.register(
            GitTool(
                "git_merge",
                "Merge branch",
                lambda path, branch="", **kw: git_ops.merge_branch(path, branch),
            )
        )
        self.register(
            GitTool(
                "git_stash",
                "Stash changes",
                lambda path, message="", **kw: git_ops.stash_save(path, message),
            )
        )
        self.register(
            GitTool(
                "git_stash_pop",
                "Apply latest stash",
                lambda path, **kw: git_ops.stash_apply(path, 0),
            )
        )
        self.register(
            GitTool(
                "git_clone",
                "Clone repository",
                lambda path=None, url="", dest=".", **kw: git_ops.clone_repo(
                    url, dest
                ),
            )
        )
        # Destructive — registered but graph must NEVER auto-plan these
        self.register(
            GitTool(
                "git_reset_hard",
                "Reset --hard (destructive)",
                lambda path, **kw: git_ops.run_git(["reset", "--hard"], cwd=path),
                is_destructive=True,
            )
        )


def run_git_subprocess(
    cmd: List[str],
    cwd: Optional[str] = None,
    timeout: int = 30,
    stream_output: bool = False,
    on_output_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[str, str, int]:
    try:
        from gitpilot.git_ops import GIT_BINARY
    except Exception:
        from gitpilot.git_ops import find_git_binary

        GIT_BINARY = find_git_binary()

    full_cmd = [GIT_BINARY] + cmd
    try:
        res = subprocess.run(
            full_cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return res.stdout.strip(), res.stderr.strip(), res.returncode
    except subprocess.TimeoutExpired:
        return "", f"Git command timed out after {timeout} seconds.", 124
    except Exception as exc:
        return "", f"Git subprocess error: {exc}", 1


_GLOBAL_REGISTRY: Optional[GitToolRegistry] = None


def get_registry() -> GitToolRegistry:
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = GitToolRegistry()
    return _GLOBAL_REGISTRY
