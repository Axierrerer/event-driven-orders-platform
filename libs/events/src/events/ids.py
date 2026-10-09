import os
import threading
import time
from uuid import UUID

_RAND_A_BITS = 12
_RAND_A_MAX = (1 << _RAND_A_BITS) - 1
_RAND_B_MASK = (1 << 62) - 1

_lock = threading.Lock()
_last_ms = 0
_counter = 0


def uuid7() -> UUID:
    """UUID версии 7 (RFC 9562): 48 бит времени в мс + 12-битный счётчик + случайные биты.

    В пределах процесса значения строго возрастают даже внутри одной миллисекунды
    (метод 1 из RFC 9562, раздел 6.2), поэтому подходят для сортировки по порядку создания.
    """
    global _last_ms, _counter
    with _lock:
        unix_ms = time.time_ns() // 1_000_000
        if unix_ms > _last_ms:
            _last_ms = unix_ms
            _counter = int.from_bytes(os.urandom(2), "big") & (_RAND_A_MAX >> 1)
        else:
            _counter += 1
            if _counter > _RAND_A_MAX:  # счётчик переполнился — занимаем следующую миллисекунду
                _last_ms += 1
                _counter = 0
        timestamp, counter = _last_ms, _counter

    value = (timestamp & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # версия
    value |= counter << 64
    value |= 0b10 << 62  # вариант RFC 9562
    value |= int.from_bytes(os.urandom(8), "big") & _RAND_B_MASK
    return UUID(int=value)
