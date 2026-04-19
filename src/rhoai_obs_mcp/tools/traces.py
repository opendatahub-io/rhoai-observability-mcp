from typing import Literal

from rhoai_obs_mcp.backends.tempo import TempoBackend

_TEMPO_UNAVAILABLE_MSG = (
    "Trace queries are not available — Tempo is not configured in this cluster.\n\n"
    "Alternatives:\n"
    "- Use `query_logs` to search for request-scoped log entries\n"
    "- Use `query_prometheus` to check latency histograms (e.g., vllm:e2e_request_latency_seconds)\n"
    "- Use `investigate_latency` for a correlated view of metrics and logs"
)


def _format_trace(data: dict) -> str:
    """Format a single trace response into readable markdown."""
    if data.get("status") == "error":
        return f"Error fetching trace: {data.get('error', 'Unknown error')}"

    batches = data.get("batches", [])
    if not batches:
        return "Trace not found or contains no spans."

    lines = ["## Trace Spans\n"]
    for batch in batches:
        resource = batch.get("resource", {})
        attrs = {
            a["key"]: a["value"].get("stringValue", a["value"].get("intValue", ""))
            for a in resource.get("attributes", [])
        }
        service = attrs.get("service.name", "unknown")

        for scope_span in batch.get("scopeSpans", []):
            for span in scope_span.get("spans", []):
                name = span.get("name", "unknown")
                start_ns = int(span.get("startTimeUnixNano", 0))
                end_ns = int(span.get("endTimeUnixNano", 0))
                duration_ms = (end_ns - start_ns) / 1_000_000 if end_ns > start_ns else 0
                status_code = span.get("status", {}).get("code", 0)
                status_str = {0: "UNSET", 1: "OK", 2: "ERROR"}.get(status_code, "UNKNOWN")
                lines.append(f"- **{service}** / `{name}` — {duration_ms:.1f}ms [{status_str}]")
    return "\n".join(lines)


def _format_search_results(data: dict) -> str:
    """Format search results into readable markdown."""
    if data.get("status") == "error":
        return f"Error searching traces: {data.get('error', 'Unknown error')}"

    traces = data.get("traces", [])
    if not traces:
        return "No traces found matching the query."

    lines = [f"## Trace Search Results ({len(traces)} traces)\n"]
    lines.append("| Trace ID | Service | Operation | Duration |")
    lines.append("|----------|---------|-----------|----------|")
    for trace in traces:
        trace_id = trace.get("traceID", "unknown")
        service = trace.get("rootServiceName", "unknown")
        operation = trace.get("rootTraceName", "unknown")
        duration_ms = trace.get("durationMs", 0)
        lines.append(f"| `{trace_id[:16]}...` | {service} | {operation} | {duration_ms}ms |")

    return "\n".join(lines)


def register_trace_tools(tempo: TempoBackend) -> dict:
    """Create trace tool functions bound to the given backend."""

    async def get_trace(
        trace_id: str,
        tenant: Literal["application", "infrastructure"] = "application",
    ) -> str:
        """Fetch a distributed trace by its trace ID.

        Returns the full span tree with service names, operations, durations,
        and status codes rendered as markdown.

        Args:
            trace_id: The 32-character hex trace ID
            tenant: Trace tenant: 'application' or 'infrastructure'
        """
        if not tempo.available:
            return _TEMPO_UNAVAILABLE_MSG
        result = await tempo.get_trace(trace_id, tenant=tenant)
        return _format_trace(result)

    async def search_traces(
        query: str,
        tenant: Literal["application", "infrastructure"] = "application",
        limit: int = 20,
        start: str | None = None,
        end: str | None = None,
    ) -> str:
        """Search for traces using TraceQL.

        TraceQL lets you query traces by service, status, duration, and span
        attributes. Results show matching trace IDs with root service, operation
        name, and total duration.

        Args:
            query: TraceQL expression (e.g., '{ resource.service.name = "vllm" && status = error }')
            tenant: Trace tenant: 'application' or 'infrastructure'
            limit: Maximum number of traces to return (default 20)
            start: Start of time range (Unix epoch seconds, optional)
            end: End of time range (Unix epoch seconds, optional)
        """
        if not tempo.available:
            return _TEMPO_UNAVAILABLE_MSG
        result = await tempo.search(query, tenant=tenant, limit=limit, start=start, end=end)
        return _format_search_results(result)

    async def list_trace_tags(
        tenant: Literal["application", "infrastructure"] = "application",
        scope: str | None = None,
    ) -> str:
        """List available trace tag names for building TraceQL queries.

        Returns tag names grouped by scope (resource, span, intrinsic).
        Use these to discover which attributes are available for filtering.

        Args:
            tenant: Trace tenant: 'application' or 'infrastructure'
            scope: Filter to a specific scope: 'resource', 'span', or 'intrinsic' (optional)
        """
        if not tempo.available:
            return _TEMPO_UNAVAILABLE_MSG
        result = await tempo.search_tags(tenant=tenant, scope=scope)
        if result.get("status") == "error":
            return f"Error listing tags: {result.get('error', 'Unknown error')}"

        scopes = result.get("scopes", [])
        if not scopes:
            return "No tags found."

        lines = ["## Available Trace Tags\n"]
        for scope_group in scopes:
            scope_name = scope_group.get("name", "unknown")
            tags = sorted(scope_group.get("tags", []))
            lines.append(f"### {scope_name}\n")
            for tag in tags:
                lines.append(f"- `{tag}`")
            lines.append("")

        return "\n".join(lines)

    return {
        "get_trace": get_trace,
        "search_traces": search_traces,
        "list_trace_tags": list_trace_tags,
    }
