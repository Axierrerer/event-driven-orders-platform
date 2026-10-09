import asyncio
import os
import time
from pathlib import Path

import pytest

from platform_lib.heartbeat import heartbeat, is_fresh, main

pytestmark = pytest.mark.unit


async def test_heartbeat_touches_file_until_stopped(tmp_path: Path) -> None:
    path = tmp_path / "alive"
    stop = asyncio.Event()
    task = asyncio.create_task(heartbeat(stop, path, interval=0.01))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=1)
    assert is_fresh(path, 5)


def test_stale_or_missing_file_is_unhealthy(tmp_path: Path) -> None:
    path = tmp_path / "alive"
    assert main([str(path), "60"]) == 1
    path.touch()
    assert main([str(path), "60"]) == 0
    old = time.time() - 120
    os.utime(path, (old, old))
    assert main([str(path), "60"]) == 1
