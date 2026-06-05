from fastapi import FastAPI
from .routers import identity, tasks, escrow, evidence, reputation
from .middleware.auth import AuthMiddleware


def create_app() -> FastAPI:
    app = FastAPI(title="AgentMesh API Gateway", version="0.1.0")
    app.add_middleware(AuthMiddleware)
    app.include_router(identity.router, prefix="/api/v1")
    app.include_router(tasks.router, prefix="/api/v1")
    app.include_router(escrow.router, prefix="/api/v1")
    app.include_router(evidence.router, prefix="/api/v1")
    app.include_router(reputation.router, prefix="/api/v1")

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    return app
