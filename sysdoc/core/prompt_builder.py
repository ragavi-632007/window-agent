from typing import Any, Dict, List

from sysdoc.config import SYSTEM_PROMPT


class PromptBuilder:
    """Formats system data into prompts for Gemini.

    Accepts module instances from the caller (SysDocExecutor) so no duplicate
    instances are created at import time.
    """

    def __init__(self, network=None, storage=None, dev_env=None, system_health=None) -> None:
        from sysdoc.modules.network import NetworkModule
        from sysdoc.modules.storage import StorageModule
        from sysdoc.modules.dev_env import DevEnvironmentModule
        from sysdoc.modules.system_health import SystemHealthModule

        self._network = network if network is not None else NetworkModule()
        self._storage = storage if storage is not None else StorageModule()
        self._dev_env = dev_env if dev_env is not None else DevEnvironmentModule()
        self._system_health = system_health if system_health is not None else SystemHealthModule()

        self._module_map: Dict[str, Any] = {
            "NETWORK": self._network,
            "STORAGE": self._storage,
            "DEV_ENV": self._dev_env,
            "SYSTEM": self._system_health,
        }

    def build_context(self, user_input: str, intent: str) -> Dict[str, Any]:
        intent_key = (intent or "").upper()

        if intent_key in {"SCAN", "GENERAL"}:
            merged: Dict[str, Any] = {}
            for module in [self._network, self._dev_env, self._system_health, self._storage]:
                merged.update(module.collect())
            return merged

        if intent_key == "TICKET":
            return self._system_health.collect()

        module = self._module_map.get(intent_key)
        if module is not None:
            return module.collect()
        return {}

    def format_for_gemini(self, os_data: Dict[str, Any]) -> str:
        if not os_data:
            return ""
        lines: List[str] = []
        keys = list(os_data.keys())
        for index, key in enumerate(keys):
            if index >= 40:
                lines.append(f"...{len(keys) - 40} more keys omitted")
                break
            value = os_data[key]
            if isinstance(value, dict):
                lines.append(f"{key}:")
                lines.extend(self._format_dict(value, indent=1))
            else:
                lines.append(f"{key}: {self._format_value(value)}")
        return "\n".join(lines)

    def _format_dict(self, value: Dict[str, Any], indent: int = 0) -> List[str]:
        lines: List[str] = []
        prefix = "  " * indent
        for subkey, subval in value.items():
            if isinstance(subval, dict):
                lines.append(f"{prefix}{subkey}:")
                lines.extend(self._format_dict(subval, indent=indent + 1))
            else:
                lines.append(f"{prefix}{subkey}: {self._format_value(subval)}")
        return lines

    def _format_value(self, value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.2f}"
        if isinstance(value, dict):
            return ", ".join(f"{k}={self._format_value(v)}" for k, v in value.items())
        if isinstance(value, list):
            formatted = []
            for item in value:
                if isinstance(item, dict):
                    formatted.append("{" + ", ".join(f"{k}={self._format_value(v)}" for k, v in item.items()) + "}")
                else:
                    formatted.append(self._format_value(item))
            return ", ".join(formatted)
        return str(value)

    def build_support_prompt(self, user_issue: str, context: str = "") -> str:
        parts = [SYSTEM_PROMPT, "", "Issue:", user_issue]
        if context:
            parts.extend(["", "System context:", context])
        parts.append("\nProvide the best terminal-friendly support response.")
        return "\n".join(parts)

    def build_scan_prompt(self, summary: str) -> str:
        return self.build_support_prompt(
            "Run a full system health scan and summarize findings.", summary
        )
