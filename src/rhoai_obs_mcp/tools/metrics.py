import json
import re
import time

from rhoai_obs_mcp.backends.prometheus import PrometheusBackend


def _relative_to_epoch(val: str, now: float | None = None) -> str:
    """Convert a relative duration like '1h' or '30m' to a Unix timestamp.

    Supports s/m/h/d suffixes. If the value doesn't match a known suffix,
    it is returned unchanged (assumed to be an absolute timestamp or RFC3339).

    Args:
        val: Duration string (e.g. '1h', '30m') or absolute timestamp.
        now: Reference time as Unix epoch. Defaults to time.time().
    """
    val = val.strip()
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if val and val[-1].lower() in units and val[:-1].replace(".", "", 1).isdigit():
        if now is None:
            now = time.time()
        seconds_ago = float(val[:-1]) * units[val[-1].lower()]
        return str(now - seconds_ago)
    return val


# Key vLLM metrics with human-readable descriptions
VLLM_METRICS = {
    "ttft": ("vllm:time_to_first_token_seconds", "Time to First Token (TTFT)"),
    "tpot": ("vllm:request_time_per_output_token_seconds", "Time Per Output Token (TPOT)"),
    "e2e": ("vllm:e2e_request_latency_seconds", "End-to-End Latency"),
    "cache": ("vllm:kv_cache_usage_perc", "GPU KV Cache Usage"),
    "throughput": ("vllm:generation_tokens_total", "Generation Throughput (tokens/sec)"),
    "queue": ("vllm:num_requests_waiting", "Requests Waiting in Queue"),
    "running": ("vllm:num_requests_running", "Requests Currently Running"),
    "preempted": ("vllm:num_requests_preempted", "Requests Preempted"),
}


def register_metrics_tools(prometheus: PrometheusBackend) -> dict:
    """Create metrics tool functions bound to the given backend."""

    async def query_prometheus(query: str, time: str | None = None) -> str:
        """Execute a raw PromQL query against ThanosQuerier.

        Args:
            query: PromQL expression (e.g., 'vllm:num_requests_running')
            time: Optional evaluation timestamp (RFC3339 or Unix)
        """
        result = await prometheus.query(query, time=time)
        return json.dumps(result, indent=2, default=str)

    async def get_vllm_metrics(
        model_name: str,
        metrics: str = "ttft,tpot,e2e,cache,queue,running,preempted",
    ) -> str:
        """Get a summary of key vLLM metrics for a specific model.

        Args:
            model_name: The model name label in vLLM metrics
            metrics: Comma-separated list of: ttft, tpot, e2e, cache, throughput, queue, running, preempted
        """
        requested = [m.strip() for m in metrics.split(",")]
        lines = [f"## vLLM Metrics for model: {model_name}\n"]

        for key in requested:
            if key not in VLLM_METRICS:
                lines.append(f"- **{key}**: Unknown metric key")
                continue

            metric_name, description = VLLM_METRICS[key]

            # For rate-based metrics, wrap in rate()
            if key == "throughput":
                promql = f'rate({metric_name}{{model_name="{model_name}"}}[5m])'
            elif key in ("cache", "queue", "running", "preempted"):
                promql = f'{metric_name}{{model_name="{model_name}"}}'
            else:
                # Histograms: get p50, p95, p99
                promql = f'histogram_quantile(0.95, rate({metric_name}_bucket{{model_name="{model_name}"}}[5m]))'

            result = await prometheus.query(promql)
            if result.get("status") == "success" and result["data"].get("result"):
                value = result["data"]["result"][0]["value"][1]
                lines.append(f"- **{description}**: {value}")
            else:
                lines.append(f"- **{description}**: No data available")

        return "\n".join(lines)

    async def query_prometheus_range(
        query: str,
        start: str = "1h",
        end: str = "now",
        step: str = "60s",
    ) -> str:
        """Execute a PromQL range query and return time-series data.

        Use this to see how a metric changed over time — for example GPU
        utilization during a load test, or latency trends over the last hour.
        Returns timestamped values suitable for identifying spikes, trends,
        and correlations across metrics.

        Args:
            query: PromQL expression (e.g., 'DCGM_FI_DEV_GPU_UTIL')
            start: Start of the range — relative like '1h', '30m', '2d'
                   or absolute (RFC3339 / Unix timestamp). Default '1h'.
            end: End of the range — 'now' (default) or same formats as start.
            step: Query resolution step (e.g., '15s', '60s', '5m'). Default '60s'.
        """
        now = time.time()
        start_ts = _relative_to_epoch(start, now=now)
        end_ts = str(now) if end.strip().lower() == "now" else _relative_to_epoch(end, now=now)

        result = await prometheus.query_range(promql=query, start=start_ts, end=end_ts, step=step)
        return json.dumps(result, indent=2, default=str)

    async def list_metrics(filter: str = "") -> str:
        """List available Prometheus metric names, optionally filtered.

        Args:
            filter: Regex pattern to filter metric names (e.g., 'vllm' to show only vLLM metrics)
        """
        all_metrics = await prometheus.list_metrics()
        if filter:
            pattern = re.compile(filter, re.IGNORECASE)
            filtered = [m for m in all_metrics if pattern.search(m)]
        else:
            filtered = all_metrics

        if not filtered:
            return (
                f"No metrics found matching filter: '{filter}'"
                if filter
                else "No metrics available"
            )

        return "\n".join(sorted(filtered))

    return {
        "query_prometheus": query_prometheus,
        "query_prometheus_range": query_prometheus_range,
        "get_vllm_metrics": get_vllm_metrics,
        "list_metrics": list_metrics,
    }
