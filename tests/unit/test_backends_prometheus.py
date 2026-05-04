import httpx
import pytest
import respx
from rhoai_obs_mcp.backends.prometheus import PrometheusBackend


class TestPrometheusBackend:
    @respx.mock
    @pytest.mark.asyncio
    async def test_instant_query(self, settings, auth):
        """Should execute an instant PromQL query."""
        respx.get("https://thanos.test:9091/api/v1/query").mock(
            return_value=httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "resultType": "vector",
                        "result": [{"metric": {"__name__": "up"}, "value": [1708000000, "1"]}],
                    },
                },
            )
        )

        backend = PrometheusBackend(settings, auth)
        result = await backend.query("up")
        assert result["status"] == "success"
        assert len(result["data"]["result"]) == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_range_query(self, settings, auth):
        """Should execute a range PromQL query."""
        respx.get("https://thanos.test:9091/api/v1/query_range").mock(
            return_value=httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "resultType": "matrix",
                        "result": [
                            {
                                "metric": {"__name__": "vllm:num_requests_running"},
                                "values": [[1708000000, "5"], [1708000060, "8"]],
                            }
                        ],
                    },
                },
            )
        )

        backend = PrometheusBackend(settings, auth)
        result = await backend.query_range(
            "vllm:num_requests_running",
            start="2024-01-01T00:00:00Z",
            end="2024-01-01T01:00:00Z",
            step="60s",
        )
        assert result["status"] == "success"
        assert result["data"]["resultType"] == "matrix"

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_metrics(self, settings, auth):
        """Should list available metric names."""
        respx.get("https://thanos.test:9091/api/v1/label/__name__/values").mock(
            return_value=httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": ["vllm:num_requests_running", "vllm:kv_cache_usage_perc", "up"],
                },
            )
        )

        backend = PrometheusBackend(settings, auth)
        result = await backend.list_metrics()
        assert "vllm:num_requests_running" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_query_error_handling(self, settings, auth):
        """Should return error dict when backend is unreachable."""
        respx.get("https://thanos.test:9091/api/v1/query").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        backend = PrometheusBackend(settings, auth)
        result = await backend.query("up")
        assert result["status"] == "error"
        assert "Connection" in result["error"]

    @respx.mock
    @pytest.mark.asyncio
    async def test_auth_headers_sent(self, settings, auth):
        """Should send bearer token in request headers."""
        route = respx.get("https://thanos.test:9091/api/v1/query").mock(
            return_value=httpx.Response(200, json={"status": "success", "data": {"result": []}})
        )

        backend = PrometheusBackend(settings, auth)
        await backend.query("up")
        assert route.calls[0].request.headers["Authorization"] == "Bearer test-token"
