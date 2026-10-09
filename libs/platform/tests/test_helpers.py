from uuid import UUID

import pytest

from events import Role
from platform_lib.db import make_engine, make_session_factory
from platform_lib.testing import TokenFactory

pytestmark = pytest.mark.unit


async def test_token_factory_tokens_pass_its_verifier() -> None:
    factory = TokenFactory()
    user_id = UUID("0192f0a0-0000-7000-8000-000000000001")

    principal = await factory.verifier.verify(
        factory.token(user_id, [Role.ADMIN], email_verified=False)
    )

    assert principal.user_id == user_id
    assert principal.roles == {Role.ADMIN}
    assert principal.email_verified is False
    assert factory.headers(user_id)["Authorization"].startswith("Bearer ")


async def test_engine_and_session_factory_are_lazy() -> None:
    engine = make_engine("postgresql+asyncpg://u:p@127.0.0.1:1/db", pool_size=2)
    session_factory = make_session_factory(engine)
    assert engine.pool.size() == 2  # type: ignore[attr-defined]
    async with session_factory() as session:
        assert session.bind is engine
    await engine.dispose()
