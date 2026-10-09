from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from events import Role
from platform_lib.auth import CurrentPrincipal, Principal, require_roles
from src.api.schemas import SetRolesRequest, UpdateMeRequest
from src.domain.profile import Profile
from src.services.users import UserService

router = APIRouter(prefix="/api/v1/users", tags=["users"])


def get_user_service(request: Request) -> UserService:
    service: UserService = request.app.state.user_service
    return service


Users = Annotated[UserService, Depends(get_user_service)]
Staff = Annotated[Principal, Depends(require_roles(Role.MANAGER, Role.ADMIN))]
Admin = Annotated[Principal, Depends(require_roles(Role.ADMIN))]


@router.get("/me", response_model=Profile)
async def get_me(principal: CurrentPrincipal, users: Users) -> Profile:
    return await users.get_me(principal)


@router.patch("/me", response_model=Profile)
async def update_me(body: UpdateMeRequest, principal: CurrentPrincipal, users: Users) -> Profile:
    return await users.update_me(principal, body.model_dump(exclude_unset=True))


@router.get("", response_model=list[Profile])
async def list_users(
    _staff: Staff,
    users: Users,
    email: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Profile]:
    return await users.list_users(email_contains=email, limit=limit, offset=offset)


@router.get("/{user_id}", response_model=Profile)
async def get_user(user_id: UUID, principal: CurrentPrincipal, users: Users) -> Profile:
    return await users.get(principal, user_id)


@router.put("/{user_id}/roles", response_model=Profile)
async def set_roles(user_id: UUID, body: SetRolesRequest, admin: Admin, users: Users) -> Profile:
    return await users.set_roles(admin, user_id, body.roles)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: UUID, admin: Admin, users: Users) -> Response:
    await users.delete(admin, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
