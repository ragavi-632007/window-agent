import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".gitpilot"
ENV_FILE = CONFIG_DIR / ".env"


def ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def get_api_key() -> str | None:
    # Reuse FixBot's existing GEMINI_API_KEY — no separate setup needed
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    # Fallback: GitPilot's own persisted key
    ensure_config_dir()
    if ENV_FILE.exists():
        with open(ENV_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("GEMINI_API_KEY="):
                    k = line.split("=", 1)[1].strip()
                    if k:
                        return k
    return None


def save_api_key(key: str):
    ensure_config_dir()
    with open(ENV_FILE, "w") as f:
        f.write(f"GEMINI_API_KEY={key}\n")


def clear_api_key():
    if ENV_FILE.exists():
        ENV_FILE.unlink()
