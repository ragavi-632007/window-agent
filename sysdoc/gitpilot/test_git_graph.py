"""Tests for Git Action Graph."""
from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from gitpilot.nodes import (
    _analyze_text,
    error_analyzer_node,
    executor_node,
    planner_node,
    supervisor_node,
)


class TestErrorAnalyzer(unittest.TestCase):
    def test_upstream(self):
        a = _analyze_text("The current branch main has no upstream branch")
        self.assertEqual(a.strategy_id, "set_upstream")
        self.assertTrue(a.recoverable)

    def test_rejected(self):
        a = _analyze_text("! [rejected] failed to push some refs non-fast-forward")
        self.assertEqual(a.strategy_id, "pull_rebase_then_push")

    def test_auth(self):
        a = _analyze_text("Permission denied (publickey)")
        self.assertEqual(a.strategy_id, "auth_help")
        self.assertFalse(a.recoverable)

    def test_analyzer_does_not_call_git(self):
        state = {
            "verification": {"success": False},
            "last_error": "has no upstream branch",
            "step_results": [],
        }
        with patch("gitpilot.git_ops.push") as m:
            out = error_analyzer_node(state)
            m.assert_not_called()
        self.assertEqual(out["error_analysis"]["strategy_id"], "set_upstream")


class TestSupervisor(unittest.TestCase):
    def test_retry(self):
        out = supervisor_node(
            {
                "verification": {"success": False},
                "error_analysis": {
                    "recoverable": True,
                    "strategy_id": "set_upstream",
                    "reason": "x",
                },
                "planning_cycle": 1,
            }
        )
        self.assertEqual(out["supervisor_decision"]["action"], "retry")
        self.assertEqual(out["strategy_hint"], "set_upstream")
        self.assertEqual(out["planning_cycle"], 2)

    def test_success(self):
        out = supervisor_node(
            {
                "verification": {"success": True, "summary": "ok"},
                "error_analysis": {},
                "planning_cycle": 1,
            }
        )
        self.assertEqual(out["supervisor_decision"]["action"], "success")


class TestPlanner(unittest.TestCase):
    def test_hint_upstream(self):
        out = planner_node(
            {
                "user_query": "push",
                "planning_cycle": 2,
                "strategy_hint": "set_upstream",
                "inspect": {"branch": "main", "dirty": False},
                "attempts_made": [],
            }
        )
        names = [s["name"] for s in out["git_plan"]["steps"]]
        self.assertEqual(names, ["push_upstream"])


class TestExecutorAllowlist(unittest.TestCase):
    def test_unknown_blocked(self):
        state = {
            "approved": True,
            "repo_path": tempfile.gettempdir(),
            "git_plan": {"steps": [{"name": "rm_rf", "args": {}}]},
            "inspect": {"branch": "main"},
            "attempts_made": [],
        }
        out = executor_node(state)
        self.assertFalse(out["executor_ok"])
        self.assertIn("blocked", (out.get("last_error") or "").lower())


if __name__ == "__main__":
    unittest.main()
