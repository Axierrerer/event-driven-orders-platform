from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from src.domain.errors import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidTokenError,
    TooManyAttemptsError,
    WeakPasswordError,
)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(EmailAlreadyRegisteredError)
    async def email_taken(_request: Request, _exc: EmailAlreadyRegisteredError) -> JSONResponse:
        return JSONResponse({"detail": "email already registered"}, status.HTTP_409_CONFLICT)

    @app.exception_handler(WeakPasswordError)
    async def weak_password(_request: Request, exc: WeakPasswordError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status.HTTP_422_UNPROCESSABLE_CONTENT)

    @app.exception_handler(InvalidCredentialsError)
    async def bad_credentials(_request: Request, _exc: InvalidCredentialsError) -> JSONResponse:
        return JSONResponse(
            {"detail": "invalid email or password"},
            status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(InvalidTokenError)
    async def bad_token(request: Request, _exc: InvalidTokenError) -> JSONResponse:
        # Токен подтверждения email — 400, refresh-токен — 401
        code = (
            status.HTTP_400_BAD_REQUEST
            if request.url.path.endswith("/verify-email")
            else status.HTTP_401_UNAUTHORIZED
        )
        return JSONResponse({"detail": "invalid or expired token"}, code)

    @app.exception_handler(TooManyAttemptsError)
    async def too_many(_request: Request, exc: TooManyAttemptsError) -> JSONResponse:
        return JSONResponse(
            {"detail": "too many failed login attempts"},
            status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )
