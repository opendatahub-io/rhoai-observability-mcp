# Makefile for RHOAI Observability MCP Server

# =============================================================================
# Configuration
# =============================================================================

IMAGE_NAME ?= quay.io/rh-ee-amoren/rhoai-observability-mcp
IMAGE_TAG ?= latest
IMAGE := $(IMAGE_NAME):$(IMAGE_TAG)

# Container runtime detection (prefer podman)
CONTAINER_RUNTIME := $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null)

# Build platform
PLATFORM ?= linux/amd64

# Deploy namespace
NAMESPACE ?= rhoai-obs-mcp

# Kind cluster
KIND_CLUSTER_NAME ?= rhoai-obs-mcp
KIND_NAMESPACE ?= default
MONITORING_NAMESPACE ?= monitoring

# External backend overrides (optional, for pointing at real clusters)
THANOS_URL ?=
ALERTMANAGER_URL ?=
GRAFANA_URL ?=
TEMPO_URL ?=

.PHONY: help build push deploy undeploy restart clean kind-create kind-backends kind-deploy kind-up kind-down

# =============================================================================
# Help
# =============================================================================

help: ## Show this help message
	@echo "RHOAI Observability MCP Server"
	@echo ""
	@echo "Runtime: $(CONTAINER_RUNTIME)"
	@echo "Image:   $(IMAGE)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# =============================================================================
# Container
# =============================================================================

build: ## Build the container image
	DOCKER_DEFAULT_PLATFORM=$(PLATFORM) $(CONTAINER_RUNTIME) build --platform=$(PLATFORM) -f Containerfile -t $(IMAGE) .

push: ## Push the container image to registry
	$(CONTAINER_RUNTIME) push $(IMAGE)

# =============================================================================
# OpenShift
# =============================================================================

deploy: ## Deploy to OpenShift (requires oc login, NAMESPACE default: rhoai-obs-mcp)
	@command -v kustomize >/dev/null 2>&1 || { echo "Error: kustomize is required but not installed"; exit 1; }
	kustomize build deploy/overlays/openshift | oc apply -n $(NAMESPACE) -f -

undeploy: ## Remove from OpenShift
	kustomize build deploy/overlays/openshift | oc delete --ignore-not-found -n $(NAMESPACE) -f -

restart: ## Rollout restart the deployment (e.g. after pushing a new :latest image)
	oc rollout restart deployment/rhoai-obs-mcp -n $(NAMESPACE)

# =============================================================================
# Kind (local development)
# =============================================================================

kind-create: ## Create a Kind cluster for local development
	@command -v kind >/dev/null 2>&1 || { echo "Error: kind is required. Install from https://kind.sigs.k8s.io/"; exit 1; }
	@command -v kubectl >/dev/null 2>&1 || { echo "Error: kubectl is required"; exit 1; }
	kind create cluster --name $(KIND_CLUSTER_NAME) --config deploy/overlays/kind/kind-config.yaml
	@echo "Kind cluster '$(KIND_CLUSTER_NAME)' created"

kind-backends: ## Install Prometheus, Alertmanager, and Grafana via Helm
	@command -v helm >/dev/null 2>&1 || { echo "Error: helm is required. Install from https://helm.sh/"; exit 1; }
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true
	helm repo update prometheus-community
	kubectl create namespace $(MONITORING_NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -
	helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
		--namespace $(MONITORING_NAMESPACE) \
		-f deploy/overlays/kind/kube-prometheus-values.yaml \
		--wait --timeout 5m

kind-deploy: ## Deploy the MCP server to Kind
	@command -v kustomize >/dev/null 2>&1 || { echo "Error: kustomize is required"; exit 1; }
	$(CONTAINER_RUNTIME) build --platform=$(PLATFORM) -f Containerfile -t $(IMAGE) .
	$(CONTAINER_RUNTIME) save $(IMAGE) | kind load image-archive /dev/stdin --name $(KIND_CLUSTER_NAME)
	kustomize build deploy/overlays/kind | kubectl apply -n $(KIND_NAMESPACE) -f -
	$(if $(THANOS_URL),kubectl set env deployment/rhoai-obs-mcp -n $(KIND_NAMESPACE) "THANOS_URL=$(THANOS_URL)",)
	$(if $(ALERTMANAGER_URL),kubectl set env deployment/rhoai-obs-mcp -n $(KIND_NAMESPACE) "ALERTMANAGER_URL=$(ALERTMANAGER_URL)",)
	$(if $(GRAFANA_URL),kubectl set env deployment/rhoai-obs-mcp -n $(KIND_NAMESPACE) "GRAFANA_URL=$(GRAFANA_URL)",)
	$(if $(TEMPO_URL),kubectl set env deployment/rhoai-obs-mcp -n $(KIND_NAMESPACE) "TEMPO_URL=$(TEMPO_URL)",)
	@echo "MCP server deployed. Access at http://localhost:30080"

kind-up: kind-create kind-backends kind-deploy ## Create Kind cluster with backends and deploy MCP server

kind-down: ## Delete the Kind cluster
	kind delete cluster --name $(KIND_CLUSTER_NAME)

# =============================================================================
# Development
# =============================================================================

clean: ## Remove the container image
	-$(CONTAINER_RUNTIME) rmi $(IMAGE) 2>/dev/null || true
