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

__all__ = ["KgClient", "KgManifestSource", "neo4j_kg_client", "MANDATED_IMPACT_CYPHER"]

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
    """Production `KgClient` over a real neo4j bolt connection (dgx). Lazy `neo4j`."""
    import neo4j  # lazy: only when actually connecting (the '.[kg]' extra)

    driver = neo4j.GraphDatabase.driver(uri, auth=auth)

    class _Neo4jClient:
        def run(self, query: str, params: dict) -> list[dict]:
            with driver.session(database=database) as session:
                return [dict(record) for record in session.run(query, **params)]

    return _Neo4jClient()
