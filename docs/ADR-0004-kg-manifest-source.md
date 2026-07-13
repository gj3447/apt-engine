# ADR-0004 — KG manifest source + the ManifestSource seam

- **Status:** Accepted (2026-06-28)
- **Builds on:** ADR-0003 (trusted runner + manifest trust root).

## Context

ADR-0003 closed the *trusted-runner* half of H-C (CI runs the gate, config/env
isolated) and named a **KG-sourced manifest** as the non-caller trust root, to plug
in "at the existing `manifest_path` seam." The file manifest is only as trusted as
the caller's path; the non-caller trust root is the shared KG, where the mandated
tests can be authored by KG governance rather than the gated party's working tree.

## Decision

1. **Generalise the seam.** `apt_engine.precondition` adds a `ManifestSource`
   Protocol (`specs() -> dict[str, ImpactSpec]`) and `FileManifestSource` (the
   stdlib default, reads `--impact-manifest`). `evaluate_measured_mandated_from(
   …, source=…)` is the production entry; `evaluate_measured_mandated_default(
   manifest_path=…)` is now a thin wrapper over `FileManifestSource`. The core
   stays stdlib + KG-free.

2. **`KgManifestSource`** (`apt_engine.contrib.kg_manifest`, `pip install '.[kg]'`,
   lazy `neo4j`, injectable `KgClient`) resolves the mandated node ids + shas from
   the KG contract:
   `(:AptEngine {id})-[:MANDATES_IMPACT]->(:AptImpactTest {transition, node_id, sha256})`.
   It runs on any host that can reach a standard Neo4j endpoint for the governed
   graph. A backend failure raises `ValueError`, which the measured wrapper reports
   as fail-closed `ERROR` (could-not-evaluate), not an evaluated `FAIL`.

3. **The contract is registered in the shared airo KG.** Two `:AptImpactTest`
   nodes for `SCW→MetaReview`, sha-pinned to the committed `tests/impact/
   test_apt_contract.py`, linked from the `apt-engine` node. The
   `MANDATED_IMPACT_CYPHER` was verified against the live KG (it returns exactly
   those two node ids + shas), and the end-to-end path
   `KG rows → KgManifestSource → evaluate_measured_mandated_from → PASS` was
   exercised against real pytest.

## Consequences

- The manifest trust root is now **pluggable**: `FileManifestSource` (caller /
  CI-committed) or `KgManifestSource` (non-caller, governance-authored). A deployment
  can swap `KgManifestSource(neo4j_kg_client(uri, auth=…))` at the seam once it has a
  governed reachable endpoint — no engine change.
- The code capability for both H-C halves now exists. The stronger deployment claim
  applies only when a trusted runner can actually reach a governed, non-caller KG;
  this repository does not create that network route or governance policy.
- ADR-0002 is honored: the core does not import the KG layer (import-linter still
  passes); the neo4j dependency is optional and lazy.

## Honest residual

- KG **write access** is itself a trust question — who may create `:AptImpactTest`
  nodes is a KG-governance matter, not the engine's.
- The bolt connection / dgx deployment is environment config, not in this repo
  (this repo ships the source + the contract, unit-tested with a fake client).
- The execution-environment residual from ADR-0003 (a target `conftest.py` runs
  code) is unchanged — the full sandbox is future dgx work.

## Deployment topology (measured 2026-06-28)

Real-network mapping, so the deploy target is unambiguous:

- The apt-engine engineering graph — `AptEngine`, `AptPhaseV27`, and the
  `:AptImpactTest` contract — lives **only in the airo KG**, reached via the
  airo-neo4j **MCP HTTP gateway** (`<KG_HTTP_GATEWAY>`, ZeroTier). Its standard
  neo4j endpoints are **firewalled**: bolt `7687` is localhost-only on the KG host;
  HTTP `7474` is not exposed.
- `neo4j.metahumotonic.com` is a **separate** neo4j (the cosmology KG, 94k nodes,
  HTTP-443 reachable) — it has **zero** apt-engine nodes, so it is NOT a deploy
  target for this contract.
- The dgx nodes (`<DGX_NODES>`) are on **Tailscale** with **no route** to
  the KG's ZeroTier net — dgx **cannot reach the KG**. (SSH to dgx works, but the
  KG is on a different host/network.)

Consequence: this PR ships **`http_kg_client`** (stdlib `urllib`, Neo4j HTTP
transactional API) alongside `neo4j_kg_client`. The client protocol was
live-verified against the separate reachable metahumotonic Neo4j; that does **not**
make the airo transactional endpoint reachable. The real `:AptImpactTest` contract
was independently verified through the airo MCP gateway, and those returned rows
were exercised through `KgManifestSource → gate → PASS` with real pytest. The MCP
gateway is evidence/source access, not an endpoint consumed by `http_kg_client`.

The in-process client (`neo4j_kg_client` bolt or `http_kg_client`) reaches the
**airo** contract only from a host with a standard airo-KG endpoint — i.e. the KG
host `<KG_HOST>` itself, or wherever the airo KG exposes bolt/HTTP. That is an
infra/runbook step (open a route or run on the KG host), not an engine change.
