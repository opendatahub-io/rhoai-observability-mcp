"""Fake vLLM metrics exporter for local Kind development.

Exposes synthetic Prometheus metrics that mimic a running vLLM instance,
so MCP server tools (get_vllm_metrics, query_prometheus, etc.) return
realistic data in a local dev environment.
"""

import math
import random
import time

from prometheus_client import Counter, Gauge, Histogram, start_http_server

MODEL_NAME = "granite-3.1-8b"

# --- Histograms (match vLLM metric names) ---
ttft = Histogram(
    "vllm:time_to_first_token_seconds",
    "Time to first token in seconds",
    ["model_name"],
    buckets=(0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.5, 1.0),
)
tpot = Histogram(
    "vllm:time_per_output_token_seconds",
    "Time per output token in seconds",
    ["model_name"],
    buckets=(0.005, 0.01, 0.015, 0.02, 0.03, 0.04, 0.05, 0.075, 0.1),
)
e2e = Histogram(
    "vllm:e2e_request_latency_seconds",
    "End-to-end request latency in seconds",
    ["model_name"],
    buckets=(0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0),
)

# --- Gauges ---
cache_usage = Gauge(
    "vllm:gpu_cache_usage_perc",
    "GPU KV cache usage percentage",
    ["model_name"],
)
requests_waiting = Gauge(
    "vllm:num_requests_waiting",
    "Number of requests waiting in queue",
    ["model_name"],
)
requests_running = Gauge(
    "vllm:num_requests_running",
    "Number of requests currently running",
    ["model_name"],
)
gpu_util = Gauge(
    "DCGM_FI_DEV_GPU_UTIL",
    "GPU utilization percentage",
    ["gpu", "modelName"],
)

# --- Counters ---
gen_tokens = Counter(
    "vllm:generation_tokens_total",
    "Total generation tokens",
    ["model_name"],
)


def generate_samples():
    """Generate one round of synthetic metric observations."""
    t = time.time()

    # Histograms: observe random samples
    ttft.labels(model_name=MODEL_NAME).observe(random.uniform(0.05, 0.3))
    tpot.labels(model_name=MODEL_NAME).observe(random.uniform(0.01, 0.05))
    e2e.labels(model_name=MODEL_NAME).observe(random.uniform(0.1, 2.0))

    # Gauges: oscillate with jitter using sine wave for smooth variation
    phase = t / 60.0  # one full cycle per ~6 minutes
    cache_usage.labels(model_name=MODEL_NAME).set(
        0.55 + 0.25 * math.sin(phase) + random.uniform(-0.05, 0.05)
    )
    requests_waiting.labels(model_name=MODEL_NAME).set(
        max(0, int(7 + 8 * math.sin(phase * 0.7) + random.randint(-2, 2)))
    )
    requests_running.labels(model_name=MODEL_NAME).set(
        max(1, int(4 + 3 * math.sin(phase * 1.3) + random.randint(-1, 1)))
    )
    gpu_util.labels(gpu="0", modelName=MODEL_NAME).set(
        67 + 28 * math.sin(phase * 0.5) + random.uniform(-5, 5)
    )

    # Counter: increment generation tokens
    gen_tokens.labels(model_name=MODEL_NAME).inc(random.randint(50, 200))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fake vLLM metrics exporter")
    parser.add_argument("--port", type=int, default=8000, help="Port to serve metrics on")
    parser.add_argument(
        "--interval", type=float, default=5.0, help="Seconds between sample generation"
    )
    args = parser.parse_args()

    start_http_server(args.port)
    print(f"Fake vLLM exporter serving on :{args.port}/metrics")
    while True:
        generate_samples()
        time.sleep(args.interval)
