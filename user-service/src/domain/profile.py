from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from events import Role

E164_PATTERN = r"^\+[1-9]\d{6,14}$"

Phone = Annotated[str, Field(pattern=E164_PATTERN, description="Телефон в формате E.164")]

STAFF_ROLES = frozenset({Role.MANAGER, Role.ADMIN})


class Address(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    street: str | None = Field(default=None, max_length=200)
    postal_code: str | None = Field(default=None, max_length=20)


class Profile(BaseModel):
    id: UUID
    email: str
    full_name: str | None
    phone: str | None
    address: Address | None
    roles: list[Role]
    created_at: datetime
    updated_at: datetime


def anonymized_email(user_id: UUID) -> str:
    """Адрес удалённого пользователя: персональные данные не хранятся."""
    return f"deleted+{user_id}@invalid"
