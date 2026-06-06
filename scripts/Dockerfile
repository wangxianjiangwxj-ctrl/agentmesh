# AgentMesh Dockerfile
# Offline-ready container image for AgentMesh API Gateway
# Base: python:3.11-slim
# Build: docker build -f scripts/Dockerfile -t agentmesh:latest .

FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system build dependencies (required by some wheels)
RUN apt-get update && \
    apt-get install --no-install-recommends -y \
        gcc \
        libffi-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy dependency specification first for Docker layer caching
COPY pyproject.toml ./

# Pre-install build tooling
RUN pip install --no-cache-dir build wheel

# Copy source code
COPY agentmesh/ ./agentmesh/

# Install the project and its runtime dependencies
RUN pip install --no-cache-dir .

# Expose the API gateway port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

# Run the FastAPI gateway via uvicorn
CMD ["uvicorn", "agentmesh.platform.gateway.main:app", "--host", "0.0.0.0", "--port", "8080"]
