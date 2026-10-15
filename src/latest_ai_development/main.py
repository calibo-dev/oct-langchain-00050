"""Application entrypoint used by uvicorn and the local CLI command."""

from __future__ import annotations

from latest_ai_development.application import create_app

# Uvicorn imports this module-level variable when the server starts.
app = create_app()


def run() -> None:
    """Run the FastAPI app using settings loaded during startup."""
    import uvicorn

    settings = app.state.settings
    uvicorn.run(
        "latest_ai_development.main:app",
        host=settings.api_host,
        port=settings.port,
        reload=settings.debug,
        log_level=str(getattr(settings, "log_level", "INFO")).lower(),
    )


if __name__ == "__main__":
    run()
