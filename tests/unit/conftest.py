import pytest
from rhoai_obs_mcp.config import Settings
from rhoai_obs_mcp.auth import AuthProvider


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        thanos_url="https://thanos.test:9091",
        alertmanager_url="https://alertmanager.test:9093",
        loki_url="https://loki.test:8080",
        grafana_url="https://grafana.test:3000",
        tempo_url="https://tempo.test:8080",
        openshift_token="test-token",
    )


@pytest.fixture
def auth(settings):
    return AuthProvider(settings)
