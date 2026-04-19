from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

_SA_TOKEN_PATH = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")

_IN_CLUSTER_DEFAULTS: dict[str, str] = {
    "thanos_url": "https://thanos-querier.openshift-monitoring.svc.cluster.local:9091",
    "alertmanager_url": "https://alertmanager-main.openshift-monitoring.svc.cluster.local:9094",
    "grafana_url": "https://grafana.open-cluster-management-observability.svc.cluster.local:3001",
    # Loki intentionally omitted — not available in standard RHOAI clusters
}


class Settings(BaseSettings):
    """Configuration for the RHOAI Observability MCP server."""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # Backend URLs (auto-detected if not set)
    thanos_url: str | None = Field(default=None, description="ThanosQuerier URL")
    alertmanager_url: str | None = Field(default=None, description="Alertmanager URL")
    loki_url: str | None = Field(default=None, description="LokiStack gateway URL")
    grafana_url: str | None = Field(default=None, description="Grafana URL")
    tempo_url: str | None = Field(default=None, description="Tempo gateway URL")

    # Auth
    openshift_token: str | None = Field(default=None, description="Bearer token override")

    # Behavior
    default_time_range: str = Field(default="5m", description="Default PromQL/LogQL time range")
    log_level: str = Field(default="INFO", description="Logging level")
    request_timeout: float = Field(default=30.0, description="HTTP request timeout in seconds")

    @property
    def is_in_cluster(self) -> bool:
        """Detect if running inside an OpenShift/Kubernetes cluster."""
        return _SA_TOKEN_PATH.exists()

    @property
    def loki_enabled(self) -> bool:
        """Whether Loki log queries are available."""
        return self.loki_url is not None

    @property
    def tempo_enabled(self) -> bool:
        """Whether Tempo trace queries are available."""
        return self.tempo_url is not None

    @model_validator(mode="after")
    def _apply_in_cluster_defaults(self) -> "Settings":
        """Apply well-known service DNS URLs when running in-cluster."""
        if not self.is_in_cluster:
            return self
        for field_name, default_url in _IN_CLUSTER_DEFAULTS.items():
            if getattr(self, field_name) is None:
                object.__setattr__(self, field_name, default_url)
        return self
