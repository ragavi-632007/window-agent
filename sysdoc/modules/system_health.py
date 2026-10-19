import json
import platform
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Tuple, Union

import psutil

import os as _os

# Processes that must never be shown or killed — Windows shell, services, security
_SYSTEM_PROCS = {
    # NT kernel / core
    "system", "registry", "idle", "system idle process", "memcompression",
    "ntoskrnl.exe", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
    # Core services
    "services.exe", "lsass.exe", "lsm.exe", "spoolsv.exe", "svchost.exe",
    # Windows shell
    "explorer.exe", "dwm.exe", "sihost.exe", "taskhostw.exe",
    "runtimebroker.exe", "shellexperiencehost.exe",
    # Windows UI host processes
    "startmenuexperiencehost.exe", "searchhost.exe", "textinputhost.exe",
    "phoneexperiencehost.exe", "lockapp.exe", "applicationframehost.exe",
    "settingssynchost.exe", "fontdrvhost.exe", "conhost.exe",
    # Search / indexing
    "searchindexer.exe", "searchprotocolhost.exe", "searchfilterhost.exe",
    # Audio / input
    "audiodg.exe", "ctfmon.exe",
    # Windows Update / store
    "wuauclt.exe", "usocoreworker.exe", "wuapihost.exe", "wuauclt.exe",
    "tiworker.exe", "waasmedicagent.exe",
    # Security / Defender
    "msmpeng.exe", "mssense.exe", "nissrv.exe", "securityhealthservice.exe",
    "securityhealthsystray.exe", "securityhealthhost.exe",
    # Error reporting
    "wermgr.exe", "werfault.exe", "werfaultsecure.exe",
    # DLL / COM infrastructure
    "dllhost.exe", "msiexec.exe",
    # Task manager / fixbot itself
    "taskmgr.exe",
    # WebView2 (embedded in many system apps)
    "msedgewebview2.exe",
    # Terminal / Python (the fixbot host)
    "python.exe", "pythonw.exe", "cmd.exe", "powershell.exe",
    "windowsterminal.exe", "wt.exe",
}

# Apps that need an extra ⚠ warning before killing
_IMPORTANT_APPS = {
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
    "teams.exe", "slack.exe",
    "outlook.exe", "winword.exe", "excel.exe", "powerpnt.exe",
    "code.exe", "devenv.exe", "idea64.exe", "pycharm64.exe",
    "onedrive.exe",
}


class SystemHealthModule:
    def __init__(self) -> None:
        self.last_tabs: List[Dict[str, Any]] = []

    def collect(self) -> Dict[str, Any]:
        cpu_percent = psutil.cpu_percent(interval=1)
        virtual = psutil.virtual_memory()
        return {
            "cpu_percent": float(cpu_percent),
            "cpu_count": psutil.cpu_count() or 0,
            "cpu_temp_c": self._get_cpu_temp(),
            "ram_used_pct": float(virtual.percent),
            "ram_used_gb": round(virtual.used / 1e9, 2),
            "ram_total_gb": round(virtual.total / 1e9, 2),
            "top_ram_processes": self._top_ram_processes(),
            "gpu": self._get_gpu_info(),
            "fan_speeds": self._get_fan_speeds(),
            "uptime_str": self._format_uptime(),
            "recent_crashes": self._get_crash_events(),
            "browser_tabs": self.list_browser_tabs(),
        }

    def _get_gpu_info(self) -> Union[List[Dict[str, Any]], str]:
        try:
            import GPUtil  # type: ignore
            gpus = GPUtil.getGPUs()
            if gpus:
                return [
                    {
                        "name": g.name,
                        "load_pct": round(g.load * 100, 1),
                        "mem_used_pct": round(g.memoryUtil * 100, 1),
                        "temp_c": g.temperature,
                    }
                    for g in gpus
                ]
        except ImportError:
            pass
        except Exception:
            pass

        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                gpus = []
                for line in result.stdout.strip().splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 5:
                        mem_used = float(parts[2])
                        mem_total = float(parts[3])
                        gpus.append(
                            {
                                "name": parts[0],
                                "load_pct": float(parts[1]),
                                "mem_used_pct": round(mem_used / mem_total * 100, 1) if mem_total > 0 else 0.0,
                                "temp_c": float(parts[4]),
                            }
                        )
                if gpus:
                    return gpus
        except Exception:
            pass

        return "no GPU detected"

    def _get_cpu_temp(self) -> Union[float, str]:
        if platform.system().lower() != "windows":
            return "unavailable — platform not supported"
        try:
            import wmi
        except ImportError:
            return "unavailable — install OpenHardwareMonitor"

        try:
            client = wmi.WMI(namespace=r"root\OpenHardwareMonitor")
            sensors = client.Sensor()
            temps = [float(sensor.Value) for sensor in sensors if getattr(sensor, "SensorType", "") == "Temperature"]
            if not temps:
                return "unavailable — install OpenHardwareMonitor"
            return round(min(temps), 1) if temps else "unavailable — install OpenHardwareMonitor"
        except Exception:
            return "unavailable — install OpenHardwareMonitor"

    def _top_ram_processes(self) -> List[Dict[str, Any]]:
        processes: List[Dict[str, Any]] = []
        for proc in psutil.process_iter(["name", "pid", "memory_info", "memory_percent"]):
            try:
                info = proc.info
                mem_info = info.get("memory_info")
                if not mem_info:
                    continue
                processes.append(
                    {
                        "name": info.get("name") or "unknown",
                        "pid": info.get("pid"),
                        "ram_gb": round(mem_info.rss / 1e9, 2),
                        "pct": round(float(info.get("memory_percent", 0.0)), 1),
                    }
                )
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except Exception:
                continue
        processes.sort(key=lambda item: item["ram_gb"], reverse=True)
        return processes[:5]

    def _get_fan_speeds(self) -> Union[List[Dict[str, Union[str, float]]], str]:
        if platform.system().lower() != "windows":
            return "unavailable"
        try:
            import wmi
        except ImportError:
            return "unavailable"

        try:
            client = wmi.WMI(namespace=r"root\OpenHardwareMonitor")
            sensors = client.Sensor()
            fans: List[Dict[str, Union[str, float]]] = []
            for sensor in sensors:
                if getattr(sensor, "SensorType", "") == "Fan":
                    fans.append({
                        "name": getattr(sensor, "Name", "unknown"),
                        "speed_rpm": float(getattr(sensor, "Value", 0.0)),
                    })
            return fans if fans else "unavailable"
        except Exception:
            return "unavailable"

    def _format_uptime(self) -> str:
        boot = psutil.boot_time()
        now = time.time()
        uptime_seconds = int(now - boot)
        days, remainder = divmod(uptime_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{days}d {hours}h {minutes}m"

    def _get_crash_events(self) -> List[str]:
        if platform.system().lower() != "windows":
            return ["Event log unavailable on this OS"]
        try:
            command = [
                "wevtutil",
                "qe",
                "System",
                "/q:*[System[EventID=41]]",
                "/c:5",
                "/f:text",
            ]
            result = subprocess.run(command, capture_output=True, text=True)
            output = result.stdout or result.stderr
            lines = []
            for line in output.splitlines():
                if any(token in line for token in ["Date", "Description", "Event ID"]):
                    lines.append(line.strip())
                if len(lines) >= 6:
                    break
            return lines if lines else ["No recent crashes found"]
        except Exception:
            return ["No recent crashes found"]

    def _get_browser_debug_ports(self) -> List[int]:
        ports = []
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name in {"chrome.exe", "msedge.exe", "brave.exe", "opera.exe", "vivaldi.exe", "arc.exe"}:
                    for arg in proc.info.get("cmdline", []):
                        if "--remote-debugging-port=" in arg:
                            parts = arg.split("=", 1)
                            if len(parts) == 2 and parts[1].isdigit():
                                ports.append(int(parts[1]))
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except Exception:
                continue
        ports.append(9222)
        return list(dict.fromkeys(ports))

    def _fetch_chrome_devtools_tabs(self, port: int, filter_lower: str = "") -> List[Dict[str, Any]]:
        try:
            url = f"http://127.0.0.1:{port}/json/list"
            with urllib.request.urlopen(url, timeout=1) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, ValueError, Exception):
            return []

        tabs: List[Dict[str, Any]] = []
        for page in data:
            if page.get("type") != "page":
                continue
            title = page.get("title") or page.get("url") or "Chrome tab"
            if filter_lower:
                title_lower = title.lower()
                if filter_lower not in title_lower and filter_lower not in (page.get("url", "").lower()):
                    continue
            tab_id = page.get("id")
            if not tab_id:
                ws = page.get("webSocketDebuggerUrl", "")
                if "/" in ws:
                    tab_id = ws.rsplit("/", 1)[-1]
            if not tab_id:
                continue
            tabs.append(
                {
                    "browser": "Chrome Tab",
                    "pid": page.get("pid") or 0,
                    "cpu_pct": 0.0,
                    "ram_pct": 0.0,
                    "title": title[:80],
                    "hwnd": None,
                    "remote_debug_port": port,
                    "remote_debug_id": tab_id,
                    "source": "remote_tab",
                }
            )
        return tabs

    def _close_remote_tab(self, port: int, tab_id: str) -> bool:
        try:
            url = f"http://127.0.0.1:{port}/json/close/{tab_id}"
            with urllib.request.urlopen(url, timeout=1) as response:
                result = response.read().decode("utf-8")
            return "closed" in result.lower() or response.status == 200
        except Exception:
            return False

    def fix_kill_processes(self) -> str:
        candidates: List[Any] = []
        for proc in psutil.process_iter(["name", "pid", "memory_percent"]):
            try:
                info = proc.info
                candidates.append((proc, float(info.get("memory_percent", 0.0))))
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue

        candidates.sort(key=lambda item: item[1], reverse=True)
        killed: List[str] = []
        for proc, percent in candidates[:3]:
            if percent > 5.0:
                try:
                    proc.kill()
                    killed.append(proc.name())
                except Exception:
                    continue
        return f"Killed processes: {', '.join(killed)}" if killed else "No high-memory processes killed"

    def fix_power_balanced(self) -> str:
        if platform.system().lower() != "windows":
            return "Power plan fix only supported on Windows"
        try:
            subprocess.run(["powercfg", "/setactive", "SCHEME_BALANCED"], capture_output=True, text=True)
            return "Power plan set to Balanced"
        except Exception as error:
            return f"Failed to set power plan: {error}"

    def list_processes(self, top: int = 20, filter_name: str = "") -> List[Dict[str, Any]]:
        """Return top processes sorted by CPU%. Fast path — no open_files() (hangs on Windows)."""
        procs: List[Dict[str, Any]] = []
        filter_lower = (filter_name or "").lower().strip()

        # Prime CPU counters (first call often returns 0.0)
        try:
            for proc in psutil.process_iter(["pid"]):
                try:
                    proc.cpu_percent(interval=None)
                except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                    continue
            time.sleep(0.15)
        except Exception:
            pass

        for proc in psutil.process_iter(
            ["name", "pid", "cpu_percent", "memory_percent", "status"]
        ):
            try:
                info = proc.info
                name = info.get("name") or "unknown"
                if filter_lower and filter_lower not in name.lower():
                    continue
                procs.append({
                    "name": name[:35],
                    "pid": info.get("pid", 0),
                    "cpu_pct": round(float(info.get("cpu_percent") or 0.0), 1),
                    "ram_pct": round(float(info.get("memory_percent") or 0.0), 1),
                    "open_files": -1,  # skipped — open_files() is too slow on Windows
                    "status": info.get("status") or "?",
                    "important": False,
                })
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except Exception:
                continue

        procs.sort(key=lambda p: (p["cpu_pct"], p["ram_pct"]), reverse=True)
        return procs[:top]

    def kill_process(self, pid: int) -> str:
        """Kill a process by PID. Returns result message."""
        try:
            proc = psutil.Process(pid)
            name = proc.name()
            proc.kill()
            return f"Killed: {name} (PID {pid})"
        except psutil.NoSuchProcess:
            return f"Process {pid} not found."
        except psutil.AccessDenied:
            return f"Access denied — run as Administrator to kill PID {pid}."
        except Exception as error:
            return f"Failed to kill PID {pid}: {error}"

    def kill_process_by_name(self, name: str) -> str:
        """Kill all processes whose name or visible window title matches the string (case-insensitive)."""
        target = name.lower().strip()
        if not target:
            return "No process name specified."
        
        killed_list = []
        access_denied_count = 0
        
        # Check active browser tabs to see if a tab title matches
        matched_tab_pids = set()
        try:
            tabs = self.list_browser_tabs()
            for tab in tabs:
                if target in tab["title"].lower() or target in tab["browser"].lower():
                    if tab.get("remote_debug_port") and tab.get("remote_debug_id"):
                        if self._close_remote_tab(tab["remote_debug_port"], tab["remote_debug_id"]):
                            killed_list.append(f"{tab['title']} (tab)")
                            continue
                    matched_tab_pids.add(tab["pid"])
        except Exception:
            pass
                
        # Iterate all processes
        for proc in psutil.process_iter(["name", "pid"]):
            try:
                pname = (proc.info.get("name") or "").lower()
                pid = proc.info.get("pid")
                if not pid:
                    continue
                if target in pname or pid in matched_tab_pids:
                    proc.kill()
                    killed_list.append(f"{proc.info.get('name') or 'unknown'} ({pid})")
            except psutil.AccessDenied:
                access_denied_count += 1
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except Exception:
                continue
                
        if killed_list:
            msg = f"Killed processes: {', '.join(killed_list)}"
            if access_denied_count > 0:
                msg += f" (skipped {access_denied_count} processes due to Access Denied)"
            return msg
        elif access_denied_count > 0:
            return f"Access Denied: Could not kill processes matching '{name}' (run as Administrator)."
        else:
            return f"No processes found matching '{name}'."

    def close_window_by_hwnd(self, hwnd: int) -> bool:
        """Close a window by sending a WM_CLOSE message to its HWND."""
        try:
            import win32gui
            win32gui.PostMessage(hwnd, 0x0010, 0, 0) # 0x0010 is WM_CLOSE
            return True
        except Exception:
            return False

    def kill_by_index_or_pid(self, target: str) -> str:
        """Helper to kill/close either by index (from last_tabs) or by PID / name."""
        target_stripped = target.strip()
        if not target_stripped:
            return "No target specified."

        if target_stripped.isdigit():
            val = int(target_stripped)
            # Check if it matches a tab index in last_tabs
            if 1 <= val <= len(self.last_tabs):
                tab = self.last_tabs[val - 1]
                if tab.get("remote_debug_port") and tab.get("remote_debug_id"):
                    if self._close_remote_tab(tab["remote_debug_port"], tab["remote_debug_id"]):
                        return f"Closed browser tab: {tab['title']}"
                    else:
                        return f"Failed to close browser tab: {tab['title']}"
                hwnd = tab.get("hwnd")
                if hwnd:
                    if self.close_window_by_hwnd(hwnd):
                        return f"Closed browser tab/window: {tab['title']}"
                    else:
                        return f"Failed to close tab/window: {tab['title']}"
                else:
                    # No hwnd, fall back to killing its process PID
                    return self.kill_process(tab["pid"])
            
            # Otherwise, treat as PID
            return self.kill_process(val)
        
        # Not a digit, treat as name
        return self.kill_process_by_name(target_stripped)

    # Vendor service prefixes — background daemons the user can't meaningfully close
    _VENDOR_PREFIXES = (
        "dell.", "dellsupport", "supportassist", "intel.", "realtek",
        "nvidia.", "amd.", "qualcomm", "broadcom", "hp.", "lenovo.",
        "asus.", "acer.", "msi.", "logitech.", "corsair.", "razer.",
    )
    _VENDOR_SUFFIXES = (
        "agent.exe", "service.exe", "daemon.exe", "helper.exe",
        "updater.exe", "tray.exe", "watcher.exe", "monitor.exe",
        "remediationservice.exe",
    )

    # Apps known to run without a visible window but are user-installed
    _KNOWN_USER_BG = {
        "anydesk.exe", "teamviewer.exe", "rustdesk.exe",
        "discord.exe", "discordptb.exe", "discordcanary.exe",
        "telegram.exe", "whatsapp.exe", "whatsapp.root.exe",
        "spotify.exe", "steam.exe", "steamwebhelper.exe",
        "epicgameslauncher.exe", "origin.exe", "upc.exe",
        "lively.exe", "rainmeter.exe",
        "slack.exe", "zoom.exe", "skype.exe",
        "dropbox.exe", "onedrive.exe",
        "nordvpn.exe", "expressvpn.exe", "mullvad.exe",
        "1password.exe", "lastpass.exe", "bitwarden.exe",
        "comet.exe",          # Facebook Messenger desktop
        "claude.exe",         # Claude Code desktop app
        "notion.exe", "obsidian.exe", "logseq.exe",
        "plex.exe", "plexmediaplayer.exe",
        "barrier.exe", "synergy.exe",
        "parsec.exe", "sunshine.exe",
    }

    def get_background_processes(self, min_ram_mb: float = 5.0) -> List[Dict[str, Any]]:
        """
        Return user-installed background processes — apps the user can actually close.
        Filters: system procs, vendor services, current process.
        Deduplicates by exe name (multi-instance apps show combined RAM).
        """
        current_pid = _os.getpid()

        # Collect PIDs that own a visible window (definitely user-facing)
        windowed_pids: set = set()
        try:
            import win32gui
            import win32process

            def _enum_cb(hwnd: int, _: object) -> bool:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                title = win32gui.GetWindowText(hwnd)
                if not title or len(title) < 2:
                    return True
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    windowed_pids.add(pid)
                except Exception:
                    pass
                return True

            win32gui.EnumWindows(_enum_cb, None)
        except Exception:
            pass  # win32gui unavailable — fall back to known-app list only

        # Build aggregated map: exe_name → combined stats
        agg: Dict[str, Dict[str, Any]] = {}

        for proc in psutil.process_iter(["name", "pid", "memory_percent", "cpu_percent", "memory_info"]):
            try:
                pid        = proc.info.get("pid", 0)
                name_raw   = proc.info.get("name") or "unknown"
                name_lower = name_raw.lower()

                if pid == current_pid:
                    continue
                if name_lower in _SYSTEM_PROCS:
                    continue
                # Windows *Host.exe / *ExperienceHost.exe patterns
                if name_lower.endswith("host.exe") or "experiencehost" in name_lower:
                    continue
                # Vendor background service patterns
                if any(name_lower.startswith(p) for p in self._VENDOR_PREFIXES):
                    continue
                if any(name_lower.endswith(s) for s in self._VENDOR_SUFFIXES):
                    continue

                has_window = pid in windowed_pids
                is_known   = name_lower in self._KNOWN_USER_BG

                # Include only apps with a visible window OR in the known-user list
                if not has_window and not is_known:
                    continue

                mem_info = proc.info.get("memory_info")
                ram_mb   = round(mem_info.rss / (1024 * 1024), 1) if mem_info else 0.0
                if ram_mb < min_ram_mb:
                    continue

                if name_lower not in agg:
                    agg[name_lower] = {
                        "name":      name_raw,
                        "pids":      [pid],
                        "ram_mb":    ram_mb,
                        "ram_pct":   round(float(proc.info.get("memory_percent") or 0.0), 1),
                        "cpu_pct":   round(float(proc.info.get("cpu_percent") or 0.0), 1),
                        "important": name_lower in _IMPORTANT_APPS,
                        "windowed":  has_window,
                    }
                else:
                    agg[name_lower]["pids"].append(pid)
                    agg[name_lower]["ram_mb"]  += ram_mb
                    agg[name_lower]["ram_pct"] += round(float(proc.info.get("memory_percent") or 0.0), 1)
                    agg[name_lower]["cpu_pct"] += round(float(proc.info.get("cpu_percent") or 0.0), 1)

            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except Exception:
                continue

        # Flatten to list — keep "pid" as primary (first) PID, expose instance count
        result: List[Dict[str, Any]] = []
        for entry in agg.values():
            pids = entry.pop("pids")
            entry["pid"]       = pids[0]
            entry["instances"] = len(pids)
            entry["_all_pids"] = pids
            entry["ram_mb"]    = round(entry["ram_mb"], 1)
            entry["ram_pct"]   = round(entry["ram_pct"], 1)
            entry["cpu_pct"]   = round(entry["cpu_pct"], 1)
            result.append(entry)

        result.sort(key=lambda p: p["ram_mb"], reverse=True)
        return result[:20]

    def close_processes_bulk(self, procs: List[Dict[str, Any]]) -> Tuple[int, int]:
        """Kill all PIDs for each grouped process entry. Returns (killed_count, failed_count)."""
        killed = failed = 0
        for p in procs:
            for pid in p.get("_all_pids", [p["pid"]]):
                try:
                    psutil.Process(pid).kill()
                    killed += 1
                except Exception:
                    failed += 1
        return killed, failed

    def restart_explorer(self) -> str:
        """Kill explorer.exe — Windows auto-relaunches it within ~2 s."""
        if platform.system().lower() != "windows":
            return "restart explorer only supported on Windows"
        try:
            killed = 0
            for proc in psutil.process_iter(["name", "pid"]):
                if (proc.info.get("name") or "").lower() == "explorer.exe":
                    proc.kill()
                    killed += 1
            time.sleep(2)
            subprocess.Popen(["explorer.exe"])
            return f"Explorer restarted (killed {killed} instance(s))."
        except Exception as exc:
            return f"Explorer restart failed: {exc}"

    def list_browser_tabs(self, filter_name: str = "") -> List[Dict[str, Any]]:
        """Return list of visible browser windows and, when available, Chrome remote-debug tabs."""
        BROWSER_EXES = {
            "chrome.exe":      "Chrome",
            "msedge.exe":      "Edge",
            "firefox.exe":     "Firefox",
            "brave.exe":       "Brave",
            "opera.exe":       "Opera",
            "iexplore.exe":    "IE",
            "vivaldi.exe":     "Vivaldi",
            "arc.exe":         "Arc",
        }

        filter_lower = filter_name.lower().strip()

        # Build pid -> process info map for browser processes
        browser_procs: Dict[int, Dict[str, Any]] = {}
        for proc in psutil.process_iter(["name", "pid", "cpu_percent", "memory_percent"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name in BROWSER_EXES:
                    browser_procs[proc.pid] = {
                        "browser": BROWSER_EXES[name],
                        "pid": proc.pid,
                        "cpu_pct": round(float(proc.info.get("cpu_percent") or 0.0), 1),
                        "ram_pct": round(float(proc.info.get("memory_percent") or 0.0), 1),
                    }
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue

        remote_tabs: List[Dict[str, Any]] = []
        for port in self._get_browser_debug_ports():
            remote_tabs.extend(self._fetch_chrome_devtools_tabs(port, filter_lower))

        tabs: List[Dict[str, Any]] = []
        if browser_procs:
            # Use win32gui to get window titles per PID
            try:
                import win32gui
                import win32process

                def enum_windows_callback(hwnd: int, _: Any) -> bool:
                    if not win32gui.IsWindowVisible(hwnd):
                        return True
                    title = win32gui.GetWindowText(hwnd)
                    if not title or len(title) < 3:
                        return True
                    try:
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    except Exception:
                        return True
                    if pid in browser_procs:
                        entry = dict(browser_procs[pid])
                        entry["title"] = title[:80]
                        entry["hwnd"] = hwnd
                        entry["source"] = "window"

                        # Apply filter
                        if filter_lower:
                            match_proc = filter_lower in entry["browser"].lower()
                            match_title = filter_lower in entry["title"].lower()
                            if not (match_proc or match_title):
                                return True

                        tabs.append(entry)
                    return True

                win32gui.EnumWindows(enum_windows_callback, None)
            except ImportError:
                # win32gui unavailable — fall back to showing all browser processes
                for pid, info in browser_procs.items():
                    info["title"] = f"[{info['browser']} process]"
                    info["hwnd"] = None

                    # Apply filter
                    if filter_lower:
                        match_proc = filter_lower in info["browser"].lower()
                        match_title = filter_lower in info["title"].lower()
                        if not (match_proc or match_title):
                            continue

                    tabs.append(info)
            except Exception:
                # If win32gui fails for any other reason, still continue with remote tab info
                pass

        tabs.extend(remote_tabs)

        # Sort by browser name then title
        tabs.sort(key=lambda t: (t["browser"], t["title"]))
        self.last_tabs = tabs
        return tabs
