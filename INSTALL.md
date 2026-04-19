# Installation

## Prerequisites

- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/)** package manager
- Access to an **OpenShift cluster** with RHOAI deployed (for live usage)
- `oc` CLI authenticated to the cluster (or a bearer token)

## Install

```bash
git clone https://github.com/your-org/rhoai-observability-mcp.git
cd rhoai-observability-mcp
uv pip install -e ".[dev]"
```

## Configuration

All settings are configured via environment variables or a `.env` file in the project root.

| Variable | Description | Default |
|----------|-------------|---------|
| `THANOS_URL` | ThanosQuerier URL for Prometheus queries | Auto-detected via OpenShift route |
| `ALERTMANAGER_URL` | Alertmanager URL | Auto-detected via OpenShift route |
| `LOKI_URL` | LokiStack gateway URL | Auto-detected via OpenShift route |
| `GRAFANA_URL` | Grafana URL | Auto-detected via OpenShift route |
| `TEMPO_URL` | Tempo gateway URL for distributed traces | Not auto-detected |
| `OPENSHIFT_TOKEN` | Bearer token override | Auto-detected from service account or `oc whoami -t` |
| `DEFAULT_TIME_RANGE` | Default PromQL/LogQL time range | `5m` |
| `LOG_LEVEL` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `REQUEST_TIMEOUT` | HTTP request timeout in seconds | `30.0` |

### Auto-Detection

When running **inside** an OpenShift cluster (as a pod), the server automatically:

- Reads the service account token from `/var/run/secrets/kubernetes.io/serviceaccount/token`
- Uses in-cluster service URLs for backends

When running **externally**, set the URL and token environment variables, or ensure `oc` is authenticated so the smoke tests can auto-discover routes.

### Example `.env` File

```env
THANOS_URL=https://thanos-querier-openshift-monitoring.apps.mycluster.example.com
ALERTMANAGER_URL=https://alertmanager-main-openshift-monitoring.apps.mycluster.example.com
LOKI_URL=https://logging-loki-openshift-logging.apps.mycluster.example.com
GRAFANA_URL=https://grafana-open-cluster-management-observability.apps.mycluster.example.com
TEMPO_URL=https://tempo-data-science-tempostack-gateway.apps.mycluster.example.com
OPENSHIFT_TOKEN=sha256~xxxxxxxxxxxxxxxxxxxx
LOG_LEVEL=DEBUG
```

## Local Development (Kind)

For local development without an OpenShift cluster, use Kind with mock backends:

### Prerequisites

- [Kind](https://kind.sigs.k8s.io/) — local Kubernetes clusters
- [kubectl](https://kubernetes.io/docs/tasks/tools/) — Kubernetes CLI
- [Helm](https://helm.sh/) — package manager for Kubernetes
- [Kustomize](https://kustomize.io/) — Kubernetes manifest customization

### Quick Start

```bash
make kind-up
```

This will:
1. Create a single-node Kind cluster
2. Install Prometheus, Alertmanager, and Grafana (via kube-prometheus-stack Helm chart)
3. Deploy a fake vLLM metrics exporter generating synthetic data
4. Build and deploy the MCP server

The MCP server is accessible at `http://localhost:30080`.

### Using Real Backends

To point the MCP server at real external backends instead of the in-cluster mocks:

```bash
make kind-deploy THANOS_URL=https://your-cluster:9091 ALERTMANAGER_URL=https://your-cluster:9093 GRAFANA_URL=https://your-cluster:3000 TEMPO_URL=https://your-cluster:8080
```

### Cleanup

```bash
make kind-down
```

## Running the Server

### Direct execution

```bash
python -m rhoai_obs_mcp.server
```

This starts the MCP server on stdio transport.

### Via MCP CLI

```bash
mcp run src/rhoai_obs_mcp/server.py
```

### Programmatic

```python
from rhoai_obs_mcp.server import create_server

mcp = create_server()
mcp.run(transport="stdio")
```

You can also pass configuration overrides:

```python
mcp = create_server(settings_override={
    "thanos_url": "https://thanos.example.com",
    "openshift_token": "my-token",
})
```

## Claude Desktop Integration

### Local server

Add the following to your Claude Desktop MCP configuration (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "rhoai-observability": {
      "command": "python",
      "args": ["-m", "rhoai_obs_mcp.server"],
      "cwd": "/path/to/rhoai-observability-mcp",
      "env": {
        "THANOS_URL": "https://thanos-querier.apps.mycluster.example.com",
        "ALERTMANAGER_URL": "https://alertmanager-main.apps.mycluster.example.com",
        "OPENSHIFT_TOKEN": "sha256~xxxxxxxxxxxxxxxxxxxx"
      }
    }
  }
}
```

### Remote server (deployed on OpenShift)

If the MCP server is [deployed on OpenShift](README.md#deploy-to-openshift), get the route URL and connect to it directly — no local checkout required:

```bash
oc get route rhoai-obs-mcp -n rhoai-obs-mcp -o jsonpath='https://{.spec.host}'
```

Then add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "rhoai-observability": {
      "url": "https://rhoai-obs-mcp-rhoai-obs-mcp.apps.mycluster.example.com/sse"
    }
  }
}
```

## Claude Code Integration

### Local server

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "rhoai-observability": {
      "command": "python",
      "args": ["-m", "rhoai_obs_mcp.server"],
      "cwd": "/path/to/rhoai-observability-mcp",
      "env": {
        "THANOS_URL": "https://thanos-querier.apps.mycluster.example.com",
        "OPENSHIFT_TOKEN": "sha256~xxxxxxxxxxxxxxxxxxxx"
      }
    }
  }
}
```

### Remote server (deployed on OpenShift)

Connect to the deployed server via its route URL:

```bash
claude mcp add rhoai-observability https://rhoai-obs-mcp-rhoai-obs-mcp.apps.mycluster.example.com/sse
```

Or add to `.mcp.json`:

```json
{
  "mcpServers": {
    "rhoai-observability": {
      "url": "https://rhoai-obs-mcp-rhoai-obs-mcp.apps.mycluster.example.com/sse"
    }
  }
}
```
