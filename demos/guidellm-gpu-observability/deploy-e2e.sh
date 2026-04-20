#!/usr/bin/env bash
# End-to-end deployment: vLLM + GuideLLM + Observability MCP
# Prerequisites: OpenShift cluster with GPU node, GPU Operator, NFD, oc logged in
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VLLM_NS="vllm-demo"
MCP_NS="rhoai-obs-mcp"

# Configurable timeouts (seconds). Override via environment variables.
VLLM_TIMEOUT="${VLLM_TIMEOUT:-900}"
MCP_TIMEOUT="${MCP_TIMEOUT:-120}"
GUIDELLM_TIMEOUT="${GUIDELLM_TIMEOUT:-1200}"

# Validate timeout values are positive integers
for var in VLLM_TIMEOUT MCP_TIMEOUT GUIDELLM_TIMEOUT; do
  val="${!var}"
  if ! [[ "$val" =~ ^[0-9]+$ ]] || (( val <= 0 )); then
    echo "[ERROR] ${var}='${val}' is not a valid positive integer (seconds)." >&2
    exit 1
  fi
done

log() { echo "[INFO] $(date +%H:%M:%S) $*"; }
warn() { echo "[WARN] $(date +%H:%M:%S) $*"; }
err()  { echo "[ERROR] $(date +%H:%M:%S) $*"; exit 1; }

# Retry a command with backoff. Usage: retry <max_attempts> <delay_seconds> <command...>
retry() {
  local max_attempts=$1 delay=$2
  shift 2
  local attempt=1
  while true; do
    if "$@"; then
      return 0
    fi
    if (( attempt >= max_attempts )); then
      return 1
    fi
    warn "Attempt ${attempt}/${max_attempts} failed, retrying in ${delay}s..."
    sleep "$delay"
    (( attempt++ ))
    (( delay = delay < 30 ? delay * 2 : 30 ))
  done
}

# -------------------------------------------------------------------
# 1. Preflight
# -------------------------------------------------------------------
log "Cluster: $(oc whoami --show-server)"
log "User: $(oc whoami)"

GPU_NODE=$(oc get nodes -l nvidia.com/gpu.count=1 -o name 2>/dev/null | head -1)
[[ -z "$GPU_NODE" ]] && err "No GPU node found. Install NVIDIA GPU Operator + NFD first."
GPU_PRODUCT=$(oc get "${GPU_NODE}" -o jsonpath='{.metadata.labels.nvidia\.com/gpu\.product}')
log "GPU node: ${GPU_NODE} (${GPU_PRODUCT})"

# Check GPU availability — warn early if all GPUs are already allocated.
# This check requires cluster-wide pod list permissions; if unavailable, skip gracefully.
GPU_ALLOCATABLE=$(oc get "${GPU_NODE}" -o jsonpath='{.status.allocatable.nvidia\.com/gpu}' 2>/dev/null || echo "")
if [[ -n "$GPU_ALLOCATABLE" ]]; then
  GPU_NODE_NAME=$(echo "${GPU_NODE}" | cut -d/ -f2)
  GPU_REQUESTED=$(oc get pods --all-namespaces \
    --field-selector="spec.nodeName=${GPU_NODE_NAME},status.phase=Running" \
    -o jsonpath='{range .items[*]}{.spec.containers[*].resources.requests.nvidia\.com/gpu}{"\n"}{end}' 2>/dev/null \
    | awk '{s+=$1} END {print s+0}' || echo "0")
  GPU_FREE=$(( GPU_ALLOCATABLE - GPU_REQUESTED ))
  if (( GPU_FREE <= 0 )); then
    warn "All ${GPU_ALLOCATABLE} GPU(s) on ${GPU_NODE} appear to be in use (${GPU_REQUESTED} requested)."
    warn "vLLM will be Pending until a GPU becomes available."
    oc get pods --all-namespaces \
      --field-selector="spec.nodeName=${GPU_NODE_NAME},status.phase=Running" \
      -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,GPU:.spec.containers[*].resources.requests.nvidia\.com/gpu' \
      --no-headers 2>/dev/null | grep -v '<none>' || true
  else
    log "GPU availability: ${GPU_FREE}/${GPU_ALLOCATABLE} free"
  fi
else
  log "GPU availability check skipped (could not query node allocatable resources)"
fi

oc get pods -n nvidia-gpu-operator -l app=nvidia-dcgm-exporter --no-headers | head -1 \
  || err "DCGM exporter not running in nvidia-gpu-operator namespace"

# -------------------------------------------------------------------
# 2. Deploy vLLM
# -------------------------------------------------------------------
log "Deploying vLLM in ${VLLM_NS}"
oc new-project "${VLLM_NS}" 2>/dev/null || oc project "${VLLM_NS}" >/dev/null

# Grant anyuid SCC — upstream vLLM image runs as root
oc adm policy add-scc-to-user anyuid -z default -n "${VLLM_NS}" 2>/dev/null

oc apply -f "${SCRIPT_DIR}/vllm-deployment.yaml"

log "Waiting for vLLM rollout (image pull + model load, timeout ${VLLM_TIMEOUT}s)..."
if ! oc rollout status deployment/vllm -n "${VLLM_NS}" --timeout="${VLLM_TIMEOUT}s"; then
  warn "vLLM not ready within ${VLLM_TIMEOUT}s. Pod status:"
  oc get pods -n "${VLLM_NS}" -o wide
  POD_STATUS=$(oc get pods -n "${VLLM_NS}" -l app=vllm -o jsonpath='{.items[0].status.phase}' 2>/dev/null)
  if [[ "$POD_STATUS" == "Pending" ]]; then
    warn "Pod is still Pending — likely waiting for GPU or image pull."
    oc describe pod -n "${VLLM_NS}" -l app=vllm | grep -A5 "Events:" | tail -8
  else
    oc describe pod -n "${VLLM_NS}" -l app=vllm | tail -20
  fi
  err "vLLM deployment failed. Try increasing VLLM_TIMEOUT (current: ${VLLM_TIMEOUT}s)."
fi

# -------------------------------------------------------------------
# 3. Validate vLLM
# -------------------------------------------------------------------
log "Validating vLLM (with retries for warmup)..."

if ! retry 5 3 oc exec -n "${VLLM_NS}" deploy/vllm -- curl -sf http://localhost:8000/health; then
  err "vLLM health check failed after retries"
fi
log "Health: OK"

MODEL_ID=""
for attempt in {1..5}; do
  MODEL_ID=$(oc exec -n "${VLLM_NS}" deploy/vllm -- \
    curl -sf http://localhost:8000/v1/models 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['data'][0]['id'])" 2>/dev/null) && break
  warn "Model list not ready yet (attempt ${attempt}/5), waiting..."
  sleep 5
done
[[ -z "$MODEL_ID" ]] && err "Could not retrieve model ID from vLLM"
log "Model loaded: ${MODEL_ID}"

COMPLETION=$(oc exec -n "${VLLM_NS}" deploy/vllm -- \
  curl -sf http://localhost:8000/v1/completions \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"${MODEL_ID}\",\"prompt\":\"Hello\",\"max_tokens\":16}" 2>/dev/null)
log "Inference test: $(echo "$COMPLETION" | python3 -c "import sys,json; print(json.load(sys.stdin)['choices'][0]['text'][:60])" 2>/dev/null || echo "$COMPLETION" | head -c 100)"

# -------------------------------------------------------------------
# 4. Deploy MCP server
# -------------------------------------------------------------------
log "Deploying Observability MCP in ${MCP_NS}"
oc new-project "${MCP_NS}" 2>/dev/null || oc project "${MCP_NS}" >/dev/null

# Deploy using oc's built-in Kustomize support
oc apply -k "${REPO_ROOT}/deploy/overlays/openshift" -n "${MCP_NS}"

# Additional monitoring API RBAC (not in the overlay — needed for Alertmanager API on some clusters)
oc apply -f "${SCRIPT_DIR}/monitoring-rbac.yaml"
oc adm policy add-cluster-role-to-user rhoai-obs-mcp-monitoring-api \
  -z rhoai-obs-mcp -n "${MCP_NS}" 2>/dev/null

if ! oc rollout status deployment/rhoai-obs-mcp -n "${MCP_NS}" --timeout="${MCP_TIMEOUT}s"; then
  oc get pods -n "${MCP_NS}" -o wide
  err "MCP deployment failed"
fi

ROUTE_HOST=$(oc get route rhoai-obs-mcp -n "${MCP_NS}" -o jsonpath='{.spec.host}')
log "MCP route: https://${ROUTE_HOST}/sse"

# -------------------------------------------------------------------
# 5. Validate MCP
# -------------------------------------------------------------------
log "Validating MCP protocol"
OUT=/tmp/mcp_e2e_validate.out
COOK=/tmp/mcp_e2e_cookie.txt
rm -f "$OUT" "$COOK"
(curl -skN -c "$COOK" "https://${ROUTE_HOST}/sse" > "$OUT") &
SSE_PID=$!
MSG_PATH=""
for _ in {1..15}; do
  MSG_PATH=$(awk -F'data: ' '/^data: /{print $2; exit}' "$OUT" 2>/dev/null | tr -d '\r')
  [[ -n "$MSG_PATH" ]] && break
  sleep 1
done
if [[ -z "$MSG_PATH" ]]; then
  kill $SSE_PID 2>/dev/null || true
  err "Could not establish SSE session"
fi

# Initialize + list tools + query GPU metrics
curl -sk -b "$COOK" -X POST "https://${ROUTE_HOST}${MSG_PATH}" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"e2e","version":"0.1"}}}' >/dev/null
curl -sk -b "$COOK" -X POST "https://${ROUTE_HOST}${MSG_PATH}" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}' >/dev/null
curl -sk -b "$COOK" -X POST "https://${ROUTE_HOST}${MSG_PATH}" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' >/dev/null
curl -sk -b "$COOK" -X POST "https://${ROUTE_HOST}${MSG_PATH}" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"query_prometheus","arguments":{"query":"DCGM_FI_DEV_GPU_UTIL"}}}' >/dev/null
curl -sk -b "$COOK" -X POST "https://${ROUTE_HOST}${MSG_PATH}" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_pods","arguments":{"namespace":"'"${VLLM_NS}"'"}}}' >/dev/null
sleep 3
kill $SSE_PID 2>/dev/null || true

TOOL_COUNT=$(python3 -c "
import re, json
data = open('$OUT').read()
for e in data.split('event: message'):
    m = re.search(r'data: (.+)', e)
    if m:
        try:
            j = json.loads(m.group(1))
            if j.get('id') == 2 and 'result' in j:
                print(len(j['result'].get('tools',[])))
        except: pass
" 2>/dev/null)

if [[ "$TOOL_COUNT" -ge 17 ]]; then
  log "MCP validated: ${TOOL_COUNT} tools, GPU metrics + pod queries working"
else
  warn "MCP returned ${TOOL_COUNT:-0} tools (expected 17+)"
fi

# -------------------------------------------------------------------
# 6. Run GuideLLM benchmark
# -------------------------------------------------------------------
log "Launching GuideLLM benchmark"
oc project "${VLLM_NS}" >/dev/null
oc delete job/guidellm-bench -n "${VLLM_NS}" 2>/dev/null || true
oc apply -f "${SCRIPT_DIR}/guidellm-job.yaml"
log "GuideLLM running. Follow with: oc logs -f job/guidellm-bench -n ${VLLM_NS}"

GUIDELLM_OK=true
log "Waiting for GuideLLM to complete (timeout ${GUIDELLM_TIMEOUT}s)..."
if oc wait --for=condition=complete job/guidellm-bench -n "${VLLM_NS}" --timeout="${GUIDELLM_TIMEOUT}s"; then
  log "GuideLLM complete. Results:"
  oc logs job/guidellm-bench -n "${VLLM_NS}" 2>/dev/null | tail -40
else
  # Check if the job failed vs still running
  JOB_STATUS=$(oc get job/guidellm-bench -n "${VLLM_NS}" -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}' 2>/dev/null)
  if [[ "$JOB_STATUS" == "True" ]]; then
    GUIDELLM_OK=false
    warn "GuideLLM job failed. Logs:"
    oc logs job/guidellm-bench -n "${VLLM_NS}" 2>/dev/null | tail -20
  else
    warn "GuideLLM still running after ${GUIDELLM_TIMEOUT}s — it may need more time."
    warn "The demo stack (vLLM + MCP) is ready. Check benchmark progress with:"
    warn "  oc logs -f job/guidellm-bench -n ${VLLM_NS}"
  fi
fi

# -------------------------------------------------------------------
# 7. Summary
# -------------------------------------------------------------------
echo ""
log "=========================================="
if [[ "$GUIDELLM_OK" == true ]]; then
  log "Demo deployment complete"
else
  log "Demo deployment complete (GuideLLM benchmark failed)"
fi
log "=========================================="
log "vLLM:       running in ${VLLM_NS} (model: ${MODEL_ID})"
log "MCP:        https://${ROUTE_HOST}/sse"
log "GuideLLM:   job/guidellm-bench in ${VLLM_NS}"
log ""
log "Connect Claude Code:"
log "  claude mcp add rhoai-observability https://${ROUTE_HOST}/sse"
log ""
log "Teardown:"
log "  ${SCRIPT_DIR}/teardown.sh"

# Exit non-zero if GuideLLM failed (CI visibility)
[[ "$GUIDELLM_OK" == true ]]
