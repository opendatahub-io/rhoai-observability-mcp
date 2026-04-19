import logging

from mcp.server.fastmcp import FastMCP

from rhoai_obs_mcp.auth import AuthProvider
from rhoai_obs_mcp.backends.alertmanager import AlertmanagerBackend
from rhoai_obs_mcp.backends.grafana import GrafanaBackend
from rhoai_obs_mcp.backends.loki import LokiBackend
from rhoai_obs_mcp.backends.openshift import OpenShiftBackend
from rhoai_obs_mcp.backends.prometheus import PrometheusBackend
from rhoai_obs_mcp.backends.tempo import TempoBackend
from rhoai_obs_mcp.config import Settings
from rhoai_obs_mcp.tools.alerts import register_alert_tools
from rhoai_obs_mcp.tools.cluster import register_cluster_tools
from rhoai_obs_mcp.tools.dashboards import register_dashboard_tools
from rhoai_obs_mcp.tools.investigate import register_investigation_tools
from rhoai_obs_mcp.tools.logs import register_log_tools
from rhoai_obs_mcp.tools.metrics import register_metrics_tools
from rhoai_obs_mcp.tools.traces import register_trace_tools

logger = logging.getLogger(__name__)


def _log_backend_status(settings: Settings) -> None:
    """Log the status of each backend at startup."""
    mode = "in-cluster" if settings.is_in_cluster else "external"
    logger.info("Running in %s mode", mode)

    backends = [
        ("Prometheus (Thanos)", settings.thanos_url),
        ("Alertmanager", settings.alertmanager_url),
        ("Grafana", settings.grafana_url),
        ("Loki", settings.loki_url),
        ("Tempo", settings.tempo_url),
    ]
    for name, url in backends:
        if url:
            logger.info("  %s: %s", name, url)
        else:
            logger.info("  %s: disabled (not configured)", name)


def create_server(
    settings_override: dict | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    """Create and configure the RHOAI Observability MCP server."""
    settings = Settings(_env_file=None, **(settings_override or {}))  # type: ignore[call-arg]

    logging.basicConfig(level=getattr(logging, settings.log_level))
    _log_backend_status(settings)

    auth = AuthProvider(settings)

    # Initialize backends
    prometheus = PrometheusBackend(settings, auth)
    alertmanager = AlertmanagerBackend(settings, auth)
    loki = LokiBackend(settings, auth)
    grafana = GrafanaBackend(settings, auth)
    openshift = OpenShiftBackend(settings, auth)
    tempo = TempoBackend(settings, auth)

    # Create FastMCP server
    mcp = FastMCP(
        name="rhoai-observability",
        instructions=(
            "You are an OpenShift AI observability assistant. "
            "Use the available tools to query metrics, logs, alerts, "
            "and cluster state to help troubleshoot vLLM inference workloads. "
            "For complex issues, use the investigate_* tools to correlate data "
            "across multiple sources."
        ),
        host=host,
        port=port,
    )

    # Register all tools
    tool_groups = [
        register_metrics_tools(prometheus),
        register_alert_tools(alertmanager),
        register_log_tools(loki),
        register_cluster_tools(openshift),
        register_dashboard_tools(grafana),
        register_trace_tools(tempo),
        register_investigation_tools(prometheus, alertmanager, loki, openshift, tempo),
    ]

    for group in tool_groups:
        for name, func in group.items():
            mcp.tool(name=name)(func)

    return mcp
