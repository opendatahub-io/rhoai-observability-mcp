# tests/unit/test_tools_investigate.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from rhoai_obs_mcp.tools.investigate import register_investigation_tools


class TestInvestigationTools:
    def setup_method(self):
        self.prometheus = AsyncMock()
        self.alertmanager = AsyncMock()
        self.loki = AsyncMock()
        self.openshift = MagicMock()
        self.tempo = AsyncMock()
        self.tools = register_investigation_tools(
            self.prometheus, self.alertmanager, self.loki, self.openshift, self.tempo
        )

    @pytest.mark.asyncio
    async def test_investigate_latency(self):
        """Should correlate metrics, logs, and alerts for latency issues."""
        # Mock Prometheus responses
        self.prometheus.query.return_value = {
            "status": "success",
            "data": {"result": [{"metric": {}, "value": [1, "0.85"]}]},
        }
        # Mock Loki response
        self.loki.query_range.return_value = {
            "status": "success",
            "data": {"result": []},
        }
        # Mock Alertmanager response
        self.alertmanager.get_alerts.return_value = []
        # Mock Tempo response
        self.tempo.search.return_value = {
            "traces": [
                {
                    "traceID": "abc123def456",
                    "rootServiceName": "llama",
                    "rootTraceName": "POST /v1/completions",
                    "durationMs": 2500,
                }
            ],
        }

        result = await self.tools["investigate_latency"](model_name="llama")
        assert "llama" in result
        # Should include sections for metrics, logs, alerts
        assert "Latency" in result or "latency" in result
        assert "abc123def456" in result or "Traces" in result

    @pytest.mark.asyncio
    async def test_investigate_gpu(self):
        """Should correlate GPU metrics, cache usage, and pod status."""
        self.prometheus.query.return_value = {
            "status": "success",
            "data": {"result": [{"metric": {}, "value": [1, "0.95"]}]},
        }
        self.openshift.get_pods.return_value = [
            {
                "name": "vllm-0",
                "namespace": "vllm",
                "status": "Running",
                "restarts": 0,
                "created": "2024-01-01",
            },
        ]
        self.alertmanager.get_alerts.return_value = []

        result = await self.tools["investigate_gpu"](time_range="15m")
        assert "GPU" in result or "gpu" in result

    @pytest.mark.asyncio
    async def test_investigate_errors(self):
        """Should correlate error logs, alerts, and pod restarts."""
        self.loki.query_range.return_value = {
            "status": "success",
            "data": {
                "result": [
                    {
                        "stream": {"kubernetes_pod_name": "vllm-0"},
                        "values": [["1", "ERROR: OOM killed"]],
                    }
                ]
            },
        }
        self.alertmanager.get_alerts.return_value = [
            {
                "labels": {"alertname": "KubePodCrashLooping", "severity": "warning"},
                "annotations": {"summary": "Pod crash looping"},
                "status": {"state": "active"},
            },
        ]
        self.openshift.get_events.return_value = [
            {
                "reason": "BackOff",
                "message": "Back-off restarting",
                "type": "Warning",
                "count": 5,
                "object": "Pod/vllm-0",
                "timestamp": "2024-01-01",
            },
        ]

        result = await self.tools["investigate_errors"](namespace="vllm")
        assert "OOM" in result or "error" in result.lower()
        assert "KubePodCrashLooping" in result or "crash" in result.lower()

    @pytest.mark.asyncio
    async def test_investigate_latency_traces_exception(self):
        """Should handle trace fetch raising an exception."""
        self.prometheus.query.return_value = {
            "status": "success",
            "data": {"result": [{"metric": {}, "value": [1, "0.5"]}]},
        }
        self.loki.query_range.return_value = {"status": "success", "data": {"result": []}}
        self.alertmanager.get_alerts.return_value = []
        self.tempo.search.side_effect = RuntimeError("Tempo unavailable")

        result = await self.tools["investigate_latency"](model_name="llama")
        assert "Error fetching traces" in result

    @pytest.mark.asyncio
    async def test_investigate_latency_traces_error_status(self):
        """Should handle trace response with status=error."""
        self.prometheus.query.return_value = {
            "status": "success",
            "data": {"result": [{"metric": {}, "value": [1, "0.5"]}]},
        }
        self.loki.query_range.return_value = {"status": "success", "data": {"result": []}}
        self.alertmanager.get_alerts.return_value = []
        self.tempo.search.return_value = {
            "status": "error",
            "error": "Tempo is not configured. Set TEMPO_URL to enable trace queries.",
        }

        result = await self.tools["investigate_latency"](model_name="llama")
        assert "Traces not available" in result

    @pytest.mark.asyncio
    async def test_investigate_latency_traces_empty(self):
        """Should handle empty trace list."""
        self.prometheus.query.return_value = {
            "status": "success",
            "data": {"result": [{"metric": {}, "value": [1, "0.5"]}]},
        }
        self.loki.query_range.return_value = {"status": "success", "data": {"result": []}}
        self.alertmanager.get_alerts.return_value = []
        self.tempo.search.return_value = {"traces": []}

        result = await self.tools["investigate_latency"](model_name="llama")
        assert "No error traces found" in result

    @pytest.mark.asyncio
    async def test_investigate_latency_traces_non_dict(self):
        """Should handle non-dict trace response (e.g. unexpected type)."""
        self.prometheus.query.return_value = {
            "status": "success",
            "data": {"result": [{"metric": {}, "value": [1, "0.5"]}]},
        }
        self.loki.query_range.return_value = {"status": "success", "data": {"result": []}}
        self.alertmanager.get_alerts.return_value = []
        self.tempo.search.return_value = "unexpected string"

        result = await self.tools["investigate_latency"](model_name="llama")
        assert "No error traces found." in result
