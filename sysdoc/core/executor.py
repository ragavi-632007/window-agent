import inspect
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Dict, Optional, Tuple

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from .gemini_client import GeminiClient
from .intent_engine import IntentEngine
from .prompt_builder import PromptBuilder
from .verifier import Verifier, VerificationResult
from sysdoc.modules.dev_env import DevEnvironmentModule
from sysdoc.modules.network import NetworkModule
from sysdoc.modules.storage import StorageModule
from sysdoc.modules.system_health import SystemHealthModule
from sysdoc.tickets.ticket_manager import TicketManager

_DANGEROUS_PATTERNS = [
    "format", "wipe", "factory reset", "delete all", "rm -rf",
    "drop table", "truncate", "destroy",
]

FIX_TIMEOUT_SECONDS = 60
_STORAGE_TIMEOUT_SECONDS = 300


class SysDocExecutor:
    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self.intent_engine = IntentEngine()
        self.gemini = GeminiClient()
        self.console = Console()

        # Fix #1 — single instances shared with PromptBuilder (no duplicates)
        self.network = NetworkModule()
        self.storage = StorageModule()
        self.system_health = SystemHealthModule()
        self.dev_env = DevEnvironmentModule()

        self.prompt_builder = PromptBuilder(
            network=self.network,
            storage=self.storage,
            dev_env=self.dev_env,
            system_health=self.system_health,
        )

        self.ticket_manager = TicketManager()
        self.verifier = Verifier()

        # Fix #15 — persistent thread pool instead of one-per-fix
        self._fix_pool = ThreadPoolExecutor(max_workers=1)

        self.last_verification: Optional[VerificationResult] = None

        self.FIX_MAP = {
            ("NETWORK", "f"): (self.network.fix_dns,                  "Flushing DNS + switching to 8.8.4.4"),
            ("NETWORK", "r"): (self.network.fix_reset_adapter,        "Resetting Wi-Fi adapter"),
            ("STORAGE", "c"): (self._fix_storage_cleanup,             "Cleaning temp and Recycle Bin"),
            ("STORAGE", "x"): (self._fix_storage_duplicates,          "Removing duplicate files"),
            ("STORAGE", "p"): (self.storage.partition_wizard,         "Launching partition wizard"),
            ("DEV_ENV", "y"): (self.dev_env.fix_path,                 "Fixing Python PATH"),
            ("DEV_ENV", "c"): (self.dev_env.fix_pip,                  "Repairing pip"),
            ("DEV_ENV", "v"): (self.dev_env.fix_rebuild_venv,         "Rebuilding virtual environment"),
            ("SYSTEM",  "k"): (self.system_health.fix_kill_processes, "Killing high-RAM processes"),
            ("SYSTEM",  "p"): (self.system_health.fix_power_balanced, "Setting power plan to Balanced"),
        }

    def __del__(self) -> None:
        try:
            self._fix_pool.shutdown(wait=False)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Safety
    # ------------------------------------------------------------------

    def _is_safe(self, description: str) -> bool:
        desc_lower = description.lower()
        return not any(pattern in desc_lower for pattern in _DANGEROUS_PATTERNS)

    # ------------------------------------------------------------------
    # Fix execution
    # ------------------------------------------------------------------

    def _call_fix_with_timeout(
        self, fix_function: Any, os_data: Dict[str, Any], timeout: int = FIX_TIMEOUT_SECONDS
    ) -> Any:
        future = self._fix_pool.submit(self._call_fix_function, fix_function, os_data)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            raise TimeoutError(f"Fix timed out after {timeout}s")

    def run(
        self, intent: str, action: str, os_data: Dict[str, Any]
    ) -> Tuple[str, Dict[str, Any]]:
        intent_key = (intent or "").upper()
        action_key = (action or "").lower()

        if action_key == "t":
            return self._run_ticket_action(intent_key, os_data)

        mapping_key = (intent_key, action_key)
        if mapping_key not in self.FIX_MAP:
            self.console.print(f"No fix mapped for {intent_key} / {action_key}", style="yellow")
            return ("unsupported", os_data)

        fix_function, description = self.FIX_MAP[mapping_key]

        if not self._is_safe(description):
            self.console.print(f"  [red][BLOCKED][/red] Unsafe operation refused: {description}")
            return ("blocked", os_data)

        if self.dry_run:
            self.console.print(f"  [yellow][DRY RUN][/yellow] Would execute: {description}")
            return (f"[dry-run] {description}", os_data)

        before_snapshot = self.verifier.snapshot(intent_key)

        # Interactive or long-running fixes that must run directly on the main thread
        _direct_ops = {("STORAGE", "c"), ("STORAGE", "p")}
        if mapping_key in _direct_ops:
            try:
                result = fix_function(os_data) if mapping_key != ("STORAGE", "c") else self._fix_storage_cleanup(os_data)
            except Exception as error:
                self.console.print(f"[!] Fix failed: {error}", style="bold red")
                return ("failed", os_data)
        else:
            timeout = FIX_TIMEOUT_SECONDS
            try:
                with self.console.status(
                    f"  [dim]{description}...[/dim]", spinner="dots"
                ):
                    result = self._call_fix_with_timeout(fix_function, os_data, timeout=timeout)
            except TimeoutError as error:
                self.console.print(f"[!] {error}", style="bold red")
                return ("timeout", os_data)
            except Exception as error:
                self.console.print(f"[!] Fix failed: {error}", style="bold red")
                return ("failed", os_data)

        response = str(result or "")
        for line in response.splitlines():
            self.console.print(line)

        after_snapshot = self.verifier.snapshot(intent_key)
        verification = self.verifier.verify(intent_key, before_snapshot, after_snapshot)
        self.verifier.display(verification)
        self.last_verification = verification

        new_os_data = self.prompt_builder.build_context("", intent_key)
        self._report_changes(os_data, new_os_data)
        return (response, new_os_data)

    def _call_fix_function(self, function: Any, os_data: Dict[str, Any]) -> Any:
        signature = inspect.signature(function)
        if len(signature.parameters) > 0:
            return function(os_data)
        return function()

    def _fix_storage_cleanup(self, os_data: Dict[str, Any]) -> str:
        from display.banner import get_theme_hex
        theme_hex = get_theme_hex()

        BAR_WIDTH = 36
        SNAKE_LEN = 10

        PHASES = [
            ("1", "User Temp Files",  "⟳", theme_hex),
            ("2", "Browser Cache",    "⊕", "#00cfff"),
            ("3", "System Cache",     "⚙", "#cc88ff"),
            ("4", "Recycle Bin",      "♻", "#ffaa00"),
        ]
        TOTAL_PHASES = len(PHASES)

        state: Dict[str, Any] = {
            "file":            "",
            "count":           0,
            "phase_idx":       0,   # 0-3 while running, 4 = all done
        }

        def on_delete(name: str) -> None:
            state["file"]  = name
            state["count"] += 1

        results: Dict[str, str] = {}

        def run_temp() -> None:
            state["phase_idx"] = 0
            results["temp"] = self.storage.fix_temp(on_delete=on_delete)

        def run_browser() -> None:
            state["phase_idx"] = 1
            results["browser"] = self.storage.fix_browser_cache(on_delete=on_delete)

        def run_system() -> None:
            state["phase_idx"] = 2
            results["system"] = self.storage.fix_system_cache(on_delete=on_delete)

        def run_recycle() -> None:
            state["phase_idx"] = 3
            results["recycle"] = self.storage.fix_recycle_bin()
            state["phase_idx"] = 4

        def _render(frame: int) -> Panel:
            idx  = state["phase_idx"]
            done = idx >= TOTAL_PHASES

            if done:
                phase_num, phase_name, phase_icon, bar_color = "✓", "Complete", "✔", "#00ff88"
            else:
                phase_num, phase_name, phase_icon, bar_color = PHASES[idx]

            # Completed phases shown as ticked rows above the active one
            tick_lines = []
            for i, (pn, pname, _, _) in enumerate(PHASES):
                if i < idx:
                    tick_lines.append(f"  [bold #00ff88]✔[/bold #00ff88]  [dim]Phase {pn} — {pname}[/dim]")

            if done:
                bar_markup = f"[bold #00ff88]{'█' * BAR_WIDTH}[/bold #00ff88]"
            else:
                pos    = frame % BAR_WIDTH
                inside = min(SNAKE_LEN, BAR_WIDTH - pos)
                bar_str = "░" * pos + "█" * inside + "░" * (BAR_WIDTH - pos - inside)
                bar_markup = f"[bold {bar_color}]{bar_str}[/bold {bar_color}]"

            fname = state["file"]
            if fname:
                label = fname if len(fname) <= 44 else "…" + fname[-43:]
            elif done:
                label = "All phases complete."
            else:
                label = f"Scanning {phase_name}..."

            active_line  = (
                f"  [bold {bar_color}]Phase {phase_num} of {TOTAL_PHASES}[/bold {bar_color}]"
                f"  —  {phase_name}"
            )
            bar_line     = f"  {bar_markup}"
            action_line  = f"  [dim]{phase_icon}[/dim]  [white]{label}[/white]"
            counter_line = f"  [dim]Files removed :[/dim] [bold]{state['count']}[/bold]"

            rows = ([""] + tick_lines
                    + ([""] if tick_lines else [])
                    + [active_line, "", bar_line, "", action_line, "", counter_line, ""])
            content = "\n".join(rows)
            title = f"[bold {theme_hex}]  ◈  CACHE REMOVAL  [/bold {theme_hex}]"
            return Panel(content, title=title, border_style=theme_hex, padding=(0, 1))

        # Run phases sequentially on a background thread so animation stays live
        def _run_all() -> None:
            run_temp()
            run_browser()
            run_system()
            run_recycle()

        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_run_all)
            frame = 0
            with Live(console=self.console, refresh_per_second=20) as live:
                while state["phase_idx"] < TOTAL_PHASES:
                    live.update(_render(frame))
                    frame += 1
                    time.sleep(0.05)
                live.update(_render(frame))
                time.sleep(0.8)
            fut.result(timeout=_STORAGE_TIMEOUT_SECONDS)

        self._last_files_removed = state["count"]

        self.console.print()
        self.console.print(f"  [bold #00ff88]✔  Cache removal complete.[/bold #00ff88]")
        self.console.print(f"  [dim]Total files removed : {state['count']}[/dim]")
        self.console.print()

        return "\n".join([
            results.get("temp",    ""),
            results.get("browser", ""),
            results.get("system",  ""),
            results.get("recycle", ""),
        ])

    def preview_cache_cleanup(self) -> None:
        """Print the bot explanation panel with all 4 cache categories and sizes."""
        from display.banner import get_theme_hex
        theme_hex = get_theme_hex()

        self.console.print()
        self.console.print(f"  [bold {theme_hex}]◉ FIXBOT[/bold {theme_hex}]  [dim]Full System Cache Removal[/dim]")
        self.console.print(f"  [dim]{'─' * 50}[/dim]")
        self.console.print()
        self.console.print("  Every browsing session, app launch, and Windows update leaves")
        self.console.print("  behind cached fragments. With many browser tabs open, Chrome")
        self.console.print("  and Edge alone can hold several GB of stale cache on disk.")
        self.console.print()

        with self.console.status("  [dim]Scanning cache sizes...[/dim]", spinner="dots"):
            sizes = self.storage.get_cache_sizes()

        temp_gb    = sizes.get("temp_gb",    0.0)
        browser_gb = sizes.get("browser_gb", 0.0)
        system_gb  = sizes.get("system_gb",  0.0)
        recycle_gb = sizes.get("recycle_gb", 0.0)
        total_gb   = round(temp_gb + browser_gb + system_gb + recycle_gb, 2)

        rows = [
            ("1", "User Temp Files",  temp_gb,    "Safe",  "#00ff88", "Windows recreates these automatically"),
            ("2", "Browser Cache",    browser_gb, "Safe",  "#00ff88", "Chrome / Edge / Firefox tab & page cache"),
            ("3", "System Cache",     system_gb,  "Safe",  "#00ff88", "Prefetch, thumbnails, DNS, error reports"),
            ("4", "Recycle Bin",      recycle_gb, "Low",   "#ffaa00", "Permanently removed — not recoverable"),
        ]

        self.console.print(f"  [dim]  #  {'Category':<22}{'Size':>9}   Risk    Notes[/dim]")
        self.console.print(f"  [dim]{'─' * 68}[/dim]")
        for num, name, gb, risk, risk_col, note in rows:
            self.console.print(
                f"  [bold {theme_hex}]  {num}[/bold {theme_hex}]  "
                f"[white]{name:<22}[/white]"
                f"[bold]{gb:>6.2f} GB[/bold]   "
                f"[{risk_col}]{risk:<7}[/{risk_col}]"
                f"[dim]{note}[/dim]"
            )
        self.console.print(f"  [dim]{'─' * 68}[/dim]")
        self.console.print(
            f"  [dim]  {'Total':>26}[/dim]"
            f"  [bold green]{total_gb:>6.2f} GB[/bold green]  [dim]estimated space to recover[/dim]"
        )
        self.console.print()

        # Warn if browsers are open — their cache can't be cleared while locked
        running_browsers = self.storage._running_browsers()
        if running_browsers:
            self.console.print(
                f"  [bold yellow]⚠  {', '.join(running_browsers)} is open.[/bold yellow]"
                f"  [dim]Browser cache files are locked while the browser runs.[/dim]"
            )
            self.console.print(
                f"  [dim]  → Close {', '.join(running_browsers)} before proceeding to clear browser cache.[/dim]"
                f"  [dim]  → Temp, System cache, and Recycle Bin will still be cleared now.[/dim]"
            )
            self.console.print()

    def _animate_complete(
        self,
        freed_gb: float,
        files_removed: int,
        label: str = "CLEANUP COMPLETE",
    ) -> None:
        """Fill-bar + count-up animation shown after any fix completes."""
        from display.banner import get_theme_hex
        theme_hex = get_theme_hex()

        STEPS     = 50
        BAR_WIDTH = 32
        DONE_COL  = "#00ff88"

        with Live(console=self.console, refresh_per_second=30) as live:
            for step in range(STEPS + 1):
                pct       = step / STEPS
                filled    = int(pct * BAR_WIDTH)
                bar       = "█" * filled + "░" * (BAR_WIDTH - filled)
                cur_gb    = freed_gb * pct
                pct_label = f"{int(pct * 100):>3}%"

                content = "\n".join([
                    "",
                    f"  [bold {DONE_COL}][{bar}][/bold {DONE_COL}] "
                    f"[bold white]{pct_label}[/bold white]",
                    "",
                    f"  [dim]Space freed  :[/dim]  "
                    f"[bold {DONE_COL}]{cur_gb:>6.2f} GB[/bold {DONE_COL}]"
                    f"  [dim]of  {freed_gb:.2f} GB[/dim]",
                    f"  [dim]Files removed:[/dim]  "
                    f"[bold]{files_removed:,}[/bold]",
                    "",
                ])
                live.update(Panel(
                    content,
                    title=f"[bold {DONE_COL}]  ✔  {label}  [/bold {DONE_COL}]",
                    border_style=DONE_COL,
                    padding=(0, 1),
                ))
                time.sleep(0.035)

    def run_cache_cleanup(self) -> str:
        """Run cleanup animation then show fill-bar count-up on completion."""
        import psutil as _psutil
        before_snap = self.verifier.snapshot("STORAGE")

        # Measure actual free space before
        try:
            free_before = _psutil.disk_usage("C:\\").free
        except Exception:
            free_before = 0

        result = self._fix_storage_cleanup({})

        # Measure actual free space after
        try:
            free_after  = _psutil.disk_usage("C:\\").free
            freed_gb    = max(0.0, round((free_after - free_before) / (1024 ** 3), 2))
        except Exception:
            freed_gb    = 0.0

        # Parse total files removed from result string
        files_removed = self._last_files_removed

        self.console.print()
        self._animate_complete(freed_gb, files_removed)

        # Print per-phase result lines
        self.console.print()
        for line in result.splitlines():
            if line.strip():
                self.console.print(f"  [dim]{line}[/dim]")
        self.console.print()

        after_snap   = self.verifier.snapshot("STORAGE")
        verification = self.verifier.verify("STORAGE", before_snap, after_snap)
        self.verifier.display(verification)
        self.last_verification = verification
        return result

    def _fix_storage_duplicates(self) -> str:
        candidate_dirs = [str(p) for p in self.storage._candidate_dirs()]
        duplicates = self.storage.find_duplicates(candidate_dirs)
        return self.storage.fix_delete_duplicates(duplicates)

    def _run_ticket_action(
        self, intent_key: str, os_data: Dict[str, Any]
    ) -> Tuple[str, Dict[str, Any]]:
        self.console.print("  running: creating ticket...", style="dim")
        try:
            result = self.ticket_manager.create_ticket(
                problem="auto-created by executor",
                os_data=os_data,
                gemini_reply="",
                module=intent_key,
            )
        except Exception as error:
            self.console.print(f"[!] Ticket creation failed: {error}", style="bold red")
            return ("failed", os_data)

        new_os_data = self.prompt_builder.build_context("", intent_key)
        self._report_changes(os_data, new_os_data)
        return (str(result), new_os_data)

    def _report_changes(
        self, old_data: Dict[str, Any], new_data: Dict[str, Any]
    ) -> None:
        for key in sorted(set(old_data).intersection(new_data)):
            old_val = old_data.get(key)
            new_val = new_data.get(key)
            if old_val == new_val:
                continue
            # Skip complex values (lists/dicts) — they produce unreadable output
            if isinstance(old_val, (list, dict)) or isinstance(new_val, (list, dict)):
                continue
            self.console.print(f"  [green][OK][/green] [dim]{key}:[/dim] {old_val} → {new_val}")
