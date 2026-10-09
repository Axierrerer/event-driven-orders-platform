from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status

from platform_lib.auth import CurrentPrincipal
from src.api.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    TokenResponse,
    VerifyEmailRequest,
)
from src.services.auth import AuthService, TokenPair
from src.services.jwt_issuer import JwtIssuer

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def get_auth_service(request: Request) -> AuthService:
    service: AuthService = request.app.state.auth_service
    return service


def get_issuer(request: Request) -> JwtIssuer:
    issuer: JwtIssuer = request.app.state.jwt_issuer
    return issuer


Auth = Annotated[AuthService, Depends(get_auth_service)]


def _tokens(pair: TokenPair) -> TokenResponse:
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        token_type=pair.token_type,
        expires_in=pair.expires_in,
    )


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=RegisterResponse)
async def register(body: RegisterRequest, auth: Auth) -> RegisterResponse:
    user_id = await auth.register(body.email, body.password)
    return RegisterResponse(user_id=user_id)


@router.post("/verify-email", status_code=status.HTTP_204_NO_CONTENT)
async def verify_email(body: VerifyEmailRequest, auth: Auth) -> Response:
    await auth.verify_email(body.token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/resend-verification", status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(body: ResendVerificationRequest, auth: Auth) -> dict[str, str]:
    await auth.resend_verification(body.email)
    return {"status": "accepted"}


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, auth: Auth) -> TokenResponse:
    return _tokens(await auth.login(body.email, body.password))


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, auth: Auth) -> TokenResponse:
    return _tokens(await auth.refresh(body.refresh_token))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest, auth: Auth) -> Response:
    await auth.logout(body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest, principal: CurrentPrincipal, auth: Auth
) -> Response:
    await auth.change_password(principal.user_id, body.old_password, body.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/.well-known/jwks.json")
async def jwks(issuer: Annotated[JwtIssuer, Depends(get_issuer)]) -> dict[str, Any]:
    return issuer.jwks()
