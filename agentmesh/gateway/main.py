"""Gateway entry point — creates the FastAPI app and starts the server."""

import uvicorn
from .app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run("gateway.main:app", host="0.0.0.0", port=8000, reload=True)
