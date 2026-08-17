"""FastAPI app factory — static GUI + JSON API on a single port."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from hermes_panel import __version__
from hermes_panel.models import ApiResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


class NoCacheStatic(StaticFiles):
    """Buộc trình duyệt kiểm tra lại mỗi lần tải.

    Không có header này, sau khi nâng cấp panel người dùng vẫn chạy JS/CSS cũ
    trong cache cho tới khi tự bấm hard-reload.
    """

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app() -> FastAPI:
    app = FastAPI(title="Hermes LAN Panel", version=__version__, docs_url=None, redoc_url=None)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ApiResponse(ok=False, error=str(exc.detail)).model_dump(),
        )

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Lỗi không bắt được tại %s", request.url)
        return JSONResponse(
            status_code=500,
            content=ApiResponse(ok=False, error="Lỗi nội bộ của panel").model_dump(),
        )

    @app.get("/health", include_in_schema=False)
    async def health() -> dict:
        return {"ok": True, "version": __version__}

    from hermes_panel.routes import all_routers

    for router in all_routers:
        app.include_router(router)

    app.mount("/static", NoCacheStatic(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
