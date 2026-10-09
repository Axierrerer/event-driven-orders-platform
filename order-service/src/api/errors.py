from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from src.domain.errors import (
    DependencyUnavailableError,
    EmailNotVerifiedError,
    ForbiddenActionError,
    IdempotencyConflictError,
    InvalidOrderError,
    OrderNotFoundError,
    OutOfStockError,
    PaymentDeclinedError,
)
from src.domain.status import InvalidTransitionError


def install_error_handlers(app: FastAPI) -> None:
    def respond(code: int, detail: object) -> JSONResponse:
        return JSONResponse({"detail": detail}, code)

    @app.exception_handler(OrderNotFoundError)
    async def not_found(_r: Request, _e: OrderNotFoundError) -> JSONResponse:
        return respond(status.HTTP_404_NOT_FOUND, "order not found")

    @app.exception_handler(EmailNotVerifiedError)
    async def unverified(_r: Request, _e: EmailNotVerifiedError) -> JSONResponse:
        return respond(status.HTTP_403_FORBIDDEN, "confirm your email before placing orders")

    @app.exception_handler(ForbiddenActionError)
    async def forbidden(_r: Request, _e: ForbiddenActionError) -> JSONResponse:
        return respond(status.HTTP_403_FORBIDDEN, "action not allowed for your role")

    @app.exception_handler(InvalidOrderError)
    async def invalid(_r: Request, exc: InvalidOrderError) -> JSONResponse:
        detail = {"message": str(exc), "product_ids": [str(p) for p in exc.product_ids]}
        return respond(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)

    @app.exception_handler(OutOfStockError)
    async def out_of_stock(_r: Request, exc: OutOfStockError) -> JSONResponse:
        detail = {
            "message": "not enough stock",
            "items": [
                {"product_id": str(p), "requested": req, "available": avail}
                for p, req, avail in exc.details
            ],
        }
        return respond(status.HTTP_409_CONFLICT, detail)

    @app.exception_handler(InvalidTransitionError)
    async def transition(_r: Request, exc: InvalidTransitionError) -> JSONResponse:
        return respond(status.HTTP_409_CONFLICT, str(exc))

    @app.exception_handler(IdempotencyConflictError)
    async def idempotency(_r: Request, _e: IdempotencyConflictError) -> JSONResponse:
        return respond(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Idempotency-Key was already used with a different request body",
        )

    @app.exception_handler(PaymentDeclinedError)
    async def declined(_r: Request, _e: PaymentDeclinedError) -> JSONResponse:
        return respond(status.HTTP_402_PAYMENT_REQUIRED, "payment declined")

    @app.exception_handler(DependencyUnavailableError)
    async def unavailable(_r: Request, _e: DependencyUnavailableError) -> JSONResponse:
        return respond(status.HTTP_503_SERVICE_UNAVAILABLE, "catalog is unavailable, retry later")
