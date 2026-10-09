from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from src.domain.errors import (
    AccessDeniedError,
    LastAdminError,
    SelfModificationError,
    UserNotFoundError,
)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(UserNotFoundError)
    async def not_found(_request: Request, _exc: UserNotFoundError) -> JSONResponse:
        return JSONResponse({"detail": "user not found"}, status.HTTP_404_NOT_FOUND)

    @app.exception_handler(AccessDeniedError)
    async def denied(_request: Request, _exc: AccessDeniedError) -> JSONResponse:
        return JSONResponse({"detail": "access denied"}, status.HTTP_403_FORBIDDEN)

    @app.exception_handler(LastAdminError)
    async def last_admin(_request: Request, _exc: LastAdminError) -> JSONResponse:
        return JSONResponse(
            {"detail": "operation would leave the system without administrators"},
            status.HTTP_409_CONFLICT,
        )

    @app.exception_handler(SelfModificationError)
    async def self_change(_request: Request, _exc: SelfModificationError) -> JSONResponse:
        return JSONResponse(
            {"detail": "administrators cannot remove their own admin role or account"},
            status.HTTP_409_CONFLICT,
        )
