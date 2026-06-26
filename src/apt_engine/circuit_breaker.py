"""3-state circuit breaker (ported from gate_endpoint_prototype/circuit_breaker.py).

    CLOSED --(3 consecutive fails)--> OPEN
    OPEN   --(open_duration elapsed)--> HALF_OPEN
    HALF_OPEN --(success)--> CLOSED  /  (fail)--> OPEN

The prototype hard-bound this to redis; here the store is a `KVStore` Protocol so
the default `InMemoryStore` (stdlib) works for tests/embedding with no redis
(redis was a documented fragility). The clock is injectable for deterministic
OPEN->HALF_OPEN tests. A redis client satisfies `KVStore` as-is.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

__all__ = [
    "State",
    "CircuitDecision",
    "CircuitBreaker",
    "InMemoryStore",
    "KVStore",
    "OPEN_DURATION_S",
    "FAIL_THRESHOLD",
]

OPEN_DURATION_S = 30.0
FAIL_THRESHOLD = 3


class State(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass(frozen=True)
class CircuitDecision:
    state: State
    allow_request: bool
    reason: str


class KVStore(Protocol):
    def get(self, key: str): ...
    def set(self, key: str, value, ex: int | None = None): ...
    def incr(self, key: str): ...
    def delete(self, *keys: str): ...


class InMemoryStore:
    """Minimal stdlib KVStore — redis-free circuit breaker backing."""

    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    def get(self, key: str):
        return self._d.get(key)

    def set(self, key: str, value, ex: int | None = None):
        self._d[key] = str(value)

    def incr(self, key: str):
        n = int(self._d.get(key, "0")) + 1
        self._d[key] = str(n)
        return n

    def delete(self, *keys: str):
        for k in keys:
            self._d.pop(k, None)


def _decode(v) -> str:
    return v.decode() if isinstance(v, bytes) else str(v)


class CircuitBreaker:
    def __init__(
        self,
        store: KVStore,
        gate_name: str,
        *,
        clock: Callable[[], float] = time.monotonic,
        open_duration_s: float = OPEN_DURATION_S,
        fail_threshold: int = FAIL_THRESHOLD,
    ) -> None:
        self._s = store
        self._gate = gate_name
        self._clock = clock
        self._open_duration = open_duration_s
        self._threshold = fail_threshold

    def _key(self, suffix: str) -> str:
        return f"circuit:{self._gate}:{suffix}"

    def check(self) -> CircuitDecision:
        raw = self._s.get(self._key("state"))
        if raw is None:
            return CircuitDecision(State.CLOSED, True, "fresh circuit, allow")
        state = State(_decode(raw))

        if state is State.CLOSED:
            return CircuitDecision(State.CLOSED, True, "circuit closed")

        if state is State.OPEN:
            opened_raw = self._s.get(self._key("opened_at"))
            if opened_raw is None:
                self._reset()
                return CircuitDecision(State.CLOSED, True, "corrupt OPEN reset")
            elapsed = self._clock() - float(_decode(opened_raw))
            if elapsed >= self._open_duration:
                self._s.set(self._key("state"), State.HALF_OPEN.value)
                return CircuitDecision(State.HALF_OPEN, True, "OPEN elapsed, trial request")
            return CircuitDecision(State.OPEN, False, f"circuit OPEN ({elapsed:.1f}s ago)")

        return CircuitDecision(State.HALF_OPEN, True, "trial request in HALF_OPEN")

    def record_success(self) -> None:
        self._s.set(self._key("state"), State.CLOSED.value)
        self._s.delete(self._key("fail_count"), self._key("opened_at"))

    def record_failure(self) -> State:
        count = self._s.incr(self._key("fail_count"))
        if count >= self._threshold:
            self._s.set(self._key("state"), State.OPEN.value)
            self._s.set(self._key("opened_at"), str(self._clock()))
            return State.OPEN
        return State.CLOSED

    def _reset(self) -> None:
        self._s.delete(self._key("state"), self._key("fail_count"), self._key("opened_at"))
