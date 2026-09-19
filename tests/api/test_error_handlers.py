from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from latest_ai_development.api.error_handlers import register_error_handlers


def test_http_exception_uses_structured_error_response() -> None:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/custom-error")
    def custom_error() -> None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "custom_error",
                "message": "Custom error happened",
                "details": {"field": "name"},
            },
        )

    response = TestClient(app).get("/custom-error")

    assert response.status_code == 400
    assert response.json() == {
        "error": "custom_error",
        "message": "Custom error happened",
        "details": {"field": "name"},
    }


def test_validation_error_uses_structured_error_response() -> None:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/items/{item_id}")
    def get_item(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    response = TestClient(app).get("/items/not-an-int")

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "request_validation_failed"
    assert body["message"] == "Request validation failed"
    assert body["details"]


def test_unhandled_exception_uses_structured_error_response() -> None:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("boom")

    response = TestClient(app, raise_server_exceptions=False).get("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "error": "internal_server_error",
        "message": "Unexpected server error",
    }
