"""Read-only NETWORK tools for the planner (LangChain tools)."""
from __future__ import annotations

from langchain_core.tools import tool


def make_network_tools(network_module) -> list:
    @tool
    def get_network_status() -> dict:
        """Live network telemetry: gateway, ping, packet loss, DNS, Wi-Fi, internet."""
        return network_module.collect()

    @tool
    def get_active_interface() -> str:
        """Name of the active network interface (Wi-Fi/Ethernet) used for fixes."""
        return network_module.get_active_interface()

    @tool
    def list_network_interfaces() -> list:
        """All network interface names known to the OS."""
        return network_module.list_interfaces()

    @tool
    def generate_isp_report() -> str:
        """Formatted connectivity report for ISP/support. Does not change settings."""
        return network_module.generate_isp_report()

    @tool
    def ping_host(host: str) -> str:
        """Ping a host once; returns latency ms or timeout."""
        result = network_module._ping(host)
        return str(result)

    @tool
    def get_wifi_password(ssid: str = "") -> dict:
        """Saved Wi-Fi password for an SSID (Windows). Empty ssid = current network."""
        return network_module.get_wifi_password(ssid or None)

    @tool
    def run_speed_test(duration: int = 10) -> dict:
        """Run LibreSpeed-compatible internet speed test (Python client)."""
        return network_module.run_speedtest(duration=duration)

    return [
        get_network_status,
        get_active_interface,
        list_network_interfaces,
        generate_isp_report,
        ping_host,
        get_wifi_password,
        run_speed_test,
    ]