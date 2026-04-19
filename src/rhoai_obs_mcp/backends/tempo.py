import logging
from typing import Literal

import httpx

from rhoai_obs_mcp.auth import AuthProvider
from rhoai_obs_mcp.config import Settings

logger = logging.getLogger(__name__)

Tenant = Literal["application", "infrastructure"]

_TEMPO_NOT_CONFIGURED = "Tempo is not configured. Set TEMPO_URL to enable trace queries."


class TempoBackend:
    """HTTP client for Tempo via the Tempo Operator gateway."""

    def __init__(self, settings: Settings, auth: AuthProvider) -> None:
        self._base_url = settings.tempo_url or ""
        self._timeout = settings.request_timeout
        self._auth = auth
        self._available = settings.tempo_enabled

    @property
    def available(self) -> bool:
        """Whether Tempo is configured and available for queries."""
        return self._available

    def _client(self, tenant: Tenant) -> httpx.AsyncClient:
        headers = {**self._auth.get_headers(), "X-Scope-OrgID": tenant}
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=self._timeout,
            verify=False,
        )

    def _tenant_path(self, tenant: Tenant) -> str:
        return f"/api/traces/v1/{tenant}/tempo/api"

    async def get_trace(
        self,
        trace_id: str,
        tenant: Tenant = "application",
    ) -> dict:
        """Fetch a single trace by ID."""
        if not self._available:
            return {"status": "error", "error": _TEMPO_NOT_CONFIGURED}

        try:
            async with self._client(tenant) as client:
                resp = await client.get(
                    f"{self._tenant_path(tenant)}/traces/{trace_id}",
                )
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, httpx.ConnectError) as exc:
            logger.error("Tempo get_trace failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    async def search(
        self,
        query: str,
        tenant: Tenant = "application",
        start: str | None = None,
        end: str | None = None,
        limit: int = 20,
    ) -> dict:
        """Search traces using TraceQL."""
        if not self._available:
            return {"status": "error", "error": _TEMPO_NOT_CONFIGURED}

        params: dict = {"q": query, "limit": limit}
        if start:
            params["start"] = start
        if end:
            params["end"] = end

        try:
            async with self._client(tenant) as client:
                resp = await client.get(
                    f"{self._tenant_path(tenant)}/search",
                    params=params,
                )
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, httpx.ConnectError) as exc:
            logger.error("Tempo search failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    async def search_tags(
        self,
        tenant: Tenant = "application",
        scope: str | None = None,
    ) -> dict:
        """List available tag names."""
        if not self._available:
            return {"status": "error", "error": _TEMPO_NOT_CONFIGURED}

        params: dict = {}
        if scope:
            params["scope"] = scope

        try:
            async with self._client(tenant) as client:
                resp = await client.get(
                    f"{self._tenant_path(tenant)}/v2/search/tags",
                    params=params,
                )
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, httpx.ConnectError) as exc:
            logger.error("Tempo search_tags failed: %s", exc)
            return {"status": "error", "error": str(exc)}
