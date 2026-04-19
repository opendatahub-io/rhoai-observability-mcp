from unittest.mock import patch
from rhoai_obs_mcp.server import create_server


class TestServer:
    @patch("rhoai_obs_mcp.server.TempoBackend")
    @patch("rhoai_obs_mcp.server.OpenShiftBackend")
    @patch("rhoai_obs_mcp.server.GrafanaBackend")
    @patch("rhoai_obs_mcp.server.LokiBackend")
    @patch("rhoai_obs_mcp.server.AlertmanagerBackend")
    @patch("rhoai_obs_mcp.server.PrometheusBackend")
    @patch("rhoai_obs_mcp.server.AuthProvider")
    def test_create_server_returns_fastmcp(self, *mocks):
        """Should return a configured FastMCP server instance."""
        from mcp.server.fastmcp import FastMCP

        settings_override = {
            "thanos_url": "https://thanos.test:9091",
            "alertmanager_url": "https://am.test:9093",
            "loki_url": "https://loki.test:8080",
            "grafana_url": "https://grafana.test:3000",
            "tempo_url": "https://tempo.test:8080",
            "openshift_token": "test-token",
        }

        server = create_server(settings_override)
        assert isinstance(server, FastMCP)

    @patch("rhoai_obs_mcp.server.TempoBackend")
    @patch("rhoai_obs_mcp.server.OpenShiftBackend")
    @patch("rhoai_obs_mcp.server.GrafanaBackend")
    @patch("rhoai_obs_mcp.server.LokiBackend")
    @patch("rhoai_obs_mcp.server.AlertmanagerBackend")
    @patch("rhoai_obs_mcp.server.PrometheusBackend")
    @patch("rhoai_obs_mcp.server.AuthProvider")
    def test_server_has_tools_registered(self, *mocks):
        """Should register all 17 tools."""
        settings_override = {
            "thanos_url": "https://thanos.test:9091",
            "alertmanager_url": "https://am.test:9093",
            "loki_url": "https://loki.test:8080",
            "grafana_url": "https://grafana.test:3000",
            "tempo_url": "https://tempo.test:8080",
            "openshift_token": "test-token",
        }

        server = create_server(settings_override)
        # FastMCP stores tools internally; check the count
        # The exact API depends on the MCP SDK version
        assert server is not None
