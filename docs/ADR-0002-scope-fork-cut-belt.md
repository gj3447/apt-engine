# ADR-0002 — Scope fork: CUT the layer-2 ports out of the core

- **Status:** Accepted (2026-06-27)
- **Supersedes (partial):** the implicit in-scope status the ports acquired in
  commits `15747b4` (GateOverride, MCP frontend) and `3362b38` (resolver + OPA),
  which landed despite `ADR-0001` and `adr-apt-engine-scope-decision-2026-05-25`
  ruling KG-backed precondition resolution / OPA / GateOverride lifecycle
  out-of-scope.

## Context

The 2026-06-27 deep-think (finding **T2**) measured the engine: **~636 LOC** were
layer-2 ports — `gate_policy`, `circuit_breaker`, `opa`, `gate_override`, and
`resolver/` — with **no composition root**. (That `~636 LOC` is stable across the
PR stack; the *fraction* is not: 636/1474 = 43% at the original measurement
[`3362b38`], ≈ 33% of the 1919-LOC tree at cut time after the H-C work landed.)
`evaluate_transition`
imports only `phases.*`; the only callers of `enforce` / `override_allows` /
`CircuitBreaker` were their own unit tests; `opa` was not even re-exported. Yet
`apt_engine.__all__` advertised them, and the README listed the same names as both
in-repo modules and "stays on dgx" — a direct contradiction. T2's verdict: *inert
is the worst state; either WIRE or CUT.*

## Decision

**CUT.** Demote the five port modules to `apt_engine/contrib/` and remove them from
the core public surface (`apt_engine.__all__`). The code is kept (re-exported from
`apt_engine.contrib`), not deleted. The deterministic core now promises only what
it actually composes: `phases`, `gate`, `detect`, `precondition`, `phase_map`,
`legion`, and the MCP/CLI frontends.

## Alternatives considered

**WIRE** — add a composition root that chains
`verdict → passed → circuit_breaker → OPA → enforce` and authenticates
`authorized_by`, turning apt-engine into a runnable gate-endpoint. **Rejected:**

1. It contradicts the engine's stated identity — a *stdlib-only, deterministic,
   KG-free substrate* (README; `pyproject` core has zero deps). WIRE pulls
   httpx/redis/neo4j into a real runtime path.
2. The gate-server / OPA / config-resolver runtime is, by an existing ADR
   (`adr-apt-dgx-runtime-delegation-2026-05-25`), the **dgx/SYMPOSIUM** layer's
   responsibility, not this substrate's.
3. There is no current consumer of a wired gate-endpoint here; building one now is
   speculative scaffolding.

## Consequences

- The core surface is honest: it exports only wired capabilities (the ISP/cohesion
  violation T2 named is gone).
- The ports remain available for whoever builds the standalone gate-endpoint, via
  `from apt_engine.contrib import enforce, CircuitBreaker, GateOverride, …`.
- The suite is **not** halved — the ports keep their existing tests (now importing
  from `apt_engine.contrib.*`); CUT is about the public promise, not coverage.
- A boundary test (`tests/test_contrib_boundary.py`) pins that the belt stays out
  of `apt_engine.__all__` and importable only from `contrib`.

## Reversibility

Fully reversible: `git mv` the modules back and re-export them in a superseding
ADR — but only **together with** the composition root WIRE requires. Re-promote in
the core, not piecemeal, so the surface never again advertises what it cannot run.
