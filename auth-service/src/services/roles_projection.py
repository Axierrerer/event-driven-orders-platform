from sqlalchemy.ext.asyncio import AsyncSession

from events import UserRolesChanged
from platform_lib.logging import get_logger
from src.repositories.users import UserRepository

log = get_logger(__name__)


async def apply_roles_changed(event: UserRolesChanged, session: AsyncSession) -> None:
    """Проекция ролей из user-service: следующий выданный access-токен содержит новые роли."""
    users = UserRepository(session)
    user_id = event.payload.user_id
    if await users.get_by_id(user_id) is None:
        log.warning("roles_changed_for_unknown_user", user_id=str(user_id))
        return
    await users.replace_roles(user_id, event.payload.roles)
    log.info("roles_projection_updated", user_id=str(user_id), roles=sorted(event.payload.roles))
