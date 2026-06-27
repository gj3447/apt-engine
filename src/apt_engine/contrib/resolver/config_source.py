"""ConfigSource — where the resolver reads MethodologyConfig magic numbers from.

A `Protocol` so the resolver is decoupled from the backend: tests/embedding use
`DictConfigSource` (stdlib); production uses `CypherConfigSource` (neo4j, lazy
import). Composition-root validation (`verify_core_present`) refuses to proceed
when a core magic field is absent — the prototype's "partial render forbidden".
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .drift import CORE_MAGIC_FIELDS

__all__ = [
    "ConfigSource",
    "DictConfigSource",
    "CypherConfigSource",
    "MissingConfigError",
    "verify_core_present",
    "CONFIG_NODE_NAME",
]

CONFIG_NODE_NAME = "MethodologyConfig_default_v27"


class MissingConfigError(KeyError):
    """A required cfg field is absent — composition root must fail, not partial-render."""


@runtime_checkable
class ConfigSource(Protocol):
    def fetch(self) -> dict[str, Any]:
        """Return the resolved MethodologyConfig as a flat dict."""
        ...


class DictConfigSource:
    """In-memory ConfigSource — stdlib, for tests and embedded use."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self._cfg = dict(cfg)

    def fetch(self) -> dict[str, Any]:
        return dict(self._cfg)


def verify_core_present(
    cfg: dict[str, Any],
    core_fields: tuple[str, ...] = CORE_MAGIC_FIELDS,
) -> None:
    """Raise MissingConfigError if any core magic field is absent from cfg."""
    missing = [f for f in core_fields if f not in cfg]
    if missing:
        raise MissingConfigError(
            f"core magic fields missing in {CONFIG_NODE_NAME}: {missing}"
        )


class CypherConfigSource:
    """neo4j-backed ConfigSource with a 60s TTL cache (lazy `neo4j` import).

    Needs the `resolver` extra: pip install -e '.[resolver]'.
    """

    _CACHE_TTL = 60.0

    def __init__(self, uri: str, user: str, password: str,
                 node_name: str = CONFIG_NODE_NAME) -> None:
        from neo4j import GraphDatabase  # lazy: optional dep

        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._node = node_name
        self._cache: tuple[float, dict[str, Any]] | None = None

    def health_check(self) -> bool:
        with self._driver.session() as s:
            r = s.run("RETURN 1 AS ok").single()
            return bool(r and r["ok"] == 1)

    def fetch(self) -> dict[str, Any]:
        import time

        now = time.monotonic()
        if self._cache and (now - self._cache[0]) < self._CACHE_TTL:
            return dict(self._cache[1])
        q = "MATCH (cfg:MethodologyConfig {name: $name}) RETURN properties(cfg) AS props"
        with self._driver.session() as s:
            r = s.run(q, name=self._node).single()
        if not r:
            raise MissingConfigError(f"KG node not found: {self._node}")
        props = dict(r["props"])
        self._cache = (now, props)
        return dict(props)

    def close(self) -> None:
        self._driver.close()
