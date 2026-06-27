"""KG-backed `ManifestSource` — the NON-caller trust root for H-C (ADR-0003).

The file-based manifest is only as trusted as the caller's path. This source
resolves the mandated impact tests (node id + sha256) for a transition from the
shared KG instead: the contract lives as `(:AptEngine)-[:MANDATES_IMPACT]->
(:AptImpactTest)` nodes, authored by KG governance — not by the gated party's
working tree. Run on dgx where the bolt route to the KG exists.

Layer-2 / optional (`pip install '.[kg]'`): the neo4j driver is imported lazily,
only when actually connecting, so this module (and `KgManifestSource` with an
injected client) imports and unit-tests with zero runtime deps. It implements
`apt_engine.precondition.ManifestSource`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..precondition import ImpactReq, ImpactSpec

__all__ = [
    "KgClient",
    "KgManifestSource",
    "neo4j_kg_client",
    "http_kg_client",
    "MANDATED_IMPACT_CYPHER",
]

#: Resolve a transition's mandated impact tests from the KG contract.
MANDATED_IMPACT_CYPHER = (
    "MATCH (e:AptEngine {id: $engine})-[:MANDATES_IMPACT]->"
    "(t:AptImpactTest {transition: $transition}) "
    "RETURN t.node_id AS node_id, t.sha256 AS sha256"
)


class KgClient(Protocol):
    """Minimal read seam — `run(query, params) -> list of row dicts`."""

    def run(self, query: str, params: dict) -> list[dict]: ...


@dataclass(frozen=True)
class KgManifestSource:
    """A `ManifestSource` that resolves mandated tests from the KG (non-caller).

    `client` is injected (a `KgClient`); production passes `neo4j_kg_client(...)`,
    tests pass a fake. A backend failure raises `ValueError` so the gate fails
    closed (`evaluate_measured_mandated_from` catches it).
    """

    client: KgClient
    engine: str = "apt-engine"
    transitions: tuple[str, ...] = ("SCW->MetaReview",)

    def specs(self) -> dict[str, ImpactSpec]:
        out: dict[str, ImpactSpec] = {}
        for txn in self.transitions:
            try:
                rows = self.client.run(
                    MANDATED_IMPACT_CYPHER, {"engine": self.engine, "transition": txn}
                )
            except Exception as exc:  # noqa: BLE001 — translate to fail-closed signal
                raise ValueError(f"KG manifest source failed for {txn!r}: {exc}") from exc
            frm, _, to = txn.partition("->")
            reqs = tuple(
                ImpactReq(node_id=row["node_id"], sha256=row.get("sha256"))
                for row in rows
                if isinstance(row, dict) and row.get("node_id")
            )
            out[txn] = ImpactSpec(transition=(frm, to), required=reqs)
        return out


def neo4j_kg_client(uri: str, *, auth: tuple[str, str] | None = None, database: str = "neo4j") -> KgClient:
    """`KgClient` over a real neo4j BOLT connection (lazy `neo4j`, the '.[kg]' extra).

    Bolt is the production path where the KG host's 7687 is reachable. In some
    topologies bolt is firewalled (localhost-only / not routed) — use
    `http_kg_client` there.
    """
    import neo4j  # lazy: only when actually connecting (the '.[kg]' extra)

    driver = neo4j.GraphDatabase.driver(uri, auth=auth)

    class _Neo4jClient:
        def run(self, query: str, params: dict) -> list[dict]:
            with driver.session(database=database) as session:
                return [dict(record) for record in session.run(query, **params)]

    return _Neo4jClient()


def _parse_neo4j_http_rows(payload: dict) -> list[dict]:
    """Parse a neo4j HTTP transactional-API response into `[{col: value}, ...]`."""
    errors = payload.get("errors") or []
    if errors:
        raise ValueError(f"neo4j HTTP error: {errors}")
    results = payload.get("results") or []
    if not results:
        return []
    columns = results[0].get("columns", [])
    return [dict(zip(columns, datum["row"])) for datum in results[0].get("data", [])]


def http_kg_client(
    url: str, *, auth: tuple[str, str] | None = None, database: str = "neo4j", timeout: float = 15.0
) -> KgClient:
    """`KgClient` over the neo4j HTTP transactional API (stdlib `urllib`, no deps).

    `url` is the base (e.g. ``https://neo4j.example.com``); the endpoint used is
    ``{url}/db/{database}/tx/commit``. This is the reachable path in topologies
    where bolt (7687) is firewalled but the neo4j HTTP API (443/7474) is open
    (e.g. behind a reverse proxy). Read-only here — the gate never writes.
    """
    import base64
    import json as _json
    import urllib.request

    endpoint = f"{url.rstrip('/')}/db/{database}/tx/commit"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        # A real UA: some reverse proxies 403 the default "Python-urllib/*".
        "User-Agent": "apt-engine-kg/0.1",
    }
    if auth is not None:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"

    class _HttpClient:
        def run(self, query: str, params: dict) -> list[dict]:
            body = _json.dumps(
                {"statements": [{"statement": query, "parameters": params}]}
            ).encode()
            req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed scheme
                payload = _json.loads(resp.read())
            return _parse_neo4j_http_rows(payload)

    return _HttpClient()
