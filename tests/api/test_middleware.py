import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from latest_ai_development.api.middleware import RequestLoggingMiddleware


def test_request_logging_middleware_logs_completed_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {"status": "ok"}

    with caplog.at_level(logging.INFO):
        response = TestClient(app).get("/ping")

    assert response.status_code == 200
    assert "API request started | method=GET | path=/ping" in caplog.text
    assert "API request completed | method=GET | path=/ping | status_code=200" in caplog.text
