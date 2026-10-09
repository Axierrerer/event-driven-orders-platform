from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from src.domain.errors import InvalidAdjustmentError, StockNotFoundError


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StockNotFoundError)
    async def not_found(_request: Request, _exc: StockNotFoundError) -> JSONResponse:
        return JSONResponse({"detail": "product is not tracked"}, status.HTTP_404_NOT_FOUND)

    @app.exception_handler(InvalidAdjustmentError)
    async def invalid(_request: Request, _exc: InvalidAdjustmentError) -> JSONResponse:
        return JSONResponse(
            {"detail": "on hand quantity cannot drop below reserved quantity"},
            status.HTTP_409_CONFLICT,
        )
