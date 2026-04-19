from unittest.mock import patch

from rhoai_obs_mcp.config import Settings, _IN_CLUSTER_DEFAULTS


class TestSettings:
    def test_defaults(self):
        """Settings should have sensible defaults."""
        settings = Settings(
            _env_file=None,  # don't read .env in tests
        )
        assert settings.default_time_range == "5m"
        assert settings.log_level == "INFO"
        assert settings.request_timeout == 30.0

    def test_env_override(self, monkeypatch):
        """Environment variables should override defaults."""
        monkeypatch.setenv("THANOS_URL", "https://thanos.example.com")
        monkeypatch.setenv("DEFAULT_TIME_RANGE", "15m")
        settings = Settings(_env_file=None)
        assert settings.thanos_url == "https://thanos.example.com"
        assert settings.default_time_range == "15m"

    def test_all_backend_urls_optional(self):
        """All backend URLs should be optional (auto-detected later)."""
        settings = Settings(_env_file=None)
        assert settings.thanos_url is None
        assert settings.alertmanager_url is None
        assert settings.loki_url is None
        assert settings.grafana_url is None

    def test_is_in_cluster_false_by_default(self):
        """Should detect as external when no SA token exists."""
        settings = Settings(_env_file=None)
        assert isinstance(settings.is_in_cluster, bool)


class TestLokiEnabled:
    def test_loki_enabled_when_url_set(self):
        settings = Settings(_env_file=None, loki_url="https://loki.test:8080")
        assert settings.loki_enabled is True

    def test_loki_disabled_when_url_not_set(self):
        settings = Settings(_env_file=None)
        assert settings.loki_enabled is False


class TestTempoEnabled:
    def test_tempo_enabled_when_url_set(self):
        settings = Settings(_env_file=None, tempo_url="https://tempo.test:8080")
        assert settings.tempo_enabled is True

    def test_tempo_disabled_when_url_not_set(self):
        settings = Settings(_env_file=None)
        assert settings.tempo_enabled is False


class TestInClusterAutoDetection:
    def test_auto_detection_applies_defaults_in_cluster(self):
        with patch("rhoai_obs_mcp.config._SA_TOKEN_PATH") as mock_path:
            mock_path.exists.return_value = True
            settings = Settings(_env_file=None)

        assert settings.thanos_url == _IN_CLUSTER_DEFAULTS["thanos_url"]
        assert settings.alertmanager_url == _IN_CLUSTER_DEFAULTS["alertmanager_url"]
        assert settings.grafana_url == _IN_CLUSTER_DEFAULTS["grafana_url"]

    def test_loki_not_auto_detected_in_cluster(self):
        with patch("rhoai_obs_mcp.config._SA_TOKEN_PATH") as mock_path:
            mock_path.exists.return_value = True
            settings = Settings(_env_file=None)

        assert settings.loki_url is None
        assert settings.loki_enabled is False

    def test_env_var_overrides_in_cluster_default(self, monkeypatch):
        monkeypatch.setenv("THANOS_URL", "https://custom-thanos:9091")
        with patch("rhoai_obs_mcp.config._SA_TOKEN_PATH") as mock_path:
            mock_path.exists.return_value = True
            settings = Settings(_env_file=None)

        assert settings.thanos_url == "https://custom-thanos:9091"

    def test_no_auto_detection_outside_cluster(self):
        with patch("rhoai_obs_mcp.config._SA_TOKEN_PATH") as mock_path:
            mock_path.exists.return_value = False
            settings = Settings(_env_file=None)

        assert settings.thanos_url is None
        assert settings.alertmanager_url is None
        assert settings.grafana_url is None
