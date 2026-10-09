from pydantic import BaseModel, ConfigDict, Field

from events import Role
from src.domain.profile import Address, Phone


class UpdateMeRequest(BaseModel):
    """Изменяемые пользователем поля. email и роли здесь менять нельзя (extra=forbid → 422)."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: Phone | None = None
    address: Address | None = None


class SetRolesRequest(BaseModel):
    roles: list[Role] = Field(min_length=1)
