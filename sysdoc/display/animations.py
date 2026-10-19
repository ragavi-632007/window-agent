import sys
import time
import threading
import subprocess
import shutil
import math

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Ensure UTF-8 output encoding on Windows terminals to prevent UnicodeEncodeError on unicode blocks
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _safe_stdout_write(s: str) -> None:
    try:
        sys.stdout.write(s)
    except (UnicodeEncodeError, AttributeError):
        try:
            sys.stdout.buffer.write(s.encode("utf-8", errors="replace"))
        except Exception:
            pass

console = Console()

# ANSI colour codes used by terminal animations
_ANSI_COLORS = {
    "white":   "\033[97m",
    "cyan":    "\033[96m",
    "yellow":  "\033[93m",
    "magenta": "\033[95m",
    "green":   "\033[92m",
    "dim":     "\033[2m",
    # TrueColor palette matching CSS terminal cursor aesthetics (#3b82f6, #38bdf8, #6366f1, #00f0ff)
    "blue_bright":  "\033[38;2;59;130;246m",
    "sky_cyan":     "\033[38;2;56;189;248m",
    "neon_cyan":    "\033[38;2;0;240;255m",
    "indigo_glow":  "\033[38;2;99;102;241m",
    "flash_white":  "\033[38;2;255;255;255m\033[1m",
    "bg_white":     "\033[48;2;255;255;255m",
    "bg_cyan":      "\033[48;2;56;189;248m",
    "bg_blue":      "\033[48;2;59;130;246m",
}
_ANSI_RESET = "\033[0m"


# =========================================================
# AUTHENTIC LINUX TERMINAL CURSOR & LINE WRAP FLASH
# =========================================================

def right_to_left_wrap_flash(width: int = None, duration: float = 0.28) -> None:
    """
    Triggers a Right-to-Left sweeping laser flash animation across the terminal line
    when text wraps from the right boundary back to the left margin.
    Mirrors keyframe 'rightToLeftWrapFlash' (280ms cubic-bezier curve):
      0%: White laser sweep from right boundary back to left column.
      40%: Cyan/indigo trail glow.
      100%: Settles into electric blue terminal cursor overlay.
    """
    if width is None:
        try:
            width = shutil.get_terminal_size().columns
        except Exception:
            width = console.width or 80
    width = max(30, min(width, 120))

    fps = 30
    steps = max(6, int(duration * fps))
    frame_delay = duration / steps

    # Save initial state & prepare line sweep
    sys.stdout.write("\033[s")  # save cursor position
    sys.stdout.flush()

    for step in range(steps + 1):
        progress = step / float(steps)
        # cubic-bezier approximation for rapid initial sweep (0% -> 40% -> 100%)
        t = progress
        curve = 1.0 - math.pow(1.0 - t, 3)

        # Right-to-left sweep index
        current_col = int(width * (1.0 - curve))

        if progress < 0.4:
            # 0% - 40%: High contrast white laser streak & sky cyan aura
            head = f"\033[38;2;255;255;255m\033[48;2;255;255;255m█\033[0m"
            trail = f"\033[38;2;56;189;248m\033[48;2;59;130;246m▒\033[0m"
            tail = f"\033[38;2;99;102;241m░\033[0m"
        else:
            # 40% - 100%: Cyan & blue aura settling back to left margin
            head = f"\033[38;2;56;189;248m\033[1m▌\033[0m"
            trail = f"\033[38;2;59;130;246m▌\033[0m"
            tail = f"\033[38;2;99;102;241m\033[2m╎\033[0m"

        # Render sweep burst on line
        sys.stdout.write("\033[u")  # restore position
        sys.stdout.write("\r")
        sys.stdout.write(" " * current_col)
        sys.stdout.write(head + trail + tail)
        sys.stdout.flush()
        time.sleep(frame_delay)

    # Clean up sweep trail & return to left margin with active cursor
    sys.stdout.write("\r\033[K")
    sys.stdout.write(f"\033[38;2;56;189;248m\033[1m▌\033[0m")
    sys.stdout.flush()


def linux_terminal_flash(duration: float = 0.20) -> None:
    """
    Sharp, high-contrast vertical line cursor Linux Terminal Flash triggered on Enter key.
    Flashes a sleek vertical blue line cursor bar matching caret aesthetics.
    """
    try:
        sys.stdout.write("\033[s")  # save position

        # Vertical line cursor bar (▌) flash sequence: Bright white vertical bar -> Neon cyan bar -> Sky blue bar
        flash_1 = "\033[38;2;255;255;255m\033[1m▌\033[0m"
        flash_2 = "\033[38;2;0;240;255m\033[1m▌\033[0m"
        flash_3 = "\033[38;2;56;189;248m\033[1m▌\033[0m"
        flash_4 = "\033[38;2;59;130;246m▌\033[0m"

        frames = [
            (flash_1, 0.04),
            (flash_2, 0.05),
            (flash_3, 0.05),
            (flash_4, 0.06),
        ]

        for symbol, delay in frames:
            sys.stdout.write("\033[u")  # restore position
            _safe_stdout_write(symbol)
            sys.stdout.flush()
            time.sleep(delay)

        sys.stdout.write("\033[u")  # restore position
        sys.stdout.flush()
    except Exception:
        pass


def tactile_key_pulse(char: str, color: str = "cyan") -> None:
    """
    Tactile keypress micro-pulse animation on character input.
    Mirrors keyframe 'tactileKeyPulse' (90ms micro-pulse).
    """
    ansi = _ANSI_COLORS.get(color, "\033[96m")
    if sys.stdout.isatty():
        pulse_ansi = "\033[38;2;255;255;255m\033[1m"
        sys.stdout.write(f"{pulse_ansi}{char}{_ANSI_RESET}")
        sys.stdout.flush()
        time.sleep(0.004)
        sys.stdout.write(f"\b{ansi}{char}{_ANSI_RESET}")
        sys.stdout.flush()
    else:
        sys.stdout.write(f"{ansi}{char}{_ANSI_RESET}")
        sys.stdout.flush()


class BlinkingCursor:
    """
    Blinks a terminal cursor with ambient breathing aura, tactile pulse,
    and line-wrap flash support on a background thread.
    """

    def __init__(self, color: str = "sky_cyan", interval: float = 0.45):
        self._color = color
        self._ansi = _ANSI_COLORS.get(color, "\033[38;2;56;189;248m")
        self._interval = interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._pulse_requested = False
        self._wrap_flash_requested = False
        self._enter_flash_requested = False

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._blink_loop, daemon=True)
        self._thread.start()

    def trigger_typing_pulse(self) -> None:
        self._pulse_requested = True

    def trigger_right_to_left_flash(self) -> None:
        self._wrap_flash_requested = True

    def trigger_enter_flash(self) -> None:
        self._enter_flash_requested = True

    def _blink_loop(self) -> None:
        # Breathing aura phase palette: #3b82f6 -> #38bdf8 -> #00f0ff -> #6366f1
        aura_colors = [
            "\033[38;2;59;130;246m",
            "\033[38;2;56;189;248m",
            "\033[38;2;0;240;255m",
            "\033[38;2;99;102;241m",
        ]
        phase = 0
        shown = False

        while not self._stop_event.is_set():
            if self._wrap_flash_requested:
                self._wrap_flash_requested = False
                right_to_left_wrap_flash()
                shown = True
                continue

            if self._enter_flash_requested:
                self._enter_flash_requested = False
                linux_terminal_flash()
                shown = True
                continue

            if self._pulse_requested:
                self._pulse_requested = False
                sys.stdout.write("\033[38;2;255;255;255m\033[1m▌\033[0m")
                sys.stdout.flush()
                time.sleep(0.04)
                sys.stdout.write(f"\b{self._ansi}▌{_ANSI_RESET}")
                sys.stdout.flush()
                shown = True
                continue

            if shown:
                sys.stdout.write("\b \b")   # erase cursor character
            else:
                aura_color = aura_colors[phase % len(aura_colors)]
                sys.stdout.write(f"{aura_color}▌{_ANSI_RESET}")
                phase += 1

            sys.stdout.flush()
            shown = not shown
            self._stop_event.wait(self._interval)

        # guarantee cursor is erased when stopped
        if shown:
            sys.stdout.write("\b \b")
            sys.stdout.flush()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join()


EnhancedBlinkingCursor = BlinkingCursor


EnhancedBlinkingCursor = BlinkingCursor


def typewriter(text: str, color: str = "white", delay: float = 0.022) -> None:
    ansi = _ANSI_COLORS.get(color, "")
    for char in text:
        sys.stdout.write(f"{ansi}{char}{_ANSI_RESET}")
        sys.stdout.flush()
        time.sleep(delay)
    sys.stdout.write("\n")
    sys.stdout.flush()


def typewriter_stream(chunks, color: str = "white", delay: float = 0.013) -> str:
    """
    Print each streaming chunk character by character with tactile keypress pulse
    and Right-to-Left sweeping laser flash on line wrap.
    """
    full = ""
    ansi = _ANSI_COLORS.get(color, "")
    cursor = BlinkingCursor(color="sky_cyan")
    cursor.start()
    first = True

    try:
        width = shutil.get_terminal_size().columns
    except Exception:
        width = console.width or 80
    col_pos = 0

    for chunk in chunks:
        if first:
            cursor.stop()  # erase cursor before text appears
            first = False
        for char in chunk:
            if char == "\n":
                linux_terminal_flash()
                sys.stdout.write("\n")
                sys.stdout.flush()
                col_pos = 0
            else:
                col_pos += 1
                if col_pos >= width:
                    # Line wrap boundary reached! Trigger Right-to-Left laser sweep
                    right_to_left_wrap_flash(width=width)
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    col_pos = 0
                tactile_key_pulse(char, color=color)
                time.sleep(delay)
        full += chunk
    if first:  # generator was empty
        cursor.stop()
    sys.stdout.write("\n")
    sys.stdout.flush()
    return full


def demo_terminal_cursor_flash() -> None:
    """
    Interactive demonstration of the Terminal Cursor Flash & Right-to-Left Line Wrap Animation.
    """
    console.print("\n[bold cyan]── Terminal Cursor Flash & Line Wrap Animation Demo ──[/bold cyan]\n")

    # 1. Ambient Breathing Aura Cursor
    console.print("[dim]1. Ambient Breathing Aura Cursor (3s)...[/dim]")
    cursor = BlinkingCursor(color="sky_cyan", interval=0.3)
    cursor.start()
    time.sleep(3)
    cursor.stop()
    console.print("\n")

    # 2. Tactile Keypress Micro-pulse Typing
    console.print("[dim]2. Tactile Keypress Micro-pulse Typing...[/dim]")
    typewriter_stream(["System initialized. Testing tactile response...\n"], color="sky_cyan", delay=0.02)

    # 3. Enter Flash
    console.print("[dim]3. Linux Terminal Flash on Enter Key...[/dim]")
    sys.stdout.write("  Executing payload... ")
    sys.stdout.flush()
    linux_terminal_flash()
    console.print("[green]OK[/green]\n")

    # 4. Right-to-Left Line Wrap Sweeping Laser Flash
    console.print("[dim]4. Right-to-Left Sweeping Laser Flash on Line Wrap...[/dim]")
    wrap_text = "Accelerating neural processing pipeline across multi-node cluster boundaries... " * 2
    typewriter_stream([wrap_text], color="neon_cyan", delay=0.01)

    console.print("\n[bold green]✓ Demo completed successfully![/bold green]\n")



class ScrollingLog:
    """Rolling window of N lines rendered inside a Rich panel."""

    def __init__(self, max_lines: int = 8, title: str = "execution log"):
        self.max_lines = max_lines
        self.title = title
        self.lines: list[tuple[str, str]] = []
        self._drawn = False

    def add(self, text: str, style: str = "white", prefix: str = "") -> None:
        full = f"{prefix}{text}" if prefix else text
        self.lines.append((full, style))
        if len(self.lines) > self.max_lines:
            self.lines.pop(0)
        self._render()

    def _render(self) -> None:
        if self._drawn:
            sys.stdout.write(f"\033[{self.max_lines + 2}A")
            sys.stdout.flush()

        panel_text = Text()
        for text, style in self.lines:
            panel_text.append(text + "\n", style=style)
        for _ in range(self.max_lines - len(self.lines)):
            panel_text.append("\n")

        console.print(Panel(
            panel_text,
            title=f"[dim]{self.title}[/dim]",
            border_style="dim",
            padding=(0, 1),
        ))
        self._drawn = True

    def clear(self) -> None:
        self.lines = []
        self._drawn = False


def log_step(text: str, style: str = "dim", delay: float = 0.0) -> None:
    console.print(f"  [dim]→[/dim] [{style}]{text}[/{style}]")
    if delay:
        time.sleep(delay)


def log_ok(text: str) -> None:
    console.print(f"  [green][✓][/green] {text}")


def log_warn(text: str) -> None:
    console.print(f"  [yellow][!][/yellow] {text}")


def log_err(text: str) -> None:
    console.print(f"  [red][ERR][/red] {text}")


def log_cmd(cmd: str) -> None:
    console.print(f"  [dim]running:[/dim] [white]{cmd}[/white]")


# ── Claude Code-style agent log animation ─────────────────────────────────

_AGENT_COLORS = {
    "supervisor": "cyan",
    "planner": "blue",
    "executor": "yellow",
    "verifier": "magenta",
    "summary": "green",
    "parser": "blue",
    "search": "yellow",
    # FILE_RAG agents
    "locator": "yellow",
    "scope": "blue",
    "ingester": "magenta",
    "retriever": "cyan",
    "reasoner": "green",
    "analyst": "green",
    "rag": "cyan",
}

_AGENT_LABELS = {
    "supervisor": "Supervisor",
    "planner": "Planner",
    "executor": "Executor",
    "verifier": "Verifier",
    "summary": "Summary",
    "parser": "QueryParser",
    "search": "SearchAgent",
    # FILE_RAG agents
    "locator": "Locator",
    "scope": "ScopeResolver",
    "ingester": "Ingester",
    "retriever": "Retriever",
    "reasoner": "Reasoner",
    "analyst": "Analyst",
    "rag": "FileRAG",
}


_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _typewrite_line(text: str, *, indent: str = "    ", color: str = "white", delay: float = 0.008) -> None:
    """Print one line character-by-character with tactile keypulse, right-to-left wrap flash, and Linux terminal cursor."""
    ansi = _ANSI_COLORS.get(color, "")
    sys.stdout.write(indent)
    sys.stdout.flush()

    try:
        width = shutil.get_terminal_size().columns
    except Exception:
        width = console.width or 80

    col_pos = len(indent)

    for char in text:
        col_pos += 1
        if col_pos >= width:
            right_to_left_wrap_flash(width=width)
            sys.stdout.write("\n" + indent)
            sys.stdout.flush()
            col_pos = len(indent)

        tactile_key_pulse(char, color=color)
        if char not in (" ", "\t"):
            time.sleep(delay)

    linux_terminal_flash()
    sys.stdout.write("\n")
    sys.stdout.flush()


def agent_log(agent: str, message: str, *, animate: bool = True) -> None:
    """Emit an agent log block with optional typewriter animation."""
    color = _AGENT_COLORS.get(agent, "white")
    label = _AGENT_LABELS.get(agent, agent.title())
    ansi = _ANSI_COLORS.get(color, "")

    sys.stdout.write("\n")
    sys.stdout.write(f"  {ansi}● {label}{_ANSI_RESET}\n")
    sys.stdout.flush()

    for line in message.splitlines():
        if not line.strip():
            continue
        if animate:
            _typewrite_line(line, indent="  ⎿  ", color=color)
        else:
            console.print(f"  [dim]⎿[/dim]  [{color}]{line}[/{color}]")


def agent_log_step(text: str, *, animate: bool = True) -> None:
    """Dim running step with brief spinner then reveal."""
    if not animate:
        log_step(text)
        return

    frames = _SPINNER_FRAMES
    for i, frame in enumerate(frames[:6]):
        sys.stdout.write(f"\r  {_ANSI_COLORS['dim']}{frame}{_ANSI_RESET} {text}")
        sys.stdout.flush()
        time.sleep(0.06)
    sys.stdout.write(f"\r  {_ANSI_COLORS['dim']}→{_ANSI_RESET} {text}\n")
    sys.stdout.flush()


def agent_log_ok(text: str) -> None:
    _typewrite_line(f"✓ {text}", indent="  ", color="green", delay=0.004)


def agent_log_warn(text: str) -> None:
    _typewrite_line(f"! {text}", indent="  ", color="yellow", delay=0.004)


def agent_log_err(text: str) -> None:
    short = text[:160]
    sys.stdout.write(f"  \033[91m✗\033[0m ")
    sys.stdout.flush()
    _typewrite_line(short, indent="", color="white", delay=0.004)


def agent_log_scan(location: str, found: int) -> None:
    """Live scanning line — overwrites in place like Claude Code file search."""
    dim = _ANSI_COLORS["dim"]
    yellow = _ANSI_COLORS.get("yellow", "")
    loc = location[:58]
    line = f"  {dim}⎿{_ANSI_RESET}  {yellow}scanning{_ANSI_RESET} {loc}  {dim}({found} found){_ANSI_RESET}"
    sys.stdout.write(f"\r{line}{' ' * 8}\n")
    sys.stdout.flush()


def agent_log_progress(label: str, current: int, total: int, detail: str = "") -> None:
    """In-place progress line for indexing / loading files."""
    dim = _ANSI_COLORS["dim"]
    cyan = _ANSI_COLORS.get("cyan", "")
    pct = int((current / total) * 100) if total else 0
    bar_w = 16
    filled = int(bar_w * current / total) if total else 0
    bar = "█" * filled + "░" * (bar_w - filled)
    det = f" {detail[:40]}" if detail else ""
    line = (
        f"  {dim}⎿{_ANSI_RESET}  {cyan}{label}{_ANSI_RESET} "
        f"[{bar}] {pct:3d}%  {current}/{total}{dim}{det}{_ANSI_RESET}"
    )
    sys.stdout.write(f"\r{line}{' ' * 6}")
    sys.stdout.flush()
    if current >= total and total:
        sys.stdout.write("\n")
        sys.stdout.flush()



class WgetBar:
    """
    wget-style single-line progress bar for install / update operations.

    Runs the command in a background thread; animates the bar on the
    calling thread.  The bar snaps to 100 % when the process exits.

    Usage:
        bar = WgetBar("discord", color="cyan")
        returncode, output = bar.run(["winget", "install", "--id", "Discord.Discord"])
        if returncode != 0:
            print(output)   # show captured stderr on failure
    """

    _BAR_WIDTH = 40
    _FILL      = "█"
    _EMPTY     = "░"
    _SPEEDS    = [
        "1.2 MB/s", "2.7 MB/s", "3.4 MB/s",
        "1.9 MB/s", "4.1 MB/s", "2.2 MB/s", "3.8 MB/s",
    ]

    def __init__(self, label: str, color: str = "cyan", total_mb: float = 48.0):
        self._label = label[:22]
        self._ansi  = _ANSI_COLORS.get(color, "\033[96m")
        self._total_mb = total_mb

    # ── public ────────────────────────────────────────────────────────────

    def run(self, cmd_list: list) -> tuple[int, str]:
        """Execute cmd_list in a thread; return (returncode, captured_output)."""
        returncode_box: list[int] = [1]
        output_box:     list[str] = [""]

        def _worker() -> None:
            try:
                proc = subprocess.run(
                    cmd_list,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                returncode_box[0] = proc.returncode
                output_box[0]     = proc.stdout + proc.stderr
            except Exception as exc:
                returncode_box[0] = 1
                output_box[0]     = str(exc)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        self._animate(thread, returncode_box)

        return returncode_box[0], output_box[0]

    # ── internals ─────────────────────────────────────────────────────────

    def _animate(self, thread: threading.Thread, returncode_box: list) -> None:
        start = time.time()
        pct   = 0.0
        si    = 0
        first = True

        while thread.is_alive():
            elapsed = time.time() - start
            # Asymptotic curve: fast rise → slows → caps at 95 % until done
            target = min(95.0, 100.0 * (1.0 - 1.0 / (1.0 + elapsed * 0.45)))
            pct   += (target - pct) * 0.35
            self._draw(pct, self._SPEEDS[si % len(self._SPEEDS)], elapsed, overwrite=not first)
            first  = False
            si    += 1
            thread.join(timeout=0.22)   # doubles as sleep

        elapsed = time.time() - start
        # Show green "done" or red "failed" based on real exit code
        status = "done" if returncode_box[0] == 0 else "failed"
        self._draw(100.0, status, elapsed, overwrite=not first)
        sys.stdout.write("\n")
        sys.stdout.flush()

    def _draw(self, pct: float, speed: str, elapsed: float, *, overwrite: bool) -> None:
        filled = int(self._BAR_WIDTH * pct / 100)
        empty  = self._BAR_WIDTH - filled
        bar    = self._FILL * filled + self._EMPTY * empty

        downloaded = self._total_mb * pct / 100.0
        label_col = f"\033[97m{self._label:<22}\033[0m"
        bar_col   = f"\033[2m[\033[0m{self._ansi}{bar}\033[0m\033[2m]\033[0m"
        pct_col   = f"\033[1m{pct:5.1f}%\033[0m"
        mb_col    = f"\033[2m{downloaded:5.1f}/{self._total_mb:.0f} MB\033[0m"
        time_str  = f"{elapsed:.1f}s"

        if speed == "done":
            spd_col = f"\033[32m✔ Complete\033[0m"
        elif speed == "failed":
            spd_col = f"\033[31m✘ Failed\033[0m"
        else:
            spd_col = f"\033[2m{speed:<10}\033[0m"

        line = f"  {label_col} {bar_col} {pct_col}  {mb_col}  {spd_col}  \033[2m({time_str})\033[0m"

        if overwrite:
            sys.stdout.write("\r")
        sys.stdout.write(line)
        sys.stdout.flush()


class AnimatedMenu:
    """
    Arrow-key navigable option list.
    ↑ / ↓ to move, Enter to confirm, Esc / Ctrl-C cancels (returns last option's key).
    Falls back to typed input on non-Windows platforms.
    """

    def __init__(self, options: list[tuple[str, str, str]]):
        self.options = options      # [(key, description, color), ...]
        self.selected = 0
        self._drawn = False

    # total lines the rendered block occupies:
    # 1 blank + N options + 1 blank + 1 hint = N + 3
    @property
    def _block_lines(self) -> int:
        return len(self.options) + 3

    def _render(self) -> None:
        if self._drawn:
            sys.stdout.write(f"\033[{self._block_lines}A\033[J")
            sys.stdout.flush()

        console.print()
        for i, (key, desc, color) in enumerate(self.options):
            if i == self.selected:
                console.print(f"  [bold {color}]❯ [{key}] {desc}[/bold {color}]")
            else:
                console.print(f"    [dim][{key}] {desc}[/dim]")
        console.print()
        console.print("  [dim]↑/↓  navigate    Enter  select[/dim]")
        self._drawn = True

    def run(self, prompt_func=None) -> str:
        self.selected = 0
        self._render()
        try:
            import msvcrt
            return self._run_keys(msvcrt)
        except ImportError:
            return self._run_text(prompt_func)

    # ── keyboard navigation (Windows) ─────────────────────────────────────

    def _run_keys(self, msvcrt) -> str:
        while True:
            ch = msvcrt.getch()
            if ch in (b'\xe0', b'\x00'):        # extended-key prefix
                arrow = msvcrt.getch()
                if arrow == b'H':               # ↑
                    self.selected = (self.selected - 1) % len(self.options)
                    self._render()
                elif arrow == b'P':             # ↓
                    self.selected = (self.selected + 1) % len(self.options)
                    self._render()
            elif ch == b'\r':                   # Enter
                console.print()
                return self.options[self.selected][0]
            elif ch in (b'\x03', b'\x1b'):      # Ctrl-C / Esc → pick last option
                console.print()
                return self.options[-1][0]

    # ── typed fallback (non-Windows) ──────────────────────────────────────

    def _run_text(self, prompt_func) -> str:
        valid = {opt[0] for opt in self.options}
        if prompt_func is None:
            import builtins
            get_input = lambda: builtins.input("  choice → ").strip()
        else:
            get_input = prompt_func

        while True:
            try:
                choice = get_input().strip()
            except (KeyboardInterrupt, EOFError):
                return self.options[-1][0]
            if not choice:
                continue
            if choice in valid:
                return choice
            console.print(f"  [dim]type one of: {', '.join(sorted(valid))}[/dim]")


class MultiSelectMenu:
    """
    Arrow-key + Space multi-select list for update selection.

    ↑ ↓  navigate     Space  toggle selection
    A    select all   Enter  confirm   Esc / Ctrl-C  cancel

    items: list of dicts with keys: name, from, to, source
    Returns list of selected item dicts (empty list = cancelled / none chosen).
    """

    _W_NAME    = 26
    _W_FROM    = 11
    _W_TO      = 11
    _W_SRC     =  7
    _PAGE_SIZE = 14   # max items shown at once — keeps the block short enough to redraw without jumping

    def __init__(self, items: list[dict], color: str = "cyan"):
        self.items    = items
        self.color    = color
        self.cursor   = 0
        self.selected: set[int] = set()
        self._drawn   = False

    @property
    def _block_lines(self) -> int:
        # header + separator + visible items + blank + hint
        return min(len(self.items), self._PAGE_SIZE) + 4

    def _viewport(self) -> tuple[int, int]:
        """Sliding window that keeps the cursor centred in the visible region."""
        n  = len(self.items)
        ps = min(n, self._PAGE_SIZE)
        start = max(0, min(self.cursor - ps // 2, n - ps))
        return start, start + ps

    def _render(self) -> None:
        col   = _ANSI_COLORS.get(self.color, "\033[96m")
        reset = _ANSI_RESET
        dim   = "\033[2m"
        bold  = "\033[1m"
        white = "\033[97m"

        if self._drawn:
            sys.stdout.write(f"\033[{self._block_lines}A\033[J")
            sys.stdout.flush()

        start, end = self._viewport()
        total = len(self.items)
        pos   = f"  {start + 1}-{end}/{total}" if total > self._PAGE_SIZE else ""

        # Header + separator (pure sys.stdout — no Rich, so line count is exact)
        sys.stdout.write(
            f"  {dim}{'App':<{self._W_NAME + 5}} "
            f"{'Current':<{self._W_FROM}}   "
            f"{'Available':<{self._W_TO}} Source{reset}\n"
        )
        sys.stdout.write(f"  {dim}{'─' * 64}{reset}\n")

        for i in range(start, end):
            item      = self.items[i]
            checked   = "✓" if i in self.selected else " "   # ✓ or space
            at_cursor = i == self.cursor
            is_sel    = i in self.selected

            name = item.get("name",   "?")[:self._W_NAME]
            frm  = item.get("from",   "?")[:self._W_FROM]
            to   = item.get("to",     "?")[:self._W_TO]
            src  = item.get("source", "")[:self._W_SRC]

            row = (
                f"[{checked}] {name:<{self._W_NAME}}  "
                f"{frm:<{self._W_FROM}} → {to:<{self._W_TO}} {src}"
            )

            if at_cursor and is_sel:
                sys.stdout.write(f"  {bold}{col}▶ {row}{reset}\n")
            elif at_cursor:
                sys.stdout.write(f"  {col}▶ {row}{reset}\n")
            elif is_sel:
                sys.stdout.write(f"  {bold}{white}  {row}{reset}\n")
            else:
                sys.stdout.write(f"  {dim}  {row}{reset}\n")

        n_sel    = len(self.selected)
        sel_note = f"  ({n_sel} selected)" if n_sel else ""
        sys.stdout.write(
            f"\n  {dim}↑ ↓ move   Space select   A all   "
            f"Enter confirm   Esc cancel{sel_note}{pos}{reset}\n"
        )
        sys.stdout.flush()
        self._drawn = True

    # ── public entry ──────────────────────────────────────────────────────

    def run(self) -> list[dict]:
        self.cursor   = 0
        self.selected = set()
        self._drawn   = False
        self._render()
        try:
            import msvcrt
            return self._run_keys(msvcrt)
        except ImportError:
            return self._run_text()

    # ── keyboard (Windows) ────────────────────────────────────────────────

    def _run_keys(self, msvcrt) -> list[dict]:
        while True:
            ch = msvcrt.getch()
            if ch in (b'\xe0', b'\x00'):
                arrow = msvcrt.getch()
                if arrow == b'H':           # ↑
                    self.cursor = (self.cursor - 1) % len(self.items)
                    self._render()
                elif arrow == b'P':         # ↓
                    self.cursor = (self.cursor + 1) % len(self.items)
                    self._render()
            elif ch == b' ':               # Space — toggle
                if self.cursor in self.selected:
                    self.selected.discard(self.cursor)
                else:
                    self.selected.add(self.cursor)
                self._render()
            elif ch in (b'a', b'A'):       # A — select / deselect all
                if len(self.selected) == len(self.items):
                    self.selected.clear()
                else:
                    self.selected = set(range(len(self.items)))
                self._render()
            elif ch == b'\r':              # Enter — confirm
                linux_terminal_flash()
                sys.stdout.write("\n")
                sys.stdout.flush()
                return [self.items[i] for i in sorted(self.selected)]
            elif ch in (b'\x03', b'\x1b'): # Ctrl-C / Esc — cancel
                sys.stdout.write("\n")
                sys.stdout.flush()
                return []

    # ── typed fallback (non-Windows) ──────────────────────────────────────

    def _run_text(self) -> list[dict]:
        sys.stdout.write("  Enter numbers (e.g. 1,3) or 'all', or Enter to cancel:\n")
        sys.stdout.flush()
        while True:
            try:
                raw = input("  ❯ ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                return []
            if not raw:
                return []
            if raw == "all":
                return list(self.items)
            try:
                idxs = [int(x.strip()) - 1 for x in raw.split(",")]
                return [self.items[i] for i in idxs if 0 <= i < len(self.items)]
            except ValueError:
                sys.stdout.write("  Enter numbers like 1,3 or 'all'\n")
                sys.stdout.flush()
