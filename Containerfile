# Multi-stage Containerfile for RHOAI Observability MCP Server
# Build: podman build --platform=linux/amd64 -f Containerfile -t rhoai-obs-mcp .

# =============================================================================
# Stage 1: Builder - Install dependencies with uv
# =============================================================================
ARG BUILD_PLATFORM=linux/amd64
FROM --platform=${BUILD_PLATFORM} registry.access.redhat.com/ubi9/python-312 AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /opt/app-root/src

COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

RUN uv sync --frozen --no-dev

# =============================================================================
# Stage 2: Runtime - Minimal production image
# =============================================================================
FROM --platform=${BUILD_PLATFORM} registry.access.redhat.com/ubi9/python-312 AS runtime

LABEL org.opencontainers.image.title="RHOAI Observability MCP Server"
LABEL org.opencontainers.image.description="MCP server for Red Hat OpenShift AI observability and troubleshooting"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.source="https://github.com/opendatahub-io/rhoai-observability-mcp"

WORKDIR /opt/app-root/src

COPY --from=builder /opt/app-root/src/.venv /opt/app-root/src/.venv
COPY --from=builder /opt/app-root/src/src /opt/app-root/src/src

ENV PATH="/opt/app-root/src/.venv/bin:$PATH"

ENV MCP_TRANSPORT="sse"
ENV MCP_HOST="0.0.0.0"
ENV MCP_PORT="8080"
ENV LOG_LEVEL="INFO"

EXPOSE 8080

USER 1001

ENTRYPOINT ["python", "-m", "rhoai_obs_mcp"]
