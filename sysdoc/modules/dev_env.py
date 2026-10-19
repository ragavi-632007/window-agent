import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List


class DevEnvironmentModule:
    def collect(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "python_paths_found": self._find_all_python(),
            "python_in_path": "YES" if shutil.which("python") else "NO",
            "active_python": self._command_version(["python", "--version"]),
            "pip_status": "BROKEN",
            "pip_version": "NOT FOUND",
            "dependency_conflicts": "none",
            "node_version": self._command_version(["node", "--version"]),
            "npm_version": self._command_version(["npm", "--version"]),
            "venv_found": Path(".venv").exists() or Path("venv").exists(),
            "path_entries": os.environ.get("PATH", "").split(os.pathsep),
        }

        pip_result = self._run_command(["pip", "--version"])
        if pip_result["returncode"] == 0:
            result["pip_status"] = "OK"
            result["pip_version"] = pip_result["stdout"].strip()
        else:
            result["pip_status"] = "BROKEN"
            result["pip_version"] = pip_result["stderr"].strip() or "NOT FOUND"

        pip_check = self._run_command(["pip", "check"])
        if pip_check["returncode"] != 0:
            result["dependency_conflicts"] = pip_check["stdout"].strip() or pip_check["stderr"].strip()

        return result

    def fix_path(self) -> str:
        python_paths = self._find_all_python()
        if not python_paths:
            return "No python.exe paths found"

        best_path = max(python_paths, key=self._version_from_path)
        parent = Path(best_path).parent
        scripts = parent / "Scripts"

        if platform.system().lower() != "windows":
            return "Path fix only supported on Windows"

        # Fix #3 — expand PATH ourselves; no shell=True with f-string interpolation
        current_path = os.environ.get("PATH", "")
        new_path = f"{current_path};{parent};{scripts}"
        result = subprocess.run(
            ["setx", "PATH", new_path],
            shell=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return f"PATH updated with {parent} and {scripts}"
        return f"PATH update failed: {result.stderr.strip() or result.stdout.strip()}"

    def fix_pip(self) -> str:
        python_exe = shutil.which("python") or "python"
        result = subprocess.run(
            [python_exe, "-m", "pip", "install", "--upgrade", "pip"],
            capture_output=True,
            text=True,
        )
        return f"returncode={result.returncode}\n{result.stdout.strip()}\n{result.stderr.strip()}"

    def fix_rebuild_venv(self, project_path: str = ".") -> str:
        project = Path(project_path)
        venv_dir = project / ".venv"
        if venv_dir.exists():
            try:
                shutil.rmtree(venv_dir)
            except Exception as error:
                return f"Failed to delete existing .venv: {error}"

        python_exe = shutil.which("python") or "python"
        result = subprocess.run(
            [python_exe, "-m", "venv", str(venv_dir)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return f"venv creation failed: {result.stderr.strip() or result.stdout.strip()}"

        pip_path = (
            venv_dir / "Scripts" / "pip.exe"
            if platform.system().lower() == "windows"
            else venv_dir / "bin" / "pip"
        )
        if not pip_path.exists():
            return "venv created but pip not found"

        if (project / "requirements.txt").exists():
            install = subprocess.run(
                [str(pip_path), "install", "-r", str(project / "requirements.txt")],
                capture_output=True,
                text=True,
            )
            if install.returncode != 0:
                return f"requirements install failed: {install.stderr.strip() or install.stdout.strip()}"

        check = subprocess.run([str(pip_path), "check"], capture_output=True, text=True)
        return f"pip check returncode={check.returncode}\n{check.stdout.strip()}\n{check.stderr.strip()}"

    def fix_pin_conflict(self, package: str, version: str) -> str:
        python_exe = shutil.which("python") or "python"
        install = subprocess.run(
            [python_exe, "-m", "pip", "install", f"{package}=={version}"],
            capture_output=True,
            text=True,
        )
        check = subprocess.run([python_exe, "-m", "pip", "check"], capture_output=True, text=True)
        return (
            f"install_returncode={install.returncode}\n"
            f"{install.stdout.strip()}\n{install.stderr.strip()}\n"
            f"pip_check_returncode={check.returncode}\n"
            f"{check.stdout.strip()}\n{check.stderr.strip()}"
        )

    def _find_all_python(self) -> List[str]:
        result: List[str] = []
        seen: set = set()

        found = shutil.which("python")
        if found:
            result.append(found)
            seen.add(found.lower())

        common_roots = [
            Path(os.environ.get("LOCALAPPDATA", "C:\\Users")) / "Programs" / "Python",
            Path("C:\\Python"),
            Path("C:\\Program Files\\Python"),
            Path("C:\\Program Files (x86)\\Python"),
        ]
        for root in common_roots:
            if not root.exists():
                continue
            try:
                for child in root.iterdir():
                    if child.is_dir():
                        candidate = child / "python.exe"
                        if candidate.is_file() and str(candidate).lower() not in seen:
                            result.append(str(candidate))
                            seen.add(str(candidate).lower())
            # Fix #23 — catch OSError too (symlinks, junctions, access errors)
            except (PermissionError, OSError):
                continue
        return result

    def _command_version(self, command: List[str]) -> str:
        try:
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip() or result.stderr.strip()
        except Exception:
            pass
        return "NOT FOUND"

    def _run_command(self, command: List[str]) -> Dict[str, Any]:
        try:
            result = subprocess.run(command, capture_output=True, text=True)
            return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        except Exception as error:
            return {"returncode": 1, "stdout": "", "stderr": str(error)}

    def _version_from_path(self, path: str) -> List[int]:
        matches = re.findall(r"(\d+(?:\.\d+)+)", path)
        best: List[int] = [0]
        for match in matches:
            parts = [int(p) for p in match.split(".") if p.isdigit()]
            if parts > best:
                best = parts
        return best
