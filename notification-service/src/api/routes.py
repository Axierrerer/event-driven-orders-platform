from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from events import Role
from platform_lib.auth import Principal, require_roles
from src.domain.models import EmailTemplate, NotificationStatus
from src.domain.templates import TemplateRenderError
from src.services.admin import AdminService

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

Admin = Annotated[Principal, Depends(require_roles(Role.ADMIN))]


def get_admin(request: Request) -> AdminService:
    service: AdminService = request.app.state.admin
    return service


AdminOps = Annotated[AdminService, Depends(get_admin)]


class NotificationOut(BaseModel):
    id: str
    user_id: UUID
    email: str | None
    template: str
    status: NotificationStatus
    attempts: int
    next_attempt_at: datetime
    last_error: str | None
    sent_at: datetime | None
    created_at: datetime


class TemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=300)
    body_html: str = Field(min_length=1, max_length=50_000)
    body_text: str = Field(min_length=1, max_length=50_000)
    locale: str = Field(default="ru", pattern=r"^[a-z]{2}$")


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    _admin: Admin,
    admin: AdminOps,
    user_id: UUID | None = None,
    status_filter: Annotated[NotificationStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[NotificationOut]:
    found = await admin.list_notifications(
        user_id=user_id, status=status_filter, limit=limit, offset=offset
    )
    return [NotificationOut.model_validate(n.model_dump(exclude={"context"})) for n in found]


@router.get("/templates", response_model=list[str])
async def template_keys(_admin: Admin, admin: AdminOps) -> list[str]:
    return await admin.template_keys()


@router.get("/templates/{key}", response_model=EmailTemplate)
async def get_template(key: str, _admin: Admin, admin: AdminOps) -> EmailTemplate:
    template = await admin.get_template(key)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="template not found")
    return template


@router.put("/templates/{key}", response_model=EmailTemplate)
async def put_template(key: str, body: TemplateIn, _admin: Admin, admin: AdminOps) -> EmailTemplate:
    template = EmailTemplate(key=key, **body.model_dump())
    try:
        await admin.save_template(template)
    except TemplateRenderError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return template
