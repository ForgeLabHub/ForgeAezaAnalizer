import time
from collections.abc import Callable
from threading import RLock
from typing import Generic, TypeVar


T = TypeVar("T")


class CacheFull(Exception):
    pass


class TTLCache(Generic[T]):
    def __init__(self, capacity: int, clock: Callable[[], float] = time.monotonic):
        self.capacity = capacity
        self.clock = clock
        self._entries: dict[str, tuple[float, T]] = {}
        self._lock = RLock()

    def put(self, key: str, value: T, ttl: float) -> None:
        with self._lock:
            now = self.clock()
            if len(self._entries) >= self.capacity:
                self._entries = {
                    key: entry for key, entry in self._entries.items() if entry[0] > now
                }
            if key not in self._entries and len(self._entries) >= self.capacity:
                raise CacheFull
            self._entries[key] = (now + ttl, value)

    def get(self, key: str) -> T | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry[0] <= self.clock():
                self._entries.pop(key, None)
                return None
            return entry[1]

    def pop(self, key: str) -> T | None:
        with self._lock:
            value = self.get(key)
            self._entries.pop(key, None)
            return value


class LoginLimiter:
    def __init__(self, capacity: int, attempts: int = 10, window: int = 60):
        self.cache: TTLCache[int] = TTLCache(capacity)
        self.attempts = attempts
        self.window = window
        self._lock = RLock()

    def check(self, address: str) -> bool:
        with self._lock:
            count = self.cache.get(address) or 0
            if count >= self.attempts:
                return False
            try:
                self.cache.put(address, count + 1, self.window)
            except CacheFull:
                return False
            return True
