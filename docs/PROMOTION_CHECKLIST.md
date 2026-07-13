# contrib → core promotion checklist

> PROM16 P2 item 8 (cells D3·D4). ADR-0002 CUT five layer-2 ports into
> `apt_engine.contrib`; ADR-0004 later added `kg_manifest` as the sixth. The PROM16
> D4 audit re-tested all six against a "real consumer" gate and found **0/6
> promotable** — all remain import-safe and tested in their supported modes, but
> none has a real core consumer; `kg_manifest` and `resolver` also remain opt-in.
> This checklist makes that gate a standing rule so promotion never happens
> piecemeal (the D3 trap: each step looks harmless; the sum re-creates the
> 636-LOC/43%-dead T2 module this engine was extracted to escape).

A `contrib` module may move into the core **only when ALL of these hold**:

1. **Real consumer** — `cli.py` or `frontends/mcp_server.py` (or another core
   module) needs the import *in shipped code*, not in a test or a hypothetical.
   A prototype "would be nice behind a flag" is not a consumer.
2. **Stdlib-only** — the module (and everything it drags in) adds zero runtime
   dependencies. Optional-extra deps (`neo4j`, `jinja2`, `httpx`, `redis`)
   disqualify outright.
3. **Tested** — its tests already run green in the suite, and the promotion PR
   moves them alongside the code (no orphaned test paths).
4. **Boundary contracts intact** — after the move, `lint-imports` still passes
   both contracts: the deterministic core must not import `contrib`, and the
   parallel `detect` / `phase_map` / `legion` adapters remain independent. Any new
   core module must also be added to the forbidden contract's enumerated
   `source_modules`; `tests/test_contrib_boundary.py` pins that coverage.
5. **Not one of the permanent opt-ins** — `kg_manifest` and `resolver` are
   KG/Jinja-coupled and stay opt-in **even with a consumer**; they plug into the
   `ManifestSource` seam from outside (ADR-0004).
6. **Whole-feature move** — promote a working vertical (module + consumer wiring
   + tests + docs) in one change, never "just the enum/type first" (that is the
   piecemeal trap this list exists to block).

Positive control for the same criteria: `receipt.py` (2026-07-13) — it was created
directly as a wired stdlib feature, not promoted from `contrib`; it is
consumed by `cli.py --receipt-out` and the MCP `apt_gate_measured` response in
the same change, with dedicated tests and both import-linter contracts kept.

Worked example that FAILS it today: `gate_override` — stdlib-clean and tested
(closest of the six), but no call site anywhere in core; it stays in `contrib`
until a real consumer exists.

Relatedly, in the other direction: a gate **PASS is a necessary, not a
sufficient, condition** for the transition being *right* — see the README
one-liner and the TRUST BOUNDARY note in `precondition.py`.
