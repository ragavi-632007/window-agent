import ctypes

from prompt_toolkit import prompt as tk_prompt
from prompt_toolkit.styles import Style
from rich.console import Console

_console = Console()
_PROMPT_STYLE = Style.from_dict({"prompt": "#00c6ff"})


class PermissionGate:
    @staticmethod
    def has_admin() -> bool:
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False

    @staticmethod
    def ask_initial_permissions() -> None:
        import time
        import sys
        from display.banner import get_theme_color

        theme_col = get_theme_color()
        _console.print()
        _console.print(f"  [bold {theme_col}]System Initialization[/bold {theme_col}]")
        _console.print("  [dim]─────────────────────[/dim]")

        permissions = [
            "Network Adapter & Traffic Analysis",
            "Storage Drive Deep Scan Access",
            "Process Management & Termination",
            "System Registry & Environment Variables",
        ]

        for perm in permissions:
            try:
                raw = tk_prompt(
                    f"  ❯ Grant access to {perm} [y/n]: ",
                    style=_PROMPT_STYLE,
                ).strip().lower()
            except (KeyboardInterrupt, EOFError):
                raw = "n"

            sys.stdout.write("\033[1A\r\033[2K")
            sys.stdout.flush()

            if raw == "y":
                with _console.status(f"  [bold {theme_col}]Initializing {perm}...[/bold {theme_col}]", spinner="dots"):
                    time.sleep(1.2)
                _console.print(f"  [bold green]✓[/bold green] [dim]{perm}[/dim]")
            else:
                with _console.status(f"  [dim]Skipping {perm}...[/dim]", spinner="dots"):
                    time.sleep(0.6)
                _console.print(f"  [bold red]✗[/bold red] [dim]{perm} (Skipped)[/dim]")
            time.sleep(0.3)

        _console.print(f"\n  [bold green]✓[/bold green] [dim]All subsystems online. Ready.[/dim]\n")

    @staticmethod
    def ask_permission(intent: str = "", repair_plan: dict | None = None) -> str:
        from display.banner import get_theme_color
        from display.animations import AnimatedMenu

        theme_col = get_theme_color()
        intent_key = (intent or "").upper()

        if repair_plan:
            from display.banner import get_theme_color
            theme_col = get_theme_color()
            intent_key = (intent or "").upper()
            cycle = repair_plan.get("planning_cycle", 1)
            cycle_note = f" (cycle {cycle})" if cycle and cycle > 1 else ""

            # ── INSTALL plan (InstallPlan: target_id / strategy — no primary_fix)
            if intent_key == "INSTALL" or (
                repair_plan.get("domain") == "INSTALL"
                or ("target_id" in repair_plan and "primary_fix" not in repair_plan)
            ):
                goal = repair_plan.get("goal") or f"Install {repair_plan.get('target_name') or repair_plan.get('target_id') or 'app'}"
                pkg = repair_plan.get("target_id") or repair_plan.get("target_name") or "?"
                mgr = repair_plan.get("manager") or "winget"
                strategy = repair_plan.get("strategy") or "install"
                _console.print()
                _console.print(f"  [bold {theme_col}]Ready to install{cycle_note}[/bold {theme_col}]")
                _console.print(f"  [dim]{'─' * 50}[/dim]")
                _console.print(f"  [white]•[/white] [bold]{pkg}[/bold]  [dim]via {mgr} · {strategy}[/dim]")
                if repair_plan.get("reasoning"):
                    _console.print(f"  [dim]{repair_plan.get('reasoning')[:200]}[/dim]")
                _console.print(f"  [dim]{'─' * 50}[/dim]")
                options = [
                    ("y", f"Install {pkg} now", theme_col),
                    ("n", "Cancel", "dim"),
                    ("t", "Open support ticket", "magenta"),
                ]

            # ── UPDATE plan (packages list)
            elif intent_key == "UPDATE" or repair_plan.get("packages"):
                packages = repair_plan.get("packages") or []
                _console.print()
                _console.print(f"  [bold {theme_col}]Ready to update{cycle_note}[/bold {theme_col}]")
                if packages:
                    _console.print(f"  [dim]{'─' * 50}[/dim]")
                    for pkg in packages:
                        name = pkg.get("name", "?")
                        frm = pkg.get("from_version") or pkg.get("from") or "?"
                        to = pkg.get("to_version") or pkg.get("to") or "latest"
                        mgr = pkg.get("manager", "winget")
                        _console.print(
                            f"  [white]•[/white] [bold]{name}[/bold]  "
                            f"[dim]{frm} → {to}[/dim]  [dim](via {mgr})[/dim]"
                        )
                    _console.print(f"  [dim]{'─' * 50}[/dim]")
                    pkg_count = len(packages)
                    fix_desc = f"Update {pkg_count} selected package{'s' if pkg_count != 1 else ''} now"
                else:
                    fix_desc = "Run selected updates now"

                options = [
                    ("y", fix_desc, theme_col),
                    ("d", "Show update details before proceeding", "dim"),
                    ("n", "Skip — return to update list", "dim"),
                    ("t", "Open support ticket for this update", "magenta"),
                ]

            # ── Classic repair plan (primary_fix required)
            elif "primary_fix" in repair_plan:
                from agents.fix_registry import fix_label

                primary = repair_plan["primary_fix"]
                fix_desc = fix_label(intent_key, primary["id"])
                cycle_note = f" (retry #{cycle})" if cycle > 1 else ""

                _console.print()
                _console.print(f"  [bold {theme_col}]Recommended Goal:[/bold {theme_col}] {repair_plan['goal']}{cycle_note}")
                _console.print(f"  [bold]Root Cause:[/bold] {repair_plan['root_cause']}")
                _console.print(f"  [bold]Confidence:[/bold] {repair_plan['confidence']:.0%}")
                _console.print(f"  [bold]Primary Fix:[/bold] {fix_desc}  [dim]({primary['risk']} risk)[/dim]")
                if repair_plan.get("fallbacks"):
                    fallback_labels = [
                        f"{fix_label(intent_key, f['id'])} ({f['risk']} risk)" for f in repair_plan["fallbacks"]
                    ]
                    _console.print(f"  [dim]Fallbacks:[/dim] " + ", ".join(fallback_labels))
                _console.print(f"  [dim]Reasoning Summary:[/dim] {repair_plan['reasoning']}")

                options = [("y", fix_desc, theme_col)]
                if intent_key == "STORAGE":
                    options.append(("x", "Find & remove duplicate files", "dim"))
                    options.append(("p", "Launch Partition Wizard", "yellow"))
                options += [
                    ("d", "Inspect telemetry diagnostic details", "dim"),
                    ("t", "Open an automated support ticket", "magenta"),
                    ("n", "Skip recommendations / ignore", "dim"),
                ]
            else:
                # Safe generic fallback — never KeyError
                goal = repair_plan.get("goal") or intent_key or "Action"
                _console.print()
                _console.print(f"  [bold {theme_col}]Ready: {goal}{cycle_note}[/bold {theme_col}]")
                options = [
                    ("y", "Proceed", theme_col),
                    ("n", "Cancel", "dim"),
                ]
        else:
            # Legacy path -- unchanged, for any caller not yet migrated to
            # producing a RepairPlan.
            fix_desc = "Apply automatic fix"
            if intent_key == "NETWORK":
                fix_desc = "Flush DNS & Switch to Google DNS"
            elif intent_key == "STORAGE":
                fix_desc = "Run storage cleanup (Temp & Recycle Bin)"
            elif intent_key == "DEV_ENV":
                fix_desc = "Repair Python environment PATH"
            elif intent_key == "SYSTEM":
                fix_desc = "Terminate high-memory runaway tasks"

            options = [("y", fix_desc, theme_col)]
            if intent_key == "STORAGE":
                options.append(("x", "Find & remove duplicate files", "dim"))
                options.append(("p", "Launch Partition Wizard", "yellow"))
            options += [
                ("d", "Inspect telemetry diagnostic details", "dim"),
                ("t", "Open an automated support ticket", "magenta"),
                ("n", "Skip recommendations / ignore", "dim"),
            ]

        menu_title = "What would you like to do?" if intent_key == "UPDATE" else "Recommendation Dashboard"
        _console.print()
        _console.print(f"  [bold {theme_col}]{menu_title}[/bold {theme_col}]")
        _console.print("  [dim]────────────────────────[/dim]")

        menu = AnimatedMenu(options)
        choice = menu.run()

        if repair_plan:
            # fix_registry.py + plan_executor.py dispatch by fix_id, not
            # the old FIX_MAP letters -- return the raw menu choice and
            # let resolve_gate_choice() in agents/permission_gate_node.py
            # translate it.
            return choice

        if choice == "y":
            if intent_key == "NETWORK": return "f"
            if intent_key == "STORAGE": return "c"
            if intent_key == "DEV_ENV": return "y"
            if intent_key == "SYSTEM":  return "k"
        return choice
