# GuideLLM + GPU Observability MCP Demo

Deploy vLLM on a GPU node, benchmark it with GuideLLM, then use the Observability MCP server to investigate GPU behavior via natural language.

The story: **Run load. Ask questions. Get answers with evidence.**

## Prerequisites

- OpenShift 4.16+ cluster with at least one GPU worker node
- NVIDIA GPU Operator and NFD Operator installed (DCGM exporter running)
- `oc` CLI installed (includes built-in Kustomize support)
- Authenticated with cluster-admin (`oc login`)

No RHOAI, KServe, Service Mesh, or HuggingFace token required. The model (`Qwen/Qwen2.5-0.5B-Instruct`) is publicly available. Everything deploys as plain Kubernetes resources.

## Quick Start

```bash
./demos/guidellm-gpu-observability/deploy-e2e.sh
```

This will:
1. Verify a GPU node exists and DCGM exporter is running
2. Deploy vLLM (`Qwen/Qwen2.5-0.5B-Instruct`) in `vllm-demo` namespace
3. Validate model health and run a test inference
4. Deploy the Observability MCP server in `rhoai-obs-mcp` namespace
5. Grant monitoring RBAC for Thanos/Alertmanager API access
6. Validate MCP protocol (SSE handshake + tools/list + GPU metrics query)
7. Run GuideLLM benchmark (3 concurrency levels, ~6-8 min) and print results

## Step-by-Step Manual Deploy

### 1. Verify cluster and GPU

```bash
oc whoami
oc get nodes -l nvidia.com/gpu.count=1 \
  -o custom-columns='NAME:.metadata.name,GPU:.status.capacity.nvidia\.com/gpu,GPU_PRODUCT:.metadata.labels.nvidia\.com/gpu\.product'
oc get pods -n nvidia-gpu-operator -l app=nvidia-dcgm-exporter
```

### 2. Deploy vLLM

```bash
oc new-project vllm-demo
oc adm policy add-scc-to-user anyuid -z default -n vllm-demo
oc apply -f demos/guidellm-gpu-observability/vllm-deployment.yaml
oc rollout status deployment/vllm -n vllm-demo --timeout=600s
```

### 3. Validate vLLM

```bash
oc exec -n vllm-demo deploy/vllm -- curl -s http://localhost:8000/health
oc exec -n vllm-demo deploy/vllm -- curl -s http://localhost:8000/v1/models | python3 -m json.tool
oc exec -n vllm-demo deploy/vllm -- \
  curl -s http://localhost:8000/v1/completions \
    -H 'Content-Type: application/json' \
    -d '{"model":"Qwen/Qwen2.5-0.5B-Instruct","prompt":"What is Kubernetes?","max_tokens":64}' \
  | python3 -m json.tool
```

### 4. Deploy the Observability MCP server

Uses `oc apply -k` (built-in Kustomize support) with the OpenShift overlay from `deploy/overlays/openshift/`.

```bash
oc new-project rhoai-obs-mcp
oc apply -k deploy/overlays/openshift -n rhoai-obs-mcp
oc apply -f demos/guidellm-gpu-observability/monitoring-rbac.yaml
oc adm policy add-cluster-role-to-user rhoai-obs-mcp-monitoring-api -z rhoai-obs-mcp -n rhoai-obs-mcp
oc rollout status deployment/rhoai-obs-mcp -n rhoai-obs-mcp --timeout=120s
echo "MCP endpoint:"
oc get route rhoai-obs-mcp -n rhoai-obs-mcp -o jsonpath='https://{.spec.host}/sse'
```

### 5. Run GuideLLM benchmark

```bash
oc apply -f demos/guidellm-gpu-observability/guidellm-job.yaml
oc logs -f job/guidellm-bench -n vllm-demo
```

### 6. Connect an MCP client

**Claude Code:**

OpenShift routes use self-signed TLS certs by default, so Claude Code needs TLS verification disabled to connect without trusting the cluster CA:

```bash
ROUTE_HOST=$(oc get route rhoai-obs-mcp -n rhoai-obs-mcp -o jsonpath='{.spec.host}')
NODE_TLS_REJECT_UNAUTHORIZED=0 claude mcp add --transport sse rhoai-observability "https://${ROUTE_HOST}/sse"
```

> This is appropriate for demo/dev environments. For production, configure the cluster with a trusted certificate instead.

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "rhoai-observability": {
      "url": "https://<route-host>/sse"
    }
  }
}
```

## Validate the Full Stack

Run this after deployment to confirm vLLM, MCP, and GPU metrics are all working together:

```bash
ROUTE_HOST=$(oc get route rhoai-obs-mcp -n rhoai-obs-mcp -o jsonpath='{.spec.host}')

# 1. vLLM health
echo "=== vLLM health ==="
oc exec -n vllm-demo deploy/vllm -- curl -sf http://localhost:8000/health && echo "OK" || echo "FAIL"

# 2. MCP SSE handshake
echo "=== MCP SSE handshake ==="
curl -sk "https://${ROUTE_HOST}/sse" --max-time 3
echo "  <- should show 'event: endpoint' with a session_id"

# 3. Full MCP protocol: init -> tools/list -> GPU metrics -> pods
echo "=== MCP protocol validation ==="
OUT=/tmp/mcp_validate.out
COOK=/tmp/mcp_validate_cookie.txt
rm -f "$OUT" "$COOK"
(curl -skN -c "$COOK" "https://${ROUTE_HOST}/sse" > "$OUT") &
SSE_PID=$!
sleep 2
MSG_PATH=$(awk -F'data: ' '/^data: /{print $2; exit}' "$OUT" | tr -d '\r')

# Initialize
curl -sk -b "$COOK" -o /dev/null -w "init: HTTP %{http_code}\n" \
  -X POST "https://${ROUTE_HOST}${MSG_PATH}" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"validate","version":"0.1"}}}'
curl -sk -b "$COOK" -o /dev/null -w "initialized: HTTP %{http_code}\n" \
  -X POST "https://${ROUTE_HOST}${MSG_PATH}" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'

# List tools
curl -sk -b "$COOK" -o /dev/null -w "tools/list: HTTP %{http_code}\n" \
  -X POST "https://${ROUTE_HOST}${MSG_PATH}" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

# Query GPU metrics
curl -sk -b "$COOK" -o /dev/null -w "GPU metrics: HTTP %{http_code}\n" \
  -X POST "https://${ROUTE_HOST}${MSG_PATH}" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"query_prometheus","arguments":{"query":"DCGM_FI_DEV_GPU_UTIL"}}}'

# Get pods
curl -sk -b "$COOK" -o /dev/null -w "get_pods: HTTP %{http_code}\n" \
  -X POST "https://${ROUTE_HOST}${MSG_PATH}" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_pods","arguments":{"namespace":"vllm-demo"}}}'

sleep 3
kill $SSE_PID 2>/dev/null || true

echo ""
echo "MCP response IDs (expect 1,2,3,4):"
grep -o '"id":[0-9]*' "$OUT" | sort -t: -k2 -n -u
```

**Expected results:**
- All HTTP status codes should be `202`
- id=1: MCP initialize response (protocol version, capabilities)
- id=2: tools/list with 17+ tools
- id=3: `DCGM_FI_DEV_GPU_UTIL` data for the GPU node
- id=4: vLLM pod listed as Running in `vllm-demo`

## What to Ask the MCP

Once connected, try these prompts:

```
"Show me the GPU nodes and what's using them"
"What does GPU utilization look like across the cluster?"
"Investigate GPU behavior — compute utilization, VRAM, temperature, and power"
"Are there any active alerts? What's the overall cluster health?"
"Show me the pods and events in the vllm-demo namespace"
```

The MCP queries Thanos/Prometheus for DCGM GPU metrics, Alertmanager for alerts, and the OpenShift API for pod/node/event data — then explains the results in natural language with source attribution.

## Available GPU Metrics (DCGM)

The NVIDIA DCGM exporter provides these metrics through Thanos:

| Metric | What it tells you |
|--------|-------------------|
| `DCGM_FI_DEV_GPU_UTIL` | GPU compute utilization (%) |
| `DCGM_FI_DEV_FB_USED` / `FB_FREE` | VRAM used/free (MiB) |
| `DCGM_FI_DEV_GPU_TEMP` | GPU temperature (C) |
| `DCGM_FI_DEV_POWER_USAGE` | Power draw (W) |
| `DCGM_FI_DEV_SM_CLOCK` / `MEM_CLOCK` | SM/memory clock (MHz) |
| `DCGM_FI_PROF_GR_ENGINE_ACTIVE` | Graphics engine active ratio |
| `DCGM_FI_PROF_DRAM_ACTIVE` | Memory bandwidth utilization |
| `DCGM_FI_PROF_PIPE_TENSOR_ACTIVE` | Tensor core activity |
| `DCGM_FI_PROF_PCIE_TX_BYTES` / `RX_BYTES` | PCIe throughput |

## Known Gotchas

These were discovered during deployment and are already handled in the manifests:

1. **K8s Service naming conflict**: A Service named `vllm` causes Kubernetes to inject `VLLM_PORT` and `VLLM_SERVICE_HOST` env vars, which collide with vLLM's own `VLLM_PORT` variable (`ValueError: VLLM_PORT appears to be a URI`). The Service is named `vllm-server` to avoid this.

2. **OpenShift SCC**: The upstream `vllm/vllm-openai` image runs as root. The deploy script grants `anyuid` SCC to the default ServiceAccount in the `vllm-demo` namespace.

3. **Cache directory permissions**: The upstream image needs writable cache dirs. The manifest sets `HF_HOME`, `TRANSFORMERS_CACHE`, and `XDG_CACHE_HOME` to `/tmp/hf-cache` backed by an emptyDir volume.

4. **GuideLLM CLI syntax**: Recent versions of GuideLLM use `guidellm benchmark run --target ...` (not the older `guidellm --target ...`). The job manifest has the correct syntax.

## Files

| File | Purpose |
|------|---------|
| `deploy-e2e.sh` | Full deployment, validation, and benchmark script |
| `teardown.sh` | Clean removal of all resources |
| `vllm-deployment.yaml` | vLLM Deployment + Service (with gotcha fixes) |
| `guidellm-job.yaml` | GuideLLM benchmark Job (concurrent profile, 3 rates) |
| `monitoring-rbac.yaml` | ClusterRole for Prometheus/Alertmanager API access |

## Teardown

```bash
./demos/guidellm-gpu-observability/teardown.sh
```

Or manually:

```bash
oc delete job/guidellm-bench -n vllm-demo
oc delete deployment/vllm service/vllm-server -n vllm-demo
oc delete project vllm-demo
oc delete -k deploy/overlays/openshift -n rhoai-obs-mcp --ignore-not-found
oc delete clusterrole rhoai-obs-mcp-monitoring-api
oc delete project rhoai-obs-mcp
```

## Architecture

```
+------------------+     natural language      +-------------------+
|  Claude Desktop  | -----------------------> |  Observability    |
|  or Claude Code  | <----------------------- |  MCP Server       |
+------------------+   structured evidence     | (rhoai-obs-mcp)   |
                                               +--------+----------+
                                                        |
                                    +-------------------+-------------------+
                                    |                   |                   |
                              +-----v-----+      +-----v------+     +-----v------+
                              |  Thanos   |      | Alertmanager|     | OpenShift  |
                              |  Querier  |      |             |     | API        |
                              +-----+-----+      +------------+     +-----+------+
                                    |                                      |
                          +---------+---------+                     +------+------+
                          |                   |                     |             |
                    +-----v-----+       +-----v-----+        +-----v---+   +-----v----+
                    |  DCGM     |       | Prometheus |       | Pods    |   | Events   |
                    |  Exporter |       | (cluster)  |       | Nodes   |   |          |
                    +-----+-----+       +-----------+        +---------+   +----------+
                          |
                    +-----v-----+
                    | GPU       |  <--- vLLM (Qwen2.5-0.5B-Instruct)
                    |           |  <--- GuideLLM benchmark
                    +-----------+
```
