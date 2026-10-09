import pytest

pytestmark = pytest.mark.unit


def test_package_imports() -> None:
    import events

    assert events.__doc__
