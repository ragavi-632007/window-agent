import json
import shutil
import subprocess
from typing import Optional


class UpdateScanner:
    """Scans winget, pip, and npm for available package updates."""

    # ── public ────────────────────────────────────────────────────────────

    def scan_all(self) -> list[dict]:
        results: list[dict] = []
        results.extend(self.scan_winget())
        results.extend(self.scan_pip())
        results.extend(self.scan_npm())
        return results

    def scan_winget(self) -> list[dict]:
        if not shutil.which("winget"):
            return []
        try:
            proc = subprocess.run(
                ["winget", "upgrade", "--accept-source-agreements"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=40,
            )
            return self._parse_winget(proc.stdout)
        except Exception:
            return []

    def scan_pip(self) -> list[dict]:
        if not shutil.which("pip"):
            return []
        try:
            proc = subprocess.run(
                ["pip", "list", "--outdated", "--format=json"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            packages = json.loads(proc.stdout or "[]")
            return [
                {
                    "name":    p["name"],
                    "id":      p["name"],
                    "from":    p["version"],
                    "to":      p["latest_version"],
                    "source":  "pip",
                    "manager": "pip",
                }
                for p in packages
            ]
        except Exception:
            return []

    def scan_npm(self) -> list[dict]:
        if not shutil.which("npm"):
            return []
        try:
            proc = subprocess.run(
                ["npm", "outdated", "-g", "--json"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            data = json.loads(proc.stdout or "{}")
            return [
                {
                    "name":    name,
                    "id":      name,
                    "from":    info.get("current", "?"),
                    "to":      info.get("latest", "?"),
                    "source":  "npm",
                    "manager": "npm",
                }
                for name, info in data.items()
            ]
        except Exception:
            return []

    def get_update_cmd(self, item: dict) -> list[str]:
        mgr = item["manager"]
        if mgr == "winget":
            return [
                "winget", "upgrade",
                "--id", item["id"],
                "--accept-package-agreements",
                "--accept-source-agreements",
            ]
        if mgr == "pip":
            return ["pip", "install", "--upgrade", item["name"]]
        if mgr == "npm":
            return ["npm", "update", "-g", item["name"]]
        return []

    # ── winget table parser ────────────────────────────────────────────────

    def _parse_winget(self, output: str) -> list[dict]:
        lines = output.splitlines()

        # Find the header row (contains all four column labels)
        header_idx: Optional[int] = None
        for i, line in enumerate(lines):
            if ("Name" in line and "Id" in line
                    and "Version" in line and "Available" in line):
                header_idx = i
                break
        if header_idx is None:
            return []

        header = lines[header_idx]
        # Derive column positions from where each header word starts.
        # winget uses a single solid separator line (no gaps), so we cannot
        # use the separator to detect columns — we must use the header itself.
        col_starts = self._col_starts_from_header(header)
        if len(col_starts) < 4:
            return []

        results: list[dict] = []
        for line in lines[header_idx + 2:]:   # skip header + separator
            stripped = line.strip()
            if not stripped:
                continue
            # "30 upgrades available." — stop
            if stripped[0].isdigit() and "upgrade" in stripped.lower():
                break
            # Pure separator lines
            if all(c in ("-", "─", " ") for c in line):
                continue

            fields = []
            for k, start in enumerate(col_starts):
                end   = col_starts[k + 1] if k + 1 < len(col_starts) else len(line)
                value = line[start:end].strip() if start < len(line) else ""
                fields.append(value)

            if len(fields) < 4 or not fields[0] or not fields[1]:
                continue

            results.append({
                "name":    fields[0],
                "id":      fields[1],
                "from":    fields[2],
                "to":      fields[3],
                "source":  fields[4] if len(fields) > 4 else "winget",
                "manager": "winget",
            })

        return results

    @staticmethod
    def _col_starts_from_header(header: str) -> list[int]:
        """Return sorted column start positions found in the winget header row."""
        positions: list[int] = []
        for word in ("Name", "Id", "Version", "Available", "Source"):
            idx = header.find(word)
            if idx != -1:
                positions.append(idx)
        return sorted(positions)

    # ── Multi-agent pipeline methods ──────────────────────────────────────

    def search_package(self, query: str) -> list[dict]:
        """Search winget for packages matching *query* (fuzzy name match).

        Returns a list of dicts with keys: name, id, version, source.
        Used by the Planner's ``search_package`` tool so the LLM can resolve
        a human name like 'microsoft edge' to the canonical winget id.
        """
        if not shutil.which("winget"):
            return []
        try:
            proc = subprocess.run(
                ["winget", "search", "--name", query,
                 "--accept-source-agreements"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
            return self._parse_winget_search(proc.stdout)
        except Exception:
            return []

    def upgrade_package(self, item: dict) -> tuple[bool, str]:
        """Run the standard upgrade command for *item*.

        Returns ``(success, output_text)``.
        """
        return self.run_strategy(item, "standard_upgrade")

    def force_upgrade_package(self, item: dict) -> tuple[bool, str]:
        """Retry upgrade with ``--force`` (winget) or ``--force-reinstall`` (pip)."""
        return self.run_strategy(item, "force_upgrade")

    def reinstall_package(self, item: dict) -> tuple[bool, str]:
        """Uninstall then install fresh (winget only, pip/npm fall back to force)."""
        return self.run_strategy(item, "reinstall")

    def purge_reinstall_package(self, item: dict) -> tuple[bool, str]:
        """Aggressive winget reinstall for install-technology mismatch (exit 93)."""
        return self.run_strategy(item, "purge_reinstall")

    # ── INSTALL strategies ────────────────────────────────────────────────

    def install_package(self, item: dict) -> tuple[bool, str]:
        """Fresh install of a package not yet on the system."""
        return self.run_strategy(item, "install")

    def force_install_package(self, item: dict) -> tuple[bool, str]:
        """Fresh install with --force, overriding any partial/mismatch state."""
        return self.run_strategy(item, "force_install")

    # ── UNINSTALL strategies ──────────────────────────────────────────────

    def uninstall_package(self, item: dict) -> tuple[bool, str]:
        """Remove a package via the package manager."""
        return self.run_strategy(item, "uninstall")

    def force_uninstall_package(self, item: dict) -> tuple[bool, str]:
        """Force-remove a package (kills blocking processes first)."""
        return self.run_strategy(item, "force_uninstall")

    def purge_uninstall_package(self, item: dict) -> tuple[bool, str]:
        """Purge uninstall — kills processes, uninstalls with --force, removes leftover dirs."""
        return self.run_strategy(item, "purge_uninstall")

    def get_strategy_commands(self, item: dict, strategy: str) -> list[list[str]]:
        """Return argv lists for *strategy* (multi-step for reinstall paths)."""
        mgr = item.get("manager", "")
        pkg_id = item.get("id", "")

        if strategy == "standard_upgrade":
            cmd = self.get_update_cmd(item)
            return [cmd] if cmd else []

        if strategy == "force_upgrade":
            if mgr == "winget":
                return [[
                    "winget", "upgrade", "--id", pkg_id, "--force",
                    "--accept-package-agreements", "--accept-source-agreements",
                ]]
            if mgr == "pip":
                return [["pip", "install", "--upgrade", "--force-reinstall", item["name"]]]
            if mgr == "npm":
                return [["npm", "install", "-g", item["name"]]]
            return []

        if strategy in ("reinstall", "purge_reinstall"):
            if mgr != "winget":
                return self.get_strategy_commands(item, "force_upgrade")
            force = strategy == "purge_reinstall"
            uninstall = [
                "winget", "uninstall", "--id", pkg_id,
                "--accept-source-agreements", "--disable-interactivity",
            ]
            uninstall.append("--force" if force else "--silent")
            install = [
                "winget", "install", "--id", pkg_id,
                "--accept-package-agreements", "--accept-source-agreements",
                "--disable-interactivity",
            ]
            if force:
                install.append("--force")
            return [uninstall, install]

        # ── INSTALL strategies ─────────────────────────────────────────────
        if strategy == "install":
            if mgr == "winget":
                return [[
                    "winget", "install", "--id", pkg_id,
                    "--accept-package-agreements", "--accept-source-agreements",
                    "--disable-interactivity",
                ]]
            if mgr == "pip":
                return [["pip", "install", item.get("name") or pkg_id]]
            if mgr == "npm":
                return [["npm", "install", "-g", item.get("name") or pkg_id]]
            return []

        if strategy == "force_install":
            if mgr == "winget":
                return [[
                    "winget", "install", "--id", pkg_id, "--force",
                    "--accept-package-agreements", "--accept-source-agreements",
                    "--disable-interactivity",
                ]]
            if mgr == "pip":
                return [["pip", "install", "--force-reinstall", item.get("name") or pkg_id]]
            if mgr == "npm":
                return [["npm", "install", "-g", "--force", item.get("name") or pkg_id]]
            return []

        if strategy == "accept_agreements":
            if mgr == "winget":
                return [[
                    "winget", "install", "--id", pkg_id,
                    "--accept-package-agreements", "--accept-source-agreements",
                    "--disable-interactivity", "--silent",
                ]]
            return self.get_strategy_commands(item, "install")

        if strategy == "choco_install":
            cid = item.get("choco_id") or item.get("name") or pkg_id
            return [["choco", "install", cid, "-y", "--no-progress"]]

        if strategy == "scoop_install":
            sid = item.get("scoop_id") or item.get("name") or pkg_id
            return [["scoop", "install", sid]]

        # ── UNINSTALL strategies ───────────────────────────────────────────
        if strategy == "uninstall":
            if mgr == "winget":
                return [[
                    "winget", "uninstall", "--id", pkg_id,
                    "--accept-source-agreements", "--disable-interactivity",
                ]]
            if mgr == "pip":
                return [["pip", "uninstall", "-y", item.get("name") or pkg_id]]
            if mgr == "npm":
                return [["npm", "uninstall", "-g", item.get("name") or pkg_id]]
            return []

        if strategy == "uninstall_user_scope":
            # Per-user package while shell is elevated: run winget unelevated
            if mgr == "winget":
                args = (
                    f"uninstall --id {pkg_id} "
                    f"--accept-source-agreements --disable-interactivity"
                )
                # Scheduled task runs as current user at medium integrity
                ps = (
                    f"$p='winget'; $a='{args}'; "
                    f"$t='FixbotWingetUninstall'; "
                    f"Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue; "
                    f"$action=New-ScheduledTaskAction -Execute $p -Argument $a; "
                    f"$principal=New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited; "
                    f"Register-ScheduledTask -TaskName $t -Action $action -Principal $principal -Force | Out-Null; "
                    f"Start-ScheduledTask -TaskName $t; "
                    f"while((Get-ScheduledTask -TaskName $t).State -eq 'Running'){{ Start-Sleep -Milliseconds 400 }}; "
                    f"Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue"
                )
                return [["powershell", "-NoProfile", "-Command", ps]]
            return self.get_strategy_commands(item, "uninstall")

        if strategy == "force_uninstall":
            if mgr == "winget":
                return [[
                    "winget", "uninstall", "--id", pkg_id, "--force",
                    "--accept-source-agreements", "--disable-interactivity",
                ]]
            return self.get_strategy_commands(item, "uninstall")

        if strategy == "purge_uninstall":
            # Last resort: winget uninstall + delete known user folders
            cmds = self.get_strategy_commands(item, "uninstall_user_scope")
            return cmds

        return []

    def run_strategy(
        self,
        item: dict,
        strategy: str,
        color: str = "cyan",
        use_progress: bool = True,
        **kwargs,
    ) -> tuple[bool, str]:
        """Run *strategy* with optional PowerShell-style progress bars."""
        # Kill locking apps before install/reinstall strategies
        if strategy in (
            "install", "force_install", "accept_agreements",
            "purge_reinstall", "reinstall", "force_upgrade",
            "choco_install", "scoop_install",
        ):
            try:
                self._kill_blocking_for_package(item)
            except Exception:
                pass

        if strategy in ("reinstall", "purge_reinstall") and item.get("manager") == "winget":
            force = strategy == "purge_reinstall"
            return self._winget_reinstall(item, force=force, color=color, use_progress=use_progress)

        cmds = self.get_strategy_commands(item, strategy)
        if not cmds:
            return False, f"No commands for strategy '{strategy}' on manager '{item.get('manager')}'"

        outputs: list[str] = []
        success = True
        for i, cmd in enumerate(cmds):
            if use_progress:
                from display.animations import WgetBar
                label = item.get("name", "package")[:22]
                if len(cmds) > 1:
                    label = f"{label[:16]} step{i + 1}"
                rc, out = WgetBar(label=label, color=color).run(cmd)
            else:
                rc, out = self._run_cmd(cmd)
            outputs.append(out)
            if rc != 0:
                success = False
                break

        # After uninstall strategies, purge leftover user dirs for known apps
        if strategy in ("purge_uninstall", "uninstall_user_scope", "force_uninstall"):
            self._purge_user_app_dirs(item)

        return success, "\n".join(outputs).strip()

    def _purge_user_app_dirs(self, item: dict) -> None:
        import os, shutil
        from pathlib import Path
        key = f"{item.get('id','')} {item.get('name','')}".lower()
        home = Path.home()
        targets = []
        if "discord" in key:
            targets = [
                home / "AppData" / "Local" / "Discord",
                home / "AppData" / "Roaming" / "discord",
                home / "Desktop" / "Discord.lnk",
                home / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Discord Inc",
            ]
        for t in targets:
            try:
                if t.is_dir():
                    shutil.rmtree(t, ignore_errors=True)
                elif t.is_file():
                    t.unlink(missing_ok=True)
            except Exception:
                pass

    def _winget_reinstall(
        self,
        item: dict,
        *,
        force: bool,
        color: str = "cyan",
        use_progress: bool = True,
    ) -> tuple[bool, str]:
        """Shared winget uninstall→install path with optional force flags."""
        pkg_id = item["id"]
        logs: list[str] = []

        self._kill_blocking_processes(item)
        logs.append(f"Stopped blocking processes for {item.get('name', pkg_id)}")

        uninstall_cmd = [
            "winget", "uninstall", "--id", pkg_id,
            "--accept-source-agreements",
            "--disable-interactivity",
        ]
        uninstall_cmd.append("--force" if force else "--silent")

        install_cmd = [
            "winget", "install", "--id", pkg_id,
            "--accept-package-agreements",
            "--accept-source-agreements",
            "--disable-interactivity",
        ]
        if force:
            install_cmd.append("--force")

        name = item.get("name", pkg_id)[:22]
        if use_progress:
            from display.animations import WgetBar
            _, unsub_out = WgetBar(label=f"{name[:16]} uninstall", color=color).run(uninstall_cmd)
            logs.append(unsub_out)
            rc, out = WgetBar(label=f"{name[:16]} install", color=color).run(install_cmd)
        else:
            unsub = subprocess.run(
                uninstall_cmd,
                capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=180,
            )
            logs.append((unsub.stdout + unsub.stderr).strip())
            ok, out = self._run_cmd(install_cmd, timeout=300)
            rc = 0 if ok else 1

        logs.append(out)
        combined = "\n".join(logs).strip()
        if rc == 0:
            return True, combined

        if self._is_technology_mismatch(combined) and not force:
            return self._winget_reinstall(item, force=True, color=color, use_progress=use_progress)

        return False, combined

    def verify_update(self, item: dict) -> dict:
        """Check whether *item* is now at the target version.

        Returns ``{"verified": bool, "current_version": str, "target": str, "output": str}``.
        """
        mgr = item.get("manager", "")
        target = item.get("to", "")
        if mgr == "winget":
            ok, out = self._run_cmd(
                ["winget", "list", "--id", item["id"],
                 "--accept-source-agreements"],
            )
            # If the target version appears in the output, it's updated
            verified = target in out if target else ok
            return {"verified": verified, "current_version": self._extract_version(out), "target": target, "output": out}
        if mgr == "pip":
            ok, out = self._run_cmd(["pip", "show", item["name"]])
            verified = target in out if target else ok
            return {"verified": verified, "current_version": self._extract_version(out), "target": target, "output": out}
        if mgr == "npm":
            ok, out = self._run_cmd(["npm", "list", "-g", item["name"]])
            verified = target in out if target else ok
            return {"verified": verified, "current_version": self._extract_version(out), "target": target, "output": out}
        return {"verified": False, "current_version": "unknown", "target": target, "output": "unsupported manager"}

    # ── Internal helpers ──────────────────────────────────────────────────

    _LOCK_PROCESSES = {
        "discord": ["Discord.exe", "Update.exe"],
        "spotify": ["Spotify.exe"],
        "slack": ["slack.exe"],
        "teams": ["Teams.exe", "ms-teams.exe"],
        "chrome": ["chrome.exe"],
    }

    def _kill_blocking_for_package(self, item: dict) -> None:
        import subprocess
        key = f"{item.get('id','')} {item.get('name','')}".lower()
        names = []
        for k, procs in self._LOCK_PROCESSES.items():
            if k in key:
                names.extend(procs)
        if not names:
            n = (item.get("name") or "").split()[0]
            if n:
                names.append(f"{n}.exe")
        for proc in names:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", proc, "/T"],
                    capture_output=True, text=True, timeout=15,
                )
            except Exception:
                pass

    _PROCESS_MAP: dict[str, list[str]] = {
        "microsoft edge": ["msedge", "msedgewebview2", "MicrosoftEdgeUpdate"],
        "google chrome": ["chrome", "GoogleUpdate"],
        "mozilla firefox": ["firefox"],
        "visual studio code": ["Code"],
        "discord": ["Discord", "Update"],
        "spotify": ["Spotify"],
        "zoom": ["Zoom"],
        "teams": ["Teams", "ms-teams"],
        "slack": ["slack"],
    }

    @classmethod
    def _kill_blocking_processes(cls, item: dict) -> None:
        """Best-effort kill of processes that commonly block package uninstall."""
        if not shutil.which("taskkill"):
            return

        name_key = item.get("name", "").lower()
        pkg_id = item.get("id", "").lower()
        procs: list[str] = []

        for key, proc_names in cls._PROCESS_MAP.items():
            if key in name_key or key.replace(" ", "") in pkg_id.replace(".", ""):
                procs.extend(proc_names)

        # Generic fallback: first word of package name
        if not procs and name_key:
            procs.append(name_key.split()[0])

        seen: set[str] = set()
        for proc in procs:
            if proc.lower() in seen:
                continue
            seen.add(proc.lower())
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", f"{proc}.exe", "/T"],
                    capture_output=True, text=True, timeout=15,
                )
            except Exception:
                pass

    @staticmethod
    def _is_technology_mismatch(output: str) -> bool:
        lowered = output.lower()
        return (
            "install technology is different" in lowered
            or "exit code: 93" in lowered
            or "uninstall failed with exit code: 93" in lowered
        )

    @staticmethod
    def _run_cmd(cmd: list[str], timeout: int = 120) -> tuple[bool, str]:
        """Run *cmd* and return ``(success, combined_output)``."""
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            output = (proc.stdout + proc.stderr).strip()
            return proc.returncode == 0, output
        except subprocess.TimeoutExpired:
            return False, f"Command timed out after {timeout}s"
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def _extract_version(output: str) -> str:
        """Best-effort version extraction from command output."""
        import re
        m = re.search(r"(\d+\.\d+[\.\d]*)", output)
        return m.group(1) if m else "unknown"

    def _parse_winget_search(self, output: str) -> list[dict]:
        """Parse ``winget search`` output into structured results."""
        lines = output.splitlines()
        header_idx: Optional[int] = None
        for i, line in enumerate(lines):
            if "Name" in line and "Id" in line and "Version" in line:
                header_idx = i
                break
        if header_idx is None:
            return []

        header = lines[header_idx]
        col_starts = self._col_starts_from_header(header)
        if len(col_starts) < 3:
            return []

        results: list[dict] = []
        for line in lines[header_idx + 2:]:
            stripped = line.strip()
            if not stripped:
                continue
            if all(c in ("-", "─", " ") for c in line):
                continue
            # Summary line at bottom
            if stripped[0].isdigit() and ("package" in stripped.lower() or "result" in stripped.lower()):
                break

            fields = []
            for k, start in enumerate(col_starts):
                end = col_starts[k + 1] if k + 1 < len(col_starts) else len(line)
                value = line[start:end].strip() if start < len(line) else ""
                fields.append(value)

            if len(fields) < 3 or not fields[0] or not fields[1]:
                continue

            results.append({
                "name": fields[0],
                "id": fields[1],
                "version": fields[2] if len(fields) > 2 else "",
                "source": fields[3] if len(fields) > 3 else "winget",
            })

        return results

    def is_installed(self, item: dict) -> tuple[bool, str]:
        """Return (installed?, version). Require winget match AND real files when possible."""
        import re
        import subprocess
        from pathlib import Path

        mgr = (item.get("manager") or "winget").lower()
        pkg_id = (item.get("id") or "").strip()
        name = (item.get("name") or pkg_id).strip()
        key = f"{pkg_id} {name}".lower()

        def _discord_files_present() -> bool:
            home = Path.home()
            candidates = [
                home / "AppData" / "Local" / "Discord" / "Update.exe",
                home / "AppData" / "Local" / "Discord" / "Discord.exe",
            ]
            # versioned app folder: AppData\Local\Discord\app-*\Discord.exe
            root = home / "AppData" / "Local" / "Discord"
            if root.is_dir():
                for p in root.rglob("Discord.exe"):
                    if p.is_file():
                        return True
            return any(p.is_file() for p in candidates)

        def _generic_exe_present(app: str) -> bool:
            home = Path.home()
            stems = [app, app.replace(" ", "")]
            for stem in stems:
                for base in (
                    home / "AppData" / "Local",
                    home / "AppData" / "Roaming",
                    Path(r"C:\Program Files"),
                    Path(r"C:\Program Files (x86)"),
                ):
                    try:
                        if not base.is_dir():
                            continue
                        for p in base.rglob(f"{stem}.exe"):
                            # limit depth cost
                            if len(p.parts) - len(base.parts) <= 4 and p.is_file():
                                return True
                    except Exception:
                        continue
            return False

        # ── winget registration ───────────────────────────────────────────
        winget_says_yes = False
        version = ""
        try:
            if mgr == "winget" and pkg_id:
                r = subprocess.run(
                    [
                        "winget", "list", "--id", pkg_id,
                        "--accept-source-agreements",
                        "--disable-interactivity",
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=60,
                )
                out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
                low = out.lower()
                if "no installed package" not in low and "no packages found" not in low:
                    if pkg_id.lower() in low:
                        winget_says_yes = True
                        for line in out.splitlines():
                            if pkg_id.lower() in line.lower():
                                parts = re.split(r"\s{2,}", line.strip())
                                if len(parts) >= 3 and parts[2].lower() not in (
                                    "available", "id", "version",
                                ):
                                    version = parts[2]
                                break
        except Exception:
            pass

        # ── filesystem truth (critical after manual delete) ────────────────
        files_ok = True
        if "discord" in key:
            files_ok = _discord_files_present()
        elif name and mgr == "winget":
            # light check for other apps — if winget says no, trust that
            if not winget_says_yes:
                files_ok = False
            # if winget says yes, optionally verify exe (best-effort)
            # files_ok stays True unless we want strict mode

        if winget_says_yes and not files_ok:
            # Stale winget entry — treat as NOT installed so install can run
            return False, "stale_registration"

        if winget_says_yes and files_ok:
            return True, version or "unknown"

        # pip / npm unchanged
        try:
            if mgr == "pip":
                r = subprocess.run(
                    ["pip", "show", name],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=30,
                )
                if r.returncode == 0 and (r.stdout or "").strip():
                    ver = ""
                    for line in (r.stdout or "").splitlines():
                        if line.lower().startswith("version:"):
                            ver = line.split(":", 1)[1].strip()
                            break
                    return True, ver or "unknown"
                return False, ""

            if mgr == "npm":
                r = subprocess.run(
                    ["npm", "list", "-g", name, "--depth=0"],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=30,
                )
                out = r.stdout or ""
                if name.lower() in out.lower() and "empty" not in out.lower():
                    return True, "unknown"
                return False, ""
        except Exception:
            return False, ""

        return False, ""
