from fastapi import Request
from fastapi.responses import JSONResponse

from exception.exceptions import AppError
from logger.logger import get_logger

logger = get_logger(__name__)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger.warning(f"{request.method} {request.url.path} -> {exc.status_code} {exc.message}")
    return JSONResponse(status_code=exc.status_code, content={"error": exc.message})


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(f"Unhandled error on {request.method} {request.url.path}")
    return JSONResponse(status_code=500, content={"error": "Internal server error"})
