import pytest
from unittest.mock import AsyncMock
from rhoai_obs_mcp.tools.traces import register_trace_tools


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
            "traceID": "abc123def456789000",
            "rootServiceName": "vllm",
            "rootTraceName": "POST /v1/completions",
            "startTimeUnixNano": "1708000000000000000",
            "durationMs": 1500,
        }
    ],
    "metrics": {"inspectedTraces": 100},
}

SAMPLE_TAGS_RESPONSE = {
    "scopes": [
        {"name": "resource", "tags": ["service.name", "k8s.namespace.name"]},
        {"name": "span", "tags": ["http.method", "http.status_code"]},
    ]
}


class TestTraceTools:
    def setup_method(self):
        self.tempo = AsyncMock()
        self.tempo.available = True
        self.tools = register_trace_tools(self.tempo)

    @pytest.mark.asyncio
    async def test_get_trace_formats_spans(self):
        """Should render spans as markdown with service, operation, duration."""
        self.tempo.get_trace.return_value = SAMPLE_TRACE_RESPONSE
        result = await self.tools["get_trace"](trace_id="abc123")
        assert "vllm" in result
        assert "POST /v1/completions" in result
        assert "1000.0ms" in result
        assert "OK" in result

    @pytest.mark.asyncio
    async def test_get_trace_not_found(self):
        """Should handle empty trace response."""
        self.tempo.get_trace.return_value = {"batches": []}
        result = await self.tools["get_trace"](trace_id="missing")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_search_traces_formats_table(self):
        """Should render search results as markdown table."""
        self.tempo.search.return_value = SAMPLE_SEARCH_RESPONSE
        result = await self.tools["search_traces"](query="{ status = error }")
        assert "vllm" in result
        assert "1500ms" in result
        assert "abc123def45678" in result

    @pytest.mark.asyncio
    async def test_search_traces_no_results(self):
        """Should handle empty search results."""
        self.tempo.search.return_value = {"traces": []}
        result = await self.tools["search_traces"](query="{ status = error }")
        assert "No traces found" in result

    @pytest.mark.asyncio
    async def test_list_trace_tags(self):
        """Should render tags grouped by scope."""
        self.tempo.search_tags.return_value = SAMPLE_TAGS_RESPONSE
        result = await self.tools["list_trace_tags"]()
        assert "service.name" in result
        assert "http.method" in result
        assert "resource" in result
        assert "span" in result

    @pytest.mark.asyncio
    async def test_get_trace_error_response(self):
        """Should format error from backend."""
        self.tempo.get_trace.return_value = {"status": "error", "error": "Connection refused"}
        result = await self.tools["get_trace"](trace_id="abc123")
        assert "Error fetching trace" in result
        assert "Connection refused" in result

    @pytest.mark.asyncio
    async def test_search_traces_error_response(self):
        """Should format error from backend."""
        self.tempo.search.return_value = {"status": "error", "error": "timeout"}
        result = await self.tools["search_traces"](query="{ status = error }")
        assert "Error searching traces" in result
        assert "timeout" in result

    @pytest.mark.asyncio
    async def test_list_trace_tags_error_response(self):
        """Should format error from backend."""
        self.tempo.search_tags.return_value = {"status": "error", "error": "Connection refused"}
        result = await self.tools["list_trace_tags"]()
        assert "Error listing tags" in result
        assert "Connection refused" in result

    @pytest.mark.asyncio
    async def test_list_trace_tags_empty_scopes(self):
        """Should handle empty scopes list."""
        self.tempo.search_tags.return_value = {"scopes": []}
        result = await self.tools["list_trace_tags"]()
        assert "No tags found" in result
