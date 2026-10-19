"""Canonical fix_id -> (module method name, human label) per domain.

Single source of truth for:
  - Planner validation (hallucinated fix_ids are dropped before the gate)
  - Executor dispatch (fix_id -> method name, never by string eval)
  - Permission Gate labels (human-readable, not hardcoded per-domain)

Adding a new domain:
  1. Add an entry here with its strategy chain.
  2. Add the corresponding methods to the executor module.
  3. Create *_graph.py that calls build_action_graph().
"""
from __future__ import annotations

FIX_REGISTRY: dict[str, dict[str, tuple[str, str]]] = {
    "NETWORK": {
        "flush_dns":      ("fix_flush_dns_only", "Flush DNS Cache"),
        "set_public_dns": ("fix_dns",            "Set Public DNS (Cloudflare/Google)"),
        "renew_ip":       ("fix_renew_ip",       "Release / Renew IP"),
        "reset_adapter":  ("fix_reset_adapter",  "Reset Network Adapter"),
        "dns_dhcp":       ("fix_dns_dhcp",       "Restore DNS to DHCP"),
        "tcp_reset":      ("fix_tcp_reset",      "Reset TCP Stack"),
        "winsock_reset":  ("fix_winsock_reset",  "Reset Winsock + IP"),
    },
    "STORAGE": {
        "clean_temp":         ("fix_temp",              "Clean Temp Files"),
        "clean_browser_cache":("fix_browser_cache",     "Clear Browser Cache"),
        "clean_system_cache": ("fix_system_cache",      "Clear System Cache"),
        "empty_recycle_bin":  ("fix_recycle_bin",       "Empty Recycle Bin"),
        "delete_duplicates":  ("fix_delete_duplicates", "Remove Duplicate Files"),
        "partition_wizard":   ("partition_wizard",      "Launch Partition Wizard"),
    },
    "DEV_ENV": {
        "fix_path":      ("fix_path",         "Fix Python PATH"),
        "fix_pip":       ("fix_pip",          "Repair pip"),
        "rebuild_venv":  ("fix_rebuild_venv", "Rebuild Virtual Environment"),
        "pin_conflict":  ("fix_pin_conflict", "Pin Conflicting Package"),
    },
    "SYSTEM": {
        "kill_high_ram":      ("fix_kill_processes",  "Kill High-RAM Processes"),
        "set_power_balanced": ("fix_power_balanced",  "Set Power Plan to Balanced"),
        "restart_explorer":   ("restart_explorer",    "Restart Explorer"),
    },
    "UPDATE": {
        "standard_upgrade": ("upgrade_package",        "Upgrade via package manager"),
        "force_upgrade":    ("force_upgrade_package",  "Force upgrade (override checks)"),
        "reinstall":        ("reinstall_package",      "Uninstall and reinstall fresh"),
        "purge_reinstall":  ("purge_reinstall_package","Force purge and reinstall (technology mismatch)"),
    },
    "INSTALL": {
        "install":         ("install_package",       "Install package (not yet on system)"),
        "force_install":   ("force_install_package", "Force install (override partial state)"),
        "purge_reinstall": ("purge_reinstall_package","Purge any remnants then install fresh"),
    },
    "UNINSTALL": {
        "uninstall":       ("uninstall_package",       "Remove package via package manager"),
        "force_uninstall": ("force_uninstall_package", "Force remove (override running processes)"),
        "purge_uninstall": ("purge_uninstall_package", "Purge package and all remaining files"),
    },
}

KNOWN_VERIFICATIONS = {"dns_lookup"}


def known_fix_ids(domain: str) -> set[str]:
    return set(FIX_REGISTRY.get(domain, {}).keys())


def fix_label(domain: str, fix_id: str) -> str:
    return FIX_REGISTRY.get(domain, {}).get(fix_id, (None, fix_id))[1]


def fix_method_name(domain: str, fix_id: str) -> str | None:
    entry = FIX_REGISTRY.get(domain, {}).get(fix_id)
    return entry[0] if entry else None
