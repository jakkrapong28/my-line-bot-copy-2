"""Entrypoint — keeps the conventional ``main:app`` import path.

The application is implemented as a package under ``app/``. This module just
re-exports the ASGI app and provides a local ``python main.py`` runner.
"""

from app.main import app

__all__ = ["app"]

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, workers=1, log_level="info")
