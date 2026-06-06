"""Gateway entry point — runs the FastAPI application via uvicorn.

Usage:
    python -m agentmesh.platform.gateway.main
"""
import uvicorn

from .app import create_app

app = create_app()

if __name__ == "__main__":
    """Run the development server on port 8000 with auto-reload."""
    uvicorn.run("gateway.main:app", host="0.0.0.0", port=8000, reload=True)
