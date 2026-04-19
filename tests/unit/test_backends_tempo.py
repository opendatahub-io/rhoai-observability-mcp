import httpx
import pytest
import respx

from rhoai_obs_mcp.backends.tempo import TempoBackend

SAMPLE_TRACE_RESPONSE = {
    "batches": [
        {
            "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "vllm"}}]},
            "scopeSpans": [
                {
                    "spans": [
                        {
                            "traceId": "abc123",
                            "spanId": "span1",
                            "name": "POST /v1/completions",
                            "startTimeUnixNano": "1708000000000000000",
                            "endTimeUnixNano": "1708000001000000000",
                            "status": {"code": 1},
                        }
                    ]
                }
            ],
        }
    ]
}

SAMPLE_SEARCH_RESPONSE = {
    "traces": [
        {
            "traceID": "abc123def456",
            "rootServiceName": "vllm",
            "rootTraceName": "POST /v1/completions",
            "startTimeUnixNano": "1708000000000000000",
            "durationMs": 1500,
            "spanSets": [{"spans": [{"spanID": "span1"}]}],
        }
    ],
    "metrics": {"inspectedTraces": 100},
}

SAMPLE_TAGS_RESPONSE = {
    "scopes": [
        {
            "name": "resource",
            "tags": ["service.name", "k8s.namespace.name", "k8s.pod.name"],
        },
        {
            "name": "span",
            "tags": ["http.method", "http.status_code", "http.url"],
        },
    ]
}


class TestTempoBackendGetTrace:
    @respx.mock
    @pytest.mark.asyncio
    async def test_get_trace(self, settings, auth):
        """Should fetch a trace by ID through the gateway."""
        respx.get("https://tempo.test:8080/api/traces/v1/application/tempo/api/traces/abc123").mock(
            return_value=httpx.Response(200, json=SAMPLE_TRACE_RESPONSE)
        )

        backend = TempoBackend(settings, auth)
        result = await backend.get_trace("abc123", tenant="application")
        assert "batches" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_trace_infrastructure_tenant(self, settings, auth):
        """Should use the correct tenant path for infrastructure traces."""
        route = respx.get(
            "https://tempo.test:8080/api/traces/v1/infrastructure/tempo/api/traces/abc123"
        ).mock(return_value=httpx.Response(200, json=SAMPLE_TRACE_RESPONSE))

        backend = TempoBackend(settings, auth)
        await backend.get_trace("abc123", tenant="infrastructure")
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_trace_sends_org_id_header(self, settings, auth):
        """Should send X-Scope-OrgID header with tenant name."""
        route = respx.get(
            "https://tempo.test:8080/api/traces/v1/application/tempo/api/traces/abc123"
        ).mock(return_value=httpx.Response(200, json=SAMPLE_TRACE_RESPONSE))

        backend = TempoBackend(settings, auth)
        await backend.get_trace("abc123", tenant="application")
        assert route.calls[0].request.headers["X-Scope-OrgID"] == "application"

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_trace_connection_error(self, settings, auth):
        """Should return error dict on connection failure."""
        respx.get("https://tempo.test:8080/api/traces/v1/application/tempo/api/traces/abc123").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        backend = TempoBackend(settings, auth)
        result = await backend.get_trace("abc123")
        assert result["status"] == "error"


class TestTempoBackendSearch:
    @respx.mock
    @pytest.mark.asyncio
    async def test_search(self, settings, auth):
        """Should execute a TraceQL search."""
        respx.get("https://tempo.test:8080/api/traces/v1/application/tempo/api/search").mock(
            return_value=httpx.Response(200, json=SAMPLE_SEARCH_RESPONSE)
        )

        backend = TempoBackend(settings, auth)
        result = await backend.search('{ resource.service.name = "vllm" }')
        assert "traces" in result
        assert len(result["traces"]) == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_search_passes_parameters(self, settings, auth):
        """Should pass q, limit, start, end as query parameters."""
        route = respx.get(
            "https://tempo.test:8080/api/traces/v1/application/tempo/api/search"
        ).mock(return_value=httpx.Response(200, json=SAMPLE_SEARCH_RESPONSE))

        backend = TempoBackend(settings, auth)
        await backend.search(
            "{ status = error }",
            limit=10,
            start="1708000000",
            end="1708003600",
        )
        url = str(route.calls[0].request.url)
        assert "limit=10" in url
        assert "start=1708000000" in url
        assert "end=1708003600" in url


class TestTempoBackendSearchTags:
    @respx.mock
    @pytest.mark.asyncio
    async def test_search_tags(self, settings, auth):
        """Should list available tag names."""
        respx.get(
            "https://tempo.test:8080/api/traces/v1/application/tempo/api/v2/search/tags"
        ).mock(return_value=httpx.Response(200, json=SAMPLE_TAGS_RESPONSE))

        backend = TempoBackend(settings, auth)
        result = await backend.search_tags(tenant="application")
        assert "scopes" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_search_tags_with_scope(self, settings, auth):
        """Should pass scope parameter."""
        route = respx.get(
            "https://tempo.test:8080/api/traces/v1/application/tempo/api/v2/search/tags"
        ).mock(return_value=httpx.Response(200, json=SAMPLE_TAGS_RESPONSE))

        backend = TempoBackend(settings, auth)
        await backend.search_tags(tenant="application", scope="resource")
        url = str(route.calls[0].request.url)
        assert "scope=resource" in url

    @respx.mock
    @pytest.mark.asyncio
    async def test_search_tags_connection_error(self, settings, auth):
        """Should return error dict on connection failure."""
        respx.get(
            "https://tempo.test:8080/api/traces/v1/application/tempo/api/v2/search/tags"
        ).mock(side_effect=httpx.ConnectError("Connection refused"))

        backend = TempoBackend(settings, auth)
        result = await backend.search_tags()
        assert result["status"] == "error"
        assert "Connection refused" in result["error"]


class TestTempoBackendSearchConnectionError:
    @respx.mock
    @pytest.mark.asyncio
    async def test_search_connection_error(self, settings, auth):
        """Should return error dict on connection failure."""
        respx.get("https://tempo.test:8080/api/traces/v1/application/tempo/api/search").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        backend = TempoBackend(settings, auth)
        result = await backend.search("{ status = error }")
        assert result["status"] == "error"
        assert "Connection refused" in result["error"]
