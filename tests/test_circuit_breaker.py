"""Circuit breaker FSM — redis-free InMemoryStore + injected clock (deterministic)."""

from apt_engine.circuit_breaker import (
    CircuitBreaker,
    InMemoryStore,
    State,
)


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _cb(clock):
    return CircuitBreaker(InMemoryStore(), "G3.5", clock=clock, open_duration_s=30.0,
                          fail_threshold=3)


def test_fresh_circuit_is_closed_and_allows():
    d = _cb(FakeClock()).check()
    assert d.state is State.CLOSED and d.allow_request


def test_three_fails_open_the_circuit():
    cb = _cb(FakeClock())
    assert cb.record_failure() is State.CLOSED  # 1
    assert cb.record_failure() is State.CLOSED  # 2
    assert cb.record_failure() is State.OPEN     # 3 -> OPEN
    d = cb.check()
    assert d.state is State.OPEN and d.allow_request is False


def test_open_blocks_until_duration_then_half_opens():
    clk = FakeClock()
    cb = _cb(clk)
    for _ in range(3):
        cb.record_failure()
    assert cb.check().allow_request is False           # still OPEN
    clk.t += 29.9
    assert cb.check().allow_request is False           # not yet
    clk.t += 0.2                                        # 30.1s elapsed
    d = cb.check()
    assert d.state is State.HALF_OPEN and d.allow_request is True


def test_success_closes_and_resets():
    clk = FakeClock()
    cb = _cb(clk)
    for _ in range(3):
        cb.record_failure()
    clk.t += 31
    cb.check()                 # -> HALF_OPEN
    cb.record_success()        # trial passes -> CLOSED + counters cleared
    d = cb.check()
    assert d.state is State.CLOSED and d.allow_request
    # fail count was reset: it takes a fresh 3 fails to open again
    assert cb.record_failure() is State.CLOSED


def test_redislike_protocol_satisfied_by_inmemory():
    store = InMemoryStore()
    store.set("k", "CLOSED")
    assert store.get("k") == "CLOSED"
    assert store.incr("c") == 1 and store.incr("c") == 2
    store.delete("c")
    assert store.get("c") is None
