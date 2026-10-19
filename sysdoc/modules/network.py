"""Network diagnostics + autonomous repair strategies (Windows-first)."""
from __future__ import annotations

import platform
import re
import socket
import subprocess
import time
from typing import Any, Dict, List, Optional, Union


class NetworkModule:
    def __init__(self) -> None:
        self._iface_cache: Optional[str] = None

    # ── Telemetry ─────────────────────────────────────────────────────────

    def collect(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "platform": platform.system(),
            "active_interface": self.get_active_interface(),
            "wifi_ssid": self._get_wifi_ssid(),
        }
        try:
            data["hostname"] = socket.gethostname()
            data["gateway_ip"] = self._get_gateway_ip()
            gw = data["gateway_ip"]
            data["gateway_ping_ms"] = self._ping(gw) if gw and gw != "unknown" else "n/a"
            data["packet_loss_pct"] = (
                self._measure_packet_loss(gw) if gw and gw != "unknown" else "n/a"
            )
            data["dns_primary_ms"] = self._ping("8.8.8.8")
            data["dns_secondary_ms"] = self._ping("1.1.1.1")
            data["internet"] = self._check_internet()
            data["dns_status"] = (
                "ok" if isinstance(data["dns_primary_ms"], (int, float)) else "degraded"
            )
            data["wifi_signal_dbm"] = self._get_wifi_signal_dbm()
            data["outage_prediction"] = self._predict_outage(data)
            data["adapters"] = self.list_interfaces()
        except Exception as exc:
            data["error"] = str(exc)
        return data

    def _predict_outage(self, data: Dict[str, Any]) -> str:
        loss = data.get("packet_loss_pct")
        internet = str(data.get("internet", "")).lower()
        if internet in ("offline", "no", "false"):
            return "likely_local_or_isp_outage"
        if isinstance(loss, (int, float)) and loss >= 20:
            return "unstable_link"
        if data.get("dns_status") == "degraded":
            return "dns_issues"
        return "stable"

    # ── Interface detection (fixes Wi-Fi hardcoding) ──────────────────────

    def list_interfaces(self) -> List[str]:
        if platform.system().lower() != "windows":
            return []
        out = self._run_command(
            ["netsh", "interface", "show", "interface"]
        )
        names = []
        for line in out.splitlines():
            # Connected / Disconnected  Dedicated  Name...
            m = re.search(r"\s{2,}(Connected|Disconnected)\s+\S+\s+(.+)$", line.strip())
            if m:
                names.append(m.group(2).strip())
            else:
                parts = re.split(r"\s{2,}", line.strip())
                if len(parts) >= 4 and parts[0] in ("Enabled", "Disabled"):
                    names.append(parts[-1].strip())
        return [n for n in names if n and n.lower() not in ("interface name", "name")]

    def get_active_interface(self) -> str:
        """Prefer connected Wi-Fi/Ethernet; never assume 'Wi-Fi'."""
        if self._iface_cache:
            return self._iface_cache
        if platform.system().lower() != "windows":
            self._iface_cache = "eth0"
            return self._iface_cache

        out = self._run_command(["netsh", "interface", "show", "interface"])
        connected = []
        for line in out.splitlines():
            low = line.lower()
            if "connected" in low and "disconnected" not in low:
                parts = re.split(r"\s{2,}", line.strip())
                if parts:
                    connected.append(parts[-1].strip())

        # Prefer Wi-Fi-like, then Ethernet-like
        for c in connected:
            if re.search(r"wi-?fi|wireless", c, re.I):
                self._iface_cache = c
                return c
        for c in connected:
            if re.search(r"ethernet|local area", c, re.I):
                self._iface_cache = c
                return c
        if connected:
            self._iface_cache = connected[0]
            return connected[0]

        # Fallback candidates
        for candidate in ("Wi-Fi", "Wi-Fi 2", "Ethernet", "Ethernet 2"):
            self._iface_cache = candidate
            return candidate
        self._iface_cache = "Wi-Fi"
        return self._iface_cache

    # ── Collect helpers ───────────────────────────────────────────────────

    def _run_command(self, command: List[str]) -> str:
        try:
            r = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
                shell=False,
            )
            return (r.stdout or "") + (r.stderr or "")
        except Exception as exc:
            return str(exc)

    def _get_gateway_ip(self) -> str:
        try:
            output = self._run_command(["route", "print", "0.0.0.0"])
            ip = self._parse_gateway_from_route_print(output)
            if ip:
                return ip
            output = self._run_command(["ipconfig"])
            return self._parse_gateway_from_ipconfig(output) or "unknown"
        except Exception:
            return "unknown"

    def _parse_gateway_from_route_print(self, output: str) -> str:
        for line in output.splitlines():
            if "0.0.0.0" in line:
                parts = line.split()
                # 0.0.0.0  0.0.0.0  gateway  interface  metric
                ips = [p for p in parts if re.match(r"\d+\.\d+\.\d+\.\d+", p)]
                if len(ips) >= 3:
                    return ips[2]
                if len(ips) >= 2 and ips[1] != "0.0.0.0":
                    return ips[1]
        return ""

    def _parse_gateway_from_ipconfig(self, output: str) -> str:
        for line in output.splitlines():
            if "Default Gateway" in line or "Default gateway" in line:
                m = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
                if m:
                    return m.group(1)
        return ""

    def _parse_gateway_from_ip_route(self, output: str) -> str:
        for line in output.splitlines():
            if "default" in line:
                m = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
                if m:
                    return m.group(1)
        return ""

    def _ping(self, host: str) -> Union[int, str]:
        if not host:
            return "n/a"
        try:
            flag = "-n" if platform.system().lower() == "windows" else "-c"
            out = self._run_command(["ping", flag, "1", host])
            return self._parse_ping_time(out)
        except Exception:
            return "timeout"

    def _parse_ping_time(self, output: str) -> Union[int, str]:
        m = re.search(r"time[=<](\d+)\s*ms", output, re.I)
        if m:
            return int(m.group(1))
        m = re.search(r"Average\s*=\s*(\d+)ms", output, re.I)
        if m:
            return int(m.group(1))
        return "timeout"

    def _measure_packet_loss(self, host: str, count: int = 4) -> float:
        try:
            flag = "-n" if platform.system().lower() == "windows" else "-c"
            out = self._run_command(["ping", flag, str(count), host])
            return self._parse_packet_loss(out)
        except Exception:
            return 100.0

    def _parse_packet_loss(self, output: str) -> float:
        m = re.search(r"\((\d+)%\s*loss\)", output, re.I)
        if m:
            return float(m.group(1))
        m = re.search(r"Lost\s*=\s*(\d+)", output, re.I)
        if m:
            # approximate if total known
            return float(m.group(1)) * 25.0
        return 0.0

    def _check_internet(self) -> str:
        for host in ("8.8.8.8", "1.1.1.1", "208.67.222.222"):
            t = self._ping(host)
            if isinstance(t, (int, float)):
                return "online"
        return "offline"

    def _get_wifi_ssid(self) -> str:
        if platform.system().lower() != "windows":
            return "unknown"
        out = self._run_command(["netsh", "wlan", "show", "interfaces"])
        ssid = ""
        for line in out.splitlines():
            line_st = line.strip()
            # Skip BSSID (MAC line)
            if re.match(r"^BSSID\s*:", line_st, re.I):
                continue
            m = re.match(r"^SSID\s*:\s*(.+)$", line_st, re.I)
            if m:
                val = m.group(1).strip()
                if val:
                    ssid = val
                    break
        return ssid or "unknown"

    def _get_wifi_signal_dbm(self) -> Union[int, str]:
        if platform.system().lower() != "windows":
            return "n/a"
        out = self._run_command(["netsh", "wlan", "show", "interfaces"])
        return self._parse_windows_wifi_signal(out)

    def _parse_windows_wifi_signal(self, output: str) -> Union[int, str]:
        m = re.search(r"Signal\s*:\s*(\d+)%", output, re.I)
        if m:
            return self._signal_percent_to_dbm(int(m.group(1)))
        return "n/a"

    def _parse_linux_wifi_signal(self, output: str) -> Union[int, str]:
        m = re.search(r"(-\d+)\s*dBm", output)
        return int(m.group(1)) if m else "n/a"

    def _signal_percent_to_dbm(self, percent: int) -> int:
        # rough map 0–100% → -100..-50 dBm
        percent = max(0, min(100, percent))
        return int(-100 + (percent * 0.5))

    # ── Repair strategies (autonomous ladder) ─────────────────────────────

    def fix_dns(self) -> str:
        """Flush DNS + set public DNS on active interface."""
        if platform.system().lower() != "windows":
            return "DNS fix not supported on this platform"
        iface = self.get_active_interface()
        steps = []
        r = subprocess.run(
            ["ipconfig", "/flushdns"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        steps.append("flushdns: " + ((r.stdout or r.stderr or "ok").strip()[:120]))
        for idx, dns in enumerate(("1.1.1.1", "8.8.8.8")):
            arg = "set" if idx == 0 else "add"
            cmd = [
                "netsh", "interface", "ip", arg, "dns",
                iface, "static", dns,
            ]
            if idx > 0:
                cmd += ["index=2"]
            r = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            steps.append(f"dns{idx+1}={dns} on {iface}: {(r.stdout or r.stderr or 'ok').strip()[:80]}")
        return " | ".join(steps)

    def fix_flush_dns_only(self) -> str:
        r = subprocess.run(
            ["ipconfig", "/flushdns"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        return (r.stdout or r.stderr or "flushdns done").strip()

    def fix_renew_ip(self) -> str:
        if platform.system().lower() != "windows":
            return "renew not supported"
        a = subprocess.run(
            ["ipconfig", "/release"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        time.sleep(1)
        b = subprocess.run(
            ["ipconfig", "/renew"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        return (
            f"release: {(a.stdout or a.stderr or '').strip()[:100]} | "
            f"renew: {(b.stdout or b.stderr or '').strip()[:100]}"
        )

    def fix_reset_adapter(self) -> str:
        """Disable/enable the *active* interface (not hardcoded Wi-Fi)."""
        if platform.system().lower() != "windows":
            return "adapter reset not supported"
        iface = self.get_active_interface()
        self._iface_cache = None  # refresh after reset
        subprocess.run(
            ["netsh", "interface", "set", "interface", iface, "disable"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        time.sleep(2)
        r = subprocess.run(
            ["netsh", "interface", "set", "interface", iface, "enable"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        time.sleep(2)
        return f"reset interface '{iface}': {(r.stdout or r.stderr or 'ok').strip()[:120]}"

    def fix_winsock_reset(self) -> str:
        if platform.system().lower() != "windows":
            return "winsock reset not supported"
        a = subprocess.run(
            ["netsh", "winsock", "reset"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        b = subprocess.run(
            ["netsh", "int", "ip", "reset"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        return (
            f"winsock: {(a.stdout or a.stderr or '').strip()[:100]} | "
            f"ip reset: {(b.stdout or b.stderr or '').strip()[:100]} "
            f"(reboot may be required)"
        )

    def fix_tcp_reset(self) -> str:
        if platform.system().lower() != "windows":
            return "tcp reset not supported"
        r = subprocess.run(
            ["netsh", "int", "tcp", "reset"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        return (r.stdout or r.stderr or "tcp reset done").strip()[:200]

    def fix_dns_dhcp(self) -> str:
        """Restore DNS to DHCP/automatic on active interface."""
        if platform.system().lower() != "windows":
            return "not supported"
        iface = self.get_active_interface()
        r = subprocess.run(
            ["netsh", "interface", "ip", "set", "dns", iface, "dhcp"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        subprocess.run(
            ["ipconfig", "/flushdns"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        return f"dns dhcp on {iface}: {(r.stdout or r.stderr or 'ok').strip()[:120]}"

    def generate_isp_report(self, os_data: Optional[Dict[str, Any]] = None) -> str:
        os_data = os_data or self.collect()
        lines = ["ISP report summary:"]
        for key in [
            "active_interface",
            "wifi_ssid",
            "gateway_ip",
            "gateway_ping_ms",
            "dns_primary_ms",
            "dns_secondary_ms",
            "dns_status",
            "internet",
            "packet_loss_pct",
            "outage_prediction",
            "wifi_signal_dbm",
        ]:
            lines.append(f"{key}: {os_data.get(key, 'unknown')}")
        if "error" in os_data:
            lines.append(f"error: {os_data['error']}")
        return "\n".join(lines)

    # Alias used by some registries
    def fix_reset_wifi(self) -> str:
        return self.fix_reset_adapter()

    def get_wifi_password(self, ssid: Optional[str] = None) -> Dict[str, str]:
        """Return saved Wi-Fi password for SSID (Windows netsh). Requires elevation sometimes."""
        if platform.system().lower() != "windows":
            return {"ssid": ssid or "", "password": "", "error": "Windows only"}

        ssid = (ssid or "").strip() or self._get_wifi_ssid()
        if not ssid or ssid == "unknown":
            return {"ssid": "", "password": "", "error": "No SSID — connect to Wi-Fi first"}

        # List profiles if exact name fails
        out = self._run_command(
            ["netsh", "wlan", "show", "profile", f"name={ssid}", "key=clear"]
        )
        if "not found" in out.lower() or "cannot find" in out.lower():
            # try without name= prefix variants
            out = self._run_command(
                ["netsh", "wlan", "show", "profile", ssid, "key=clear"]
            )

        password = ""
        m = re.search(r"Key Content\s*:\s*(.+)$", out, re.I | re.M)
        if m:
            password = m.group(1).strip()

        if not password:
            # Profile exists but key hidden (need admin)
            if re.search(r"Security key\s*:\s*Absent", out, re.I):
                return {
                    "ssid": ssid,
                    "password": "",
                    "error": "No password stored (open network)",
                }
            if "Key Content" not in out:
                return {
                    "ssid": ssid,
                    "password": "",
                    "error": "Password hidden — run Fixbot as Administrator",
                }
            return {"ssid": ssid, "password": "", "error": "Could not read password"}

        return {"ssid": ssid, "password": password, "error": ""}

    def list_wifi_profiles(self) -> List[str]:
        if platform.system().lower() != "windows":
            return []
        out = self._run_command(["netsh", "wlan", "show", "profiles"])
        names = re.findall(r"All User Profile\s*:\s*(.+)$", out, re.I | re.M)
        if not names:
            names = re.findall(r"Profile\s*:\s*(.+)$", out, re.I | re.M)
        return [n.strip() for n in names if n.strip()]

    def run_speedtest(self, duration: int = 10) -> Dict[str, Any]:
        from modules.speedtest_runner import run_speedtest
        def _prog(msg: str) -> None:
            try:
                from display.animations import agent_log_step
                agent_log_step(msg)
            except Exception:
                pass
        return run_speedtest(duration=duration, on_progress=_prog)