import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

import psutil

try:
    from rapidfuzz import fuzz
    _HAS_FUZZ = True
except ImportError:
    _HAS_FUZZ = False

MAX_RESULTS = 20
_MAX_READ_BYTES = 100 * 1024  # 100 KB

_SKIP_DIRS = frozenset({
    # Windows system noise
    "$Recycle.Bin", "System Volume Information", "WinSxS", "winsxs",
    "MpEngine", "SoftwareDistribution", "CbsTemp", "Panther",
    "assembly", "GAC_MSIL", "GAC_64", "GAC_32", "NativeImages",
    # App caches and temp — these produce irrelevant duplicate results
    "Cache", "cache", "CacheStorage", "Code Cache",
    "GPUCache", "ShaderCache", "DawnCache",
    "Temp", "temp",
    "Recent",           # Windows Recent shortcuts (.lnk files)
    "Crash Reports", "CrashReports",
    # Known noisy app dirs
    "claude-cli-nodejs", "node_modules", ".git",
})

# File extensions that are never the real target — skip silently
_SKIP_EXTENSIONS = frozenset({
    ".lnk",   # Windows shortcuts (in Recent, Desktop shortcuts to other places)
    ".tmp",
    ".log",
    ".db",
    ".db-shm",
    ".db-wal",
})

# Directories to search FIRST — order matters, most relevant at the top
def _build_priority_dirs() -> List[str]:
    home = os.path.expanduser("~")
    onedrive = os.path.join(home, "OneDrive")
    candidates = [
        # Desktop (regular + OneDrive-synced)
        os.path.join(home, "Desktop"),
        os.path.join(onedrive, "Desktop"),
        # Common user folders
        os.path.join(home, "Documents"),
        os.path.join(onedrive, "Documents"),
        os.path.join(home, "Downloads"),
        os.path.join(onedrive, "Downloads"),
        # OneDrive root (synced files)
        onedrive,
        # Home dir itself
        home,
        # Installed apps
        "C:\\Program Files",
        "C:\\Program Files (x86)",
        # Other users (last before full scan)
        "C:\\Users",
    ]
    # Deduplicate while preserving order
    seen: set = set()
    result = []
    for d in candidates:
        d_norm = os.path.normcase(d)
        if d_norm not in seen and os.path.isdir(d):
            seen.add(d_norm)
            result.append(d)
    return result


def _get_drives() -> List[str]:
    drives = []
    try:
        for part in psutil.disk_partitions(all=False):
            if part.fstype and "cdrom" not in part.opts:
                drives.append(part.mountpoint)
    except Exception:
        pass
    return drives or ["C:\\"]


def _safe_size(path: str) -> Optional[int]:
    try:
        return os.path.getsize(path)
    except OSError:
        return None


def _build_variants(query_lower: str) -> List[str]:
    """Bidirectional variants: 'code 99' ↔ 'code99', dashes/underscores."""
    q = (query_lower or "").strip().lower()
    variants: List[str] = [q]
    if not q:
        return variants

    if " " in q or "-" in q or "_" in q:
        compact = re.sub(r"[\s\-_]+", "", q)
        variants.append(compact)
        variants.append(re.sub(r"[\s\-_]+", "-", q))
        variants.append(re.sub(r"[\s\-_]+", "_", q))
        variants.append(re.sub(r"[\s\-_]+", " ", q).strip())
    else:
        # "code99" → "code 99" | "code-99" | "code_99"
        spaced = re.sub(r"([a-z])(\d)", r"\1 \2", q)
        spaced = re.sub(r"(\d)([a-z])", r"\1 \2", spaced)
        if spaced != q:
            variants.append(spaced)
            variants.append(spaced.replace(" ", "-"))
            variants.append(spaced.replace(" ", "_"))
            variants.append(spaced.replace(" ", ""))
        # camelCase / PascalCase → words
        camel = re.sub(r"([a-z])([A-Z])", r"\1 \2", query_lower).lower()
        if camel != q:
            variants.append(camel)
            variants.append(camel.replace(" ", ""))

    # de-dupe, keep order
    seen = set()
    out: List[str] = []
    for v in variants:
        v = v.strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _query_tokens(query_lower: str) -> List[str]:
    """Tokens including letter/digit splits: 'code99' → ['code','99']."""
    stop = {
        "my", "the", "a", "an", "file", "files", "folder", "folders",
        "app", "find", "search", "locate", "for",
    }
    q = (query_lower or "").lower().strip()
    # split on separators AND between letters and digits
    parts = re.findall(r"[a-z]+|\d+", q)
    if not parts:
        parts = [t for t in re.split(r"[\s\-_]+", q) if t]
    return [t for t in parts if t and t not in stop]


def _fuzzy_score(query: str, name: str) -> float:
    """0–100 similarity. Safe if rapidfuzz missing."""
    if not query or not name:
        return 0.0
    if not _HAS_FUZZ:
        # cheap fallback: shared prefix / substring
        if query in name or name in query:
            return 80.0
        n = min(len(query), len(name), 4)
        if n and query[:n] == name[:n]:
            return 60.0
        return 0.0
    return float(
        max(
            fuzz.ratio(query, name),
            fuzz.partial_ratio(query, name),
            fuzz.token_set_ratio(query, name),
            fuzz.token_sort_ratio(query, name),
        )
    )


def _matches(name_lower: str, variants: List[str], tokens: List[str], mode: str = "strict") -> bool:
    name_compact = re.sub(r"[\s\-_]+", "", name_lower)

    def variant_hit() -> bool:
        for v in variants:
            if not v:
                continue
            if v in name_lower or v in name_compact:
                return True
            vc = re.sub(r"[\s\-_]+", "", v)
            if vc and vc in name_compact:
                return True
        return False

    if mode == "strict":
        if variant_hit():
            return True
        if len(tokens) >= 2:
            return all(t in name_lower or t in name_compact for t in tokens)
        return bool(tokens) and (tokens[0] in name_lower or tokens[0] in name_compact)

    if mode == "any_token":
        if tokens and any(t in name_lower or t in name_compact for t in tokens):
            return True
        return variant_hit()

    # ── fuzzy: variants + tokens + misspelling tolerance ─────────────────
    if variant_hit():
        return True
    for t in tokens:
        if len(t) >= 2 and (t in name_lower or t in name_compact):
            return True

    # Typo tolerance (e.g. cdoe99 ≈ code 99, discrd ≈ discord)
    for v in variants:
        vc = re.sub(r"[\s\-_]+", "", v)
        # compare to full name and compact name
        if _fuzzy_score(v, name_lower) >= 75:
            return True
        if vc and _fuzzy_score(vc, name_compact) >= 75:
            return True
        # token-level: each query token vs name tokens
        name_toks = re.findall(r"[a-z]+|\d+", name_lower)
        for nt in name_toks:
            if len(v) >= 3 and _fuzzy_score(v, nt) >= 80:
                return True
            if len(vc) >= 3 and _fuzzy_score(vc, nt) >= 80:
                return True

    if tokens:
        name_toks = re.findall(r"[a-z]+|\d+", name_lower)
        matched = 0
        for t in tokens:
            if len(t) < 2:
                continue
            if any(_fuzzy_score(t, nt) >= 80 for nt in name_toks):
                matched += 1
            elif t in name_compact:
                matched += 1
        # require most tokens to fuzzy-match when multiple
        need = max(1, len([t for t in tokens if len(t) >= 2]) - 0)
        if matched >= need and matched > 0:
            return True

    return False


def _walk_for_query(
    root: str,
    query_lower: str,
    results: List[Dict],
    seen: set,
    *,
    on_scan: Optional[Callable[[str, int], None]] = None,
    match_mode: str = "strict",
) -> bool:
    """Walk root searching for query. Returns True when MAX_RESULTS reached."""
    variants = _build_variants(query_lower)
    tokens = _query_tokens(query_lower)
    if on_scan:
        on_scan(root, len(results))
    try:
        for dirpath, dirs, files in os.walk(root, topdown=True):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]

            for d in dirs:
                if _matches(d.lower(), variants, tokens, match_mode):
                    full = os.path.join(dirpath, d)
                    if full not in seen:
                        seen.add(full)
                        results.append({"type": "folder", "name": d, "path": full, "size": None})
                        if len(results) >= MAX_RESULTS:
                            return True

            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in _SKIP_EXTENSIONS:
                    continue
                if _matches(f.lower(), variants, tokens, match_mode):
                    full = os.path.join(dirpath, f)
                    if full not in seen:
                        seen.add(full)
                        results.append({
                            "type": "file",
                            "name": f,
                            "path": full,
                            "size": _safe_size(full),
                        })
                        if len(results) >= MAX_RESULTS:
                            return True
    except (PermissionError, OSError):
        pass
    return False


def _search_in_path_env(query_lower: str) -> List[Dict]:
    """Use 'where' to find executables registered in PATH."""
    results = []
    # Try all variants (e.g. "any desk" → also try "anydesk")
    candidates = list(dict.fromkeys(_build_variants(query_lower)))
    for term in candidates:
        try:
            proc = subprocess.run(
                ["where", term],
                capture_output=True, text=True, timeout=4,
            )
            for line in proc.stdout.strip().splitlines():
                line = line.strip()
                if line and os.path.isfile(line):
                    path_lower = line.lower()
                    if not any(r["path"].lower() == path_lower for r in results):
                        results.append({
                            "type": "app",
                            "name": os.path.basename(line),
                            "path": line,
                            "size": _safe_size(line),
                        })
        except Exception:
            pass
    return results


def search_system(query: str, on_progress=None, match_mode: str = "strict") -> List[Dict]:
    """Search all drives for files/folders/apps whose name contains query.

    *on_progress(phase, detail, found_count)* is called during the scan for
    live agent log visualization.

    *match_mode*:
      - ``strict``    — full query or ALL tokens must match (default)
      - ``any_token`` — ANY token matches (broader retry)
      - ``fuzzy``     — partial / variant matching (widest retry)
    """
    query_lower = query.lower().strip()
    results: List[Dict] = []
    seen: set = set()

    def _report(phase: str, detail: str) -> None:
        if on_progress:
            on_progress(phase, detail, len(results))

    # Phase 0: executables in PATH (fast)
    _report("path", "Scanning system PATH for executables...")
    for r in _search_in_path_env(query_lower):
        if r["path"] not in seen:
            seen.add(r["path"])
            results.append(r)
    if len(results) >= MAX_RESULTS:
        _report("done", f"Found {len(results)} match(es) in PATH")
        return results

    # Phase 1: high-value directories (fast)
    priority = _build_priority_dirs()
    _report("priority", f"Scanning {len(priority)} priority folders (Desktop, Documents, Downloads...)")
    for d in priority:
        label = os.path.basename(d.rstrip("\\")) or d
        _report("scanning", f"{label}  ({d})")
        if _walk_for_query(d, query_lower, results, seen, on_scan=lambda root, n: None, match_mode=match_mode):
            _report("done", f"Found {len(results)} match(es)")
            return results

    # Phase 2: full drive scan
    drives = _get_drives()
    _report("drives", f"Deep scan across {len(drives)} drive(s)...")
    for drive in drives:
        _report("scanning", f"Drive {drive}")
        if _walk_for_query(drive, query_lower, results, seen, on_scan=lambda root, n: None, match_mode=match_mode):
            _report("done", f"Found {len(results)} match(es)")
            return results

    _report("done", f"Scan complete — {len(results)} match(es)")
    return results


def _force_remove_readonly(func, path, exc_info):
    """Clear read-only flag and retry — required for .git folders on Windows."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def _shortcut_candidate_dirs() -> List[str]:
    """Desktop + Start Menu locations where app icons (.lnk) live."""
    home = str(Path.home())
    dirs = [
        str(Path(home) / "Desktop"),
        str(Path(home) / "OneDrive" / "Desktop"),
        r"C:\Users\Public\Desktop",
        str(Path(home) / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"),
        r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
    ]
    return [d for d in dirs if os.path.isdir(d)]


def find_related_shortcuts(app_name: str, deleted_path: str = "") -> List[str]:
    """Find Desktop/Start Menu .lnk files (and app shortcut folders) matching name."""
    name = (app_name or "").strip()
    if not name:
        name = Path(deleted_path).name if deleted_path else ""
    if not name:
        return []

    tokens = {name.lower(), name.lower().replace(" ", "")}
    base = re.sub(r"[\-_ ]?(setup|install|bin|app)$", "", name, flags=re.I).strip()
    if base:
        tokens.add(base.lower())

    found: List[str] = []
    for root in _shortcut_candidate_dirs():
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                try:
                    rel = Path(dirpath).relative_to(root)
                except Exception:
                    rel = Path(".")
                if len(rel.parts) > 3:
                    dirnames.clear()
                    continue
                for fn in filenames:
                    if not fn.lower().endswith(".lnk"):
                        continue
                    stem = Path(fn).stem.lower()
                    if any(t in stem for t in tokens if len(t) >= 3):
                        found.append(str(Path(dirpath) / fn))
                for dn in list(dirnames):
                    if any(t in dn.lower() for t in tokens if len(t) >= 3):
                        folder = str(Path(dirpath) / dn)
                        if folder not in found:
                            found.append(folder)
        except Exception:
            continue

    seen = set()
    out: List[str] = []
    for f in found:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out[:30]


def cleanup_app_shortcuts(app_name: str, deleted_path: str = "") -> List[str]:
    """Delete related Desktop/Start Menu shortcuts. Returns removed paths."""
    targets = find_related_shortcuts(app_name, deleted_path)
    removed: List[str] = []
    for t in targets:
        try:
            tp = Path(t)
            if not tp.exists():
                continue
            if tp.is_dir():
                shutil.rmtree(str(tp), onerror=_force_remove_readonly)
            else:
                try:
                    tp.unlink()
                except PermissionError:
                    os.chmod(str(tp), stat.S_IWRITE)
                    tp.unlink()
            removed.append(str(tp))
        except Exception:
            continue
    return removed


def delete_path(path: str, cleanup_shortcuts: bool = True) -> str:
    try:
        pth = Path(path)
        if not pth.exists():
            return f"Path not found: {path}"

        app_label = pth.name
        messages: List[str] = []

        if pth.is_dir():
            shutil.rmtree(path, onerror=_force_remove_readonly)
            messages.append(f"Deleted folder: {path}")
        else:
            try:
                pth.unlink()
            except PermissionError:
                os.chmod(path, stat.S_IWRITE)
                pth.unlink()
            messages.append(f"Deleted file: {path}")

        if cleanup_shortcuts:
            removed = cleanup_app_shortcuts(app_label, deleted_path=path)
            for r in removed:
                messages.append(f"Removed shortcut: {r}")
            if not any("shortcut" in m.lower() for m in messages):
                for desk in (
                    Path.home() / "Desktop" / f"{app_label}.lnk",
                    Path(r"C:\Users\Public\Desktop") / f"{app_label}.lnk",
                ):
                    if desk.exists():
                        try:
                            desk.unlink()
                            messages.append(f"Removed shortcut: {desk}")
                        except Exception:
                            pass

        return " | ".join(messages) if messages else f"Deleted: {path}"
    except Exception as e:
        return f"Delete failed: {e}"


def rename_path(path: str, new_name: str) -> str:
    try:
        p = Path(path)
        if not p.exists():
            return f"Path not found: {path}"
        new_path = p.parent / new_name
        if new_path.exists():
            return f"Already exists: {new_path}"
        p.rename(new_path)
        return f"Renamed to: {new_path}"
    except Exception as e:
        return f"Rename failed: {e}"


def copy_to_clipboard(path: str) -> str:
    try:
        subprocess.run(["clip"], input=path.encode("utf-8"), capture_output=True)
        return f"Path copied to clipboard: {path}"
    except Exception as e:
        return f"Clipboard copy failed: {e}"


def read_file_safe(path: str) -> Optional[str]:
    """Read a text file up to 100 KB. Returns None if binary or unreadable."""
    try:
        size = os.path.getsize(path)
        with open(path, "r", encoding="utf-8", errors="strict") as f:
            content = f.read(_MAX_READ_BYTES)
        if size > _MAX_READ_BYTES:
            content += f"\n\n[...truncated — file is {format_size(size)}, showing first 100 KB]"
        return content
    except UnicodeDecodeError:
        return None  # binary file
    except Exception:
        return None


def format_size(n: Optional[int]) -> str:
    if n is None:
        return "—"
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024:
            return f"{value:.1f} {unit}" if value != int(value) else f"{int(value)} {unit}"
        value /= 1024
    return f"{value:.1f} PB"
