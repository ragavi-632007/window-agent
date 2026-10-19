"""FixBot system launcher — open/close apps, files, special folders dynamically.

Examples:
  open chrome
  close chrome
  force close chrome
  open recycle bin
  open recent screenshot
  open screenshot 2002-02823 from d drive
  open downloads
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Any, Dict, List, Optional, Tuple

APP_ALIASES: Dict[str, List[str]] = {
    "chrome": ["chrome", "google chrome", "chrome.exe"],
    "edge": ["msedge", "microsoft edge", "msedge.exe"],
    "firefox": ["firefox", "firefox.exe"],
    "notepad": ["notepad", "notepad.exe"],
    "word": ["winword", "microsoft word", "winword.exe"],
    "excel": ["excel", "microsoft excel", "excel.exe"],
    "powerpoint": ["powerpnt", "powerpoint", "powerpnt.exe"],
    "vscode": ["code", "code.exe", "visual studio code"],
    "code": ["code", "code.exe"],
    "explorer": ["explorer", "explorer.exe"],
    "cmd": ["cmd", "cmd.exe"],
    "powershell": ["powershell", "pwsh", "powershell.exe"],
    "calculator": ["calculator", "calc", "calc.exe"],
    "calc": ["calc", "calculator"],
    "paint": ["mspaint", "paint", "mspaint.exe"],
    "spotify": ["spotify", "spotify.exe"],
    "discord": ["discord", "discord.exe"],
    "telegram": ["telegram", "telegram.exe"],
    "whatsapp": ["whatsapp", "whatsapp.exe"],
    "vlc": ["vlc", "vlc.exe"],
    "zoom": ["zoom", "zoom.exe"],
    "teams": ["teams", "ms-teams", "teams.exe"],
    "settings": ["ms-settings:"],
    "task manager": ["taskmgr", "taskmgr.exe"],
    "taskmgr": ["taskmgr"],
}

SPECIAL_FOLDERS: Dict[str, str] = {
    "recycle bin": "shell:RecycleBinFolder",
    "recyclebin": "shell:RecycleBinFolder",
    "trash": "shell:RecycleBinFolder",
    "downloads": "shell:Downloads",
    "documents": "shell:Personal",
    "desktop": "shell:Desktop",
    "pictures": "shell:My Pictures",
    "music": "shell:My Music",
    "videos": "shell:My Video",
    "home": "shell:Profile",
    "appdata": "shell:AppData",
    "this pc": "shell:MyComputerFolder",
    "my computer": "shell:MyComputerFolder",
    "control panel": "shell:ControlPanelFolder",
}


def _run(cmd: List[str], timeout: int = 30) -> Tuple[str, str, int]:
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
        return (r.stdout or "").strip(), (r.stderr or "").strip(), r.returncode
    except Exception as exc:
        return "", str(exc), 1


def _run_shell(cmd: str, timeout: int = 30) -> Tuple[str, str, int]:
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=True,
        )
        return (r.stdout or "").strip(), (r.stderr or "").strip(), r.returncode
    except Exception as exc:
        return "", str(exc), 1


def parse_launcher_query(query: str) -> Dict[str, Any]:
    q = (query or "").strip()
    low = q.lower()

    action = "open"
    force = False
    if low.startswith("force close") or low.startswith("forcekill") or "not responding" in low:
        action = "close"
        force = True
    elif any(low.startswith(p) for p in ("close ", "kill ", "quit ", "exit ", "stop ")):
        action = "close"
        force = "force" in low or "kill" in low
    elif any(low.startswith(p) for p in ("open ", "launch ", "start ", "run ", "show ")):
        action = "open"
    elif low.startswith("find ") or low.startswith("locate "):
        action = "find"

    target = q
    for p in (
        "force close", "force kill", "not responding",
        "close", "kill", "quit", "exit", "stop",
        "open", "launch", "start", "run", "show", "find", "locate",
    ):
        if target.lower().startswith(p):
            target = target[len(p):].strip()
            break
    target = re.sub(r"^(the|my|an|a)\s+", "", target, flags=re.I).strip()

    drive = None
    m = re.search(r"\bfrom\s+([a-zA-Z])\s*drive\b", target, re.I)
    if m:
        drive = m.group(1).upper() + ":\\"
        target = re.sub(r"\bfrom\s+[a-zA-Z]\s*drive\b", "", target, flags=re.I).strip()
    m = re.search(r"\bin\s+([a-zA-Z]):\\?", target, re.I)
    if m:
        drive = m.group(1).upper() + ":\\"
        target = re.sub(r"\bin\s+[a-zA-Z]:\\?", "", target, flags=re.I).strip()

    is_file_hint = any(
        w in target.lower()
        for w in (
            "screenshot", "screen shot", "photo", "image", "img", "pdf", "doc",
            "file", ".png", ".jpg", ".jpeg", ".pdf", ".txt", ".mp4",
            "recent", "latest", "last", "newest",
        )
    )
    recent = any(w in target.lower() for w in ("recent", "latest", "last", "newest"))

    return {
        "action": action,
        "force": force,
        "target": target,
        "drive": drive,
        "is_file_hint": is_file_hint,
        "recent": recent,
        "raw": query,
    }


class AppLauncher:
    def open_special(self, name: str) -> Dict[str, Any]:
        key = name.lower().strip()
        for k, uri in SPECIAL_FOLDERS.items():
            if k in key or key in k:
                _run_shell(f'start "" "{uri}"')
                return {
                    "ok": True,
                    "kind": "special",
                    "target": k,
                    "path": uri,
                    "message": f"Opened {k}",
                }
        return {"ok": False, "message": f"Unknown special folder: {name}"}

    def resolve_app(self, name: str) -> Optional[str]:
        low = name.lower().strip()
        candidates = APP_ALIASES.get(low, [low])

        for c in candidates:
            out, _, code = _run(["where", c], timeout=8)
            if code == 0 and out:
                line = out.splitlines()[0].strip()
                if line and os.path.isfile(line):
                    return line

        for c in candidates:
            exe = c if c.endswith(".exe") else (c if "." in c else f"{c}.exe")
            ps = (
                f'(Get-ItemProperty -Path "HKLM:\\SOFTWARE\\Microsoft\\Windows\\'
                f'CurrentVersion\\App Paths\\{exe}" -ErrorAction SilentlyContinue)'
                f'."(default)"'
            )
            out, _, code = _run(
                ["powershell", "-NoProfile", "-Command", ps], timeout=10
            )
            if code == 0 and out and os.path.isfile(out.strip().strip('"')):
                return out.strip().strip('"')

        starts = [
            os.path.expandvars(r"%AppData%\Microsoft\Windows\Start Menu\Programs"),
            os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
        ]
        tokens = re.findall(r"[a-z0-9]+", low)
        best = None
        best_score = 0
        for root in starts:
            if not os.path.isdir(root):
                continue
            for dirpath, _, files in os.walk(root):
                for f in files:
                    if not f.lower().endswith(".lnk"):
                        continue
                    fl = f.lower()
                    score = sum(1 for t in tokens if t in fl)
                    if score > best_score:
                        best_score = score
                        best = os.path.join(dirpath, f)
        if best and best_score > 0:
            return best

        return candidates[0]

    def open_app(self, name: str) -> Dict[str, Any]:
        low = name.lower()
        for k in SPECIAL_FOLDERS:
            if k in low or low in k:
                return self.open_special(name)

        resolved = self.resolve_app(name)
        if not resolved:
            return {"ok": False, "message": f"Could not find app: {name}"}

        if str(resolved).startswith("ms-") or str(resolved).startswith("shell:"):
            _run_shell(f'start "" "{resolved}"')
            return {
                "ok": True,
                "kind": "app",
                "target": name,
                "path": resolved,
                "message": f"Launched {name}",
            }

        try:
            if str(resolved).lower().endswith(".lnk") or os.path.isfile(str(resolved)):
                os.startfile(resolved)  # type: ignore[attr-defined]
            else:
                _run_shell(f'start "" "{resolved}"')
            return {
                "ok": True,
                "kind": "app",
                "target": name,
                "path": str(resolved),
                "message": f"Opened {name}",
            }
        except Exception as exc:
            out, err, code = _run_shell(f'start "" "{resolved}"')
            ok = code == 0
            return {
                "ok": ok,
                "kind": "app",
                "target": name,
                "path": str(resolved),
                "message": f"Opened {name}" if ok else (err or str(exc)),
            }

    def close_app(self, name: str, force: bool = False) -> Dict[str, Any]:
        low = name.lower().strip()
        names = APP_ALIASES.get(low, [low])
        images = []
        for n in names:
            if n.endswith(".exe"):
                images.append(n)
            elif n.startswith("ms-") or n.startswith("shell:"):
                continue
            else:
                images.append(f"{n}.exe" if " " not in n else n)

        killed = []
        failed = []
        for img in images:
            if force:
                out, err, code = _run(["taskkill", "/F", "/IM", img, "/T"], timeout=15)
            else:
                out, err, code = _run(["taskkill", "/IM", img], timeout=15)
                if code != 0:
                    out, err, code = _run(
                        ["taskkill", "/F", "/IM", img, "/T"], timeout=15
                    )
            if code == 0 or "SUCCESS" in (out or "").upper():
                killed.append(img)
            else:
                if "not found" in (err or out or "").lower():
                    failed.append(f"{img} (not running)")
                else:
                    failed.append(f"{img}: {(err or out)[:80]}")

        if killed:
            return {
                "ok": True,
                "kind": "close",
                "target": name,
                "force": force,
                "killed": killed,
                "message": f"Closed {', '.join(killed)}"
                + (" (forced)" if force else ""),
            }
        return {
            "ok": False,
            "kind": "close",
            "target": name,
            "message": f"Could not close '{name}'. " + "; ".join(failed[:3]),
        }

    def find_files(
        self,
        query: str,
        root: Optional[str] = None,
        limit: int = 15,
    ) -> List[Dict[str, str]]:
        roots: List[str] = []
        if root:
            roots.append(root)
        else:
            # Prefer likely screenshot locations first
            home = os.path.expanduser("~")
            for sub in (
                os.path.join(home, "Desktop"),
                os.path.join(home, "Pictures"),
                os.path.join(home, "Pictures", "Screenshots"),
                os.path.join(home, "OneDrive", "Desktop"),
                os.path.join(home, "OneDrive", "Pictures"),
                home,
            ):
                if os.path.isdir(sub):
                    roots.append(sub)
            for d in "CDEF":
                p = f"{d}:\\"
                if os.path.isdir(p):
                    roots.append(p)

        tokens = [t for t in re.findall(r"[a-zA-Z0-9_\-]+", query.lower()) if len(t) > 1]
        # drop filler words
        tokens = [t for t in tokens if t not in (
            "recent", "latest", "last", "newest", "the", "my", "img", "image", "file", "from", "drive"
        )]
        if not tokens:
            tokens = ["screenshot"]

        hits: List[Tuple[int, str]] = []
        skip_dirs = {
            "$recycle.bin", "system volume information", "windows",
            "node_modules", ".git", "appdata", "program files", "program files (x86)",
        }

        for base in roots:
            if not os.path.isdir(base):
                continue
            depth_limit = 3 if base.endswith(":\\") else 5
            base_depth = base.rstrip("\\").count("\\")
            try:
                for dirpath, dirnames, filenames in os.walk(base):
                    dirnames[:] = [
                        d for d in dirnames
                        if d.lower() not in skip_dirs and not d.startswith(".")
                    ]
                    if dirpath.rstrip("\\").count("\\") - base_depth > depth_limit:
                        dirnames[:] = []
                        continue
                    for fn in filenames:
                        fl = fn.lower()
                        score = sum(3 if t in fl else 0 for t in tokens)
                        if all(t in fl for t in tokens):
                            score += 10
                        if score <= 0:
                            continue
                        full = os.path.join(dirpath, fn)
                        hits.append((score, full))
            except Exception:
                continue

        enriched = []
        for score, path in hits:
            try:
                mtime = os.path.getmtime(path)
            except Exception:
                mtime = 0
            # prefer Desktop / Pictures / Screenshots paths
            pl = path.lower()
            if "screenshot" in pl or "screen shot" in pl:
                score += 5
            if "\\pictures\\" in pl or "\\desktop\\" in pl:
                score += 3
            enriched.append((score, mtime, path))

        # higher score first, then newest
        enriched.sort(key=lambda x: (-x[0], -x[1]))

        seen = set()
        out: List[Dict[str, str]] = []
        for score, mtime, path in enriched:
            if path in seen:
                continue
            seen.add(path)
            out.append({
                "path": path,
                "name": os.path.basename(path),
                "score": str(score),
            })
            if len(out) >= limit:
                break
        return out

    def open_path(self, path: str) -> Dict[str, Any]:
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.exists(path):
            return {"ok": False, "message": f"Not found: {path}"}
        try:
            os.startfile(path)  # type: ignore[attr-defined]
            return {
                "ok": True,
                "kind": "file" if os.path.isfile(path) else "folder",
                "path": path,
                "message": f"Opened {path}",
            }
        except Exception as exc:
            out, err, code = _run_shell(f'start "" "{path}"')
            return {
                "ok": code == 0,
                "path": path,
                "message": f"Opened {path}" if code == 0 else (err or str(exc)),
            }

    def handle(self, query: str, pick_index: Optional[int] = None) -> Dict[str, Any]:
        parsed = parse_launcher_query(query)
        action = parsed["action"]
        target = parsed["target"]
        force = parsed["force"]
        drive = parsed["drive"]
        is_file = parsed["is_file_hint"]

        if not target:
            return {"ok": False, "message": "Say what to open or close, e.g. open chrome"}

        if action == "close":
            return self.close_app(target, force=force)

        for k in SPECIAL_FOLDERS:
            if k in target.lower() or target.lower() in k:
                return self.open_special(target)

        if is_file or drive or any(c in target for c in ("\\", "/", ".")):
            expanded = os.path.expanduser(target)
            if os.path.exists(expanded):
                return self.open_path(expanded)

            recent = any(w in target.lower() for w in ("recent", "latest", "last", "newest"))
            hits = self.find_files(target, root=drive, limit=12)
            if not hits:
                return {
                    "ok": False,
                    "message": f"No files matching '{target}'"
                    + (f" under {drive}" if drive else ""),
                    "hits": [],
                }
            if pick_index is not None and 1 <= pick_index <= len(hits):
                return self.open_path(hits[pick_index - 1]["path"])
            # recent → open newest automatically
            if recent and hits:
                # already sorted newest among top scores — auto-open first
                return self.open_path(hits[0]["path"])
            if len(hits) == 1:
                return self.open_path(hits[0]["path"])
            return {
                "ok": True,
                "kind": "choices",
                "message": f"Found {len(hits)} matches — pick a number",
                "hits": hits,
            }

        return self.open_app(target)


launcher = AppLauncher()
