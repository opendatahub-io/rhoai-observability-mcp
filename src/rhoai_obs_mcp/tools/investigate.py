import asyncio
from typing import Any

from rhoai_obs_mcp.backends.alertmanager import AlertmanagerBackend
from rhoai_obs_mcp.backends.loki import LokiBackend
from rhoai_obs_mcp.backends.openshift import OpenShiftBackend
from rhoai_obs_mcp.backends.prometheus import PrometheusBackend
from rhoai_obs_mcp.backends.tempo import TempoBackend


def register_investigation_tools(
    prometheus: PrometheusBackend,
    alertmanager: AlertmanagerBackend,
    loki: LokiBackend,
    openshift: OpenShiftBackend,
    tempo: TempoBackend,
) -> dict:
    """Create composite investigation tool functions."""

    async def investigate_latency(model_name: str, time_range: str = "15m") -> str:
        """Investigate latency issues for a vLLM model by correlating metrics, logs, and alerts.

        Fetches TTFT, TPOT, E2E latency, queue depth, error logs, and related alerts
        to help identify root cause of slow LLM responses.

        Args:
            model_name: The vLLM model name
            time_range: Time range to analyze (e.g., '15m', '1h')
        """
        # Query all sources concurrently
        ttft_query = (
            "histogram_quantile(0.95, rate("
            f'vllm:time_to_first_token_seconds_bucket{{model_name="{model_name}"}}'
            f"[{time_range}]))"
        )
        tpot_query = (
            "histogram_quantile(0.95, rate("
            f'vllm:time_per_output_token_seconds_bucket{{model_name="{model_name}"}}'
            f"[{time_range}]))"
        )
        e2e_query = (
            "histogram_quantile(0.95, rate("
            f'vllm:e2e_request_latency_seconds_bucket{{model_name="{model_name}"}}'
            f"[{time_range}]))"
        )
        queue_query = f'vllm:num_requests_waiting{{model_name="{model_name}"}}'
        cache_query = f'vllm:gpu_cache_usage_perc{{model_name="{model_name}"}}'

        ttft, tpot, e2e, queue, cache, error_logs, alerts, traces = await asyncio.gather(
            prometheus.query(ttft_query),
            prometheus.query(tpot_query),
            prometheus.query(e2e_query),
            prometheus.query(queue_query),
            prometheus.query(cache_query),
            loki.query_range(
                f'{{kubernetes_namespace_name=~".*"}} |= "error" |= "{model_name}"',
                tenant="application",
                limit=20,
            ),
            alertmanager.get_alerts(),
            tempo.search(
                query=f'{{ resource.service.name = "{model_name}" && status = error }}',
                tenant="application",
                limit=5,
            ),
            return_exceptions=True,
        )

        lines = [f"# Latency Investigation: {model_name}\n"]

        # Metrics section
        lines.append("## Metrics (p95)\n")
        metric_results: list[tuple[str, Any]] = [
            ("TTFT", ttft),
            ("TPOT", tpot),
            ("E2E Latency", e2e),
            ("Queue Depth", queue),
            ("KV Cache Usage", cache),
        ]
        for name, result in metric_results:
            if isinstance(result, BaseException):
                lines.append(f"- **{name}:** Error fetching ({result})")
            elif result.get("status") == "success" and result["data"].get("result"):
                value = result["data"]["result"][0]["value"][1]
                lines.append(f"- **{name}:** {value}")
            else:
                lines.append(f"- **{name}:** No data")

        # Logs section
        lines.append("\n## Recent Error Logs\n")
        if isinstance(error_logs, BaseException):
            lines.append(f"Error fetching logs: {error_logs}")
        elif isinstance(error_logs, dict) and error_logs.get("status") == "error":
            lines.append(f"Log query unavailable: {error_logs.get('error', 'Unknown error')}")
        elif isinstance(error_logs, dict) and error_logs.get("status") == "success":
            results = error_logs["data"].get("result", [])
            if results:
                for stream in results[:5]:
                    for ts, msg in stream.get("values", [])[:3]:
                        lines.append(f"- {msg}")
            else:
                lines.append("No error logs found in the time range.")
        else:
            lines.append("No error logs found.")

        # Alerts section
        lines.append("\n## Related Alerts\n")
        if isinstance(alerts, BaseException):
            lines.append(f"Error fetching alerts: {alerts}")
        elif isinstance(alerts, list) and alerts:
            for alert in alerts:
                name = alert.get("labels", {}).get("alertname", "Unknown")
                severity = alert.get("labels", {}).get("severity", "unknown")
                summary = alert.get("annotations", {}).get("summary", "")
                lines.append(f"- **{name}** ({severity}): {summary}")
        else:
            lines.append("No active alerts.")

        # Traces section
        lines.append("\n## Recent Error Traces\n")
        if isinstance(traces, BaseException):
            lines.append(f"Error fetching traces: {traces}")
        elif isinstance(traces, dict) and traces.get("status") == "error":
            lines.append(f"Traces not available: {traces.get('error', 'Unknown error')}")
        elif isinstance(traces, dict):
            trace_list = traces.get("traces", [])
            if trace_list:
                for t in trace_list[:5]:
                    trace_id = t.get("traceID", "unknown")
                    duration = t.get("durationMs", 0)
                    root_name = t.get("rootTraceName", "unknown")
                    lines.append(f"- `{trace_id[:16]}...` — {root_name} ({duration}ms)")
            else:
                lines.append("No error traces found in the time range.")
        else:
            lines.append("No error traces found.")

        return "\n".join(lines)

    async def investigate_gpu(time_range: str = "15m", namespace: str | None = None) -> str:
        """Investigate GPU utilization issues by correlating GPU metrics, KV cache, and pod status.

        Args:
            time_range: Time range to analyze
            namespace: Namespace to check pods in (optional)
        """
        gpu_util_query = "DCGM_FI_DEV_GPU_UTIL"
        gpu_mem_query = "DCGM_FI_DEV_FB_USED"
        cache_query = "vllm:gpu_cache_usage_perc"
        running_query = "vllm:num_requests_running"
        waiting_query = "vllm:num_requests_waiting"

        gpu_util, gpu_mem, cache, running, waiting, alerts = await asyncio.gather(
            prometheus.query(gpu_util_query),
            prometheus.query(gpu_mem_query),
            prometheus.query(cache_query),
            prometheus.query(running_query),
            prometheus.query(waiting_query),
            alertmanager.get_alerts(),
            return_exceptions=True,
        )

        lines = ["# GPU Investigation\n"]

        lines.append("## GPU Metrics\n")
        gpu_results: list[tuple[str, Any]] = [
            ("GPU Utilization (%)", gpu_util),
            ("GPU Memory Used (MB)", gpu_mem),
            ("KV Cache Usage", cache),
            ("Requests Running", running),
            ("Requests Waiting", waiting),
        ]
        for name, result in gpu_results:
            if isinstance(result, BaseException):
                lines.append(f"- **{name}:** Error ({result})")
            elif result.get("status") == "success" and result["data"].get("result"):
                for r in result["data"]["result"]:
                    labels = r.get("metric", {})
                    gpu_id = labels.get("gpu", labels.get("model_name", ""))
                    value = r["value"][1]
                    label_str = f" [{gpu_id}]" if gpu_id else ""
                    lines.append(f"- **{name}{label_str}:** {value}")
            else:
                lines.append(f"- **{name}:** No data")

        # Pod status
        if namespace:
            lines.append(f"\n## Pod Status ({namespace})\n")
            pods = openshift.get_pods(namespace)
            if pods:
                for pod in pods:
                    lines.append(
                        f"- **{pod['name']}**: {pod['status']} (restarts: {pod['restarts']})"
                    )
            else:
                lines.append("No pods found.")

        # Alerts
        lines.append("\n## Related Alerts\n")
        if isinstance(alerts, BaseException):
            lines.append(f"Error: {alerts}")
        elif isinstance(alerts, list) and alerts:
            gpu_alerts = [
                a
                for a in alerts
                if "gpu" in str(a.get("labels", {})).lower()
                or "GPU" in str(a.get("annotations", {}))
            ]
            if gpu_alerts:
                for alert in gpu_alerts:
                    name = alert["labels"].get("alertname", "Unknown")
                    lines.append(f"- **{name}**: {alert.get('annotations', {}).get('summary', '')}")
            else:
                lines.append("No GPU-related alerts.")
        else:
            lines.append("No active alerts.")

        return "\n".join(lines)

    async def investigate_errors(namespace: str, time_range: str = "30m") -> str:
        """Investigate errors in a namespace by correlating logs, alerts, and pod events.

        Args:
            namespace: Kubernetes namespace to investigate
            time_range: Time range to analyze
        """
        error_logs, alerts, events = await asyncio.gather(
            loki.query_range(
                f'{{kubernetes_namespace_name="{namespace}"}} |= "error"',
                tenant="application",
                limit=50,
            ),
            alertmanager.get_alerts(filter_expr=f'namespace="{namespace}"'),
            asyncio.get_event_loop().run_in_executor(None, lambda: openshift.get_events(namespace)),
            return_exceptions=True,
        )

        lines = [f"# Error Investigation: {namespace}\n"]

        # Error logs
        lines.append("## Error Logs\n")
        if isinstance(error_logs, BaseException):
            lines.append(f"Error fetching logs: {error_logs}")
        elif isinstance(error_logs, dict) and error_logs.get("status") == "error":
            lines.append(f"Log query unavailable: {error_logs.get('error', 'Unknown error')}")
        elif isinstance(error_logs, dict) and error_logs.get("status") == "success":
            results = error_logs["data"].get("result", [])
            if results:
                for stream in results[:10]:
                    pod = stream.get("stream", {}).get("kubernetes_pod_name", "unknown")
                    lines.append(f"### Pod: {pod}")
                    for ts, msg in stream.get("values", [])[:5]:
                        lines.append(f"  - {msg}")
            else:
                lines.append("No error logs found.")
        else:
            lines.append("No error logs found.")

        # Alerts
        lines.append("\n## Active Alerts\n")
        if isinstance(alerts, BaseException):
            lines.append(f"Error: {alerts}")
        elif isinstance(alerts, list) and alerts:
            for alert in alerts:
                name = alert.get("labels", {}).get("alertname", "Unknown")
                severity = alert.get("labels", {}).get("severity", "unknown")
                summary = alert.get("annotations", {}).get("summary", "")
                lines.append(f"- **{name}** ({severity}): {summary}")
        else:
            lines.append("No active alerts for this namespace.")

        # Events
        lines.append("\n## Kubernetes Events\n")
        if isinstance(events, BaseException):
            lines.append(f"Error: {events}")
        elif isinstance(events, list) and events:
            warning_events = [e for e in events if e.get("type") == "Warning"]
            if warning_events:
                for event in warning_events[:10]:
                    lines.append(
                        f"- [{event['reason']}] {event['message']} "
                        f"({event['object']}, x{event['count']})"
                    )
            else:
                lines.append("No warning events.")
        else:
            lines.append("No events found.")

        return "\n".join(lines)

    return {
        "investigate_latency": investigate_latency,
        "investigate_gpu": investigate_gpu,
        "investigate_errors": investigate_errors,
    }
