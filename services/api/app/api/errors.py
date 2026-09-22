import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

PROBLEM_TYPE_BASE = "https://copilot.local/problems/"


class AppError(Exception):
    def __init__(self, status_code: int, code: str, title: str, **extensions: object) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.title = title
        self.extensions = extensions


def problem_response(status_code: int, code: str, title: str, **extensions: object) -> JSONResponse:
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
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return problem_response(exc.status_code, exc.code, exc.title, **exc.extensions)
