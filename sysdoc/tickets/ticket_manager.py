import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG_DIR = Path.home() / ".fixbot" / "tickets"
LOG_DIR.mkdir(parents=True, exist_ok=True)
REGISTRY = LOG_DIR / "ticket_registry.json"


class TicketManager:
    def create_ticket(
        self,
        problem: str,
        os_data: Dict[str, Any],
        gemini_reply: str,
        module: str,
        priority: Optional[str] = None,
    ) -> Dict[str, Any]:
        if priority is None:
            priority = self.determine_priority(module, os_data)

        # Fix #12 — count by file glob, no full registry read just for a count
        ticket_id = str(1000 + self._count_tickets())
        created = datetime.utcnow().isoformat() + "Z"
        ticket = {
            "id": ticket_id,
            "status": "OPEN",
            "priority": priority,
            "module": module,
            "problem": problem,
            "created": created,
            "gemini_reply": gemini_reply,
            "os_data": os_data,
        }

        try:
            file_path = LOG_DIR / f"diagnostic_{ticket_id}.json"
            with file_path.open("w", encoding="utf-8") as handle:
                json.dump(ticket, handle, indent=2)
        except Exception:
            pass

        summary = {
            "id": ticket_id,
            "status": "OPEN",
            "priority": priority,
            "module": module,
            "problem": problem,
            "created": created,
        }
        self._register(summary)
        return ticket

    def determine_priority(self, module: str, os_data: Dict[str, Any]) -> str:
        module_key = (module or "").upper()

        def parse_number(value: Any) -> float:
            try:
                return float(value)
            except Exception:
                if isinstance(value, str):
                    found = [s for s in value.split() if self._is_number_like(s)]
                    if found:
                        try:
                            return float(found[0])
                        except Exception:
                            return 0.0
                return 0.0

        if module_key == "SYSTEM":
            cpu_temp = parse_number(os_data.get("cpu_temp_c"))
            if cpu_temp >= 85:
                return "HIGH"
            recent = os_data.get("recent_crashes", [])
            if isinstance(recent, list) and len(recent) >= 3:
                return "HIGH"
            if cpu_temp >= 70:
                return "MEDIUM"
            return "LOW"

        if module_key == "STORAGE":
            for drive in os_data.get("drives", []):
                try:
                    dev = str(drive.get("device", "") or drive.get("mountpoint", "")).upper()
                    if dev.startswith("C:"):
                        if parse_number(drive.get("used_pct", 0)) >= 94:
                            return "HIGH"
                except Exception:
                    continue
            return "LOW"

        if module_key == "NETWORK":
            dl = parse_number(os_data.get("download_mbps", 0))
            if 0 < dl < 5:
                return "HIGH"
            return "LOW"

        if module_key == "DEV_ENV":
            return "MEDIUM"

        return "LOW"

    def list_tickets(self) -> List[Dict[str, Any]]:
        if not REGISTRY.exists():
            return []
        try:
            with REGISTRY.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
                return data if isinstance(data, list) else []
        except Exception:
            return []

    def get_ticket(self, ticket_id: str) -> Dict[str, Any]:
        try:
            file_path = LOG_DIR / f"diagnostic_{ticket_id}.json"
            if not file_path.exists():
                return {}
            with file_path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:
            return {}

    def close_ticket(self, ticket_id: str) -> None:
        resolved = datetime.utcnow().isoformat() + "Z"
        try:
            ticket = self.get_ticket(ticket_id)
            if ticket:
                ticket["status"] = "CLOSED"
                ticket["resolved"] = resolved
                file_path = LOG_DIR / f"diagnostic_{ticket_id}.json"
                with file_path.open("w", encoding="utf-8") as handle:
                    json.dump(ticket, handle, indent=2)
        except Exception:
            pass

        try:
            registry = self.list_tickets()
            updated = []
            for record in registry:
                if str(record.get("id")) == ticket_id:
                    record["status"] = "CLOSED"
                    record["resolved"] = resolved
                updated.append(record)
            self._write_registry(updated)
        except Exception:
            pass

    def export_zip(self) -> str:
        zip_path = Path("sysdoc_logs.zip")
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for file_path in LOG_DIR.glob("diagnostic_*.json"):
                    try:
                        archive.write(file_path, arcname=file_path.name)
                    except Exception:
                        continue
        except Exception:
            pass
        return str(zip_path.resolve())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _count_tickets(self) -> int:
        # Fix #12 — count by globbing files, no JSON deserialization needed
        return len(list(LOG_DIR.glob("diagnostic_*.json")))

    def _register(self, ticket_summary: Dict[str, Any]) -> None:
        registry = self.list_tickets()
        registry.append(ticket_summary)
        self._write_registry(registry)

    def _write_registry(self, data: List[Dict[str, Any]]) -> None:
        # Fix #12 — atomic write via temp file + rename to avoid corruption
        tmp = REGISTRY.with_suffix(".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
            tmp.replace(REGISTRY)
        except Exception:
            pass

    @staticmethod
    def _is_number_like(value: str) -> bool:
        try:
            float(value)
            return True
        except Exception:
            return False
