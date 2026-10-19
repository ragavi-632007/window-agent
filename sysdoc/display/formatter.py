from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from display.banner import get_theme_color

console = Console()

def print_user(text: str) -> None:
    console.print()
    console.print(f"  [bold blue]YOU[/bold blue] [dim]❯[/dim] {text}")

def print_bot_start() -> None:
    theme_col = get_theme_color()
    console.print()
    console.print(f"  [bold {theme_col}]FIXBOT[/bold {theme_col}] [dim]❯[/dim] \033[38;2;56;189;248m\033[1m▌\033[0m ", end="")

def print_ok(text: str) -> None:
    console.print(f"  [bold green]✓[/bold green] {text}")

def print_warn(text: str) -> None:
    console.print(f"  [bold yellow]⚠[/bold yellow] {text}")

def print_err(text: str) -> None:
    lines = text.split(" Run manually: ")
    if len(lines) == 2:
        console.print(f"  [bold red]❌ {lines[0]}[/bold red]")
        console.print(f"     [dim]Run manually: {lines[1]}[/dim]")
    else:
        # Check for fallback or transition patterns in error messages
        sub_lines = text.split(". Switching to ")
        if len(sub_lines) == 2:
            console.print(f"  [bold red]❌ {sub_lines[0]}[/bold red]")
            console.print(f"     [dim]Switching to {sub_lines[1]}[/dim]")
        else:
            console.print(f"  [bold red]❌ {text}[/bold red]")

def print_info(text: str) -> None:
    console.print(f"  [bold blue]ℹ[/bold blue] [dim]{text}[/dim]")

def print_data(key: str, value: str) -> None:
    theme_col = get_theme_color()
    console.print(f"    [bold {theme_col}]✦[/bold {theme_col}] [dim]{key}:[/dim] [white]{value}[/white]")

def print_collecting(module: str) -> None:
    theme_col = get_theme_color()
    console.print(f"  [bold {theme_col}]◉[/bold {theme_col}] Analyzing {module} subsystem...")

def print_section(title: str) -> None:
    from rich.rule import Rule
    theme_col = get_theme_color()
    console.print()
    console.print(Rule(f"[bold {theme_col}]{title.upper()}[/bold {theme_col}]", style=f"dim {theme_col}", align="left"))

def print_agent_supervisor(msg: str) -> None:
    from display.animations import agent_log
    agent_log("supervisor", msg)


def print_agent_planner(plan_summary: str) -> None:
    from display.animations import agent_log
    agent_log("planner", plan_summary)


def print_agent_executor(step_desc: str) -> None:
    from display.animations import agent_log
    agent_log("executor", step_desc)


def print_agent_verifier(result_desc: str) -> None:
    from display.animations import agent_log
    agent_log("verifier", result_desc)


def print_agent_summary(text: str) -> None:
    from display.animations import agent_log
    agent_log("summary", text)



def print_ticket(ticket: dict) -> None:
    from rich.rule import Rule
    priority = str(ticket.get("priority", "LOW")).upper()
    badge_color = "green"
    if priority == "HIGH":
        badge_color = "red"
    elif priority == "MEDIUM":
        badge_color = "yellow"

    status = ticket.get("status", "OPEN")
    ticket_id = ticket.get('id', 'unknown')
    module = ticket.get('module', 'unknown').upper()
    
    theme_col = get_theme_color()
    console.print()
    console.print(Rule(f"[bold {theme_col}]🎫 Ticket [{ticket_id}] — Module: {module}[/bold {theme_col}]", style=f"dim {theme_col}", align="left"))
    console.print(f"    [dim]Status:[/dim]   [bold white]{status}[/bold white]")
    console.print(f"    [dim]Priority:[/dim] [bold {badge_color}]{priority}[/bold {badge_color}]")
    console.print(f"    [dim]Problem:[/dim]  [white]{ticket.get('problem', 'n/a')}[/white]")
    console.print(f"    [dim]Created:[/dim]  [white]{ticket.get('created', 'n/a')}[/white]")
    console.print(Rule(style=f"dim {theme_col}"))



def print_system_scan(all_data: dict) -> None:
    theme_col = get_theme_color()
    table = Table(
        show_header=True,
        header_style=f"bold {theme_col}",
        box=box.SIMPLE_HEAD,
        border_style="dim",
        padding=(0, 2),
    )
    table.add_column("Subsystem", style=f"bold {theme_col}")
    table.add_column("Diagnostic Summary", style="white")

    for module, data in all_data.items():
        summary = _summarize_value(data)
        table.add_row(module.upper(), summary)

    console.print()
    console.print(table)



def _summarize_value(value: object) -> str:
    if isinstance(value, dict):
        items = []
        for key, item in value.items():
            if len(items) >= 6:
                items.append("...")
                break
            items.append(f"{key}={_summarize_value(item)}")
        return ", ".join(items)
    if isinstance(value, list):
        if not value:
            return "[]"
        if isinstance(value[0], dict):
            return ", ".join(str(v.get("name", str(v))) for v in value[:3]) + ("..." if len(value) > 3 else "")
        return ", ".join(str(item) for item in value[:6]) + ("..." if len(value) > 6 else "")
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def print_process_table(procs: list) -> None:
    theme_col = get_theme_color()
    table = Table(show_header=True, header_style=f"bold {theme_col}", box=box.SIMPLE_HEAD, border_style="dim", padding=(0, 2))
    table.add_column("IDX",       style="dim",     width=4,  no_wrap=True)
    table.add_column("PID",     style="yellow",  width=7,  no_wrap=True)
    table.add_column("Process Name",    style="white",   width=36, no_wrap=True)
    table.add_column("CPU %",    style="green",   width=6,  no_wrap=True)
    table.add_column("RAM %",    style="magenta", width=6,  no_wrap=True)
    table.add_column("Files",   style="cyan",    width=6,  no_wrap=True)
    table.add_column("Status",  style="dim",     width=10, no_wrap=True)

    for idx, proc in enumerate(procs, start=1):
        cpu = proc.get("cpu_pct", 0.0)
        cpu_style = "bold red" if cpu > 50 else ("yellow" if cpu > 20 else "green")
        open_files = proc.get("open_files", -1)
        files_str = str(open_files) if open_files >= 0 else "n/a"
        table.add_row(
            str(idx),
            str(proc.get("pid", "?")),
            proc.get("name", "unknown"),
            f"[{cpu_style}]{cpu}[/{cpu_style}]",
            str(proc.get("ram_pct", 0.0)),
            files_str,
            proc.get("status", "?"),
        )

    console.print()
    console.print(f"  [bold {theme_col}]ACTIVE PROCESSES[/bold {theme_col}] [dim]— Ranked by CPU Utilization[/dim]")
    console.print(table)
    console.print(f"  [{theme_col}]❯[/] [dim]kill <pid_or_name>  —  terminate a process by PID or name[/dim]")
    console.print()


def _fmt_size(n) -> str:
    if n is None:
        return "—"
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024:
            return f"{value:.0f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


def print_search_results_table(results: list, query: str) -> None:
    theme_col = get_theme_color()
    if not results:
        console.print(f"\n  [bold yellow]⚠[/bold yellow] [dim]No results found for '{query}'[/dim]\n")
        return

    table = Table(
        show_header=True,
        header_style=f"bold {theme_col}",
        box=box.SIMPLE_HEAD,
        border_style="dim",
        padding=(0, 2),
    )
    table.add_column("#",    style="dim",        width=4,  no_wrap=True)
    table.add_column("Type", style="cyan",        width=9,  no_wrap=True)
    table.add_column("Name", style="bold white",  width=28, no_wrap=True)
    table.add_column("Size", style="yellow",      width=9,  no_wrap=True)
    table.add_column("Path", style="dim",         no_wrap=False)

    _icons = {"folder": "📁", "app": "⚙ ", "file": "📄"}
    for idx, r in enumerate(results, start=1):
        icon = _icons.get(r["type"], "📄")
        table.add_row(
            str(idx),
            f"{icon} {r['type']}",
            r["name"],
            _fmt_size(r.get("size")),
            r["path"],
        )

    console.print()
    console.print(
        f"  [bold {theme_col}]SEARCH RESULTS[/bold {theme_col}] "
        f"[dim]— '{query}' · {len(results)} found[/dim]"
    )
    console.print(table)


def print_file_location_panel(selected: dict, location_desc: str, cmd: str, ps_cmd: str) -> None:
    from rich.rule import Rule
    theme_col = get_theme_color()

    item_type = selected.get("type", "file")
    name      = selected.get("name", "")
    path      = selected.get("path", "")

    type_icon = "📁" if item_type == "folder" else ("⚙ " if item_type == "app" else "📄")

    console.print()
    console.print(Rule(f"[bold {theme_col}]{type_icon} File Details[/bold {theme_col}]", style=f"dim {theme_col}", align="left"))
    console.print(f"    [dim]Name:[/dim]      [bold white]{name}[/bold white]")
    console.print(f"    [dim]Location:[/dim]  [white]{location_desc}[/white]")
    console.print(f"    [dim]Full path:[/dim]")
    console.print(f"       [bold {theme_col}]{path}[/bold {theme_col}]")
    console.print()
    console.print(f"    [dim]🗑  How to delete manually:[/dim]")
    console.print(f"      [dim]CMD Admin:[/dim]   [yellow]{cmd}[/yellow]")
    console.print(f"      [dim]PowerShell:[/dim]  [cyan]{ps_cmd}[/cyan]")
    console.print(Rule(style=f"dim {theme_col}"))



def print_file_ops_menu() -> None:
    theme_col = get_theme_color()
    console.print()
    console.print(f"  [bold {theme_col}]File Operations[/bold {theme_col}]")
    console.print("  [dim]─────────────────[/dim]")
    console.print(f"  [bold {theme_col}]d[/bold {theme_col}] [dim]→[/dim] Delete file or folder")
    console.print(f"  [bold {theme_col}]r[/bold {theme_col}] [dim]→[/dim] Rename file or folder")
    console.print(f"  [bold {theme_col}]c[/bold {theme_col}] [dim]→[/dim] Copy path to clipboard")
    console.print(f"  [bold {theme_col}]n[/bold {theme_col}] [dim]→[/dim] No action / skip")
    console.print()


def print_bg_process_table(procs: list) -> None:
    theme_col = get_theme_color()
    if not procs:
        console.print(f"\n  [bold green]✓[/bold green] [dim]No closeable background apps found.[/dim]\n")
        return

    table = Table(
        show_header=True, header_style=f"bold {theme_col}",
        box=box.SIMPLE_HEAD, border_style="dim", padding=(0, 2),
    )
    table.add_column("#",         style="dim",     width=4,  no_wrap=True)
    table.add_column("App",       style="white",   width=28, no_wrap=True)
    table.add_column("Inst",      style="dim",     width=5,  no_wrap=True)
    table.add_column("RAM MB",    style="magenta", width=9,  no_wrap=True)
    table.add_column("RAM %",     style="cyan",    width=7,  no_wrap=True)
    table.add_column("CPU %",     style="green",   width=7,  no_wrap=True)
    table.add_column("Status",    style="dim",     width=10, no_wrap=True)

    for idx, p in enumerate(procs, start=1):
        ram_mb    = p.get("ram_mb", 0.0)
        instances = p.get("instances", 1)
        windowed  = p.get("windowed", False)
        important = p.get("important", False)
        ram_col   = "bold red" if ram_mb > 500 else ("yellow" if ram_mb > 150 else "magenta")
        status    = "[bold yellow]⚠ open[/bold yellow]" if important else ("[dim]windowed[/dim]" if windowed else "[dim]bg[/dim]")
        inst_str  = f"×{instances}" if instances > 1 else "1"
        table.add_row(
            str(idx),
            p.get("name", "unknown"),
            inst_str,
            f"[{ram_col}]{ram_mb:.0f}[/{ram_col}]",
            str(p.get("ram_pct", 0.0)),
            str(p.get("cpu_pct", 0.0)),
            status,
        )

    total_mb = sum(p.get("ram_mb", 0) for p in procs)
    console.print()
    console.print(
        f"  [bold {theme_col}]BACKGROUND APPS[/bold {theme_col}] "
        f"[dim]— {len(procs)} apps · {total_mb/1024:.2f} GB RAM · "
        f"Inst = instances · ⚠ open = has unsaved data[/dim]"
    )
    console.print(table)
    console.print(
        f"  [dim]Vendor services (Dell, Intel, Realtek) and Windows shell processes "
        f"are hidden — type [bold]restart explorer[/bold] to reset the shell.[/dim]"
    )
    console.print()


def print_browser_tab_table(tabs: list) -> None:
    theme_col = get_theme_color()
    if not tabs:
        console.print(f"\n  [bold yellow]⚠[/bold yellow] [dim]No active browser instances detected.[/dim]\n")
        return

    table = Table(show_header=True, header_style=f"bold {theme_col}", box=box.SIMPLE_HEAD, border_style="dim", padding=(0, 2))
    table.add_column("IDX",        style="dim",     width=4,  no_wrap=True)
    table.add_column("Browser",  style="green",   width=9,  no_wrap=True)
    table.add_column("PID",      style="yellow",  width=7,  no_wrap=True)
    table.add_column("CPU %",     style="magenta", width=6,  no_wrap=True)
    table.add_column("RAM %",     style="cyan",    width=6,  no_wrap=True)
    table.add_column("Page Title",    style="white",   no_wrap=True)

    remote_tabs = any(tab.get("source") == "remote_tab" for tab in tabs)

    for idx, tab in enumerate(tabs, start=1):
        cpu = tab.get("cpu_pct", 0.0)
        cpu_style = "bold red" if cpu > 30 else ("yellow" if cpu > 10 else "magenta")
        table.add_row(
            str(idx),
            tab.get("browser", "?"),
            str(tab.get("pid", "?")),
            f"[{cpu_style}]{cpu}[/{cpu_style}]",
            str(tab.get("ram_pct", 0.0)),
            tab.get("title", ""),
        )

    console.print()
    console.print(f"  [bold {theme_col}]LIVE BROWSER TABS[/bold {theme_col}] [dim]— {len(tabs)} instances found[/dim]")
    console.print(table)
    if remote_tabs:
        console.print(f"  [bold blue]ℹ[/bold blue] [dim]Individual Chrome tabs discovered via remote debugging.[/dim]")
    else:
        console.print(f"  [bold yellow]⚠[/bold yellow] [dim]No remote-debug tabs discovered. Start Chrome with --remote-debugging-port=9222 to isolate tabs.[/dim]")
    console.print(f"  [{theme_col}]❯[/] [dim]kill <pid_or_name_or_index>  —  close a browser tab/window by PID, name, or # index[/dim]")
    console.print()
