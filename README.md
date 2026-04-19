# Red Hat OpenShift AI (RHOAI) Observability MCP

[![CI](https://github.com/amito/rhoai-observability-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/amito/rhoai-observability-mcp/actions/workflows/ci.yml)
[![Build](https://github.com/amito/rhoai-observability-mcp/actions/workflows/container-build.yml/badge.svg)](https://github.com/amito/rhoai-observability-mcp/actions/workflows/container-build.yml)
[![codecov](https://codecov.io/gh/amito/rhoai-observability-mcp/branch/main/graph/badge.svg)](https://codecov.io/gh/amito/rhoai-observability-mcp)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An MCP (Model Context Protocol) server that gives AI assistants direct access to Red Hat OpenShift AI observability data. Query Prometheus metrics, Alertmanager alerts, Loki logs, Grafana dashboards, and Kubernetes cluster state to troubleshoot vLLM inference workloads.

## Features

- **21 tools** across 7 categories for comprehensive observability
- **vLLM-aware** metrics (TTFT, TPOT, E2E latency, KV cache, queue depth)
- **Composite investigation** tools that correlate metrics, logs, and alerts automatically
- **Auto-detection** of in-cluster vs external access to OpenShift services
- Built on [FastMCP](https://github.com/jlowin/fastmcp) with async backends via `httpx`

## Architecture

```mermaid
graph TD
    A[Claude / AI Assistant] -->|MCP Protocol| B[rhoai-observability-mcp]
    B --> C[Thanos / Prometheus]
    B --> D[Alertmanager]
    B --> E[Loki]
    B --> F[Tempo]
    B --> G[Grafana]
    B --> H[Kubernetes / OpenShift]
```

**Backends:**

| Backend | Purpose | Source |
|---------|---------|-------|
| Prometheus (Thanos) | Metrics queries (PromQL) | `backends/prometheus.py` |
| Alertmanager | Active alerts and alert groups | `backends/alertmanager.py` |
| Loki | Log queries (LogQL) | `backends/loki.py` |
| Tempo | Distributed trace queries (TraceQL) | `backends/tempo.py` |
| Grafana | Dashboard discovery and panel queries | `backends/grafana.py` |
| Kubernetes (OpenShift) | Pods, events, nodes, InferenceServices | `backends/openshift.py` |

## Quick Start

```bash
# Clone and install
git clone https://github.com/amito/rhoai-observability-mcp.git
cd rhoai-observability-mcp
uv pip install -e ".[dev]"

# Configure (see INSTALL.md for all options)
export THANOS_URL=https://thanos-querier.openshift-monitoring.svc:9091
export ALERTMANAGER_URL=https://alertmanager-main.openshift-monitoring.svc:9093
export OPENSHIFT_TOKEN=$(oc whoami -t)

# Run
python -m rhoai_obs_mcp.server
```

See [INSTALL.md](INSTALL.md) for detailed setup, configuration, and Claude Desktop integration.

## Build & Deploy

### Build the container image

```bash
make build
```

Override the image name or tag:

```bash
make build IMAGE_NAME=quay.io/myorg/rhoai-observability-mcp IMAGE_TAG=v1.0.0
```

### Push to registry

```bash
make push
```

### Deploy to OpenShift

Prerequisites: `oc login` to your cluster, `kustomize` installed, and create the target project:

```bash
oc new-project rhoai-obs-mcp
```

Then deploy:

```bash
make deploy
```

This uses Kustomize to build the OpenShift overlay (`deploy/overlays/openshift/`) on top of the base manifests (`deploy/base/`) and applies them to the `rhoai-obs-mcp` namespace. To deploy to a different namespace:

```bash
make deploy NAMESPACE=my-namespace
```

### Undeploy

```bash
make undeploy
```

If you deployed to a custom namespace, pass the same value:

```bash
make undeploy NAMESPACE=my-namespace
```

### CI-built images

Container images are automatically built from `main` and published to GHCR:

```
ghcr.io/amito/rhoai-observability-mcp:latest
```

## Local Development with Kind

Set up a local Kubernetes cluster with mock observability backends for development and testing:

```bash
# Prerequisites: kind, kubectl, helm, kustomize
make kind-up
```

This creates a Kind cluster, installs Prometheus + Alertmanager + Grafana via Helm, deploys a fake vLLM metrics exporter, and deploys the MCP server. Access the MCP server at `http://localhost:30080`.

To point at real external backends instead of the mocks:

```bash
make kind-deploy THANOS_URL=https://real-cluster:9091 ALERTMANAGER_URL=https://real-cluster:9093 GRAFANA_URL=https://real-cluster:3000 TEMPO_URL=https://real-cluster:8080
```

Tear down:

```bash
make kind-down
```

## Tool Reference

### Metrics

| Tool | Description |
|------|-------------|
| `query_prometheus` | Execute a raw PromQL query against ThanosQuerier |
| `query_prometheus_range` | Execute a PromQL range query to get time-series data (trends, spikes, correlations) |
| `get_vllm_metrics` | Get a summary of key vLLM metrics (TTFT, TPOT, E2E, cache, queue) for a model |
| `list_metrics` | List available Prometheus metric names, optionally filtered by regex |

### Alerts

| Tool | Description |
|------|-------------|
| `get_alerts` | Get active alerts from Alertmanager, filterable by severity and labels |
| `get_alert_groups` | Get alerts grouped by their routing labels |

### Logs

| Tool | Description |
|------|-------------|
| `query_logs` | Execute a LogQL query against OpenShift LokiStack |
| `get_pod_logs` | Get logs for a specific pod by namespace and name |

### Traces

| Tool | Description |
|------|-------------|
| `get_trace` | Fetch a distributed trace by its trace ID |
| `search_traces` | Search for traces using TraceQL expressions |
| `list_trace_tags` | List available trace tag names for building TraceQL queries |

### Cluster

| Tool | Description |
|------|-------------|
| `get_pods` | List pods in a namespace with status, restarts, and creation time |
| `get_events` | List Kubernetes events, filterable by resource and reason |
| `get_node_status` | Get node status, capacity, and GPU allocation info |
| `describe_resource` | Get detailed description of a Kubernetes resource |
| `get_inference_services` | List KServe InferenceService resources |

### Dashboards

| Tool | Description |
|------|-------------|
| `list_dashboards` | List available Grafana dashboards, filterable by tag or title |
| `get_dashboard_panels` | Get panels and their queries from a Grafana dashboard |

### Investigation

| Tool | Description |
|------|-------------|
| `investigate_latency` | Correlate latency metrics, error logs, and alerts for a vLLM model |
| `investigate_gpu` | Correlate GPU utilization, KV cache, queue depth, and pod status |
| `investigate_errors` | Correlate error logs, alerts, and Kubernetes events in a namespace |

## Documentation

- [INSTALL.md](INSTALL.md) -- Installation, configuration, and integration
- [TESTING.md](TESTING.md) -- Running tests and writing new ones
- [CONTRIBUTING.md](CONTRIBUTING.md) -- Development setup and contribution guidelines

## License

[MIT](LICENSE)
