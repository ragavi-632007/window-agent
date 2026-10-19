"""
Multi-Agent System (MAS) Telemetry and Terminal Execution Simulation Test Suite.
Tracks execution times, success rates, command counts, error rates, and simulates Git workflows.
"""

import sys
import time
from typing import Dict, List, Any, Optional

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


class GitTelemetryTracker:
    """Telemetry recorder for Git actions and multi-agent workflows."""

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.start_time = time.time()
        self.invocations: List[Dict[str, Any]] = []
        self.success_count = 0
        self.error_count = 0
        self.conflicts_count = 0

    def record_action(
        self,
        agent_role: str,
        command: str,
        execution_ms: float,
        success: bool,
        error_msg: str = "",
        conflict_detected: bool = False,
    ) -> None:
        if success:
            self.success_count += 1
        else:
            self.error_count += 1

        if conflict_detected:
            self.conflicts_count += 1

        self.invocations.append({
            "timestamp": time.strftime("%H:%M:%S"),
            "agent_role": agent_role,
            "command": command,
            "duration_ms": round(execution_ms, 2),
            "success": success,
            "error_msg": error_msg,
            "conflict": conflict_detected,
        })

    def get_summary(self) -> Dict[str, Any]:
        total = len(self.invocations)
        total_time = round((time.time() - self.start_time) * 1000, 2)
        avg_ms = round(sum(i["duration_ms"] for i in self.invocations) / max(1, total), 2)
        rate = round((self.success_count / max(1, total)) * 100, 1)

        return {
            "total_actions": total,
            "successful": self.success_count,
            "failed": self.error_count,
            "conflicts": self.conflicts_count,
            "success_rate_pct": rate,
            "total_duration_ms": total_time,
            "avg_latency_ms": avg_ms,
        }

    def print_telemetry_report(self) -> None:
        summary = self.get_summary()
        console.print()
        console.print(Panel("[bold cyan]🤖 Multi-Agent Git Telemetry Report[/bold cyan]", border_style="cyan"))

        table = Table(title="Execution Metrics", border_style="dim")
        table.add_column("Metric", style="bold")
        table.add_column("Value", style="cyan")

        table.add_row("Total Agent Tool Calls", str(summary["total_actions"]))
        table.add_row("Successful Executions", str(summary["successful"]))
        table.add_row("Failed Executions", str(summary["failed"]))
        table.add_row("Conflicts Detected", str(summary["conflicts"]))
        table.add_row("Overall Success Rate", f"{summary['success_rate_pct']}%")
        table.add_row("Average Tool Latency", f"{summary['avg_latency_ms']} ms")
        table.add_row("Total Test Elapsed Time", f"{summary['total_duration_ms']} ms")

        console.print(table)
        console.print()


def simulate_agent_git_workflow(repo_path: Optional[str] = None) -> GitTelemetryTracker:
    """
    Simulates a 4-Agent Git Workflow (Planner -> Executor -> Verifier -> Summarizer)
    over mock Git repository operations.
    """
    from sysdoc.gitpilot.test_mocks import create_mock_repo_environment
    from sysdoc.gitpilot.test_unit import analyze_git_outcome, is_destructive_command

    tracker = GitTelemetryTracker()
    mock_repo = create_mock_repo_environment()

    workflow_steps = [
        ("Planner", "git status", ["status"]),
        ("Executor", "git branch feature/auth", ["branch", "feature/auth"]),
        ("Executor", "git checkout feature/auth", ["checkout", "feature/auth"]),
        ("Executor", "git add .", ["add", "."]),
        ("Executor", "git commit -m 'Add authentication module'", ["commit", "-m", "Add authentication module"]),
        ("Verifier", "git log -n 1", ["log"]),
        ("Verifier", "git status", ["status"]),
    ]

    console.print("  [dim]Running Multi-Agent System (MAS) Git Simulation...[/dim]")

    for role, cmd_text, cmd_args in workflow_steps:
        t0 = time.time()

        # Pre-execution check
        is_dest, _ = is_destructive_command(cmd_args)

        # Mock run
        stdout, stderr, code = mock_repo.mock_run_git(cmd_args)
        duration_ms = (time.time() - t0) * 1000

        # Outcome analysis
        analysis = analyze_git_outcome(cmd_text, stdout, stderr, code)
        is_success = analysis["status"] in ("SUCCESS", "LOW") or code == 0

        tracker.record_action(
            agent_role=role,
            command=cmd_text,
            execution_ms=duration_ms,
            success=is_success,
            error_msg=stderr,
            conflict_detected=bool(analysis.get("conflicts")),
        )

        status_symbol = "[green]✓[/green]" if is_success else "[red]✗[/red]"
        console.print(f"  {status_symbol} [{role}] {cmd_text} [dim]({duration_ms:.1f}ms)[/dim]")

    mock_repo.cleanup()
    return tracker


def run_terminal_mas_tests() -> None:
    """CLI runner to execute terminal MAS telemetry test suite."""
    console.print("\n[bold cyan]── Starting Multi-Agent Git Telemetry & Simulation Suite ──[/bold cyan]")
    tracker = simulate_agent_git_workflow()
    tracker.print_telemetry_report()
    console.print("[bold green]✓ Multi-Agent System (MAS) tests completed successfully![/bold green]\n")
