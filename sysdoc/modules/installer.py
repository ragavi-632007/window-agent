import re
import shlex
import subprocess
from typing import Any, Dict, Optional

from prompt_toolkit import prompt as tk_prompt
from prompt_toolkit.styles import Style
from rich.console import Console

_PROMPT_STYLE = Style.from_dict({"prompt": "#00c6ff"})


_INSTALL_VERBS = ("install", "download", "get", "setup", "grab", "add")
_FILLER_PREFIX = re.compile(r"^(?:me|the|a|an|please|for me|yourself)\s+", re.IGNORECASE)
_FILLER_SUFFIX = re.compile(r"\s+(?:for me|please|now|asap|quickly|here|on my pc|on my computer)$", re.IGNORECASE)
_LEADUP = re.compile(
    r"^(?:can you|could you|please|help me|i want to|i need to|i'd like to|how (?:do i|to)|i want)\s+",
    re.IGNORECASE,
)
_EXCLUDE_WORDS = (
    "broken", "fix", "error", "failed", "not working", "issue", "problem",
    "repair", "reinstall pip", "update pip", "upgrade pip", "uninstall",
    "unistall", "uninstal",
)
_SUPPORTED_MANAGERS = {"winget", "pip", "npm", "choco"}


def extract_app_name(user_input: str) -> Optional[str]:
    lower = user_input.lower()
    if any(w in lower for w in _EXCLUDE_WORDS):
        return None
    cleaned = _LEADUP.sub("", user_input.strip())
    lower_cleaned = cleaned.lower()
    for verb in _INSTALL_VERBS:
        match = re.search(rf"\b{verb}\b\s+(.*)", lower_cleaned, re.IGNORECASE)
        if match:
            start = match.start(1)
            app = cleaned[start:].strip()
            app = _FILLER_PREFIX.sub("", app)
            app = _FILLER_SUFFIX.sub("", app)
            words = app.split()
            if app and 1 <= len(words) <= 6:
                return app.strip()
    return None


class InstallerModule:
    _GEMINI_PROMPT = """\
User wants to install: "__APP__"
System: Windows
Available package managers: winget, pip, npm, choco

Rules:
- General Windows apps (browsers, media players, editors, games, tools): use winget
- Python libraries or CLI tools (numpy, flask, black, etc.): use pip
- Node.js packages used globally (prettier, eslint, nodemon, etc.): use npm with -g flag
- Software not available on winget: use choco
- The command must be complete and ready to paste into a terminal
- For winget: ALWAYS use the exact package ID with --id (e.g. winget install --id Discord.Discord --accept-package-agreements --accept-source-agreements). NEVER use bare app name like "winget install Discord" — that causes ambiguity errors when multiple packages match.

Respond ONLY in this exact 3-line format with no extra text:
MANAGER: <winget|pip|npm|choco>
COMMAND: <the exact full command>
EXPLANATION: <1-2 sentences — what it installs and why this command>"""

    def __init__(self, gemini_client: Any) -> None:
        self.gemini = gemini_client
        self.console = Console()

    # ------------------------------------------------------------------ #
    # Public entry point                                                   #
    # ------------------------------------------------------------------ #

    def handle(self, app_name: str) -> str:
        from display.banner import get_theme_color
        theme_col = get_theme_color()
        self.console.print()
        self.console.print(
            f"  [bold {theme_col}]◉[/bold {theme_col}] [dim]Resolving installation strategy for:[/dim] [bold white]{app_name}[/bold white]"
        )

        plan = self._get_plan(app_name)
        if not plan:
            # Offline / no Gemini: still try winget by id or name
            safe = app_name.strip()
            if safe:
                # Prefer known IDs
                known = {
                    "discord": "Discord.Discord",
                    "vscode": "Microsoft.VisualStudioCode",
                    "visual studio code": "Microsoft.VisualStudioCode",
                    "chrome": "Google.Chrome",
                    "git": "Git.Git",
                }
                pkg_id = known.get(safe.lower(), safe)
                plan = {
                    "manager": "winget",
                    "command": (
                        f"winget install --id {pkg_id} "
                        f"--accept-package-agreements --accept-source-agreements "
                        f"--disable-interactivity"
                    ),
                    "explanation": f"Install {safe} via winget (offline fallback).",
                }
                self.console.print(
                    f"  [dim]Using offline winget plan for[/dim] [bold]{pkg_id}[/bold]"
                )
            else:
                self.console.print(
                    f"  [bold yellow]⚠[/bold yellow] [dim]Install data unavailable. Online intelligence required.[/dim]\n"
                    f"    [dim]Ensure GEMINI_API_KEY is configured and active.[/dim]"
                )
                return "offline"

        # Check if already installed before asking to run
        installed_version = self._check_installed(plan["manager"], plan["command"])

        if installed_version:
            self._display_already_installed(app_name, plan, installed_version)
            action = self._prompt_already_installed()
            if action == "u":
                plan = dict(plan, command=self._update_command(plan["manager"], plan["command"]))
            elif action == "r":
                plan = dict(plan, command=self._reinstall_command(plan["manager"], plan["command"]))
            else:
                self.console.print("\n  [dim]Cancelled.[/dim]")
                return "cancelled"

        # Always show full plan + confirm before running (install, update, or reinstall)
        self._display_plan(plan)
        run_choice = self._prompt_run()
        if run_choice != "1":
            self.console.print("\n  [dim]Cancelled.[/dim]")
            return "cancelled"

        returncode = self._run(plan["command"], label=app_name)
        self.console.print()

        if returncode == 0:
            self.console.print(f"  [bold green]✓[/bold green] [dim]{app_name} installed successfully.[/dim]")
        else:
            self.console.print(
                f"  [bold red]✗[/bold red] [red]Process terminated with code {returncode}. Review trace above.[/red]"
            )

        return "ok" if returncode == 0 else "error"

    # ------------------------------------------------------------------ #
    # Already-installed detection                                          #
    # ------------------------------------------------------------------ #

    def _check_installed(self, manager: str, command: str) -> Optional[str]:
        """Return version string if already installed, None if not found."""
        pkg = self._extract_package_name(manager, command)
        if not pkg:
            return None
        checkers = {
            "winget": self._check_winget,
            "pip": self._check_pip,
            "npm": self._check_npm,
            "choco": self._check_choco,
        }
        checker = checkers.get(manager)
        return checker(pkg) if checker else None

    def _extract_package_name(self, manager: str, command: str) -> Optional[str]:
        parts = command.split()
        try:
            if manager in ("winget", "pip", "choco"):
                idx = parts.index("install")
                # Skip flags like --id, -e, -y
                for candidate in parts[idx + 1 :]:
                    if not candidate.startswith("-"):
                        return candidate
            elif manager == "npm":
                for flag in ("-g", "--global"):
                    if flag in parts:
                        idx = parts.index(flag)
                        if idx + 1 < len(parts) and not parts[idx + 1].startswith("-"):
                            return parts[idx + 1]
                idx = parts.index("install")
                for candidate in parts[idx + 1 :]:
                    if not candidate.startswith("-"):
                        return candidate
        except (ValueError, IndexError):
            pass
        return None

    def _check_winget(self, pkg: str) -> Optional[str]:
        try:
            result = subprocess.run(
                ["winget", "show", "--id", pkg, "--accept-source-agreements"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.strip().lower().startswith("version:"):
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
        return None

    def _check_pip(self, pkg: str) -> Optional[str]:
        try:
            result = subprocess.run(
                ["pip", "show", pkg],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.lower().startswith("version:"):
                        return line.split(":", 1)[1].strip()
                return "installed"
        except Exception:
            pass
        return None

    def _check_npm(self, pkg: str) -> Optional[str]:
        try:
            result = subprocess.run(
                ["npm", "list", "-g", pkg, "--depth=0"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and pkg in result.stdout:
                match = re.search(rf"{re.escape(pkg)}@([\d.\w-]+)", result.stdout)
                return match.group(1) if match else "installed"
        except Exception:
            pass
        return None

    def _check_choco(self, pkg: str) -> Optional[str]:
        try:
            result = subprocess.run(
                ["choco", "list", "--local-only", pkg],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if pkg.lower() in line.lower() and " " in line:
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            return parts[1]
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------ #
    # Update / reinstall commands                                          #
    # ------------------------------------------------------------------ #

    def _update_command(self, manager: str, original_command: str) -> str:
        pkg = self._extract_package_name(manager, original_command) or ""
        return {
            # --force works whether the package came from winget or the Store
            "winget": f"winget install --id {pkg} --force --accept-package-agreements --accept-source-agreements",
            "pip":    f"pip install --upgrade {pkg}",
            "npm":    f"npm update -g {pkg}",
            "choco":  f"choco upgrade {pkg} -y",
        }.get(manager, original_command)

    def _reinstall_command(self, manager: str, original_command: str) -> str:
        pkg = self._extract_package_name(manager, original_command) or ""
        return {
            "winget": f"winget install --id {pkg} --force --accept-package-agreements --accept-source-agreements",
            "pip":    f"pip install --force-reinstall {pkg}",
            "npm":    f"npm install -g {pkg}",
            "choco":  f"choco install {pkg} --force -y",
        }.get(manager, original_command)

    # ------------------------------------------------------------------ #
    # Display helpers                                                      #
    # ------------------------------------------------------------------ #

    def _display_plan(self, plan: Dict) -> None:
        from rich.panel import Panel
        from display.banner import get_theme_color
        theme_col = get_theme_color()
        
        content = f"[dim]Engine:[/dim] [bold white]{plan['manager']}[/bold white]\n"
        content += f"[dim]Exec:[/dim] [yellow]{plan['command']}[/yellow]\n"
        if plan.get("explanation"):
            content += f"\n[dim]{plan['explanation']}[/dim]"
            
        from rich import box
        self.console.print()
        self.console.print(Panel(content, title=f"[bold {theme_col}]Deployment Plan[/bold {theme_col}]", box=box.ROUNDED, border_style=theme_col))

    def _display_already_installed(self, app_name: str, plan: Dict, version: str) -> None:
        from rich.panel import Panel
        from display.banner import get_theme_color
        theme_col = get_theme_color()
        
        content = f"[dim]Engine:[/dim] [bold white]{plan['manager']}[/bold white]\n"
        if plan.get("explanation"):
            content += f"\n[dim]{plan['explanation']}[/dim]"
            
        from rich import box
        self.console.print()
        self.console.print(Panel(content, title=f"[bold green]✓ Installed:[/bold green] [bold white]{app_name}[/bold white] [dim]v{version}[/dim]", border_style="green", box=box.ROUNDED))

    def _prompt_already_installed(self) -> str:
        from display.animations import AnimatedMenu
        from display.banner import get_theme_color
        theme_col = get_theme_color()
        options = [
            ("1", "Update it",  theme_col),
            ("2", "Reinstall",  "dim"),
            ("3", "Cancel",     "dim"),
        ]
        menu = AnimatedMenu(options)
        choice = menu.run()
        return {"1": "u", "2": "r", "3": "n"}.get(choice, "n")

    def _prompt_run(self) -> str:
        from display.animations import AnimatedMenu
        from display.banner import get_theme_color
        theme_col = get_theme_color()
        options = [
            ("1", "Run it",  theme_col),
            ("2", "Cancel",  "dim"),
        ]
        menu = AnimatedMenu(options)
        return menu.run()

    # ------------------------------------------------------------------ #
    # Execution                                                            #
    # ------------------------------------------------------------------ #

    def _get_plan(self, app_name: str) -> Optional[Dict]:
        if len(app_name) > 100:
            app_name = app_name[:100]
        prompt = self._GEMINI_PROMPT.replace("__APP__", app_name)
        try:
            raw = self.gemini.generate(prompt)
        except Exception:
            return None
        if not raw or "unavailable" in raw.lower():
            return None
        return self._parse(raw)

    def _parse(self, text: str) -> Optional[Dict]:
        result: Dict = {}
        for line in text.strip().splitlines():
            if line.startswith("MANAGER:"):
                result["manager"] = line.split(":", 1)[1].strip().lower()
            elif line.startswith("COMMAND:"):
                result["command"] = line.split(":", 1)[1].strip()
            elif line.startswith("EXPLANATION:"):
                result["explanation"] = line.split(":", 1)[1].strip()
        if "manager" not in result or "command" not in result:
            return None
        if result["manager"] not in _SUPPORTED_MANAGERS:
            result["manager"] = "winget"

        # Auto-correct: if Gemini produced a bare "winget install <Name>" without
        # --id, rewrite it to use --id so winget doesn't hit an ambiguity error.
        if result["manager"] == "winget":
            cmd = result["command"]
            parts = cmd.split()
            if (
                len(parts) >= 3
                and parts[0] == "winget"
                and parts[1] == "install"
                and "--id" not in parts
                and not parts[2].startswith("-")
            ):
                bare_name = parts[2]
                tail_flags = " ".join(p for p in parts[3:] if p.startswith("-"))
                result["command"] = (
                    f"winget install --id {bare_name}"
                    f" --accept-package-agreements --accept-source-agreements"
                    + (f" {tail_flags}" if tail_flags else "")
                )

        return result

    # ------------------------------------------------------------------ #
    # Winget ambiguity helpers                                             #
    # ------------------------------------------------------------------ #

    _MULTIPLE_PACKAGES_MARKER = "Multiple packages found matching input criteria"

    def _parse_winget_candidates(self, output: str) -> list:
        """Parse the candidate table from a winget 'Multiple packages found' error using column offsets."""
        candidates = []
        in_table = False
        header = None
        col_starts = []

        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("Name") and "Id" in stripped and "Source" in stripped:
                in_table = True
                header = line
                # Find start positions of columns Name, Id, Source
                col_starts = []
                for word in ("Name", "Id", "Source"):
                    idx = header.find(word)
                    if idx != -1:
                        col_starts.append(idx)
                col_starts = sorted(col_starts)
                continue
            if in_table and stripped.startswith("---"):
                continue
            if in_table and stripped:
                if not col_starts or len(col_starts) < 2:
                    # Fallback to split if header detection failed
                    cols = re.split(r"\s{2,}", stripped)
                    if len(cols) >= 2:
                        candidates.append({
                            "name":   cols[0].strip(),
                            "id":     cols[1].strip(),
                            "source": cols[2].strip() if len(cols) >= 3 else "",
                        })
                    continue

                fields = []
                for k, start in enumerate(col_starts):
                    end = col_starts[k + 1] if k + 1 < len(col_starts) else len(line)
                    value = line[start:end].strip() if start < len(line) else ""
                    fields.append(value)

                if len(fields) >= 2 and fields[0] and fields[1]:
                    candidates.append({
                        "name":   fields[0],
                        "id":     fields[1],
                        "source": fields[2] if len(fields) > 2 else "",
                    })
        return candidates

    def _prompt_winget_choice(self, candidates: list) -> Optional[str]:
        """Show the ambiguous candidates and ask the user to pick one.

        Returns the chosen winget package ID, or None if the user cancels.
        """
        from display.banner import get_theme_color
        theme_col = get_theme_color()

        self.console.print()
        self.console.print(
            f"  [bold yellow]⚠[/bold yellow]  "
            f"[dim]winget found multiple matches — which one do you want?[/dim]"
        )
        self.console.print()

        for i, c in enumerate(candidates, 1):
            source_tag = f" [dim]({c['source']})[/dim]" if c["source"] else ""
            self.console.print(
                f"  [{theme_col}]{i}[/{theme_col}]  "
                f"[bold white]{c['name']}[/bold white]"
                f"  [dim]{c['id']}[/dim]{source_tag}"
            )

        self.console.print()
        self.console.print(f"  [dim]Enter a number, or press Enter to cancel.[/dim]")

        raw = tk_prompt("  ❯ ", style=_PROMPT_STYLE).strip()

        if not raw:
            return None
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(candidates):
                return candidates[idx]["id"]
        except ValueError:
            pass
        return None

    # ------------------------------------------------------------------ #
    # Execution                                                            #
    # ------------------------------------------------------------------ #

    def _run(self, command: str, label: str = "") -> int:
        from display.animations import WgetBar
        from display.banner import get_theme_color

        self.console.print(f"  [dim]Running:[/dim] [yellow]{command}[/yellow]\n")

        try:
            cmd_list = shlex.split(command)
        except Exception as err:
            self.console.print(f"  [red][ERR][/red] Could not parse command: {err}")
            return 1

        bar = WgetBar(label=label or "package", color=get_theme_color())
        returncode, output = bar.run(cmd_list)

        # ── Winget ambiguity recovery ──────────────────────────────────────
        # When winget can't decide which package to install it exits non-zero
        # and prints "Multiple packages found matching input criteria".
        # Instead of silently failing, we parse the candidates, ask the user
        # to pick one, and re-run with the exact --id.
        if returncode != 0 and self._MULTIPLE_PACKAGES_MARKER in output:
            candidates = self._parse_winget_candidates(output)
            if candidates:
                chosen_id = self._prompt_winget_choice(candidates)
                if chosen_id:
                    new_command = (
                        f"winget install --id {chosen_id}"
                        f" --accept-package-agreements --accept-source-agreements"
                    )
                    self.console.print(
                        f"\n  [dim]Installing:[/dim] "
                        f"[bold white]{chosen_id}[/bold white]\n"
                    )
                    try:
                        cmd_list2 = shlex.split(new_command)
                    except Exception as err:
                        self.console.print(f"  [red][ERR][/red] Could not parse command: {err}")
                        return 1
                    bar2 = WgetBar(label=label or "package", color=get_theme_color())
                    returncode, output = bar2.run(cmd_list2)
                else:
                    self.console.print("\n  [dim]Cancelled.[/dim]")
                    return 1

        if returncode != 0 and output.strip():
            self.console.print()
            for line in output.splitlines():
                if line.strip():
                    self.console.print(f"  [dim]{line}[/dim]", highlight=False)

        return returncode
