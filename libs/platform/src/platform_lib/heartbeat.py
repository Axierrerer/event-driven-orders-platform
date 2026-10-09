"""Heartbeat фоновых процессов (worker без HTTP).

Процесс периодически обновляет файл; healthcheck контейнера проверяет его свежесть:
    python -m platform_lib.heartbeat /tmp/worker.alive 60
Зависший event loop перестаёт обновлять файл — контейнер становится unhealthy.
"""

import asyncio
import sys
import time
from pathlib import Path

DEFAULT_PATH = Path("/tmp/worker.alive")  # noqa: S108 — файл внутри контейнера


async def heartbeat(stop: asyncio.Event, path: Path = DEFAULT_PATH, interval: float = 10) -> None:
    while not stop.is_set():
        await asyncio.to_thread(path.touch)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass


def is_fresh(path: Path, max_age_seconds: float) -> bool:
    try:
        return time.time() - path.stat().st_mtime <= max_age_seconds
    except FileNotFoundError:
        return False


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else DEFAULT_PATH
    max_age = float(argv[1]) if len(argv) > 1 else 60.0
    return 0 if is_fresh(path, max_age) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
