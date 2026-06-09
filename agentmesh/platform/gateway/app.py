"""Gateway application factory — wires FastAPI with all route modules and middleware.

Creates the FastAPI application, registers routers and middleware,
and exposes a convenience factory function.
"""
from fastapi import FastAPI

from .middleware.auth import AuthMiddleware
from .routers import escrow, evidence, identity, reputation, tasks, web_ui


def create_app() -> FastAPI:
    """Create and configure the AgentMesh API Gateway application.

    Registers all five route modules under the ``/api/v1`` prefix and
    attaches the AuthMiddleware.

    Returns:
        A fully configured FastAPI application instance.
    """
    app = FastAPI(title="AgentMesh API Gateway", version="0.1.0")
    app.add_middleware(AuthMiddleware)
    app.include_router(identity.router, prefix="/api/v1")
    app.include_router(tasks.router, prefix="/api/v1")
    app.include_router(escrow.router, prefix="/api/v1")
    app.include_router(evidence.router, prefix="/api/v1")
    app.include_router(reputation.router, prefix="/api/v1")
    app.include_router(web_ui.web_router)

    @app.get("/api/v1/health")
    def health():
        """Health check endpoint.

        Returns:
            A dict with ``status`` and ``version`` fields.
        """
        return {"status": "ok", "version": "0.1.0"}

    return app
