import os
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List

import psutil
from rich.console import Console


def _system_drive() -> str:
    """Fix #10 — resolve the correct root drive instead of hardcoding C:\\."""
    if platform.system().lower() == "windows":
        return os.environ.get("SystemDrive", "C:") + "\\"
    return "/"


@dataclass
class VerificationResult:
    intent: str
    passed: bool
    before: Dict[str, Any]
    after: Dict[str, Any]
    changes: Dict[str, str]
    timestamp: float = field(default_factory=time.time)


class Verifier:
    def __init__(self) -> None:
        self.console = Console()
        self.history: List[VerificationResult] = []

    def snapshot(self, intent: str) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        intent = intent.upper()

        if intent == "SYSTEM":
            vm = psutil.virtual_memory()
            data["ram_used_pct"] = round(vm.percent, 1)
            data["cpu_percent"] = psutil.cpu_percent(interval=0.5)

        if intent == "STORAGE":
            drive = _system_drive()
            total, used, free = shutil.disk_usage(drive)
            data["disk_free_gb"] = round(free / 1e9, 2)
            data["disk_used_pct"] = round(used / total * 100, 1)

        if intent == "NETWORK":
            # Fix #6 — use context manager so socket always closes
            import socket
            try:
                with socket.create_connection(("8.8.8.8", 53), timeout=2):
                    data["internet"] = True
            except Exception:
                data["internet"] = False

        if intent == "DEV_ENV":
            try:
                result = subprocess.run(
                    ["pip", "--version"], capture_output=True, text=True, timeout=5
                )
                data["pip_ok"] = result.returncode == 0
            except Exception:
                data["pip_ok"] = False

        return data

    def verify(
        self, intent: str, before: Dict[str, Any], after: Dict[str, Any]
    ) -> VerificationResult:
        intent = intent.upper()
        changes: Dict[str, str] = {}
        passed_flags: List[bool] = []

        for key in set(before) | set(after):
            old = before.get(key)
            new = after.get(key)
            if old != new:
                changes[key] = f"{old} → {new}"

        if intent == "STORAGE":
            passed_flags.append(
                float(after.get("disk_free_gb", 0)) >= float(before.get("disk_free_gb", 0))
            )
        elif intent == "SYSTEM":
            old_ram = float(before.get("ram_used_pct", 100))
            new_ram = float(after.get("ram_used_pct", 100))
            passed_flags.append(new_ram <= old_ram + 2)
        elif intent == "NETWORK":
            passed_flags.append(bool(after.get("internet", False)))
        elif intent == "DEV_ENV":
            passed_flags.append(bool(after.get("pip_ok", False)))

        passed = all(passed_flags) if passed_flags else bool(changes)
        result = VerificationResult(
            intent=intent,
            passed=passed,
            before=before,
            after=after,
            changes=changes,
        )
        self.history.append(result)
        return result

    def display(self, result: VerificationResult) -> None:
        if result.passed:
            self.console.print("  [green][VERIFIED][/green] Fix confirmed — metrics improved.")
        else:
            self.console.print("  [yellow][UNVERIFIED][/yellow] Fix ran but metrics unchanged.")

        if result.changes:
            for key, change in result.changes.items():
                self.console.print(f"    [dim]{key}:[/dim] {change}")
        else:
            self.console.print("    [dim]No measurable change detected.[/dim]")
