import hashlib
import os
import platform
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import psutil

from sysdoc.config import THRESHOLDS


class StorageModule:
    def collect(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "drives": [],
            "critical_drives": [],
            "temp_folder_path": os.environ.get("TEMP", "/tmp"),
            "temp_folder_gb": 0.0,
            "recycle_bin_gb": 0.0,
            "top_large_files": [],
            # Fix #8 — duplicate scan removed from collect(); it is on-demand only
            # (called by executor._fix_storage_duplicates or explicit user request)
            "duplicates_note": "run 'fix duplicates' to scan",
        }

        try:
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                except Exception:
                    continue
                drive_info = {
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "total_gb": round(usage.total / (1024 ** 3), 2),
                    "used_gb": round(usage.used / (1024 ** 3), 2),
                    "free_gb": round(usage.free / (1024 ** 3), 2),
                    "used_pct": round(usage.percent, 1),
                }
                result["drives"].append(drive_info)
                if drive_info["used_pct"] > THRESHOLDS["disk_critical"]:
                    result["critical_drives"].append(drive_info["device"])
        except Exception as error:
            result["error"] = f"drive enumeration failed: {error}"

        try:
            temp_path = Path(result["temp_folder_path"])
            result["temp_folder_gb"] = round(self._directory_size(temp_path) / (1024 ** 3), 2)
        except Exception as error:
            result["error"] = result.get("error", "") + f" temp scan failed: {error}"

        try:
            result["recycle_bin_gb"] = round(self._recycle_bin_size() / (1024 ** 3), 2)
        except Exception as error:
            result["error"] = result.get("error", "") + f" recycle bin scan failed: {error}"

        try:
            result["top_large_files"] = self._find_top_large_files()
        except Exception as error:
            result["error"] = result.get("error", "") + f" large file scan failed: {error}"

        if "error" in result and not result["error"]:
            result.pop("error", None)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _directory_size(self, path: Path) -> int:
        total = 0
        if not path.exists():
            return 0
        for root, _, files in os.walk(path):
            for name in files:
                try:
                    fp = Path(root) / name
                    if fp.is_file():
                        total += fp.stat().st_size
                except Exception:
                    continue
        return total

    def _recycle_bin_size(self) -> int:
        if platform.system().lower() != "windows":
            return 0
        try:
            import winshell
            total = 0
            for item in winshell.recycle_bin():
                try:
                    total += item.size
                except Exception:
                    continue
            return total
        except Exception:
            recycle_path = Path(os.environ.get("SystemDrive", "C:") + "\\$Recycle.Bin")
            return self._directory_size(recycle_path)

    def _candidate_dirs(self) -> List[Path]:
        home = Path.home()
        candidates = [home / "Downloads", home / "Documents"]
        return [p for p in candidates if p.exists()]

    def _find_top_large_files(self) -> List[Dict[str, Any]]:
        files: List[Dict[str, Any]] = []
        for directory in self._candidate_dirs():
            for root, _, names in os.walk(directory):
                for name in names:
                    try:
                        fp = Path(root) / name
                        if not fp.is_file():
                            continue
                        files.append({
                            "name": name,
                            "path": str(fp),
                            "size_mb": round(fp.stat().st_size / (1024 ** 2), 2),
                        })
                    except Exception:
                        continue
        files.sort(key=lambda item: item["size_mb"], reverse=True)
        return files[:10]

    def _duplicate_waste_size(self, paths: List[str]) -> int:
        if len(paths) < 2:
            return 0
        try:
            sizes = [Path(p).stat().st_size for p in paths if Path(p).is_file()]
            return sum(sizes[1:])
        except Exception:
            return 0

    def find_duplicates(self, scan_dirs: List[str]) -> Dict[str, List[str]]:
        groups: Dict[str, List[str]] = {}
        for scan_dir in scan_dirs:
            root_path = Path(scan_dir)
            if not root_path.exists():
                continue
            for root, _, names in os.walk(root_path):
                for name in names:
                    fp = Path(root) / name
                    try:
                        if not fp.is_file():
                            continue
                        size = fp.stat().st_size
                        if size > 500 * 1024 * 1024:
                            continue
                        file_hash = self._md5(fp)
                        if not file_hash:
                            continue
                        groups.setdefault(file_hash, []).append(str(fp))
                    except Exception:
                        continue
        return {h: paths for h, paths in groups.items() if len(paths) > 1}

    def _md5(self, file_path: Path) -> str:
        digest = hashlib.md5()
        try:
            with file_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(8192), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Fix actions
    # ------------------------------------------------------------------

    @staticmethod
    def _schedule_delete_reboot(path: str) -> bool:
        """Schedule a locked file for deletion on next Windows boot (MoveFileEx API)."""
        try:
            import ctypes
            return bool(ctypes.windll.kernel32.MoveFileExW(path, None, 0x4))
        except Exception:
            return False

    @staticmethod
    def _running_browsers() -> List[str]:
        _browser_exe = {
            "chrome.exe": "Chrome", "msedge.exe": "Edge",
            "firefox.exe": "Firefox", "brave.exe": "Brave",
            "opera.exe": "Opera",
        }
        found: set = set()
        for proc in psutil.process_iter(["name"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name in _browser_exe:
                    found.add(_browser_exe[name])
            except Exception:
                pass
        return sorted(found)

    def fix_temp(self, on_delete=None) -> str:
        temp_path = Path(os.environ.get("TEMP", "/tmp"))
        if not temp_path.exists():
            return "Temp folder not found"
        deleted = scheduled = skipped = 0
        for root, dirs, names in os.walk(temp_path, topdown=False):
            for name in names:
                fp = os.path.join(root, name)
                try:
                    os.unlink(fp)
                    deleted += 1
                    if on_delete:
                        on_delete(name)
                except PermissionError:
                    # File locked — schedule for deletion on next reboot
                    if self._schedule_delete_reboot(fp):
                        scheduled += 1
                    else:
                        skipped += 1
                except Exception:
                    skipped += 1
            for d in dirs:
                try:
                    os.rmdir(os.path.join(root, d))
                except Exception:
                    pass
        parts = [f"{deleted} deleted"]
        if scheduled:
            parts.append(f"{scheduled} scheduled for next reboot")
        if skipped:
            parts.append(f"{skipped} skipped")
        return f"Temp cleaned: {', '.join(parts)}"

    def get_cache_sizes(self) -> Dict[str, float]:
        """Return estimated GB for each cache category without deleting anything."""
        local   = os.environ.get("LOCALAPPDATA", "")
        appdata = os.environ.get("APPDATA", "")
        sizes: Dict[str, float] = {}

        # User temp
        sizes["temp_gb"] = round(self._directory_size(Path(os.environ.get("TEMP", ""))) / (1024**3), 2)

        # Recycle Bin
        try:
            sizes["recycle_gb"] = round(self._recycle_bin_size() / (1024**3), 2)
        except Exception:
            sizes["recycle_gb"] = 0.0

        # Browser cache
        browser_bytes = 0
        _browser_roots = [
            Path(local) / "Google" / "Chrome" / "User Data",
            Path(local) / "Microsoft" / "Edge" / "User Data",
            Path(local) / "BraveSoftware" / "Brave-Browser" / "User Data",
            Path(local) / "Mozilla" / "Firefox" / "Profiles",
        ]
        _browser_cache_dirs = {"Cache", "Code Cache", "GPUCache", "cache2", "cache2\\entries"}
        for base in _browser_roots:
            if not base.exists():
                continue
            try:
                for profile in base.iterdir():
                    for cname in _browser_cache_dirs:
                        cp = profile / cname
                        if cp.is_dir():
                            browser_bytes += self._directory_size(cp)
            except Exception:
                pass
        sizes["browser_gb"] = round(browser_bytes / (1024**3), 2)

        # System cache (Windows Temp, Prefetch, WER, thumbnails)
        sys_bytes = 0
        _sys_paths = [
            Path("C:\\Windows\\Temp"),
            Path("C:\\Windows\\Prefetch"),
            Path(local) / "Microsoft" / "Windows" / "Explorer",
            Path(local) / "Microsoft" / "Windows" / "WER",
        ]
        for sp in _sys_paths:
            if sp.exists():
                sys_bytes += self._directory_size(sp)
        sizes["system_gb"] = round(sys_bytes / (1024**3), 2)

        return sizes

    def fix_browser_cache(self, on_delete=None) -> str:
        running = self._running_browsers()
        if running:
            return (
                f"Browser cache skipped — {', '.join(running)} is open and locking cache files. "
                f"Close your browser, then run 'clear cache' again to free this space."
            )

        local = os.environ.get("LOCALAPPDATA", "")
        deleted = scheduled = skipped = 0

        # Cache_Data is the actual file store inside the Cache directory (Chrome 86+)
        browser_roots = [
            (Path(local) / "Google"        / "Chrome"        / "User Data",
             {"Cache", "Cache\\Cache_Data", "Code Cache", "GPUCache", "Media Cache"}),
            (Path(local) / "Microsoft"     / "Edge"          / "User Data",
             {"Cache", "Cache\\Cache_Data", "Code Cache", "GPUCache"}),
            (Path(local) / "BraveSoftware" / "Brave-Browser" / "User Data",
             {"Cache", "Cache\\Cache_Data", "Code Cache"}),
            (Path(local) / "Mozilla"       / "Firefox"       / "Profiles",
             {"cache2", "cache2\\entries", "startupCache"}),
        ]

        for base, cache_names in browser_roots:
            if not base.exists():
                continue
            try:
                for profile in base.iterdir():
                    if not profile.is_dir():
                        continue
                    for cname in cache_names:
                        cache_dir = profile / cname
                        if not cache_dir.is_dir():
                            continue
                        for root, _, names in os.walk(cache_dir, topdown=False):
                            for name in names:
                                fp = os.path.join(root, name)
                                try:
                                    os.unlink(fp)
                                    deleted += 1
                                    if on_delete:
                                        on_delete(name)
                                except PermissionError:
                                    if self._schedule_delete_reboot(fp):
                                        scheduled += 1
                                    else:
                                        skipped += 1
                                except Exception:
                                    skipped += 1
            except Exception:
                pass

        parts = [f"{deleted} files cleared"]
        if scheduled:
            parts.append(f"{scheduled} scheduled for reboot")
        if skipped:
            parts.append(f"{skipped} skipped")
        return f"Browser cache: {', '.join(parts)}"

    def fix_system_cache(self, on_delete=None) -> str:
        local   = os.environ.get("LOCALAPPDATA", "")
        deleted = 0
        skipped = 0

        # Windows Temp (system-wide, different from user %TEMP%)
        win_temp = Path("C:\\Windows\\Temp")
        if win_temp.exists():
            for root, _, names in os.walk(win_temp, topdown=False):
                for name in names:
                    try:
                        os.unlink(os.path.join(root, name))
                        deleted += 1
                        if on_delete:
                            on_delete(name)
                    except Exception:
                        skipped += 1

        # Prefetch files
        prefetch = Path("C:\\Windows\\Prefetch")
        if prefetch.exists():
            for fp in prefetch.glob("*.pf"):
                try:
                    fp.unlink()
                    deleted += 1
                    if on_delete:
                        on_delete(fp.name)
                except Exception:
                    skipped += 1

        # Thumbnail cache
        thumb_dir = Path(local) / "Microsoft" / "Windows" / "Explorer"
        if thumb_dir.exists():
            for fp in thumb_dir.glob("thumbcache_*.db"):
                try:
                    fp.unlink()
                    deleted += 1
                    if on_delete:
                        on_delete(fp.name)
                except Exception:
                    skipped += 1

        # Windows Error Reports
        wer_dir = Path(local) / "Microsoft" / "Windows" / "WER"
        if wer_dir.exists():
            for root, _, names in os.walk(wer_dir, topdown=False):
                for name in names:
                    try:
                        os.unlink(os.path.join(root, name))
                        deleted += 1
                        if on_delete:
                            on_delete(name)
                    except Exception:
                        skipped += 1

        # Flush DNS cache silently
        try:
            import subprocess as _sp
            _sp.run(["ipconfig", "/flushdns"], capture_output=True, timeout=10)
        except Exception:
            pass

        return f"System cache cleared: {deleted} files ({skipped} skipped)"

    def fix_recycle_bin(self) -> str:
        if platform.system().lower() != "windows":
            return "Recycle bin fix not supported on this platform"
        try:
            import winshell
            winshell.recycle_bin().empty(confirm=False, show_progress=False, sound=False)
            return "Recycle Bin emptied"
        except Exception:
            try:
                import ctypes
                # SHEmptyRecycleBin flags: no confirm dialog, no progress UI, no sound
                SHERB_NOCONFIRMATION = 0x00000001
                SHERB_NOPROGRESSUI   = 0x00000002
                SHERB_NOSOUND        = 0x00000004
                flags = SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
                ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
                return "Recycle Bin emptied"
            except Exception as error:
                return f"Recycle Bin cleanup failed: {error}"

    def fix_delete_duplicates(self, duplicates_dict: Dict[str, List[str]]) -> str:
        # Fix #24 — move to Recycle Bin instead of permanent delete
        try:
            import send2trash
            _trash = send2trash.send2trash
        except ImportError:
            try:
                import winshell as _ws
                def _trash(path: str) -> None:
                    _ws.delete_file(path, no_confirm=True, allow_undo=True)
            except ImportError:
                _trash = None

        deleted = 0
        groups = 0
        for paths in duplicates_dict.values():
            if len(paths) < 2:
                continue
            groups += 1
            for duplicate_path in sorted(paths)[1:]:
                try:
                    if _trash is not None:
                        _trash(duplicate_path)
                    else:
                        Path(duplicate_path).unlink()
                    deleted += 1
                except Exception:
                    continue

        action = "Moved to Recycle Bin" if _trash is not None else "Deleted"
        return f"{action}: {deleted} duplicate files across {groups} groups"

    def _get_adjacent_to_c(self) -> set:
        """Return drive letters of partitions immediately after C: on the same disk."""
        try:
            import json
            cmd = (
                "Get-Partition | Select-Object DriveLetter,DiskNumber,Offset,Size | "
                "Sort-Object DiskNumber,Offset | ConvertTo-Json -Compress"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True, text=True, shell=False, timeout=30,
            )
            raw = r.stdout.strip()
            if not raw:
                return set()
            data = json.loads(raw)
            if isinstance(data, dict):
                data = [data]

            c_part = next(
                (p for p in data if p.get("DriveLetter") and str(p["DriveLetter"]).upper() == "C"),
                None,
            )
            if not c_part:
                return set()

            c_disk = c_part["DiskNumber"]
            c_end  = int(c_part["Offset"]) + int(c_part["Size"])

            same_disk = sorted(
                [p for p in data if p.get("DiskNumber") == c_disk],
                key=lambda p: int(p.get("Offset", 0)),
            )

            # Only the first partition that starts right after C: (within 5 MiB alignment gap)
            for p in same_disk:
                if int(p.get("Offset", 0)) <= int(c_part["Offset"]):
                    continue
                letter = str(p.get("DriveLetter") or "").strip().upper()
                if not letter or letter == "C":
                    continue
                gap = int(p["Offset"]) - c_end
                if gap < 5 * 1024 * 1024:
                    return {letter}
                break  # next partition exists but isn't adjacent
        except Exception:
            pass
        return set()

    def partition_wizard(self, os_data: Dict[str, Any]) -> str:
        if platform.system().lower() != "windows":
            return "Partition wizard only supported on Windows"

        from prompt_toolkit import prompt as tk_prompt
        from prompt_toolkit.styles import Style
        from rich.console import Console
        from rich.table import Table

        console = Console()
        style = Style.from_dict({"prompt": "#00c6ff bold"})

        adjacent_letters = self._get_adjacent_to_c()

        # Build drive list excluding C:
        drives = [
            d for d in psutil.disk_partitions(all=False)
            if not d.device.upper().startswith("C:")
        ]
        if not drives:
            return "No other drives found to take space from."

        # Show numbered table with max takeable space
        table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
        table.add_column("#",              style="bold white")
        table.add_column("Drive",          style="bold white")
        table.add_column("Free GB",        justify="right")
        table.add_column("Total GB",       justify="right")
        table.add_column("Max you can take", justify="right", style="green")
        table.add_column("Extend C:",      justify="center")

        valid_drives = []
        for d in drives:
            try:
                usage = psutil.disk_usage(d.mountpoint)
                free_gb  = usage.free  / (1024 ** 3)
                total_gb = usage.total / (1024 ** 3)
                max_take = free_gb * 0.7
                letter   = d.device.strip().rstrip(":\\").upper()
                can_extend = "[bold green]Yes[/bold green]" if letter in adjacent_letters else "[dim]Maybe*[/dim]"
                valid_drives.append((d, free_gb, max_take))
                table.add_row(
                    str(len(valid_drives)),
                    d.device,
                    f"{free_gb:.1f}",
                    f"{total_gb:.1f}",
                    f"{max_take:.1f} GB",
                    can_extend,
                )
            except Exception:
                continue

        if not valid_drives:
            return "Could not read drive info."

        console.print()
        console.print("  [bold cyan]Select a drive to take space from and add to C:[/bold cyan]")
        console.print()
        console.print(table)
        console.print()
        console.print("  [dim]* Maybe = not directly adjacent to C: on disk. If extend fails, use MiniTool Partition Wizard (free).[/dim]")
        console.print()

        try:
            choice_raw = tk_prompt("  ❯ Enter drive number: ", style=style).strip()
            choice = int(choice_raw) - 1
            if not (0 <= choice < len(valid_drives)):
                return "Invalid selection."
        except (KeyboardInterrupt, EOFError):
            return "Partition wizard cancelled."
        except ValueError:
            return "Please enter a valid number."

        selected_drive, free_gb, max_take = valid_drives[choice]
        drive_letter = selected_drive.device.rstrip("\\")

        drv_display = selected_drive.device.rstrip("\\")
        console.print()
        console.print(f"  Drive selected : [bold]{drv_display}[/bold]")
        console.print(f"  Free space     : [bold]{free_gb:.1f} GB[/bold]")
        console.print(f"  Max takeable   : [bold green]{max_take:.1f} GB[/bold green]  (70% of free)")
        console.print()

        try:
            raw = tk_prompt(
                f"  > How many GB to take from {drv_display} and add to C:? ",
                style=style,
            ).strip()
            import re as _re
            num_match = _re.match(r"[\d.]+", raw)
            if not num_match:
                return "Please enter a number (e.g. 15 or 15.5)."
            amount_gb = float(num_match.group())
        except (KeyboardInterrupt, EOFError):
            return "Partition wizard cancelled."

        if amount_gb < 1:
            return "Minimum is 1 GB."
        if amount_gb > max_take:
            return f"Maximum you can take is {max_take:.1f} GB."

        shrink_mb      = int(amount_gb * 1024)
        source_volume  = self._get_volume_number(drive_letter)
        c_volume       = self._get_volume_number("C:")

        if source_volume is None:
            return f"Cannot find volume number for {selected_drive.device}."
        if c_volume is None:
            return "Cannot find C: volume number."

        # Single diskpart script: shrink source → extend C:
        script_content = (
            f"select volume {source_volume}\n"
            f"shrink desired={shrink_mb}\n"
            f"select volume {c_volume}\n"
            f"extend size={shrink_mb}\n"
        )
        script_path = Path(tempfile.gettempdir()) / "sysdoc_partition.txt"
        script_path.write_text(script_content, encoding="utf-8")

        console.print()
        console.print("  [bold]Plan:[/bold]")
        console.print(f"  Take [bold green]{amount_gb:.0f} GB[/bold green] from [bold]{drv_display}[/bold] -> Add to [bold]C:[/bold]\\")
        console.print()
        console.print("  [dim]diskpart script:[/dim]")
        for line in script_content.strip().splitlines():
            console.print(f"    [yellow]{line}[/yellow]")
        console.print()

        try:
            confirm = tk_prompt("  ❯ Apply? [y/n]: ", style=style).strip().lower()
        except (KeyboardInterrupt, EOFError):
            return "Partition wizard cancelled."

        if confirm != "y":
            return "Partition wizard cancelled."

        import threading as _th
        import time as _time
        from rich.live import Live
        from rich.text import Text

        _done   = _th.Event()
        _result = [None]

        def _run_diskpart() -> None:
            try:
                r = subprocess.run(
                    ["diskpart", "/s", str(script_path)],
                    capture_output=True, text=True, shell=False, timeout=180,
                )
                _result[0] = r
            except Exception as exc:
                _result[0] = exc
            finally:
                _done.set()

        _th.Thread(target=_run_diskpart, daemon=True).start()

        # --- transfer animation ---
        src   = selected_drive.device.rstrip("\\")
        gb    = f"{amount_gb:.0f} GB"
        slots = 8
        pos   = 0

        console.print()
        with Live(console=console, refresh_per_second=12) as live:
            while not _done.is_set():
                dots = ["."] * slots
                dots[pos % slots] = "*"
                stream = "  ".join(dots)
                live.update(Text.from_markup(
                    f"  [bold white]{src}[/bold white]"
                    f"  [cyan]{stream}[/cyan]"
                    f"  [bold white]C:[/bold white]\\"
                    f"   [dim]Transferring {gb}...[/dim]"
                ))
                pos += 1
                _time.sleep(0.08)

            # Final state while we read the result
            live.update(Text.from_markup(
                f"  [bold white]{src}[/bold white]"
                f"  [bold green]{'=' * slots}>[/bold green]"
                f"  [bold white]C:[/bold white]\\"
                f"   [dim]Finalising...[/dim]"
            ))

        console.print()

        obj = _result[0]
        if isinstance(obj, Exception):
            return f"DiskPart execution failed: {obj}"
        if obj is None:
            return "DiskPart did not return a result."

        output    = obj.stdout + obj.stderr
        shrink_ok = "successfully" in output.lower()
        extend_ok = shrink_ok and output.lower().count("successfully") >= 2

        if extend_ok:
            new_data   = self.collect()
            c_info     = next((d for d in new_data["drives"] if d["device"].upper().startswith("C:")), None)
            free_after = f"{c_info['free_gb']:.1f} GB free" if c_info else ""
            return f"Done! C:\\ extended by {amount_gb:.0f} GB.  {free_after}"

        if shrink_ok:
            console.print()
            console.print(f"  [green][OK][/green] {drv_display} shrunk by {amount_gb:.0f} GB — unallocated space is ready.")
            console.print("  [yellow][!][/yellow] C: extend needs a partition tool. Trying to launch one now...")
            console.print()
            launched, tool_name = self._launch_partition_tool(console)
            if launched:
                console.print(f"  [green][OK][/green] {tool_name} opened.")
                console.print()
                console.print("  [bold]Steps inside the tool:[/bold]")
                console.print("    1. Right-click [bold]C:[/bold] partition")
                console.print("    2. Click [bold]Extend Partition[/bold]")
                console.print(f"    3. Take Free Space From → select [bold]{drv_display}[/bold]")
                console.print(f"    4. Set amount to [bold]{amount_gb:.0f} GB[/bold]")
                console.print("    5. Click [bold]OK[/bold] → [bold]Apply[/bold] → [bold]Restart Now[/bold]")
                console.print()
                return (
                    f"{drv_display} shrunk by {amount_gb:.0f} GB.\n"
                    f"{tool_name} opened — right-click C: → Extend Partition → take from {drv_display} → Apply → Restart."
                )
            console.print("  [yellow][!][/yellow] No partition tool found. Install one of these (free):")
            console.print("    • AOMEI Partition Assistant : aomeitech.com/aomei-partition-assistant.html")
            console.print("    • MiniTool Partition Wizard : partitionwizard.com/free-partition-manager.html")
            console.print()
            console.print("  [bold]Then:[/bold] right-click C: → Extend Partition → take from D: → Apply → Restart.")
            return (
                f"{drv_display} shrunk by {amount_gb:.0f} GB.\n"
                f"No partition tool found. Install AOMEI Partition Assistant (free) then:\n"
                f"  Right-click C: → Extend Partition → take {amount_gb:.0f} GB from {drv_display} → Apply → Restart."
            )

        return f"DiskPart failed:\n{output.strip()[:500]}"

    def _launch_partition_tool(self, console: Any):
        """Try to launch any installed partition tool. Returns (launched: bool, tool_name: str)."""
        import glob as _glob

        candidates = [
            (
                "AOMEI Partition Assistant",
                [
                    r"C:\Program Files\AOMEI Partition Assistant*\PartAssist.exe",
                    r"C:\Program Files (x86)\AOMEI Partition Assistant*\PartAssist.exe",
                ],
                "PartAssist",
            ),
            (
                "MiniTool Partition Wizard",
                [
                    r"C:\Program Files\MiniTool Partition Wizard*\partitionwizard.exe",
                    r"C:\Program Files (x86)\MiniTool Partition Wizard*\partitionwizard.exe",
                ],
                "partitionwizard",
            ),
            (
                "EaseUS Partition Master",
                [
                    r"C:\Program Files\EaseUS\EaseUS Partition Master*\EaseUS Partition Master.exe",
                    r"C:\Program Files (x86)\EaseUS\EaseUS Partition Master*\EaseUS Partition Master.exe",
                ],
                "EaseUS Partition Master",
            ),
        ]

        for tool_name, patterns, where_cmd in candidates:
            for pattern in patterns:
                for exe in _glob.glob(pattern):
                    if Path(exe).is_file():
                        try:
                            subprocess.Popen([exe])
                            return True, tool_name
                        except Exception:
                            continue
            try:
                r = subprocess.run(
                    ["where", where_cmd],
                    capture_output=True, text=True, timeout=5,
                )
                exe = r.stdout.strip().splitlines()[0].strip()
                if exe and Path(exe).is_file():
                    subprocess.Popen([exe])
                    return True, tool_name
            except Exception:
                continue

        return False, ""

    def _get_volume_number(self, drive_letter: str) -> Any:
        script_path = Path(tempfile.gettempdir()) / "sysdoc_volume_lookup.txt"
        script_path.write_text("list volume\n", encoding="utf-8")
        result = subprocess.run(
            ["diskpart", "/s", str(script_path)],
            capture_output=True,
            text=True,
            shell=False,
        )
        output = result.stdout + result.stderr
        # Normalise: "C:", "C:\", "C" → just "C"
        letter = drive_letter.strip().rstrip(":\\").upper()
        for line in output.splitlines():
            upper = line.upper()
            # diskpart prints: "  Volume N     C  Label  NTFS ..."
            # Match the letter surrounded by spaces to avoid false hits
            if "VOLUME" in upper and f" {letter} " in upper:
                for part in line.split():
                    if part.isdigit():
                        return int(part)
        return None
