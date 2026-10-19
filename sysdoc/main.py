import os, sys
from pathlib import Path
from dotenv import load_dotenv

if getattr(sys, "frozen", False):
    base_path = Path(sys._MEIPASS)   # inside .exe
    ROOT_DIR = base_path / "sysdoc"
else:
    base_path = Path(__file__).parent  # normal run
    ROOT_DIR = base_path

load_dotenv(ROOT_DIR / ".env")

import re
import time

from prompt_toolkit import prompt
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown

# Add both sysdoc/ (for bare imports in main.py) and the project root
# (parent of sysdoc/) so that `from sysdoc.*` imports used by core/,
# agents/, and modules/ resolve correctly.
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
_PROJECT_ROOT = str(ROOT_DIR.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.conversation_memory import ConversationMemory
from core.executor import SysDocExecutor
from core.permission_gate import PermissionGate
from core.report_generator import ReportGenerator
from modules.installer import InstallerModule, extract_app_name
from modules import file_finder
from display.banner import print_banner, print_help, ask_theme, get_theme_color, get_theme_hex, print_welcome_panel
from display.animations import typewriter_stream, linux_terminal_flash
from display.formatter import (
    print_bot_start,
    print_collecting,
    print_data,
    print_err,
    print_info,
    print_ok,
    print_process_table,
    print_browser_tab_table,
    print_bg_process_table,
    print_search_results_table,
    print_file_ops_menu,
    print_file_location_panel,
    print_section,
    print_ticket,
    print_user,
    print_system_scan,
    print_warn,
    print_agent_supervisor,
    print_agent_planner,
    print_agent_executor,
    print_agent_verifier,
    print_agent_summary,
)
from tickets.ticket_manager import TicketManager

console = Console()

_DRY_RUN = "--dry-run" in sys.argv
_MEMORY_PATH = os.path.join(ROOT_DIR, "memory", "conversation.json")
_REPORTS_DIR = os.path.join(ROOT_DIR, "reports")

COMMANDS = {
    "exit": "exit",
    "quit": "exit",
    "clear": "clear",
    "help": "help",
    "scan": "scan",
    "tickets": "tickets",
    "processes": "processes",
    "ps": "processes",
    "process running": "processes",
    "processes running": "processes",
    "running processes": "processes",
    "running apps": "processes",
    "what is running": "processes",
    "process list": "processes",
    "tabs": "tabs",
    "live tabs": "tabs",
    "report": "report",
    "reports": "report",
    "game": "game",
    "/fixgame": "game",
    r"\fixgit": "gitpilot",
    "fixgit": "gitpilot",
}

# Matches Windows absolute paths (quoted or unquoted, no embedded spaces)
_PATH_RE = re.compile(
    r'"([A-Za-z]:\\[^"]+)"'                                            # "C:\quoted path"
    r'|([A-Za-z]:\\(?:[^\\\s"\'<>|?*\n]+\\)*[^\\\s"\'<>|?*\n]*)'     # C:\unquoted\path
)

# Matches standalone filenames with a known extension (e.g. thalas.txt, config.json)
_FILENAME_RE = re.compile(
    r'\b([\w\-]+\.(?:txt|py|js|ts|json|csv|md|yaml|yml|xml|html|css|'
    r'java|cpp|c|h|go|rs|sh|bat|ps1|ini|cfg|conf|log|sql|php|rb|kt|swift|env|toml))\b',
    re.IGNORECASE,
)

_EXPLAIN_TRIGGERS = [
    "explain about ", "explain ", "read ", "open ", "show me ",
    "what is in ", "what's in ", "describe ", "analyze ", "analyse ",
    "tell me about ", "look at ", "show ", "display ",
]

_SEARCH_PREFIXES = [
    "find my file ", "find my folder ", "find my app ", "find my ",
    "find file ", "find folder ", "find app ", "find me the ", "find me ",
    "where is the file ", "where is the folder ", "where is my ", "where is the ", "where is ",
    "where my ", "where ",
    "locate file ", "locate folder ", "locate app ", "locate ",
    "search for file ", "search for folder ", "search for app ", "search for ",
    "look for file ", "look for folder ", "look for ", "show me where ",
]

_DELETE_PREFIXES = [
    "delete my file ", "delete my folder ", "delete my app ", "delete my ",
    "delete file ", "delete folder ", "delete app ", "delete ",
    "remove my file ", "remove my folder ", "remove my app ", "remove my ",
    "remove file ", "remove folder ", "remove app ", "remove ",
    "erase my file ", "erase my folder ", "erase my ", "erase ",
    "i want to delete ", "can you delete ", "please delete ",
    "get rid of ", "i need to delete ", "help me delete ",
]


def _extract_search_query(user_input: str) -> str:
    text = user_input.strip()
    lowered = text.lower()
    for prefix in sorted(_SEARCH_PREFIXES, key=len, reverse=True):
        if lowered.startswith(prefix):
            return text[len(prefix):].strip()
    return text


def _extract_delete_query(user_input: str) -> str:
    text = user_input.strip()
    lowered = text.lower()
    for prefix in sorted(_DELETE_PREFIXES, key=len, reverse=True):
        if lowered.startswith(prefix):
            return text[len(prefix):].strip()
    return text


def _location_description(path: str) -> str:
    """Return a human-readable description of a file/folder location."""
    p = path.lower()
    if "\\onedrive\\" in p and "\\desktop" in p:
        return "OneDrive Desktop  (synced — deleting here also removes it from the cloud)"
    if "\\desktop" in p:
        return "Desktop"
    if "\\downloads" in p:
        return "Downloads folder"
    if "\\documents" in p:
        return "Documents folder"
    if "\\onedrive" in p:
        return "OneDrive  (synced to cloud — cloud copy will also be deleted)"
    if "\\appdata\\local\\temp" in p:
        return "Temporary files folder  (safe to delete)"
    if "\\appdata\\local" in p:
        return "AppData\\Local  (app cache / local config data)"
    if "\\appdata\\roaming" in p:
        return "AppData\\Roaming  (app settings / user profile data)"
    if "\\program files (x86)" in p:
        return "Program Files (x86)  (32-bit installed application)"
    if "\\program files" in p:
        return "Program Files  (installed application)"
    if "\\system32" in p:
        return "Windows System32  ⚠ system file — delete only if you are sure"
    if "\\windows" in p:
        return "Windows folder  ⚠ system file — delete only if you are sure"
    if "\\users" in p:
        return "User profile folder"
    return os.path.dirname(path)


def _delete_commands(path: str, item_type: str) -> tuple:
    """Return (cmd_command, powershell_command) for manual deletion."""
    q = f'"{path}"'
    if item_type == "folder":
        return f"rmdir /s /q {q}", f'Remove-Item -Recurse -Force {q}'
    return f"del /f /q {q}", f'Remove-Item -Force {q}'


def _do_file_search(query: str, mem: "ConversationMemory") -> None:
    from prompt_toolkit import prompt as tk_prompt
    from prompt_toolkit.styles import Style as TkStyle

    hex_col = get_theme_hex()
    input_style = TkStyle.from_dict({"prompt": f"{hex_col} bold"})

    try:
        from agents.file_search_graph import run_file_search
        final = run_file_search(query)
        results = (
            final.get("ranked_results")
            or final.get("search_results")
            or []
        )
    except Exception as exc:
        print_warn(f"Search agent fallback: {exc}")
        with console.status(
            f"  [dim]Searching for '{query}' across all drives...[/dim]",
            spinner="dots",
        ):
            results = file_finder.search_system(query)

    print_search_results_table(results, query)

    if not results:
        print_warn(f"No results found for '{query}'")
        return

    console.print(f"  [dim]Enter a number (1–{len(results)}) to select, or press Enter to skip:[/dim]")
    try:
        idx_raw = tk_prompt("  ❯ ", style=input_style).strip()
    except (KeyboardInterrupt, EOFError):
        return

    if not idx_raw:
        return

    try:
        idx = int(idx_raw)
        if not (1 <= idx <= len(results)):
            print_warn("Invalid selection.")
            return
    except ValueError:
        print_warn("Not a number — skipping.")
        return

    selected = results[idx - 1]
    loc_desc = _location_description(selected["path"])
    cmd, ps_cmd = _delete_commands(selected["path"], selected["type"])
    print_file_location_panel(selected, loc_desc, cmd, ps_cmd)

    print_file_ops_menu()

    try:
        action = tk_prompt("  ❯ Select action: ", style=input_style).strip().lower()
    except (KeyboardInterrupt, EOFError):
        return

    if action == "d":
        console.print(f"  [bold red]⚠  Delete:[/bold red] [white]{selected['path']}[/white]")
        try:
            confirm = tk_prompt(
                "  ❯ Type 'yes' to confirm delete: ",
                style=TkStyle.from_dict({"prompt": "#ff4444 bold"}),
            ).strip().lower()
        except (KeyboardInterrupt, EOFError):
            return
        if confirm == "yes":
            msg = file_finder.delete_path(selected["path"])
            (print_ok if "Deleted" in msg else print_err)(msg)
        else:
            print_info("Delete cancelled.")

    elif action == "r":
        console.print(f"  [dim]Enter new name for '{selected['name']}':[/dim]")
        try:
            new_name = tk_prompt("  ❯ New name: ", style=input_style).strip()
        except (KeyboardInterrupt, EOFError):
            return
        if new_name:
            msg = file_finder.rename_path(selected["path"], new_name)
            (print_ok if "Renamed" in msg else print_err)(msg)
        else:
            print_info("Rename cancelled.")

    elif action == "c":
        msg = file_finder.copy_to_clipboard(selected["path"])
        (print_ok if "copied" in msg.lower() else print_err)(msg)

    elif action == "n":
        print_info("No action taken.")
    else:
        print_warn("Unknown action — skipping.")

    mem.add("user", f"find {query}")
    mem.add("model", f"Found {len(results)} result(s). Selected: {selected['path']}")
    console.print()


def _do_file_delete(query: str, mem: "ConversationMemory") -> None:
    """Find a file/folder by name and delete it after confirmation."""
    from prompt_toolkit import prompt as tk_prompt
    from prompt_toolkit.styles import Style as TkStyle

    hex_col = get_theme_hex()
    input_style = TkStyle.from_dict({"prompt": f"{hex_col} bold"})
    danger_style = TkStyle.from_dict({"prompt": "#ff4444 bold"})

    with console.status(
        f"  [dim]Searching for '{query}' to delete...[/dim]", spinner="dots"
    ):
        results = file_finder.search_system(query)

    print_search_results_table(results, query)

    if not results:
        print_info("Nothing found — nothing deleted.")
        return

    console.print(f"  [dim]Enter a number (1–{len(results)}) to select for deletion, or press Enter to cancel:[/dim]")
    try:
        idx_raw = tk_prompt("  ❯ ", style=input_style).strip()
    except (KeyboardInterrupt, EOFError):
        return

    if not idx_raw:
        print_info("Delete cancelled.")
        return

    try:
        idx = int(idx_raw)
        if not (1 <= idx <= len(results)):
            print_warn("Invalid selection — nothing deleted.")
            return
    except ValueError:
        print_warn("Not a number — nothing deleted.")
        return

    selected = results[idx - 1]
    loc_desc = _location_description(selected["path"])
    cmd, ps_cmd = _delete_commands(selected["path"], selected["type"])
    print_file_location_panel(selected, loc_desc, cmd, ps_cmd)

    console.print(f"  [bold red]⚠  CONFIRM DELETE[/bold red]  [dim]— This cannot be undone.[/dim]")
    console.print()

    try:
        confirm = tk_prompt(
            "  ❯ Type 'yes' to permanently delete: ", style=danger_style
        ).strip().lower()
    except (KeyboardInterrupt, EOFError):
        print_info("Delete cancelled.")
        return

    if confirm == "yes":
        # Best-effort: stop matching processes so folder/shortcuts unlock
        try:
            import subprocess
            stem = (
                Path(selected["path"]).stem
                if selected.get("type") != "folder"
                else Path(selected["path"]).name
            )
            for proc in (f"{stem}.exe", f"{stem}.EXE"):
                subprocess.run(
                    ["taskkill", "/F", "/IM", proc, "/T"],
                    capture_output=True, text=True, timeout=10,
                )
        except Exception:
            pass

        msg = file_finder.delete_path(selected["path"], cleanup_shortcuts=True)
        for part in [x.strip() for x in msg.split(" | ") if x.strip()]:
            if part.lower().startswith("delete failed"):
                print_err(part)
            else:
                print_ok(part)
        if "shortcut" not in msg.lower():
            print_info(
                "No Desktop/Start Menu shortcuts matched — "
                "refresh desktop (F5) if an icon still appears."
            )
        mem.add("user", f"delete {query}")
        mem.add("model", msg)
    else:
        print_info("Delete cancelled.")

    console.print()


def _launch_game() -> None:
    """Arcade boot screen then launch Ticket Rush."""
    import time as _time

    theme_col = get_theme_color()
    _ANSI = {
        "yellow": "\033[93m", "magenta": "\033[95m", "cyan": "\033[96m",
    }
    col   = _ANSI.get(theme_col, "\033[96m")
    reset = "\033[0m"
    bold  = "\033[1m"
    dim   = "\033[2m"
    green = "\033[92m"
    white = "\033[97m"

    title_lines = [
        r"  ███████╗██╗██╗  ██╗██████╗  ██████╗ ████████╗",
        r"  ██╔════╝██║╚██╗██╔╝██╔══██╗██╔═══██╗╚══██╔══╝",
        r"  █████╗  ██║ ╚███╔╝ ██████╔╝██║   ██║   ██║   ",
        r"  ██╔══╝  ██║ ██╔██╗ ██╔══██╗██║   ██║   ██║   ",
        r"  ██║     ██║██╔╝ ██╗██████╔╝╚██████╔╝   ██║   ",
        r"  ╚═╝     ╚═╝╚═╝  ╚═╝╚═════╝  ╚═════╝    ╚═╝   ",
    ]

    sys.stdout.write("\n")
    for line in title_lines:
        sys.stdout.write(f"{bold}{col}{line}{reset}\n")
        sys.stdout.flush()
        _time.sleep(0.045)

    sys.stdout.write(f"\n  {col}A R C A D E   ·   T I C K E T   R U S H{reset}\n\n")
    sys.stdout.flush()
    _time.sleep(0.3)

    _BAR_W = 28
    _STEPS = [
        ("Loading assets",         0.45),
        ("Spawning tickets",       0.50),
        ("Booting game engine",    0.55),
        ("Configuring obstacles",  0.35),
        ("Priming double-jump",    0.30),
    ]

    for label, dur in _STEPS:
        for i in range(_BAR_W + 1):
            filled = "█" * i
            empty  = "░" * (_BAR_W - i)
            pct    = int(100 * i / _BAR_W)
            sys.stdout.write(
                f"\r  {dim}{label:<26}{reset}  "
                f"{col}[{filled}{empty}]{reset}  {white}{pct:3d}%{reset}"
            )
            sys.stdout.flush()
            _time.sleep(dur / _BAR_W)

        sys.stdout.write(
            f"\r  {dim}{label:<26}{reset}  "
            f"{green}[{'█' * _BAR_W}]{reset}  {green}[OK]{reset}\n"
        )
        sys.stdout.flush()

    sys.stdout.write(
        f"\n  {bold}{col}▶  LAUNCHING  —  "
        f"SPACE=Jump   P=Pause   Q=Quit   R=Restart{reset}\n\n"
    )
    sys.stdout.flush()
    _time.sleep(0.7)

    try:
        import curses as _curses
    except ImportError:
        console.print("  [dim]windows-curses not found — installing...[/dim]")
        from display.animations import WgetBar
        bar = WgetBar(label="windows-curses", color=theme_col)
        rc, out = bar.run(["pip", "install", "windows-curses", "--quiet"])
        if rc != 0:
            print_err("Failed to install windows-curses. Run manually: pip install windows-curses")
            return
        try:
            import curses as _curses
        except ImportError:
            print_err("Still could not import curses after install. Restart the terminal and try again.")
            return

    try:
        from games.ticket_rush import run_game
        _curses.wrapper(run_game)
    except Exception as exc:
        print_err(f"Game error: {exc}")
        return

    console.print()
    print_ok("Back in Fixbot.")
    console.print()


def _launch_gitpilot() -> None:
    """GitPilot boot screen → launch GitPilot AI Git assistant."""
    import time as _time

    theme_col = get_theme_color()
    _ANSI = {
        "yellow": "\033[93m", "magenta": "\033[95m", "cyan": "\033[96m",
    }
    col   = _ANSI.get(theme_col, "\033[96m")
    reset = "\033[0m"
    bold  = "\033[1m"
    dim   = "\033[2m"
    green = "\033[92m"
    white = "\033[97m"

    title_lines = [
        r"  ██████╗ ██╗████████╗██████╗ ██╗██╗      ██████╗ ████████╗",
        r" ██╔════╝ ██║╚══██╔══╝██╔══██╗██║██║     ██╔═══██╗╚══██╔══╝",
        r" ██║  ███╗██║   ██║   ██████╔╝██║██║     ██║   ██║   ██║   ",
        r" ██║   ██║██║   ██║   ██╔═══╝ ██║██║     ██║   ██║   ██║   ",
        r" ╚██████╔╝██║   ██║   ██║     ██║███████╗╚██████╔╝   ██║   ",
        r"  ╚═════╝ ╚═╝   ╚═╝   ╚═╝     ╚═╝╚══════╝ ╚═════╝    ╚═╝  ",
    ]

    sys.stdout.write("\n")
    for line in title_lines:
        sys.stdout.write(f"{bold}{col}{line}{reset}\n")
        sys.stdout.flush()
        _time.sleep(0.045)

    sys.stdout.write(
        f"\n  {col}G I T P I L O T   ·   A I - P o w e r e d   G i t   A s s i s t a n t{reset}\n\n"
    )
    sys.stdout.flush()
    _time.sleep(0.3)

    _BAR_W = 28
    _STEPS = [
        ("Initializing GitPilot",     0.40),
        ("Loading AI engine",         0.50),
        ("Connecting to Gemini",      0.45),
        ("Scanning git environment",  0.35),
        ("Ready to launch",           0.30),
    ]

    for label, dur in _STEPS:
        for i in range(_BAR_W + 1):
            filled = "█" * i
            empty  = "░" * (_BAR_W - i)
            pct    = int(100 * i / _BAR_W)
            sys.stdout.write(
                f"\r  {dim}{label:<26}{reset}  "
                f"{col}[{filled}{empty}]{reset}  {white}{pct:3d}%{reset}"
            )
            sys.stdout.flush()
            _time.sleep(dur / _BAR_W)

        sys.stdout.write(
            f"\r  {dim}{label:<26}{reset}  "
            f"{green}[{'█' * _BAR_W}]{reset}  {green}[OK]{reset}\n"
        )
        sys.stdout.flush()

    sys.stdout.write(
        f"\n  {bold}{col}▶  LAUNCHING GITPILOT  —  AI-Powered Git Assistant{reset}\n\n"
    )
    sys.stdout.flush()
    _time.sleep(0.7)

    try:
        import questionary  # noqa: F401 — verify dep is available
    except ImportError:
        console.print("  [dim]questionary not found — installing...[/dim]")
        from display.animations import WgetBar
        bar = WgetBar(label="questionary", color=theme_col)
        rc, out = bar.run(["pip", "install", "questionary", "--quiet"])
        if rc != 0:
            print_err("Failed to install questionary. Run manually: pip install questionary")
            return

    try:
        from gitpilot.main import main as gitpilot_main
        gitpilot_main()
    except Exception as exc:
        print_err(f"GitPilot error: {exc}")
        return

    console.print()
    print_ok("Back in Fixbot.")
    console.print()


# ── Agent LLM singleton ───────────────────────────────────────────────────
# One ChatGoogleGenerativeAI instance per session, shared across all domain
# subgraph calls.  Creating a new one per call (the old behaviour) wastes
# auth-token overhead and makes latency non-deterministic.

_agent_llm = None

def _get_agent_llm(api_key: str, model: str):
    """Lazy ChatGoogleGenerativeAI. Returns None on import/init failure."""
    global _agent_llm
    if _agent_llm is not None:
        return _agent_llm
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from config import STRUCTURED_TEMPERATURE
        _agent_llm = ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=STRUCTURED_TEMPERATURE,
            convert_system_message_to_human=True,
            max_retries=2,
        )
        return _agent_llm
    except Exception as exc:
        print_warn(f"Agent LLM unavailable ({exc}) — continuing without it.")
        return None



# ── Groq intent disambiguator ─────────────────────────────────────────────
# Called when IntentEngine returns GENERAL and no local command pattern
# matched.  Asks Groq (fast, cheap) whether the query maps to a known domain
# so we can route to the supervisor graph instead of falling through to the
# full Gemini chat path unnecessarily.

def _groq_disambiguate_intent(user_input: str) -> str | None:
    """Return a domain string (NETWORK/STORAGE/DEV_ENV/SYSTEM/UPDATE) or None."""
    from core.groq_client import groq_client
    from agents.models import DomainGuess

    if not groq_client.available:
        return None

    prompt = (
        f'The user typed: "{user_input}"\n\n'
        f'Does this relate to one of these Windows support domains?\n'
        f'  NETWORK  — internet, Wi-Fi, DNS, ping, connection speed\n'
        f'  STORAGE  — disk space, temp files, cache, duplicates, drives\n'
        f'  DEV_ENV  — Python, pip, npm, node, venv, PATH, build errors\n'
        f'  SYSTEM   — CPU, RAM, crashes, BSOD, overheating, processes\n'
        f'  UPDATE   — winget, pip packages, npm global updates, check for updates, software updates\n'
        f'  NONE     — off-topic, greeting, general chat\n\n'
        f'Respond ONLY with valid JSON: {{"domain": "NETWORK", "reason": "brief reason"}}\n'
        f'Use NONE if unsure.'
    )
    data = groq_client.ask_json(prompt)
    if data is None:
        return None
    try:
        guess = DomainGuess(**data)
        return guess.domain if guess.domain != "NONE" else None
    except Exception:
        return None


def _local_command_guess(user_input: str) -> tuple[str | None, str]:
    """
    Offline fallback: derive a simple Windows command from the user's query
    without calling Gemini. Handles the most common patterns (version checks, etc.).
    """
    _SKIP = {"of", "the", "my", "a", "check", "what", "show", "get", "for", "is", "are"}
    words = [w.strip("?.,!") for w in user_input.lower().split()]

    _PATH_TOOLS = {"git", "python", "node", "npm", "pip", "java", "dotnet", "pip3", "python3"}

    if "version" in words:
        vi = words.index("version")
        candidates: list[str] = []
        if vi > 0 and words[vi - 1] not in _SKIP:
            candidates.append(words[vi - 1])
        if vi + 1 < len(words) and words[vi + 1] not in _SKIP:
            candidates.append(words[vi + 1])
        for app in candidates:
            if len(app) >= 2:
                if app in _PATH_TOOLS:
                    return f"{app} --version", f"Shows {app} version"
                return f'winget list --name "{app}"', f"Lists installed version of {app}"

    if "installed" in words:
        ii = words.index("installed")
        for offset in (-1, 1):
            idx = ii + offset
            if 0 <= idx < len(words) and words[idx] not in _SKIP:
                app = words[idx]
                return f'winget list --name "{app}"', f"Checks if {app} is installed"

    return None, ""


def _do_run_command(
    user_input: str,
    cmd: str,
    reason: str,
    mem: "ConversationMemory",
    executor: "SysDocExecutor",
) -> None:
    """Confirm with user, run a Gemini-suggested command, show output + interpretation."""
    import subprocess
    from prompt_toolkit import prompt as tk_prompt
    from prompt_toolkit.styles import Style as TkStyle

    theme_col = get_theme_color()
    hex_col   = get_theme_hex()

    console.print()
    console.print(f"  [dim]Gemini suggests running:[/dim]")
    console.print(f"  [bold white]❯ {cmd}[/bold white]")
    if reason:
        console.print(f"  [dim]{reason}[/dim]")
    console.print()

    try:
        confirm = tk_prompt(
            "  ❯ Run this command? [y/n]: ",
            style=TkStyle.from_dict({"prompt": f"{hex_col} bold"}),
        ).strip().lower()
    except (KeyboardInterrupt, EOFError):
        print_info("Cancelled.")
        return

    if confirm != "y":
        print_info("Skipped.")
        return

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        output = (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        print_err("Command timed out after 60 seconds.")
        return
    except Exception as exc:
        print_err(f"Failed to run command: {exc}")
        return

    # Strip winget's progress spinner frames and collapse blank runs
    def _clean(raw: str) -> str:
        _SPINNER = {"-", "\\", "|", "/", "—"}
        cleaned: list[str] = []
        prev_blank = False
        for ln in raw.splitlines():
            s = ln.strip()
            if s in _SPINNER:
                continue
            is_blank = not s
            if is_blank and prev_blank:
                continue
            cleaned.append(ln)
            prev_blank = is_blank
        return "\n".join(cleaned).strip()

    output = _clean(output)

    console.print()
    if output:
        console.print(f"  [dim]── output ─────────────────────────────────[/dim]")
        for line in output.splitlines():
            console.print(f"  [white]{line}[/white]", highlight=False)
        console.print(f"  [dim]──────────────────────────────────────────[/dim]")
    else:
        console.print(f"  [dim](no output)[/dim]")

    # When the binary isn't found, run a winget check so Gemini knows whether
    # the app is installed-but-not-in-PATH vs truly not installed.
    extra_context = ""
    _not_found = "not recognized" in output.lower() or "command not found" in output.lower()
    if result.returncode != 0 and _not_found:
        import shutil as _shutil
        app_bin = cmd.split()[0]
        if _shutil.which("winget"):
            try:
                wg = subprocess.run(
                    f'winget list --name "{app_bin}"',
                    shell=True, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=15,
                )
                wg_out = (wg.stdout + wg.stderr).strip()
                if wg_out:
                    extra_context = f"\n\nWinget installed packages check for '{app_bin}':\n{wg_out}"
            except Exception:
                pass

    console.print()
    print_bot_start()
    full_reply = typewriter_stream(
        (getattr(chunk, "text", str(chunk))
         for chunk in executor.gemini.interpret_output(user_input, cmd, output + extra_context)),
        color=theme_col,
    )

    mem.add("user", user_input)
    mem.add("model", full_reply)
    console.print()


def _do_update_scan(mem: "ConversationMemory", executor=None, report_gen=None, ticket_manager=None) -> None:
    from modules.updater import UpdateScanner
    from display.animations import MultiSelectMenu, WgetBar

    theme_col = get_theme_color()
    console.print()
    console.print(f"  [bold {theme_col}]◉[/bold {theme_col}] [dim]Scanning for available updates...[/dim]")

    scanner = UpdateScanner()
    with console.status("  [dim]checking winget · pip · npm[/dim]", spinner="dots"):
        updates = scanner.scan_all()

    if not updates:
        print_ok("All packages are up to date.")
        console.print()
        mem.add("user", "check for updates")
        mem.add("model", "All packages are up to date.")
        return

    console.print(
        f"  [bold {theme_col}]{len(updates)} update(s) available[/bold {theme_col}] "
        f"[dim]— use Space to select, A for all, Enter to update[/dim]"
    )
    console.print()

    menu = MultiSelectMenu(updates, color=theme_col)
    selected = menu.run()

    if not selected:
        print_info("No updates selected.")
        console.print()
        return

    # If executor is provided, run the updates via the LangGraph multi-agent pipeline
    # so that retries and strategy escalations (reinstall, force, etc.) work automatically.
    if executor and report_gen and ticket_manager:
        pkg_names = ", ".join(p["name"] for p in selected)
        console.print(f"  [dim]Running multi-agent update pipeline for: {pkg_names}...[/dim]")
        query = f"update {pkg_names}"
        _run_update_graph(
            user_input=query,
            executor=executor,
            memory=mem,
            report_gen=report_gen,
            ticket_manager=ticket_manager,
            target_packages=selected,
        )
        return

    console.print()
    console.print(f"  [dim]Updating {len(selected)} package(s)...[/dim]")
    console.print()

    success, failed = 0, 0
    for item in selected:
        cmd = scanner.get_update_cmd(item)
        if not cmd:
            continue
        console.print(f"  [dim]→ {item['name']}  {item['from']} → {item['to']}[/dim]")
        bar = WgetBar(label=item["name"], color=theme_col)
        returncode, output = bar.run(cmd)
        if returncode == 0:
            success += 1
        else:
            failed += 1
            if output.strip():
                for line in output.splitlines():
                    if line.strip():
                        console.print(f"  [dim]{line}[/dim]", highlight=False)
        console.print()

    summary = f"Updated {success} package(s)."
    if failed:
        summary += f" {failed} failed — see output above."
        print_warn(summary)
    else:
        print_ok(summary)

    mem.add("user", "check for updates")
    mem.add("model", summary)
    console.print()


def format_ticket_detail(ticket: dict) -> str:
    lines = []
    for key, value in ticket.items():
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


_INTENT_PRIORITY_KEYS = {
    "NETWORK":  ["wifi_ssid", "internet", "download_mbps", "upload_mbps", "dns_status", "ping_ms", "packet_loss_pct", "gateway_ip", "outage_prediction"],
    "STORAGE":  ["drives", "critical_drives", "temp_folder_gb", "recycle_bin_gb", "top_large_files"],
    "DEV_ENV":  ["active_python", "pip_status", "dependency_conflicts", "node_version", "venv_found"],
    "SYSTEM":   ["cpu_percent", "ram_used_pct", "cpu_temp_c", "recent_crashes", "fan_speed_rpm"],
}

_DEFAULT_PRIORITY_KEYS = [
    "wifi_ssid", "cpu_percent", "ram_used_pct", "cpu_temp_c",
    "dns_status", "internet", "outage_prediction", "gateway_ip",
    "packet_loss_pct", "temp_folder_gb", "recycle_bin_gb",
]


def _top_os_data_keys(os_data: dict, intent: str = "") -> list:
    priority_keys = _INTENT_PRIORITY_KEYS.get(intent, _DEFAULT_PRIORITY_KEYS)
    keys = [key for key in priority_keys if key in os_data]
    keys.extend(k for k in os_data.keys() if k not in keys)
    return keys[:5]


def _run_supervisor_domain_graph(intent: str, user_input: str, executor, memory, report_gen, ticket_manager) -> bool:
    import uuid
    from agents.graph import build_domain_subgraph
    from agents.tracing import build_run_metadata, apply_run_metadata
    from agents.tools_network import make_network_tools
    from agents.tools_storage import make_storage_tools
    from agents.tools_dev_env import make_dev_env_tools
    from agents.tools_system import make_system_tools
    from langgraph.types import Command
    # LLM singleton: created once per session and reused across domains.
    # Declared at module level below main() to avoid re-instantiation on every call.
    from config import MODEL

    llm = None
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if api_key:
        try:
            llm = _get_agent_llm(api_key, MODEL)
        except Exception:
            llm = None

    if not api_key and intent != "NETWORK":
        return False

    domain_module_map = {
        "NETWORK": (executor.network, make_network_tools(executor.network)),
        "STORAGE": (executor.storage, make_storage_tools(executor.storage)),
        "DEV_ENV": (executor.dev_env, make_dev_env_tools(executor.dev_env)),
        "SYSTEM": (executor.system_health, make_system_tools(executor.system_health)),
    }

    if intent not in domain_module_map:
        return False

    try:
        module, read_tools = domain_module_map[intent]

        # Generate a unique thread_id per execution so that consecutive commands
        # do not pollute or resume a dirty state from previous sessions.
        thread_id = f"thread_{intent.lower()}_{uuid.uuid4().hex[:8]}"

        db_path = os.path.join(ROOT_DIR, "memory", "fixbot_state.db")
        subgraph = build_domain_subgraph(intent, module, read_tools, llm, executor, checkpoint_db_path=db_path)

        run_id = str(uuid.uuid4())
        config = {
            "configurable": {"thread_id": thread_id},
            "tags": [f"domain:{intent}"],
            "run_id": run_id,
        }

        initial_input = {"messages": [("user", user_input)], "domain": intent}

        def _handle_event(evt) -> None:
            if "__interrupt__" in evt:
                return
            for node_name, node_output in evt.items():
                if node_name == "collect_telemetry":
                    print_agent_supervisor("Analyzing subsystem telemetry...")
                elif node_name == "planner":
                    plan = node_output.get("repair_plan")
                    if plan:
                        print_agent_planner(
                            f"Goal:        {plan.get('goal')}\n"
                            f"Root Cause:  {plan.get('root_cause')}\n"
                            f"Confidence:  {plan.get('confidence'):.0%}"
                        )
                elif node_name == "plan_executor":
                    print_agent_executor("Executing recommended repair actions...")
                elif node_name == "verifier":
                    verification = node_output.get("verification")
                    if verification:
                        status_str = "SUCCESS" if verification.get("success") else "FAILED"
                        print_agent_verifier(
                            f"Outcome:     {status_str}\n"
                            f"Summary:     {verification.get('verification_summary')}"
                        )
                elif node_name == "supervisor_decide":
                    decision = node_output.get("supervisor_decision")
                    if decision:
                        action = decision.get("action")
                        reason = decision.get("reason")
                        if action == "finalize_success":
                            print_agent_summary(reason)
                        elif action == "retry_new_cycle":
                            print_agent_supervisor(f"Repair cycle incomplete. Retrying: {reason}")
                        elif action == "escalate":
                            print_agent_supervisor(f"Unable to auto-resolve. Escalating: {reason}")

        state = subgraph.get_state(config)
        next_input = initial_input if not state.values else None

        while True:
            events = subgraph.stream(next_input, config, stream_mode="updates")
            has_interrupt = False
            for event in events:
                _handle_event(event)
                if "__interrupt__" in event:
                    has_interrupt = True
                    interrupt_item = event["__interrupt__"][0]
                    payload = interrupt_item.value
                    choice = PermissionGate.ask_permission(payload["domain"], repair_plan=payload["repair_plan"])
                    next_input = Command(resume=choice)
                    break
            
            if not has_interrupt:
                break

        final_state = subgraph.get_state(config).values
        if not final_state:
            return False

        plan = final_state.get("repair_plan") or {}
        last_fix_result = final_state.get("last_fix_result") or "No fix applied"
        verification = final_state.get("verification") or {}
        telemetry = final_state.get("telemetry") or {}
        decision = final_state.get("supervisor_decision") or {}

        ai_reply = f"Goal: {plan.get('goal', 'N/A')}\nRoot Cause: {plan.get('root_cause', 'N/A')}\nReasoning: {plan.get('reasoning', 'N/A')}"

        if decision.get("action") == "escalate" or last_fix_result == "ticket_opened":
            ticket = ticket_manager.create_ticket(
                problem=user_input,
                os_data=telemetry,
                gemini_reply=ai_reply,
                module=intent,
            )
            print_ticket(ticket)
        else:
            report = report_gen.generate(
                intent=intent,
                problem=user_input,
                os_data=telemetry,
                ai_reply=ai_reply,
                fix_applied=last_fix_result,
                verification_passed=verification.get("success"),
                changes=verification.get("summary") or {},
            )
            saved = report_gen.save(report)
            report_gen.display_summary(report, saved_path=saved)

        memory.add("user", user_input)
        memory.add("model", ai_reply)

        metadata = build_run_metadata(intent, final_state)
        apply_run_metadata(run_id, metadata)
        return True
    except Exception as e:
        print_warn(f"Supervisor graph execution notice: {e}. Falling back to standard pipeline.")
        return False


def _run_update_graph(user_input: str, executor, memory, report_gen, ticket_manager, target_packages: list[dict] = None) -> bool:
    """Run the UPDATE multi-agent LangGraph pipeline.

    Returns True if the graph ran successfully, False to fall back to the
    existing _do_update_scan() interactive flow.
    """
    import uuid
    from agents.update_graph import build_update_subgraph
    from agents.tools_update import make_update_tools
    from agents.tracing import build_run_metadata, apply_run_metadata
    from modules.updater import UpdateScanner
    from langgraph.types import Command
    from config import MODEL

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return False

    try:
        llm = _get_agent_llm(api_key, MODEL)
        updater = UpdateScanner()
        read_tools = make_update_tools(updater)

        # Generate a unique thread_id per execution so that consecutive update runs
        # do not pollute or resume a dirty state from previous sessions.
        thread_id = f"thread_update_{uuid.uuid4().hex[:8]}"

        db_path = os.path.join(ROOT_DIR, "memory", "fixbot_state.db")
        subgraph = build_update_subgraph(
            updater, read_tools, llm, checkpoint_db_path=db_path,
        )

        run_id = str(uuid.uuid4())
        config = {
            "configurable": {"thread_id": thread_id},
            "tags": ["domain:UPDATE"],
            "run_id": run_id,
        }

        initial_input = {"messages": [("user", user_input)], "domain": "UPDATE"}
        if target_packages:
            initial_input["target_packages"] = target_packages

        no_packages_found = False

        def _handle_event(evt) -> None:
            nonlocal no_packages_found
            if "__interrupt__" in evt:
                return
            for node_name, node_output in evt.items():
                if node_name == "scan_updates":
                    count = (node_output.get("telemetry") or {}).get("available_updates_count", 0)
                    print_agent_supervisor(f"Found {count} available update(s).")
                elif node_name == "update_planner":
                    plan = node_output.get("update_plan")
                    if plan:
                        pkgs = plan.get("packages", [])
                        if not pkgs:
                            no_packages_found = True
                            reason = plan.get("reasoning", "No updates found.")
                            print_agent_planner(f"Goal: {plan.get('goal')}\nResult: {reason}")
                            return
                        print_agent_planner(
                            f"Goal:     {plan.get('goal')}\n"
                            f"Packages: {len(pkgs)} package(s)\n"
                            f"Strategy: {plan.get('strategy')}"
                        )
                elif node_name == "update_executor":
                    results = node_output.get("update_results", [])
                    for r in results:
                        status = "SUCCESS" if r.get("success") else "FAILED"
                        strat = r.get("strategy_used", "none")
                        print_agent_executor(f"{r.get('name')}: {status} (via {strat})")
                elif node_name == "update_verifier":
                    verification = node_output.get("verification")
                    if verification:
                        status_str = "SUCCESS" if verification.get("success") else "FAILED"
                        print_agent_verifier(
                            f"Outcome: {status_str}\n"
                            f"Summary: {verification.get('verification_summary')}"
                        )
                elif node_name == "supervisor_decide":
                    decision = node_output.get("supervisor_decision")
                    if decision:
                        action = decision.get("action")
                        reason = decision.get("reason")
                        if action == "finalize_success":
                            print_agent_summary(reason)
                        elif action == "retry_new_cycle":
                            print_agent_supervisor(f"Update incomplete. Retrying: {reason}")
                        elif action == "escalate":
                            print_agent_supervisor(f"Unable to complete update. {reason}")

        state = subgraph.get_state(config)
        next_input = initial_input if not state.values else None

        while True:
            if no_packages_found:
                break
            events = subgraph.stream(next_input, config, stream_mode="updates")
            has_interrupt = False
            try:
                for event in events:
                    _handle_event(event)
                    if no_packages_found:
                        break
                    if "__interrupt__" in event:
                        has_interrupt = True
                        interrupt_item = event["__interrupt__"][0]
                        payload = interrupt_item.value
                        choice = PermissionGate.ask_permission("UPDATE", repair_plan=payload.get("repair_plan"))
                        next_input = Command(resume=choice)
                        break
            finally:
                events.close()
            
            if not has_interrupt:
                break

        if no_packages_found:
            return True

        final_state = subgraph.get_state(config).values
        if not final_state:
            return False

        plan = final_state.get("update_plan") or {}
        update_results = final_state.get("update_results") or []
        verification = final_state.get("verification") or {}

        ai_reply = f"Goal: {plan.get('goal', 'N/A')}\nStrategy: {plan.get('strategy', 'N/A')}\nReasoning: {plan.get('reasoning', 'N/A')}"

        report = report_gen.generate(
            intent="UPDATE",
            problem=user_input,
            os_data={"update_results": update_results},
            ai_reply=ai_reply,
            fix_applied=final_state.get("last_fix_result", "No update applied"),
            verification_passed=verification.get("success"),
            changes=verification.get("summary") or {},
        )
        saved = report_gen.save(report)
        report_gen.display_summary(report, saved_path=saved)

        memory.add("user", user_input)
        memory.add("model", ai_reply)
        return True

    except Exception as e:
        print_warn(f"Update graph notice: {e}. Falling back to standard update scan.")
        return False


def _run_install_graph(app_name: str, executor, memory, report_gen, ticket_manager) -> bool:
    """Run the INSTALL multi-agent Action Graph pipeline.

    Resolves the human app name to the exact package ID via the Planner's
    search_package tool, then installs autonomously with escalating retries.
    Returns True if the graph ran. Falls back to InstallerModule on False.
    """
    import uuid
    from agents.install_graph import build_install_subgraph
    from agents.tools_update import make_update_tools
    from modules.updater import UpdateScanner
    from langgraph.types import Command
    from config import MODEL

    # INSTALL works without LangChain Gemini (discovery = winget only)
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    try:
        llm = None
        # Optional: try LLM, but never required for install
        if api_key:
            try:
                llm = _get_agent_llm(api_key, MODEL)
            except Exception:
                llm = None

        updater   = UpdateScanner()
        tools     = make_update_tools(updater)
        thread_id = f"thread_install_{uuid.uuid4().hex[:8]}"
        db_path   = os.path.join(ROOT_DIR, "memory", "fixbot_state.db")
        subgraph  = build_install_subgraph(
            updater, tools, llm, checkpoint_db_path=db_path
        )

        config = {
            "configurable": {"thread_id": thread_id},
            "tags": ["domain:INSTALL"],
        }
        initial_input = {
            "messages":      [("user", f"install {app_name}")],
            "domain":        "INSTALL",
            "planning_cycle": 1,
        }

        no_packages_found = False

        def _handle_event(evt: dict) -> None:
            nonlocal no_packages_found
            if "__interrupt__" in evt:
                return
            for node_name, node_output in evt.items():
                if node_name == "planner":
                    plan = node_output.get("action_plan") or {}
                    pkg_id = plan.get("target_id") or plan.get("target_name", "?")
                    if not plan.get("target_id"):
                        no_packages_found = True
                        reason = plan.get("reasoning", "Package not found.")
                        print_agent_planner(f"Goal: {plan.get('goal')}\nResult: {reason}")
                        return
                    print_agent_planner(
                        f"Goal:     {plan.get('goal', f'Install {app_name}')}\n"
                        f"Package:  {pkg_id}\n"
                        f"Strategy: {plan.get('strategy', 'install')}"
                    )
                elif node_name == "action_executor":
                    for r in (node_output.get("execution_results") or
                               node_output.get("update_results") or []):
                        status = "SUCCESS" if r.get("success") else "FAILED"
                        print_agent_executor(
                            f"{r.get('name')}: {status} (via {r.get('strategy_used')})"
                        )
                elif node_name == "error_analyzer":
                    analysis = node_output.get("error_analysis")
                    if analysis:
                        print_agent_verifier(
                            f"🔬 [{analysis.get('category')}] "
                            f"{analysis.get('summary')} "
                            f"→ {analysis.get('recommended_strategy')}"
                        )
                elif node_name == "action_verifier":
                    v = node_output.get("verification") or {}
                    status_str = "SUCCESS" if v.get("success") else "FAILED"
                    print_agent_verifier(
                        f"Outcome: {status_str}\n"
                        f"Summary: {v.get('verification_summary', '')}"
                    )
                elif node_name == "action_supervisor":
                    d = node_output.get("supervisor_decision") or {}
                    action = d.get("action", "")
                    reason = d.get("reason", "")
                    if action == "finalize_success":
                        print_agent_summary(reason)
                    elif action == "retry_new_cycle":
                        print_agent_supervisor(f"Install incomplete. Retrying: {reason}")
                    elif action == "escalate":
                        print_agent_supervisor(f"Unable to complete install. {reason}")

        next_input = initial_input
        while True:
            if no_packages_found:
                break
            events = subgraph.stream(next_input, config, stream_mode="updates")
            has_interrupt = False
            try:
                for event in events:
                    _handle_event(event)
                    if no_packages_found:
                        break
                    if "__interrupt__" in event:
                        has_interrupt = True
                        payload = event["__interrupt__"][0].value
                        plan = payload.get("action_plan") or payload or {}
                        # Normalize
                        if isinstance(plan, dict) and "primary_fix" not in plan:
                            plan = {
                                **plan,
                                "domain": plan.get("domain") or "INSTALL",
                                "goal": plan.get("goal")
                                    or f"Install {plan.get('target_id') or app_name}",
                                "target_id": plan.get("target_id") or "",
                                "target_name": plan.get("target_name") or app_name,
                                "manager": plan.get("manager") or "winget",
                                "strategy": plan.get("strategy") or "install",
                            }

                        # Optional: already-installed menu
                        if (plan.get("strategy") or "install") == "install" and plan.get("target_id"):
                            try:
                                already, ver = updater.is_installed({
                                    "id": plan.get("target_id"),
                                    "name": plan.get("target_name") or app_name,
                                    "manager": plan.get("manager") or "winget",
                                })
                            except Exception:
                                already, ver = False, ""

                            if already:
                                from prompt_toolkit import prompt as tk_prompt
                                console.print()
                                console.print(
                                    f"  [bold green]✓ Already installed[/bold green]  "
                                    f"[white]{plan.get('target_name') or app_name}[/white]  "
                                    f"[dim]v{ver or '?'}[/dim]"
                                )
                                console.print("  [dim]1[/dim] Leave as-is (no download)")
                                console.print("  [dim]2[/dim] Update / repair (force install)")
                                console.print("  [dim]3[/dim] Cancel")
                                try:
                                    pick = tk_prompt("  ❯ ").strip()
                                except (KeyboardInterrupt, EOFError):
                                    pick = "3"

                                if pick == "1":
                                    print_ok(
                                        f"{plan.get('target_name') or app_name} "
                                        f"already installed — no download."
                                    )
                                    next_input = Command(resume="n")
                                    break
                                if pick == "2":
                                    plan["strategy"] = "force_install"
                                    # fall through to permission gate with force_install
                                else:
                                    print_info("Install cancelled.")
                                    next_input = Command(resume="n")
                                    break

                        choice = PermissionGate.ask_permission(
                            "INSTALL",
                            repair_plan=plan,
                        )
                        next_input = Command(resume=choice, update={"action_plan": plan})
                        break
            finally:
                events.close()
            if not has_interrupt:
                break

        if no_packages_found:
            return True

        final_state = subgraph.get_state(config).values
        if not final_state:
            return False

        plan       = final_state.get("action_plan") or {}
        results    = final_state.get("execution_results") or final_state.get("update_results") or []
        verification = final_state.get("verification") or {}

        ai_reply = (
            f"Goal: {plan.get('goal', f'Install {app_name}')}\n"
            f"Strategy: {plan.get('strategy', 'install')}\n"
            f"Package: {plan.get('target_id', app_name)}"
        )
        report = report_gen.generate(
            intent="INSTALL",
            problem=f"install {app_name}",
            os_data={"install_results": results},
            ai_reply=ai_reply,
            fix_applied=final_state.get("last_fix_result", "No install applied"),
            verification_passed=verification.get("success"),
            changes=verification.get("summary") or {},
        )
        saved = report_gen.save(report)
        report_gen.display_summary(report, saved_path=saved)
        memory.add("user", f"install {app_name}")
        memory.add("model", ai_reply)
        return True

    except Exception as e:
        import traceback
        print_warn(f"Install graph notice: {e}. Falling back to direct install.")
        print_warn(traceback.format_exc().splitlines()[-1][:200])
        return False


def _run_uninstall_graph(app_name: str, executor, memory, report_gen, ticket_manager) -> bool:
    """Run the UNINSTALL multi-agent Action Graph pipeline.

    Uses the high-risk permission gate: shows a per-package preview and
    requires explicit y/n for each package before anything is removed.
    Returns True if the graph ran, False to fall back to a direct winget call.
    """
    import uuid
    from agents.uninstall_graph import build_uninstall_subgraph
    from agents.tools_update import make_update_tools
    from modules.updater import UpdateScanner
    from langgraph.types import Command
    from config import MODEL

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return False

    try:
        llm       = _get_agent_llm(api_key, MODEL)
        updater   = UpdateScanner()
        tools     = make_update_tools(updater)
        thread_id = f"thread_uninstall_{uuid.uuid4().hex[:8]}"
        db_path   = os.path.join(ROOT_DIR, "memory", "fixbot_state.db")
        subgraph  = build_uninstall_subgraph(updater, tools, llm, checkpoint_db_path=db_path)

        config = {
            "configurable": {"thread_id": thread_id},
            "tags": ["domain:UNINSTALL"],
        }
        initial_input = {
            "messages":       [("user", f"uninstall {app_name}")],
            "domain":         "UNINSTALL",
            "planning_cycle": 1,
        }

        no_packages_found = False

        def _handle_event(evt: dict) -> None:
            nonlocal no_packages_found
            if "__interrupt__" in evt:
                return
            for node_name, node_output in evt.items():
                if node_name == "planner":
                    plan = node_output.get("action_plan") or {}
                    pkgs = plan.get("packages") or []
                    if not pkgs:
                        no_packages_found = True
                        reason = plan.get("reasoning", "No package found to uninstall.")
                        print_agent_planner(f"Goal: {plan.get('goal')}\nResult: {reason}")
                        return
                    names = ", ".join(p.get("name", "?") for p in pkgs) or "none found"
                    print_agent_planner(
                        f"Goal:     {plan.get('goal', f'Uninstall {app_name}')}\n"
                        f"Packages: {names}\n"
                        f"Strategy: {plan.get('strategy', 'uninstall')}"
                    )
                elif node_name == "action_executor":
                    for r in (node_output.get("execution_results") or
                               node_output.get("update_results") or []):
                        status = "SUCCESS" if r.get("success") else "FAILED"
                        print_agent_executor(
                            f"{r.get('name')}: {status} (via {r.get('strategy_used')})"
                        )
                elif node_name == "error_analyzer":
                    analysis = node_output.get("error_analysis")
                    if analysis:
                        print_agent_verifier(
                            f"🔬 [{analysis.get('category')}] "
                            f"{analysis.get('summary')} "
                            f"→ {analysis.get('recommended_strategy')}"
                        )
                elif node_name == "action_verifier":
                    v = node_output.get("verification") or {}
                    status_str = "SUCCESS" if v.get("success") else "FAILED"
                    print_agent_verifier(
                        f"Outcome: {status_str}\n"
                        f"Summary: {v.get('verification_summary', '')}"
                    )
                elif node_name == "action_supervisor":
                    d = node_output.get("supervisor_decision") or {}
                    action = d.get("action", "")
                    reason = d.get("reason", "")
                    if action == "finalize_success":
                        print_agent_summary(reason)
                    elif action == "retry_new_cycle":
                        print_agent_supervisor(f"Uninstall incomplete. Retrying: {reason}")
                    elif action == "escalate":
                        print_agent_supervisor(f"Unable to complete uninstall. {reason}")

        next_input = initial_input
        while True:
            if no_packages_found:
                break
            events = subgraph.stream(next_input, config, stream_mode="updates")
            has_interrupt = False
            try:
                for event in events:
                    _handle_event(event)
                    if no_packages_found:
                        break
                    if "__interrupt__" in event:
                        has_interrupt = True
                        payload = event["__interrupt__"][0].value
                        gate_mode = payload.get("gate_mode", "standard")

                        if gate_mode == "high_risk":
                            # Per-package y/n prompt for UNINSTALL
                            packages  = payload.get("packages") or []
                            choices: dict[str, str] = {}
                            from display.banner import get_theme_color
                            from prompt_toolkit import prompt as tk_prompt
                            from prompt_toolkit.styles import Style as TkStyle
                            theme_hex = get_theme_color()
                            console.print()
                            console.print(f"  [bold red]⚠  UNINSTALL — confirm each package[/bold red]")
                            console.print(f"  [dim]{'─' * 52}[/dim]")
                            for pkg in packages:
                                name    = pkg.get("name", "?")
                                pkg_id  = pkg.get("id", "?")
                                version = pkg.get("installed_version", "?")
                                console.print(
                                    f"  [bold white]{name}[/bold white]  "
                                    f"[dim]{pkg_id}  v{version}[/dim]"
                                )
                                try:
                                    ans = tk_prompt(
                                        f"  Remove {name}? [y/n]: ",
                                        style=TkStyle.from_dict({"prompt": f"#{theme_hex} bold"}),
                                    ).strip().lower()
                                except (KeyboardInterrupt, EOFError):
                                    ans = "n"
                                choices[pkg_id] = "y" if ans == "y" else "n"
                            console.print(f"  [dim]{'─' * 52}[/dim]")
                            next_input = Command(resume=choices)
                        else:
                            choice = PermissionGate.ask_permission(
                                "UNINSTALL",
                                repair_plan=payload.get("action_plan"),
                            )
                            next_input = Command(resume=choice)
                        break
            finally:
                events.close()
            if not has_interrupt:
                break

        if no_packages_found:
            return True

        final_state = subgraph.get_state(config).values
        if not final_state:
            return False

        plan         = final_state.get("action_plan") or {}
        results      = final_state.get("execution_results") or final_state.get("update_results") or []
        verification = final_state.get("verification") or {}

        ai_reply = (
            f"Goal: {plan.get('goal', f'Uninstall {app_name}')}\n"
            f"Strategy: {plan.get('strategy', 'uninstall')}"
        )
        report = report_gen.generate(
            intent="UNINSTALL",
            problem=f"uninstall {app_name}",
            os_data={"uninstall_results": results},
            ai_reply=ai_reply,
            fix_applied=final_state.get("last_fix_result", "No uninstall applied"),
            verification_passed=verification.get("success"),
            changes=verification.get("summary") or {},
        )
        saved = report_gen.save(report)
        report_gen.display_summary(report, saved_path=saved)
        memory.add("user", f"uninstall {app_name}")
        memory.add("model", ai_reply)
        return True

    except Exception as e:
        print_warn(f"Uninstall graph notice: {e}. Falling back to direct uninstall.")
        return False


def _is_generic_update_query(text: str) -> bool:
    """True when the user wants a scan/list, not a targeted app update."""
    lowered = text.lower().strip().rstrip("?.!")
    phrases = {
        "check for updates", "check updates", "any updates",
        "available updates", "scan for updates", "list updates",
        "show updates", "pending updates", "what updates",
        "outdated", "updates", "any update in my pc", "updates on my pc",
        "any updates on my pc", "any update on my pc", "update my pc",
        "updates on my computer", "any updates in my pc",
    }
    if lowered in phrases:
        return True

    words = set(lowered.split())
    if not (words & {"update", "updates", "upgrade", "outdated", "pending"}):
        return False

    filler = {
        "update", "updates", "upgrade", "check", "for", "any", "my", "the", "on", "in",
        "pc", "system", "computer", "all", "apps", "packages", "available", "scan",
        "list", "show", "run", "apply", "pending", "what", "outdated", "are", "there",
        "have", "do", "i", "need", "get", "find", "see", "please", "can", "you",
        "a", "an", "is", "it", "to", "me", "some", "tell", "about", "machine",
    }
    return len(words - filler) == 0


def main() -> None:
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        console.print(
            "\n  [bold red]GEMINI_API_KEY is not set.[/bold red]"
            "\n  Add it to your environment or create a .env file with:"
            "\n  [dim]GEMINI_API_KEY=your_api_key_here[/dim]\n"
        )
        return

    if not PermissionGate.has_admin():
        console.print(
            "\n  [bold red]fixbot requires administrator privileges.[/bold red]"
            "\n  Right-click your terminal and choose 'Run as administrator', then try again.\n"
        )
        return

    executor = SysDocExecutor(dry_run=_DRY_RUN)
    prompt_builder = executor.prompt_builder
    ticket_manager = TicketManager()
    memory = ConversationMemory(path=_MEMORY_PATH)
    report_gen = ReportGenerator(reports_dir=_REPORTS_DIR)
    installer = InstallerModule(executor.gemini)

    print_banner()
    ask_theme()
    PermissionGate.ask_initial_permissions()
    time.sleep(1.0)
    print_welcome_panel()



    if _DRY_RUN:
        print_warn("DRY RUN mode — fixes will be previewed but not executed.")

    print_top_rule = True
    while True:
        try:
            hex_col = get_theme_hex()
            from rich.rule import Rule
            if print_top_rule:
                console.print(Rule(style="dim"))
            user_input = prompt(
                "  you ❯ ",
                style=Style.from_dict({"prompt": f"{hex_col} bold"}),
            ).strip()

            if user_input:
                linux_terminal_flash()

        except (KeyboardInterrupt, EOFError):
            console.print("\n  Goodbye.\n")
            break

        if not user_input:
            print_top_rule = False
            continue

        console.print(Rule(style="dim"))
        print_top_rule = True

        user_input_lower = user_input.lower().strip()
        user_query = user_input
        # Strip leading backslashes/slashes for general query paths if not a command
        if user_input_lower not in COMMANDS and not user_input_lower.startswith("ticket "):
            user_query = user_input.strip().lstrip('\\/').strip()
            user_input_lower = user_query.lower()

        action = None
        filter_arg = ""

        if user_input_lower in COMMANDS:
            action = COMMANDS[user_input_lower]
        elif user_input_lower.startswith("live tabs"):
            action = "tabs"
            filter_arg = user_input[9:].strip()
        else:
            parts = user_input.split(maxsplit=1)
            if parts:
                first_word = parts[0].lower()
                extra = parts[1].strip() if len(parts) == 2 else ""
                # Don't swallow "clear cache" / "clear temp" etc. as the clear-screen command
                if first_word in COMMANDS and not (first_word == "clear" and extra):
                    action = COMMANDS[first_word]
                    if extra:
                        filter_arg = extra

        if action is not None:
            if action == "exit":
                console.print("  Shutting down.\n")
                break
            if action == "clear":
                console.clear()
                print_banner()
                continue
            if action == "help":
                print_help()
                continue
            if action == "scan":
                all_data = {
                    "network": executor.network.collect(),
                    "storage": executor.storage.collect(),
                    "dev_env": executor.dev_env.collect(),
                    "system": executor.system_health.collect(),
                }
                print_system_scan(all_data)
                continue
            if action == "report":
                recent = report_gen.list_recent()
                if not recent:
                    print_info("No reports yet. Reports are saved automatically after each fix.")
                else:
                    print_info(f"Last {len(recent)} reports:")
                    for path in recent:
                        console.print(f"  [dim]{path}[/dim]")
                continue
            if action == "tickets":
                summaries = ticket_manager.list_tickets()
                if not summaries:
                    print_info("No tickets found.")
                    continue
                for summary in summaries:
                    print_ticket(summary)
                continue
            if action == "tabs":
                tabs = executor.system_health.list_browser_tabs(filter_name=filter_arg)
                print_browser_tab_table(tabs)
                continue
            if action == "game":
                _launch_game()
                continue
            if action == "gitpilot":
                _launch_gitpilot()
                continue

        if user_input.lower().startswith("ticket "):
            ticket_id = user_input.split(maxsplit=1)[1].strip()
            ticket = ticket_manager.get_ticket(ticket_id)
            if not ticket:
                print_warn(f"Ticket {ticket_id} not found.")
                continue
            print_ticket(ticket)
            console.print(format_ticket_detail(ticket))
            continue

        # ── Process list (interactive close all / some) ─────────────────
        _PROC_PHRASES = (
            "process running", "processes running", "running process",
            "running processes", "running apps", "what is running",
            "show processes", "list processes", "open processes",
            "active processes", "task list", "process list",
        )
        if (
            action == "processes"
            or user_input_lower in ("processes", "ps", "process")
            or user_input_lower in _PROC_PHRASES
            or any(p in user_input_lower for p in _PROC_PHRASES)
        ):
            # Optional filter: "chrome processes"
            filter_arg = ""
            for w in ("chrome", "discord", "code", "edge", "firefox"):
                if w in user_input_lower:
                    filter_arg = w
                    break

            procs = executor.system_health.list_processes(top=25, filter_name=filter_arg)
            if not procs:
                print_info("No processes to show.")
                continue
            print_process_table(procs)

            console.print("  [bold]Close processes?[/bold]")
            console.print("    [cyan]A[/cyan]  Close ALL listed (safe)")
            console.print("    [cyan]S[/cyan]  Select SOME  (1,3,5 or 2-6)")
            console.print("    [cyan]N[/cyan]  Close by name")
            console.print("    [dim]Enter[/dim] Leave running")
            try:
                choice = input("  ❯ Choice [A/S/N]: ").strip().lower()
            except Exception:
                choice = ""

            def _parse_sel(raw, n):
                raw = (raw or "").strip().lower()
                if raw in ("all", "a", "*"):
                    return list(range(n))
                chosen = set()
                for part in raw.replace(" ", "").split(","):
                    if not part:
                        continue
                    if "-" in part:
                        try:
                            a, b = part.split("-", 1)
                            for i in range(int(a), int(b) + 1):
                                if 1 <= i <= n:
                                    chosen.add(i - 1)
                        except ValueError:
                            pass
                    else:
                        try:
                            i = int(part)
                            if 1 <= i <= n:
                                chosen.add(i - 1)
                        except ValueError:
                            pass
                return sorted(chosen)

            if choice in ("a", "all"):
                critical = {
                    "system", "csrss.exe", "wininit.exe", "services.exe",
                    "lsass.exe", "smss.exe", "winlogon.exe", "explorer.exe",
                    "dwm.exe",
                }
                safe = [
                    p for p in procs
                    if not p.get("important")
                    and str(p.get("name", "")).lower() not in critical
                ]
                if safe and input(f"  Close {len(safe)}? [y/N]: ").strip().lower() == "y":
                    k, f = executor.system_health.close_processes_bulk(safe)
                    print_ok(f"Closed {k}. Failed {f}.")
            elif choice in ("s", "some"):
                raw = input("  ❯ Indexes: ").strip()
                idxs = _parse_sel(raw, len(procs))
                targets = [procs[i] for i in idxs]
                if targets and input("  Confirm? [y/N]: ").strip().lower() == "y":
                    k, f = executor.system_health.close_processes_bulk(targets)
                    print_ok(f"Closed {k}. Failed {f}.")
            elif choice in ("n", "name"):
                name = input("  ❯ App name: ").strip()
                matches = [p for p in procs if name.lower() in str(p.get("name", "")).lower()]
                if matches and input(f"  Close {len(matches)}? [y/N]: ").strip().lower() == "y":
                    k, f = executor.system_health.close_processes_bulk(matches)
                    print_ok(f"Closed {k}. Failed {f}.")
            else:
                print_info("Left running.")
            continue

        # --- File finder: "find <query>" direct command ---
        if user_input_lower.startswith("find ") and len(user_input) > 5:
            query = user_input[5:].strip()
            if query:
                _do_file_search(query, memory)
                continue

        # --- File delete: "delete/remove/erase <query>" direct command ---
        _delete_triggers = ("delete ", "remove ", "erase ")
        if any(user_input_lower.startswith(t) for t in _delete_triggers):
            query = _extract_delete_query(user_input)
            if query:
                _do_file_delete(query, memory)
                continue

        if user_input.lower().startswith("kill "):
            parts = user_input.split(maxsplit=1)
            if len(parts) == 2:
                target = parts[1].strip()
                result = executor.system_health.kill_by_index_or_pid(target)
                if "Killed" in result or "Closed" in result:
                    print_ok(result)
                else:
                    print_warn(result)
            else:
                print_warn("Usage: kill <pid_or_name_or_index>   example: kill 1 or kill 1234 or kill whatsapp")
            continue

        # --- close <app> / close all background / close all apps ---
        _close_all_phrases = (
            "close all background", "close all apps", "close all applications",
            "close background", "close background processes", "close all",
        )
        if any(user_input_lower == p or user_input_lower.startswith(p) for p in _close_all_phrases):
            from prompt_toolkit import prompt as tk_prompt
            from prompt_toolkit.styles import Style as TkStyle
            hex_col = get_theme_hex()
            procs = executor.system_health.get_background_processes()
            print_bg_process_table(procs)
            if not procs:
                console.print()
                continue
            important = [p for p in procs if p.get("important")]
            if important:
                print_warn(f"  {len(important)} important app(s) marked ⚠ — closing them may lose unsaved work.")
            try:
                sel = tk_prompt(
                    "  ❯ Close all? [y / n / numbers like 1,3,5]: ",
                    style=TkStyle.from_dict({"prompt": f"{hex_col} bold"}),
                ).strip().lower()
            except (KeyboardInterrupt, EOFError):
                print_info("Cancelled.")
                console.print()
                continue
            if sel == "n" or not sel:
                print_info("No processes closed.")
            elif sel == "y":
                killed, failed = executor.system_health.close_processes_bulk(procs)
                print_ok(f"Closed {killed} background process(es). {failed} skipped.")
            else:
                indices = []
                for part in sel.replace(" ", "").split(","):
                    if part.isdigit():
                        idx = int(part) - 1
                        if 0 <= idx < len(procs):
                            indices.append(idx)
                targets = [procs[i] for i in indices]
                killed, failed = executor.system_health.close_processes_bulk(targets)
                print_ok(f"Closed {killed} process(es). {failed} skipped.")
            console.print()
            continue

        if user_input_lower.startswith("close "):
            target_app = user_input[6:].strip()
            if target_app:
                from prompt_toolkit import prompt as tk_prompt
                from prompt_toolkit.styles import Style as TkStyle
                hex_col = get_theme_hex()
                # Find matching processes to show before killing
                matches = [
                    p for p in executor.system_health.get_background_processes(min_ram_mb=0)
                    if target_app.lower() in p["name"].lower()
                ]
                if not matches:
                    print_warn(f"No running process found matching '{target_app}'.")
                    console.print()
                    continue
                print_bg_process_table(matches)
                important_match = any(p.get("important") for p in matches)
                if important_match:
                    print_warn("This is an important app — closing may lose unsaved work.")
                try:
                    confirm = tk_prompt(
                        f"  ❯ Close {len(matches)} instance(s) of '{target_app}'? [y/n]: ",
                        style=TkStyle.from_dict({"prompt": f"{hex_col} bold"}),
                    ).strip().lower()
                except (KeyboardInterrupt, EOFError):
                    print_info("Cancelled.")
                    console.print()
                    continue
                if confirm == "y":
                    killed, failed = executor.system_health.close_processes_bulk(matches)
                    print_ok(f"Closed {killed} instance(s) of '{target_app}'. {failed} skipped.")
                else:
                    print_info("Cancelled.")
            console.print()
            continue

        # --- free memory ---
        _FREE_MEM = ("free memory", "free ram", "free up memory", "free up ram", "release memory")
        if user_input_lower in _FREE_MEM or any(user_input_lower.startswith(p) for p in _FREE_MEM):
            procs = executor.system_health.get_background_processes(min_ram_mb=50)
            print_bg_process_table(procs)
            if procs:
                total_mb = sum(p.get("ram_mb", 0) for p in procs)
                console.print(f"  [dim]Closing these will free up to [bold]{total_mb/1024:.2f} GB[/bold] of RAM.[/dim]")
                from prompt_toolkit import prompt as tk_prompt
                from prompt_toolkit.styles import Style as TkStyle
                hex_col = get_theme_hex()
                try:
                    sel = tk_prompt(
                        "  ❯ Close all non-essential? [y/n]: ",
                        style=TkStyle.from_dict({"prompt": f"{hex_col} bold"}),
                    ).strip().lower()
                except (KeyboardInterrupt, EOFError):
                    sel = "n"
                if sel == "y":
                    safe = [p for p in procs if not p.get("important")]
                    killed, failed = executor.system_health.close_processes_bulk(safe)
                    print_ok(f"Freed RAM: closed {killed} process(es). {failed} skipped.")
                else:
                    print_info("No changes made.")
            console.print()
            continue

        # --- restart explorer ---
        _RESTART_EXP = ("restart explorer", "restart taskbar", "reset taskbar", "fix taskbar", "reload explorer")
        if user_input_lower in _RESTART_EXP:
            with console.status("  [dim]Restarting Windows Explorer...[/dim]", spinner="dots"):
                result = executor.system_health.restart_explorer()
            print_ok(result)
            console.print()
            continue

        # --- optimize system ---
        _OPTIMIZE = ("optimize system", "optimize pc", "optimize", "full optimize", "speed up system")
        if user_input_lower in _OPTIMIZE:
            from prompt_toolkit import prompt as tk_prompt
            from prompt_toolkit.styles import Style as TkStyle
            hex_col = get_theme_hex()
            console.print()
            console.print(f"  [bold {hex_col}]◉ FIXBOT[/bold {hex_col}]  [dim]System Optimization[/dim]")
            console.print(f"  [dim]{'─'*46}[/dim]")
            console.print("  Running all optimizations: cache clear → close background apps → power plan.")
            console.print()
            try:
                confirm = tk_prompt(
                    "  ❯ Proceed with full system optimization? [y/n]: ",
                    style=TkStyle.from_dict({"prompt": f"{hex_col} bold"}),
                ).strip().lower()
            except (KeyboardInterrupt, EOFError):
                confirm = "n"
            if confirm == "y":
                # Step 1: cache
                console.print(f"\n  [bold {hex_col}]Step 1 — Cache Removal[/bold {hex_col}]")
                result = executor.run_cache_cleanup()
                # Step 2: background processes
                console.print(f"\n  [bold {hex_col}]Step 2 — Background Processes[/bold {hex_col}]")
                procs = executor.system_health.get_background_processes(min_ram_mb=50)
                safe  = [p for p in procs if not p.get("important")]
                if safe:
                    killed, _ = executor.system_health.close_processes_bulk(safe)
                    print_ok(f"Closed {killed} background process(es).")
                else:
                    print_ok("No significant background processes to close.")
                # Step 3: power plan
                console.print(f"\n  [bold {hex_col}]Step 3 — Power Plan[/bold {hex_col}]")
                pwr = executor.system_health.fix_power_balanced()
                print_ok(pwr)
                console.print()
                print_ok("Full system optimization complete.")
            else:
                print_info("Optimization cancelled.")
            console.print()
            continue

        # --- Auto-detect file path → explain its content ---
        path_match = _PATH_RE.search(user_input)
        if path_match:
            detected_path = (path_match.group(1) or path_match.group(2)).strip()
            if os.path.isfile(detected_path):
                content = file_finder.read_file_safe(detected_path)
                if content is not None:
                    console.print(
                        f"  [dim]Detected file:[/dim] [white]{detected_path}[/white]"
                    )
                    console.print()
                    print_bot_start()
                    full_reply = ""
                    for chunk in executor.gemini.explain_file_stream(detected_path, content):
                        full_reply += getattr(chunk, "text", str(chunk))
                    console.print(Markdown(full_reply))
                    memory.add("user", user_input)
                    memory.add("model", full_reply)
                    console.print()
                    continue

        # --- Filename-only detection: "explain about thalas.txt" / "read config.json" ---
        fn_match = _FILENAME_RE.search(user_input)
        if fn_match:
            filename_query = fn_match.group(1)
            lowered = user_input.lower()
            is_explain = (
                any(t in lowered for t in _EXPLAIN_TRIGGERS)
                or lowered.strip() == filename_query.lower()
            )
            if is_explain:
                with console.status(
                    f"  [dim]Searching for '{filename_query}'...[/dim]", spinner="dots"
                ):
                    results = file_finder.search_system(filename_query)
                if results:
                    detected_path = results[0]["path"]
                    content = file_finder.read_file_safe(detected_path)
                    if content is not None:
                        console.print(
                            f"  [dim]Found:[/dim] [white]{detected_path}[/white]"
                        )
                        console.print()
                        print_bot_start()
                        full_reply = ""
                        for chunk in executor.gemini.explain_file_stream(detected_path, content):
                            full_reply += getattr(chunk, "text", str(chunk))
                        console.print(Markdown(full_reply))
                        memory.add("user", user_input)
                        memory.add("model", full_reply)
                        console.print()
                        continue
                else:
                    print_warn(f"File '{filename_query}' not found. Try: find {filename_query}")
                    continue

        # ── UNINSTALL intent ─────────────────────────────────────────────
        _uninstall_triggers = ("uninstall", "unistall", "uninstal", "remove", "delete app", "delete program",
                               "get rid of", "delete software")
        _is_uninstall = any(t in user_input_lower for t in _uninstall_triggers)
        if _is_uninstall:
            # Extract the app name from the uninstall request
            import re as _re
            _uninstall_match = _re.search(
                r"\b(?:uninstall|unistall|uninstal|remove|delete|get rid of)\s+(.+)", user_input_lower
            )
            _uninstall_app = _uninstall_match.group(1).strip() if _uninstall_match else user_input
            # Strip filler words
            for _filler in ("app", "program", "software", "application", "the", "my"):
                _uninstall_app = _uninstall_app.replace(_filler, "").strip()
            if _uninstall_app:
                if not _run_uninstall_graph(
                    _uninstall_app, executor, memory, report_gen, ticket_manager
                ):
                    # Fallback: direct winget uninstall
                    import subprocess as _sp
                    console.print(f"  [dim]Running: winget uninstall --name {_uninstall_app}[/dim]")
                    _sp.run(
                        ["winget", "uninstall", "--name", _uninstall_app,
                         "--accept-source-agreements"],
                        check=False,
                    )
                    memory.add("user", user_input)
                    memory.add("model", f"Attempted direct uninstall of: {_uninstall_app}")
                console.print()
                continue

        # ── INSTALL intent ────────────────────────────────────────────────
        app_name = extract_app_name(user_input)
        if app_name:
            if not _run_install_graph(app_name, executor, memory, report_gen, ticket_manager):
                # Fallback: original single-shot InstallerModule (no API key / graph failed)
                installer.handle(app_name)
                memory.add("user", user_input)
                memory.add("model", f"Handled install request for: {app_name}")
            console.print()
            continue

        # --- Direct cache-clear route (no Gemini round-trip needed) ---
        # Word-level "cache" check catches typos ("cleat cache", "cler cache" etc.)
        _input_words = set(user_input_lower.split())
        _CACHE_TRIGGER_PHRASES = (
            "clear temp", "clean temp", "improve performance", "boost performance",
            "speed up my pc", "speed up pc", "free up space", "clean up pc", "clear junk",
            "clean junk", "clear system", "clean system",
        )
        _is_cache_request = (
            "cache" in _input_words
            or any(phrase in user_input_lower for phrase in _CACHE_TRIGGER_PHRASES)
        )
        if _is_cache_request:
            from prompt_toolkit import prompt as tk_prompt
            from prompt_toolkit.styles import Style as TkStyle
            hex_col = get_theme_hex()
            executor.preview_cache_cleanup()
            try:
                confirm = tk_prompt(
                    "  ❯ Proceed with cleanup? [y/n]: ",
                    style=TkStyle.from_dict({"prompt": f"{hex_col} bold"}),
                ).strip().lower()
            except (KeyboardInterrupt, EOFError):
                print_info("Cancelled.")
                console.print()
                continue
            if confirm != "y":
                print_info("Skipped — no changes made.")
                console.print()
                continue
            result = executor.run_cache_cleanup()
            os_data = prompt_builder.build_context(user_input, "STORAGE")
            verification = executor.last_verification
            report = report_gen.generate(
                intent="STORAGE",
                problem=user_input,
                os_data=os_data,
                ai_reply="Cache and temp files cleared.",
                fix_applied=result,
                verification_passed=verification.passed if verification else None,
                changes=verification.changes if verification else {},
            )
            saved = report_gen.save(report)
            report_gen.display_summary(report, saved_path=saved)
            memory.add("user", user_input)
            memory.add("model", result)

            # Offer to also close background apps to further free RAM
            try:
                bg_confirm = tk_prompt(
                    "  ❯ Also close background apps to free RAM? [y/n]: ",
                    style=Style.from_dict({"prompt": f"{hex_col} bold"}),
                ).strip().lower()
            except (KeyboardInterrupt, EOFError):
                bg_confirm = "n"
            if bg_confirm == "y":
                bg_procs = executor.system_health.get_background_processes(min_ram_mb=50)
                safe_procs = [p for p in bg_procs if not p.get("important")]
                print_bg_process_table(safe_procs)
                if safe_procs:
                    try:
                        sel = tk_prompt(
                            "  ❯ Close all non-essential? [y / n / numbers like 1,3,5]: ",
                            style=Style.from_dict({"prompt": f"{hex_col} bold"}),
                        ).strip().lower()
                    except (KeyboardInterrupt, EOFError):
                        sel = "n"
                    if sel == "y":
                        killed, failed = executor.system_health.close_processes_bulk(safe_procs)
                        print_ok(f"Closed {killed} background process(es). {failed} skipped.")
                    elif sel != "n" and sel:
                        indices = [int(p)-1 for p in sel.replace(" ","").split(",") if p.isdigit()]
                        targets = [safe_procs[i] for i in indices if 0 <= i < len(safe_procs)]
                        killed, failed = executor.system_health.close_processes_bulk(targets)
                        print_ok(f"Closed {killed} process(es). {failed} skipped.")
                    else:
                        print_info("No processes closed.")
                else:
                    print_ok("No significant background processes running.")
            console.print()
            continue

        intent = executor.intent_engine.detect_intent(user_query)

        # UPDATE words in the current message must never be overridden by follow-up
        # inheritance — check before the follow-up block runs.
        _UPDATE_WORDS = {
            "update", "updates", "upgrade", "outdated", "pending", "patch", "patches",
        }
        _has_update_words = bool(set(user_input_lower.split()) & _UPDATE_WORDS)

        # Queries that ask for specific app/tool information should stay GENERAL so
        # the command path can handle them — prevent follow-up inheritance from
        # mis-routing them into a diagnostic module (e.g. "mysql version" → SYSTEM).
        _INFO_QUERY_WORDS = {
            "version", "-v", "--version", "installed", "which", "where",
            "path", "check", "status", "info", "details",
        }
        _is_info_query = bool(set(user_input_lower.split()) & _INFO_QUERY_WORDS)

        # Only inherit technical intents from history — never GREETING, GENERAL,
        # or UPDATE-adjacent / info queries (which caused follow-up to override them).
        _INHERITABLE = {"NETWORK", "STORAGE", "DEV_ENV", "SYSTEM"}
        if memory.is_followup(user_query) and intent == "GENERAL" and not _has_update_words and not _is_info_query:
            recent = memory.get_history(6)
            if recent:
                for entry in reversed(recent):
                    if entry["role"] == "user":
                        prev_intent = executor.intent_engine.detect_intent(entry["parts"][0])
                        if prev_intent in _INHERITABLE:
                            intent = prev_intent
                            break

        # If follow-up stayed GENERAL but the message has update words, route to UPDATE.
        if intent == "GENERAL" and _has_update_words:
            intent = "UPDATE"

        # GREETING falls through to Gemini so it can answer naturally in context.
        if intent == "GREETING":
            intent = "GENERAL"

        if intent == "GENERAL":
            with console.status("  [dim]thinking...[/dim]", spinner="dots"):
                cmd, reason = executor.gemini.ask_for_command(user_query)
            if not cmd:
                # Groq/Gemini returned no command — try local pattern match
                cmd, reason = _local_command_guess(user_query)
            if cmd:
                _do_run_command(user_query, cmd, reason, memory, executor)
                continue
            # No command matched — ask Groq whether this is a known domain
            # query that the keyword engine missed, before falling through to
            # the full Gemini chat path.
            groq_domain = _groq_disambiguate_intent(user_query)
            if groq_domain:
                intent = groq_domain  # re-route into specific domains

        # ── LAUNCHER: open / close apps & files ─────────────────────────
        if intent == "LAUNCHER" or any(
            user_query.lower().startswith(p)
            for p in ("open ", "close ", "launch ", "kill ", "force close", "start ")
        ):
            # Don't steal RAG-style "open X and explain"
            _lq = user_query.lower()
            if any(w in _lq for w in ("summarize", "explain chapter", "answer questions")):
                pass  # fall through to RAG/other
            else:
                try:
                    from modules.app_launcher import launcher, parse_launcher_query
                    from display.animations import agent_log, agent_log_ok, agent_log_warn

                    agent_log("Launcher", user_query)
                    result = launcher.handle(user_query)

                    if result.get("kind") == "choices":
                        hits = result.get("hits") or []
                        console.print(f"  [bold]{result.get('message')}[/bold]")
                        for i, h in enumerate(hits, 1):
                            console.print(f"  [cyan]{i}[/cyan]  {h.get('name')}  [dim]{h.get('path')}[/dim]")
                        console.print("  Number (or Enter to cancel): ", end="")
                        try:
                            raw = input().strip()
                        except Exception:
                            raw = ""
                        if raw.isdigit():
                            result = launcher.handle(user_query, pick_index=int(raw))
                        else:
                            print_warn("Cancelled")
                            continue

                    if result.get("ok"):
                        agent_log_ok(result.get("message") or "Done")
                        if result.get("path"):
                            console.print(f"  [dim]{result['path']}[/dim]")
                    else:
                        agent_log_warn(result.get("message") or "Failed")
                    memory.add("user", user_query)
                    memory.add("model", str(result.get("message", ""))[:300])
                except Exception as exc:
                    print_err(f"Launcher error: {exc}")
                continue

        if intent == "FILE_SEARCH":
            query = _extract_search_query(user_query)
            _do_file_search(query, memory)
            continue

        if intent == "FILE_RAG":
            from agents.rag.graph import build_file_rag_graph
            from langgraph.types import Command
            from display.animations import agent_log, agent_log_err
            from config import MODEL

            api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

            agent_log("rag", "Starting multi-agent file understanding pipeline...")

            llm = _get_agent_llm(api_key, MODEL) if api_key else None
            graph = build_file_rag_graph(llm=llm)
            thread_id = getattr(memory, "session_id", None) or "default"
            config = {"configurable": {"thread_id": f"rag-{thread_id}"}}
            # Build short history for ChatGPT-style multi-turn feel
            history = []
            try:
                # Adapt to your ConversationMemory API if different
                for turn in getattr(memory, "turns", [])[-6:]:
                    history.append({
                        "role": turn.role,
                        "content": turn.content,
                    })
            except Exception:
                history = []

            init = {
                "user_query": user_query,
                "thread_id": f"rag-{thread_id}",
                "chat_history": history,
                "rag_cycle": 1,
                "max_rag_cycles": 2,
            }

            try:
                events = graph.stream(init, config, stream_mode="updates")
                while True:
                    interrupted = False
                    for event in events:
                        if "__interrupt__" in event:
                            payload = event["__interrupt__"][0].value
                            msg = payload.get("message") or "Analyze located files? [y/n]"
                            console.print(f"\n  [bold yellow]🔐 Permission Gate[/bold yellow]")
                            for line in msg.splitlines():
                                console.print(f"  {line}")
                            from prompt_toolkit import prompt as tk_prompt
                            choice = tk_prompt("  ❯ ").strip().lower() or "n"
                            events = graph.stream(Command(resume=choice), config, stream_mode="updates")
                            interrupted = True
                            break
                    if not interrupted:
                        break

                memory.add("user", user_input)
                memory.add("model", "Completed local document analysis.")
            except Exception as exc:
                agent_log_err(f"RAG pipeline failed: {exc}")
                _do_file_search(user_input, memory)

            console.print()
            continue

        # ── GIT / GitPilot ───────────────────────────────────────────────
        if intent == "GIT" or user_query.lower().strip() in (
            "fixgit", "gitpilot", "git pilot",
        ):
            q = user_query.lower().strip()
            try:
                from gitpilot.classify import classify_git_query, is_mutating
                from gitpilot.shared_state import get_last_repo_path
                from gitpilot.graph import run_git_agent, run_git_readonly
            except ImportError as exc:
                print_err(f"GitPilot import error: {exc}")
                try:
                    _launch_gitpilot()
                except Exception:
                    pass
                continue

            kind = classify_git_query(user_query)
            repo_hint = get_last_repo_path() or getattr(memory, "last_git_path", None)

            # Coach UI
            if kind == "coach" or q in ("fixgit", "gitpilot", "git pilot"):
                _launch_gitpilot()
                continue

            # Read-only fast path
            if kind == "readonly" or (not is_mutating(kind) and kind != "unknown"):
                try:
                    text = run_git_readonly(user_query, repo_path=repo_hint)
                    console.print()
                    console.print(text)
                    console.print()
                    memory.add("user", user_query)
                    memory.add("model", text[:500])
                    try:
                        memory.last_git_path = get_last_repo_path()
                    except Exception:
                        pass
                except Exception as exc:
                    print_err(f"Git read failed: {exc}")
                continue

            # Mutating → Action Graph
            if is_mutating(kind) or kind == "unknown":
                try:
                    from display.animations import agent_log, agent_log_ok, agent_log_warn

                    agent_log("GitAgent", f"Autonomous git pipeline ({kind})...")
                    final = run_git_agent(
                        user_query,
                        repo_path=repo_hint,
                        auto_approve=False,
                        git_kind=kind if kind != "unknown" else None,
                    )
                    if final.get("repo_path"):
                        try:
                            memory.last_git_path = final["repo_path"]
                        except Exception:
                            pass

                    report = final.get("report") or {}
                    if report.get("ok"):
                        agent_log_ok(report.get("summary") or "Success")
                    else:
                        agent_log_warn(report.get("summary") or "Escalated")
                        if report.get("tip"):
                            console.print(f"  [dim]{report['tip']}[/dim]")

                        # Easy auth path when push failed on credentials
                        if report.get("offer_auth_helper") or report.get("strategy") == "auth_help":
                            console.print(
                                "  Open GitHub Auth Helper? [Y/n]: ", end=""
                            )
                            try:
                                ans = input().strip().lower()
                            except Exception:
                                ans = "y"
                            if ans in ("", "y", "yes"):
                                try:
                                    from gitpilot.auth_helper import run_auth_wizard
                                    ok = run_auth_wizard(console)
                                    if ok:
                                        console.print(
                                            "  [green]Auth OK — run your push again.[/green]"
                                        )
                                    else:
                                        console.print(
                                            "  [dim]Auth not finished. "
                                            "You can still type fixgit.[/dim]"
                                        )
                                except Exception as auth_exc:
                                    print_err(f"Auth helper error: {auth_exc}")

                        if report.get("offer_fixgit"):
                            console.print(
                                "  Open guided GitPilot now? [y/N]: ", end=""
                            )
                            try:
                                ans = input().strip().lower()
                            except Exception:
                                ans = "n"
                            if ans in ("y", "yes"):
                                _launch_gitpilot()
                    memory.add("user", user_query)
                    memory.add("model", str(report)[:400])
                except Exception as exc:
                    print_err(f"Git agent error: {exc}")
                continue

            _launch_gitpilot()
            continue

        if intent == "FILE_DELETE":

            query = _extract_delete_query(user_query)
            _do_file_delete(query, memory)
            continue

        if intent == "UPDATE":
            # Generic scans ("check for updates", "any update in my pc") → interactive menu
            # Targeted updates ("update microsoft edge") → multi-agent graph
            if _is_generic_update_query(user_input_lower):
                _do_update_scan(memory, executor, report_gen, ticket_manager)
            else:
                if not _run_update_graph(user_query, executor, memory, report_gen, ticket_manager):
                    _do_update_scan(memory, executor, report_gen, ticket_manager)
            continue

        # ── Speed test (LibreSpeed) ──────────────────────────────────────
        if intent == "NETWORK" or True:
            q = user_query.lower().strip()
            wants_speed = any(
                p in q for p in (
                    "speed test", "speedtest", "internet speed",
                    "check speed", "network speed", "wifi speed",
                    "run speed", "bandwidth test", "librespeed",
                )
            )
            if wants_speed:
                from modules.speedtest_runner import run_speedtest, speed_color
                from rich.live import Live
                from rich.panel import Panel
                from rich.text import Text
                from rich.align import Align
                import time as _time

                state = {
                    "phase": "init",
                    "mbps": 0.0,
                    "peak": 0.0,
                    "label": "Connecting...",
                    "history": [],  # for smooth animation
                }

                def _smooth(mbps: float) -> float:
                    h = state["history"]
                    h.append(mbps)
                    if len(h) > 5:
                        h.pop(0)
                    return sum(h) / len(h)

                def gauge_render() -> Panel:
                    mbps = _smooth(float(state.get("mbps") or 0))
                    peak = max(float(state.get("peak") or 0), mbps)
                    state["peak"] = peak
                    phase = state.get("phase") or ""
                    cap = max(50.0, peak * 1.2, 20.0)  # auto-scale
                    filled = int(max(0, min(cap, mbps)) / cap * 32)
                    col = speed_color(mbps)
                    # animated pulse on the tip
                    tip = "●" if int(_time.time() * 8) % 2 == 0 else "○"
                    bar = "█" * filled + tip + "░" * max(0, 31 - filled)
                    body = Text()
                    body.append("\n")
                    body.append(f"   {mbps:6.2f} ", style=f"bold {col}")
                    body.append("Mbps\n", style="dim")
                    body.append(f"  [{col}]{bar}[/{col}]\n")
                    body.append(f"  0{('─' * 14)}{int(cap)//2}{('─' * 14)}{int(cap)}+\n", style="dim")
                    if phase == "download":
                        body.append("  ↓ Testing download...\n", style="bold cyan")
                    elif phase == "upload":
                        body.append("  ↑ Testing upload...\n", style="bold magenta")
                    else:
                        body.append(f"  {state.get('label', '')}\n", style="dim")
                    body.append("\n  ", style="")
                    body.append("■ slow ", style="red")
                    body.append("■ ok ", style="yellow")
                    body.append("■ fast", style="green")
                    body.append(f"   peak {peak:.1f}", style="dim")
                    return Panel(
                        Align.center(body),
                        title="[bold]Speed Test[/bold]",
                        border_style=col,
                        width=54,
                    )

                console.print()
                # IMPORTANT: do not call agent_log_step during Live — it breaks the gauge
                with Live(gauge_render(), console=console, refresh_per_second=12) as live:
                    def on_dl(spd: float) -> None:
                        state["phase"] = "download"
                        state["mbps"] = spd
                        live.update(gauge_render())

                    def on_ul(spd: float) -> None:
                        state["phase"] = "upload"
                        state["mbps"] = spd
                        live.update(gauge_render())

                    def on_prog(msg: str) -> None:
                        # only update panel label — no print/log
                        state["label"] = msg
                        live.update(gauge_render())

                    result = run_speedtest(
                        duration=10,
                        on_progress=on_prog,
                        on_download_speed=on_dl,
                        on_upload_speed=on_ul,
                    )
                    live.update(gauge_render())

                if not result.get("ok"):
                    print_warn(result.get("error") or "Speed test failed")
                    continue

                d = float(result.get("download_mbps") or 0)
                u = float(result.get("upload_mbps") or 0)
                console.print()
                console.print("  [bold]Results[/bold]")
                console.print(f"  [dim]{'─' * 42}[/dim]")
                console.print(f"  Download  [{speed_color(d)}]{d:.2f} Mbps[/]")
                console.print(f"  Upload    [{speed_color(u)}]{u:.2f} Mbps[/]")
                console.print(
                    f"  Ping      {result.get('ping_ms')} ms  "
                    f"[dim]jitter {result.get('jitter_ms')} ms[/dim]"
                )
                console.print(f"  Server    {result.get('server_name')}")
                if result.get("note"):
                    console.print(f"  [dim]{result['note']}[/dim]")
                console.print(f"  [dim]{'─' * 42}[/dim]")
                console.print()
                memory.add("user", user_query)
                memory.add("model", f"speed down={d} up={u}")
                continue

        # ── Wi-Fi password check (NETWORK or follow-up) ──────────────────
        if intent == "NETWORK" or getattr(memory, "last_domain", None) == "NETWORK":
            q = user_query.lower().strip()
            wants_pw = any(
                p in q for p in (
                    "password", "wifi password", "wi-fi password",
                    "whats the password", "what's the password",
                    "waht is the password",  # common typo
                    "show password", "wlan password", "key content",
                )
            )
            list_all = any(
                p in q for p in (
                    "list", "all password", "all passwords", "passwords u know",
                    "passwords you know", "every password", "saved password",
                    "known password", "show all", "list it", "list them",
                )
            )

            if wants_pw or list_all:
                console.print()
                if list_all:
                    profiles = []
                    try:
                        profiles = executor.network.list_wifi_profiles()
                    except Exception as exc:
                        print_warn(f"Could not list profiles: {exc}")
                    if not profiles:
                        print_warn("No saved Wi-Fi profiles found.")
                    else:
                        console.print(
                            f"  [bold]Saved Wi-Fi passwords[/bold]  "
                            f"[dim]({len(profiles)} profile(s))[/dim]"
                        )
                        console.print(f"  [dim]{'─' * 44}[/dim]")
                        for name in profiles:
                            info = executor.network.get_wifi_password(name)
                            pw = info.get("password") or ""
                            err = info.get("error") or ""
                            if pw:
                                console.print(
                                    f"  [bold]{name}[/bold]\n"
                                    f"    Password  [green]{pw}[/green]"
                                )
                            else:
                                console.print(
                                    f"  [bold]{name}[/bold]\n"
                                    f"    [yellow]{err or 'unavailable'}[/yellow]"
                                )
                        console.print(f"  [dim]{'─' * 44}[/dim]")
                        console.print(
                            "  [dim]Only profiles saved on this Windows PC are shown.[/dim]"
                        )
                else:
                    ssid = getattr(memory, "last_wifi_ssid", None)
                    info = executor.network.get_wifi_password(ssid)
                    if info.get("error") and not info.get("password"):
                        print_warn(info["error"])
                        if "Administrator" in (info.get("error") or ""):
                            console.print(
                                "  [dim]Run Fixbot as Administrator and try again.[/dim]"
                            )
                    else:
                        console.print(f"  [bold]SSID[/bold]     {info.get('ssid')}")
                        console.print(
                            f"  [bold]Password[/bold] [bold green]{info.get('password')}[/bold green]"
                        )
                        console.print(
                            "  [dim]Saved Windows profile password for this network.[/dim]"
                        )
                console.print()
                memory.add("user", user_query)
                memory.add("model", "wifi_password_query")
                try:
                    memory.last_domain = "NETWORK"
                except Exception:
                    pass
                continue

        diagnostic_intents = {"NETWORK", "STORAGE", "DEV_ENV", "SYSTEM"}
        if intent in diagnostic_intents:
            # ── NETWORK status-only (no LLM / no repair graph) ───────────────
            if intent == "NETWORK":
                q = user_query.lower().strip()
                status_phrases = (
                    "my wifi", "my wifi?", "wifi?", "wifi status", "network status",
                    "what wifi", "which wifi", "connected to", "ssid", "my network",
                    "am i connected", "wifi name", "what network",
                )
                is_status = (
                    any(p in q for p in status_phrases)
                    or q in ("wifi", "network", "internet status")
                )
                # If they only ask status (not "fix" / "slow" / "reset")
                wants_fix = any(
                    w in q for w in (
                        "slow", "fix", "reset", "flush", "not working", "down",
                        "drop", "issue", "problem", "repair", "broken", "can't",
                        "cannot", "no internet", "offline",
                    )
                )
                if is_status and not wants_fix:
                    try:
                        d = executor.network.collect()
                    except Exception as exc:
                        print_err(f"Network status failed: {exc}")
                        continue
                    iface = d.get("active_interface") or "unknown"
                    ssid = d.get("wifi_ssid") or "unknown"
                    signal = d.get("wifi_signal_dbm")
                    internet = d.get("internet") or "unknown"
                    gw = d.get("gateway_ip") or "unknown"
                    ping = d.get("gateway_ping_ms")
                    loss = d.get("packet_loss_pct")
                    dns = d.get("dns_status") or "unknown"

                    console.print()
                    console.print(f"  [bold]Wi‑Fi / Network status[/bold]")
                    console.print(f"  [dim]{'─' * 40}[/dim]")
                    console.print(f"  [bold]Interface[/bold]  {iface}")
                    console.print(f"  [bold]SSID[/bold]       {ssid}")
                    console.print(f"  [bold]Signal[/bold]     {signal} dBm")
                    console.print(f"  [bold]Internet[/bold]   {internet}")
                    console.print(f"  [bold]Gateway[/bold]    {gw}  ({ping} ms)")
                    console.print(f"  [bold]Packet loss[/bold] {loss}%")
                    console.print(f"  [bold]DNS[/bold]        {dns}")
                    console.print(f"  [dim]{'─' * 40}[/dim]")
                    if ssid and ssid != "unknown":
                        console.print(
                            f"  Connected to [bold green]{ssid}[/bold green] "
                            f"via [bold]{iface}[/bold]."
                        )
                    else:
                        console.print(
                            "  [yellow]SSID unknown[/yellow] — adapter may be Ethernet "
                            "or Wi‑Fi details unavailable."
                        )
                    console.print()
                    memory.add("user", user_query)
                    memory.add(
                        "model",
                        f"SSID={ssid}; interface={iface}; internet={internet}",
                    )
                    try:
                        memory.last_domain = "NETWORK"
                        memory.last_wifi_ssid = ssid
                    except Exception:
                        pass
                    continue  # skip repair graph + Gemini

            if _run_supervisor_domain_graph(intent, user_query, executor, memory, report_gen, ticket_manager):
                console.print()
                continue

            print_collecting(intent.lower())
            os_data = prompt_builder.build_context(user_query, intent)
            for key in _top_os_data_keys(os_data, intent):
                print_data(key, str(os_data.get(key, "n/a")))
        else:
            os_data = {}

        console.print()
        print_bot_start()
        theme_col = get_theme_color()
        full_reply = typewriter_stream(
            (getattr(chunk, "text", str(chunk))
             for chunk in executor.gemini.ask_gemini_stream(user_query, os_data, memory.get_history())),
            color=theme_col,
        )

        memory.add("user", user_query)
        memory.add("model", full_reply)

        # Only offer fix actions for intents that have mapped fixes
        actionable_intents = {"NETWORK", "STORAGE", "DEV_ENV", "SYSTEM"}
        if intent in actionable_intents:
            action = PermissionGate.ask_permission(intent)
            if action == "t":
                ticket = ticket_manager.create_ticket(
                    problem=user_query,
                    os_data=os_data,
                    gemini_reply=full_reply,
                    module=intent,
                )
                print_ticket(ticket)
            elif action == "n":
                print_info("Skipped.")
            elif action == "d":
                console.print(full_reply)
            else:
                result, new_data = executor.run(intent, action, os_data)
                os_data = new_data

                verification = executor.last_verification
                report = report_gen.generate(
                    intent=intent,
                    problem=user_query,
                    os_data=os_data,
                    ai_reply=full_reply,
                    fix_applied=result,
                    verification_passed=verification.passed if verification else None,
                    changes=verification.changes if verification else {},
                )
                saved = report_gen.save(report)
                report_gen.display_summary(report, saved_path=saved)

        console.print()


if __name__ == "__main__":
    main()
