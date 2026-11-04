"""프로세스별 최대 개수가 제한된 TTL 캐시. 실패 응답은 저장하지 않는다."""

from collections import OrderedDict
from collections.abc import Callable
from threading import RLock
from time import monotonic
from typing import TypeVar, cast

T = TypeVar("T")


class TTLCache:
    def __init__(self, ttl_seconds: float, max_entries: int = 128, timer: Callable[[], float] = monotonic):
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._timer = timer
        self._entries: OrderedDict[tuple, tuple[float, object]] = OrderedDict()
        self._lock = RLock()

    def get_or_load(self, key: tuple, load: Callable[[], T]) -> T:
        if self._ttl_seconds <= 0:
            return load()
        with self._lock:
            item = self._entries.get(key)
            if item is not None:
                expires_at, value = item
                if self._timer() < expires_at:
                    self._entries.move_to_end(key)
                    return cast(T, value)
                del self._entries[key]
        value = load()
        with self._lock:
            self._entries[key] = (self._timer() + self._ttl_seconds, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
        return value
