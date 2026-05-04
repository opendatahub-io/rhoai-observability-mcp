# tests/unit/test_tools_metrics.py
from unittest.mock import AsyncMock, patch

import pytest

from rhoai_obs_mcp.tools.metrics import _relative_to_epoch, register_metrics_tools

FIXED_NOW = 1710000000.0


class TestMetricsTools:
    def setup_method(self):
        self.prometheus = AsyncMock()
        self.tools = register_metrics_tools(self.prometheus)

    @pytest.mark.asyncio
    async def test_query_prometheus(self):
        """Should forward PromQL query to backend."""
        self.prometheus.query.return_value = {
            "status": "success",
            "data": {"result": [{"metric": {"__name__": "up"}, "value": [1, "1"]}]},
        }

        result = await self.tools["query_prometheus"](query="up")
        assert "success" in result
        self.prometheus.query.assert_called_once_with("up", time=None)

    @pytest.mark.asyncio
    async def test_get_vllm_metrics(self):
        """Should fetch and format vLLM metrics."""
        self.prometheus.query.return_value = {
            "status": "success",
            "data": {"result": [{"metric": {}, "value": [1, "0.42"]}]},
        }

        result = await self.tools["get_vllm_metrics"](model_name="llama")
        assert "llama" in result or "0.42" in result

    @pytest.mark.asyncio
    async def test_get_vllm_metrics_includes_preempted_by_default(self):
        """Should include preempted metric in the default metric set."""
        self.prometheus.query.return_value = {
            "status": "success",
            "data": {"result": [{"metric": {}, "value": [1, "3"]}]},
        }

        result = await self.tools["get_vllm_metrics"](model_name="llama")
        assert "Requests Preempted" in result

    @pytest.mark.asyncio
    async def test_get_vllm_metrics_preempted_uses_gauge_query(self):
        """Should query preempted as a raw gauge, not wrapped in rate()."""
        self.prometheus.query.return_value = {
            "status": "success",
            "data": {"result": [{"metric": {}, "value": [1, "5"]}]},
        }

        await self.tools["get_vllm_metrics"](model_name="llama", metrics="preempted")
        self.prometheus.query.assert_called_once_with(
            'vllm:num_requests_preempted{model_name="llama"}'
        )

    @pytest.mark.asyncio
    async def test_list_metrics(self):
        """Should list and optionally filter metrics."""
        self.prometheus.list_metrics.return_value = [
            "vllm:num_requests_running",
            "vllm:kv_cache_usage_perc",
            "node_cpu_seconds_total",
        ]

        result = await self.tools["list_metrics"](filter="vllm")
        assert "vllm:num_requests_running" in result
        assert "node_cpu_seconds_total" not in result

    @pytest.mark.asyncio
    async def test_query_prometheus_range(self):
        """Should forward range query with resolved timestamps."""
        self.prometheus.query_range.return_value = {
            "status": "success",
            "data": {
                "resultType": "matrix",
                "result": [
                    {
                        "metric": {"__name__": "DCGM_FI_DEV_GPU_UTIL", "gpu": "0"},
                        "values": [
                            [1710000000, "45"],
                            [1710000060, "92"],
                            [1710000120, "88"],
                        ],
                    }
                ],
            },
        }

        result = await self.tools["query_prometheus_range"](
            query="DCGM_FI_DEV_GPU_UTIL", start="1h", end="now", step="60s"
        )
        assert "success" in result
        assert "matrix" in result
        assert "92" in result
        self.prometheus.query_range.assert_called_once()
        call_kwargs = self.prometheus.query_range.call_args
        assert call_kwargs.kwargs["promql"] == "DCGM_FI_DEV_GPU_UTIL"
        assert call_kwargs.kwargs["step"] == "60s"

    @pytest.mark.asyncio
    @patch("rhoai_obs_mcp.tools.metrics.time")
    async def test_query_prometheus_range_relative_start(self, mock_time):
        """Should convert relative time strings to epoch timestamps."""
        mock_time.time.return_value = FIXED_NOW
        self.prometheus.query_range.return_value = {
            "status": "success",
            "data": {"resultType": "matrix", "result": []},
        }

        await self.tools["query_prometheus_range"](query="up", start="30m", end="now", step="15s")
        call_kwargs = self.prometheus.query_range.call_args.kwargs
        assert call_kwargs["start"] == str(FIXED_NOW - 1800)
        assert call_kwargs["end"] == str(FIXED_NOW)

    @pytest.mark.asyncio
    @patch("rhoai_obs_mcp.tools.metrics.time")
    async def test_query_prometheus_range_relative_end(self, mock_time):
        """Should support relative durations for both start and end."""
        mock_time.time.return_value = FIXED_NOW
        self.prometheus.query_range.return_value = {
            "status": "success",
            "data": {"resultType": "matrix", "result": []},
        }

        await self.tools["query_prometheus_range"](query="up", start="3h", end="1h", step="60s")
        call_kwargs = self.prometheus.query_range.call_args.kwargs
        assert call_kwargs["start"] == str(FIXED_NOW - 10800)
        assert call_kwargs["end"] == str(FIXED_NOW - 3600)

    @pytest.mark.asyncio
    async def test_query_prometheus_range_backend_error(self):
        """Should return error JSON when backend fails."""
        self.prometheus.query_range.return_value = {
            "status": "error",
            "error": "connection refused",
            "errorType": "connection",
        }

        result = await self.tools["query_prometheus_range"](
            query="up", start="1h", end="now", step="60s"
        )
        assert "error" in result
        assert "connection refused" in result


class TestRelativeToEpoch:
    def test_seconds(self):
        result = float(_relative_to_epoch("90s", now=FIXED_NOW))
        assert result == FIXED_NOW - 90

    def test_minutes(self):
        result = float(_relative_to_epoch("30m", now=FIXED_NOW))
        assert result == FIXED_NOW - 1800

    def test_hours(self):
        result = float(_relative_to_epoch("2h", now=FIXED_NOW))
        assert result == FIXED_NOW - 7200

    def test_days(self):
        result = float(_relative_to_epoch("1d", now=FIXED_NOW))
        assert result == FIXED_NOW - 86400

    def test_passthrough_absolute(self):
        assert _relative_to_epoch("2024-01-01T00:00:00Z") == "2024-01-01T00:00:00Z"

    def test_passthrough_unix(self):
        assert _relative_to_epoch("1710000000") == "1710000000"
