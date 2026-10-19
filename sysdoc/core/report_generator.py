import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from rich.console import Console
from rich.panel import Panel


@dataclass
class Report:
    intent: str
    problem: str
    os_data: Dict[str, Any]
    ai_reply: str
    fix_applied: str
    verification_passed: Optional[bool]
    changes: Dict[str, str]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "problem": self.problem,
            "os_data": {k: str(v) for k, v in self.os_data.items()},
            "ai_reply": self.ai_reply,
            "fix_applied": self.fix_applied,
            "verification_passed": self.verification_passed,
            "changes": self.changes,
            "timestamp": self.timestamp,
            "datetime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.timestamp)),
        }


class ReportGenerator:
    def __init__(self, reports_dir: str) -> None:
        self.reports_dir = reports_dir
        self.console = Console()
        os.makedirs(reports_dir, exist_ok=True)

    def generate(
        self,
        intent: str,
        problem: str,
        os_data: Dict[str, Any],
        ai_reply: str,
        fix_applied: str = "",
        verification_passed: Optional[bool] = None,
        changes: Optional[Dict[str, str]] = None,
    ) -> Report:
        return Report(
            intent=intent,
            problem=problem,
            os_data=os_data,
            ai_reply=ai_reply,
            fix_applied=fix_applied,
            verification_passed=verification_passed,
            changes=changes or {},
        )

    def save(self, report: Report) -> str:
        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime(report.timestamp))
        base = f"report_{report.intent.lower()}_{ts}"
        txt_path = os.path.join(self.reports_dir, f"{base}.txt")
        json_path = os.path.join(self.reports_dir, f"{base}.json")

        lines = [
            "SysDoc Diagnostic Report",
            "========================",
            f"Date      : {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(report.timestamp))}",
            f"Intent    : {report.intent}",
            f"Problem   : {report.problem}",
            "",
            "--- System Data ---",
        ]
        for key, value in report.os_data.items():
            lines.append(f"  {key}: {value}")
        lines += [
            "",
            "--- AI Analysis ---",
            report.ai_reply,
            "",
            "--- Fix Applied ---",
            report.fix_applied or "None",
            "",
            "--- Verification ---",
        ]
        if report.verification_passed is None:
            lines.append("  Not verified")
        elif report.verification_passed:
            lines.append("  PASSED — metrics improved")
        else:
            lines.append("  FAILED — no measurable improvement")
        if report.changes:
            lines.append("  Changes:")
            for key, change in report.changes.items():
                lines.append(f"    {key}: {change}")

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, default=str)

        return txt_path

    def display_summary(self, report: Report, saved_path: str = "") -> None:
        from rich.rule import Rule
        from display.banner import get_theme_color
        theme_col = get_theme_color()

        if report.verification_passed is True:
            status = "[bold green]VERIFIED[/bold green]"
        elif report.verification_passed is False:
            status = "[bold yellow]UNVERIFIED[/bold yellow]"
        else:
            status = "[dim]not run[/dim]"

        self.console.print()
        self.console.print(Rule(f"[bold {theme_col}]✨ Diagnostic Report Summary[/bold {theme_col}]", style=f"dim {theme_col}", align="left"))
        self.console.print(f"    [dim]Intent:[/dim]  {report.intent}")
        self.console.print(f"    [dim]Fix:[/dim]     {report.fix_applied or 'None'}")
        self.console.print(f"    [dim]Status:[/dim]  {status}")
        
        if report.changes:
            self.console.print(f"    [dim]Changes:[/dim]")
            for key, change in list(report.changes.items())[:4]:
                self.console.print(f"      ✦ {key}: {change}")
        
        if saved_path:
            try:
                rel_path = os.path.relpath(saved_path, start=os.path.dirname(os.path.dirname(saved_path)))
            except Exception:
                rel_path = os.path.basename(saved_path)
            self.console.print(f"    [dim]Saved:[/dim]   [white]reports/{rel_path}[/white]")
        
        self.console.print(Rule(style=f"dim {theme_col}"))


    def list_recent(self, n: int = 5) -> list:
        try:
            files = [
                f for f in os.listdir(self.reports_dir) if f.endswith(".txt")
            ]
            files.sort(reverse=True)
            return [os.path.join(self.reports_dir, f) for f in files[:n]]
        except Exception:
            return []
