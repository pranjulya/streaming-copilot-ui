import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

PROBLEM_TYPE_BASE = "https://copilot.local/problems/"


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        title: str,
        headers: dict[str, str] | None = None,
        **extensions: object,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.title = title
        self.headers = headers or {}
        self.extensions = extensions


def problem_response(
    status_code: int,
    code: str,
    title: str,
    headers: dict[str, str] | None = None,
    **extensions: object,
) -> JSONResponse:
    content: dict[str, object] = {
        "type": f"{PROBLEM_TYPE_BASE}{code}",
        "title": title,
        "status": status_code,
        "code": code,
        "diagnostic_id": str(uuid.uuid4()),
    }
    content.update(extensions)
    return JSONResponse(
        status_code=status_code,
        media_type="application/problem+json",
        content=content,
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        response = problem_response(
            exc.status_code,
            exc.code,
            exc.title,
            headers=exc.headers,
            **exc.extensions,
        )
        response.headers["x-problem-code"] = exc.code
        return response

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return problem_response(400, "validation_failed", "Request validation failed")

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        return problem_response(503, "service_unavailable", "A required dependency is unavailable")

    @app.exception_handler(OSError)
    async def handle_connection_failure(request: Request, exc: OSError) -> JSONResponse:
        return problem_response(503, "service_unavailable", "A required dependency is unavailable")

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        return problem_response(500, "internal_error", "An unexpected error occurred")
