import pytest

from rhoai_obs_mcp.auth import AuthProvider
from rhoai_obs_mcp.backends.tempo import TempoBackend, _TEMPO_NOT_CONFIGURED
from rhoai_obs_mcp.config import Settings
from rhoai_obs_mcp.tools.traces import _TEMPO_UNAVAILABLE_MSG, register_trace_tools


@pytest.fixture
def unavailable_tempo():
    """TempoBackend with no URL configured."""
    settings = Settings(_env_file=None, openshift_token="test-token")
    auth = AuthProvider(settings)
    return TempoBackend(settings, auth)


@pytest.fixture
def available_tempo():
    """TempoBackend with a URL configured."""
    settings = Settings(
        _env_file=None,
        tempo_url="https://tempo.test:8080",
        openshift_token="test-token",
    )
    auth = AuthProvider(settings)
    return TempoBackend(settings, auth)


class TestTempoBackendAvailability:
    def test_unavailable_when_no_url(self, unavailable_tempo):
        assert unavailable_tempo.available is False

    def test_available_when_url_set(self, available_tempo):
        assert available_tempo.available is True

    @pytest.mark.asyncio
    async def test_get_trace_returns_error_when_unavailable(self, unavailable_tempo):
        result = await unavailable_tempo.get_trace("abc123")
        assert result["status"] == "error"
        assert result["error"] == _TEMPO_NOT_CONFIGURED

    @pytest.mark.asyncio
    async def test_search_returns_error_when_unavailable(self, unavailable_tempo):
        result = await unavailable_tempo.search("{ status = error }")
        assert result["status"] == "error"
        assert result["error"] == _TEMPO_NOT_CONFIGURED

    @pytest.mark.asyncio
    async def test_search_tags_returns_error_when_unavailable(self, unavailable_tempo):
        result = await unavailable_tempo.search_tags()
        assert result["status"] == "error"
        assert result["error"] == _TEMPO_NOT_CONFIGURED


class TestTraceToolsUnavailable:
    @pytest.mark.asyncio
    async def test_get_trace_returns_unavailable_message(self, unavailable_tempo):
        tools = register_trace_tools(unavailable_tempo)
        result = await tools["get_trace"](trace_id="abc123")
        assert result == _TEMPO_UNAVAILABLE_MSG

    @pytest.mark.asyncio
    async def test_search_traces_returns_unavailable_message(self, unavailable_tempo):
        tools = register_trace_tools(unavailable_tempo)
        result = await tools["search_traces"](query="{ status = error }")
        assert result == _TEMPO_UNAVAILABLE_MSG

    @pytest.mark.asyncio
    async def test_list_trace_tags_returns_unavailable_message(self, unavailable_tempo):
        tools = register_trace_tools(unavailable_tempo)
        result = await tools["list_trace_tags"]()
        assert result == _TEMPO_UNAVAILABLE_MSG
