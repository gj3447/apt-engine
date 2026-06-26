# ADR-0001: apt-engine extracted to a standalone repo (reopens bhgman_tool scope decision)

- **Status**: ACCEPTED
- **Date**: 2026-06-26
- **Supersedes (partial)**: `bhgman_tool/ADRs/apt-engine-scope-decision-2026-05-25.md`
- **Sibling pattern**: `PROJECT/PI/tpa-engine` (independent `X-engine` repo)

---

## Context

The 2026-05-25 ADR `apt-engine-scope-decision` ruled the **APT execution engine
OUT-OF-SCOPE for `bhgman_tool`**: skills stay as thin markdown, and the
phase-gate *runtime* (resolver + gate_endpoint + OPA) lives in
`SYMPOSIUM/THEORY/APT/*_prototype/` and runs on dgx. Its final clause:

> "does not preclude bhgman_tool importing the prototype as a library later if a
> tool-layer consumer emerges. **Reopen via new ADR if that happens.**"

This is that ADR. A tool-layer consumer has emerged: we want a standalone,
dependency-light APT phase-contract engine that sits beside `tpa-engine` and can
be imported, CLI-invoked, or wrapped as an MCP tool — without a dgx round-trip
and without coupling to the `bhgman_tool` MCP package.

The dgx resolver/gate prototype is **not reachable** from the dev box (no Neo4j
bolt route; SYMPOSIUM is not mirrored locally). So `apt-engine` does **not** copy
that runtime. It instead provides the *deterministic, KG-free* layer the
prototype assumes: the canonical phase chain, the gate verdict algebra, and
on-disk phase detection.

## Decision

Create `PROJECT/PI/apt-engine` as an independent git repo (mirroring the
`tpa-engine` layout: `src/apt_engine/`, `tests/`, `docs/`, stdlib-only core).

Scope of the engine (v0.1):

1. **`phases.py`** — the canonical SA → SP → ST → SCW → MetaReview → Cleanup
   chain, transcribed from `adr-apt-phase-contract-2026-05-25`: per-phase
   precondition, postcondition, canonical `APT_GATE_VERSION` failure string,
   optional flag, and the MetaReview `self_application_forbidden` rule.
2. **`gate.py`** — the verdict algebra from `adr-apt-gate-semantics-2026-05-25`:
   `PASS | FAIL | SKIP | CONDITIONAL`, with the load-bearing rule that **SKIP is
   never counted as PASS** and CONDITIONAL requires a follow-up VR.
3. **`detect.py`** — on-disk phase detection, extracted from
   `bhgman_tool/engine/mcp_server/tools/apt.py` but importing the canonical
   `CHAIN` so detector and contract can never drift.

OUT of scope for v0.1 (kept on dgx, may arrive later via new ADR):
KG-backed precondition resolution, OPA policy evaluation, GateOverride node
lifecycle, and the Claude Code hook layer.

### Drift correction (load-bearing)

The `bhgman_tool` skeleton declared its phase tuple as
`(SA, SP, ST, SCW, "Cleanup", "MetaReview")` — Cleanup (Phase 6) *before*
MetaReview (Phase 5). The phase-contract ADR is explicit: "optional Phase 5
MetaReview + Phase 6 Cleanup." apt-engine uses the **ADR order**
`(SA, SP, ST, SCW, MetaReview, Cleanup)`. Because "current phase = latest phase
with evidence" depends on order, the skeleton would mis-rank a repo that had both
markers. `tests/test_phases.py::test_canonical_order_matches_adr_not_skeleton`
pins the correction and is revert-proof (mutation-tested 2026-06-26).

## Consequences

- **Positive**: a standalone, zero-dependency engine importable by any
  tool-layer consumer; one source of truth for phase order and gate semantics;
  the skeleton's phase-order drift is fixed and locked by test.
- **Positive**: the `bhgman_tool` scope ADR stays honest — the runtime is still
  not *in* bhgman_tool; it is now in its own sibling repo, exactly as the reopen
  clause anticipated.
- **Negative (acknowledged)**: two phase definitions now exist (this engine and
  the dgx prototype). They are aligned to the same v27 contract ADR; if v28
  revises preconditions, both must change in lockstep
  (cf. `feedback_canon_propagation_simultaneous.md`). A later ADR may make the
  dgx prototype import this package to eliminate the duplication.

## Rollback

Delete the `apt-engine` repo and revert to the 2026-05-25 status quo (engine
lives only on dgx; `bhgman_tool` ships skeleton detection via
`engine/mcp_server/tools/apt.py`).

# KG: adr-apt-phase-contract-2026-05-25, adr-apt-gate-semantics-2026-05-25, apt-engine-scope-decision-2026-05-25, APT_methodology_v27
