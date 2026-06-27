# apt-engine

Deterministic **APT** (SemanticAnchor → SemanticPyramid → SemanticTwin →
SourceCodeWorld → MetaReview → Cleanup) phase-contract engine.

Sibling to `tpa-engine` in `PROJECT/PI`. Stdlib-only core — zero runtime deps.

APT here is the methodology sense (the tech-stack 사도 / v27 phase cycle), not
the Debian package manager.

## Methodology: the phase chain drives the 7 legion commanders

APT is a development methodology that runs the **7 legion commanders** (비행기맨 #4
legion) through its phase chain. The commanders are the *executors*; the phases
are *when* and *under what gate* they run. Canonical commander order (from
`bhgman_tool` `legion_roster`):

| # | commander | verb | requires → provides |
|---|---|---|---|
| 1 | prometheus | 획득 (acquire) | run_cypher → acquired |
| 2 | longinus   | 연결 (bind)    | run_cypher → bindings |
| 3 | eureka     | 창조 (create)  | run_cypher → abstractions |
| 4 | occam      | 정리 (hygiene) | run_cypher → hygiene |
| 5 | naesengmoon| 검증 (verify)  | acquired+bindings+abstractions+hygiene → **verdict** |
| 6 | hades      | 실현 (realize) | verdict → realized |
| – | jaebaeman  | 출격 (dispatch)| the `Legion.run` dispatch loop itself (not a stage) |

The verdict naesengmoon emits is exactly the gate verdict this engine models in
`gate.py` (`PASS / FAIL / SKIP / CONDITIONAL`), and hades only realizes after a
PASS — mirroring `can_advance`. So **`apt_engine` is the deterministic
phase-and-gate substrate**; the legion runtime (commander dispatch, LLM agents)
layers on top and is out of scope for this stdlib core (see ADR-0001).

## What it is

| module | role |
|---|---|
| `apt_engine.phases` | canonical SA→SP→ST→SCW→MetaReview→Cleanup chain + per-phase precondition/postcondition + canonical `APT_GATE_VERSION` strings. Single source of truth. |
| `apt_engine.gate`   | gate verdict algebra: `PASS / FAIL / SKIP / CONDITIONAL`. **SKIP is never PASS.** Self-application (MetaReview→MetaReview) is forbidden. |
| `apt_engine.detect` | on-disk phase detection from `apt-progress.md` / `feature-spans.json`. Returns `unknown` rather than fabricating a phase. |
| `apt_engine.phase_map` | (a) v9 ↔ v27 phase-taxonomy reconciliation (KG's older 6-phase set ↔ the v27 chain). |
| `apt_engine.legion` | (b) the 7 legion commanders + KG canonical node map; naesengmoon emits the gate verdict, hades realizes iff PASS. |
| `apt_engine.precondition` | measured precondition — establishes truth from a real pytest exit code (`evaluate_measured_default`, mandated `evaluate_measured_mandated_default`), never a caller bool. |
| `apt_engine.frontends.mcp_server` | MCP frontend (`pip install -e '.[mcp]'`): `apt_chain / apt_detect / apt_gate / apt_gate_measured / apt_reconcile / apt_legion`. |

### `apt_engine.contrib` — layer-2 ports (NOT the core)

`gate_policy`, `circuit_breaker`, `opa`, `gate_override`, and `resolver` are
ported from the dgx-only SYMPOSIUM prototypes (`gj3447/symposium`
`THEORY/APT/{resolver,gate_endpoint}_prototype`). They are **not wired** into
`evaluate_transition` and are **not** part of the core public surface — import
them from `apt_engine.contrib`. The gate-server / OPA / config-resolver runtime is
the dgx/SYMPOSIUM layer's job (`adr-apt-dgx-runtime-delegation-2026-05-25`); the
scope-fork decision (CUT, not WIRE) is recorded in
[`docs/ADR-0002-scope-fork-cut-belt.md`](docs/ADR-0002-scope-fork-cut-belt.md).

Both `phases` and `gate` are transcribed from the canonical contract ADRs:
- `bhgman_tool/ADRs/apt-phase-contract-2026-05-25.md`
- `bhgman_tool/ADRs/apt-gate-semantics-2026-05-25.md`

The scope/extraction decision is recorded in
[`docs/ADR-0001-apt-engine-standalone-extraction.md`](docs/ADR-0001-apt-engine-standalone-extraction.md),
which reopens the 2026-05-25 `bhgman_tool` "engine out-of-scope" ADR exactly as
that ADR's reopen clause anticipated.

### What this engine is NOT (yet)

The **runtime** for KG-backed precondition resolution, the OPA policy service, the
GateOverride lifecycle, and the Claude Code hook layer stay on dgx
(`SYMPOSIUM/THEORY/APT/*_prototype/`). `apt_engine.contrib` holds only the inert,
stdlib-testable *ports* of those (decision logic, FSMs), not the running service —
so there is no contradiction with the contrib table above. This engine is the
deterministic, KG-free layer those assume.

## Install

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'        # core is dep-free; dev adds pytest + ruff
```

No-install dev loop also works: `PYTHONPATH=src python3 -m pytest -q`.

## CLI

```bash
apt-engine chain                       # print the canonical phase chain + contracts
apt-engine detect /path/to/repo        # detect current APT phase from on-disk artifacts
apt-engine gate SA SP --precondition-met   # -> PASS (exit 0)
apt-engine gate SA SP                      # -> FAIL, exit 1 (fail-closed: precondition unstated)
apt-engine gate SP ST --skip               # -> SKIP (never PASS), exit 1
apt-engine gate SCW MetaReview --measure tests/impact --impact-manifest apt-impact.json
                                           #   gate on a REAL pytest run of the MANDATED tests
                                           #   (manifest + tests are project-provided; a missing
                                           #    manifest fails closed — it does not crash)
apt-engine gate MetaReview MetaReview      # -> FAIL (self_application_forbidden), exit 1
```

## Measured gate & the trusted runner (CI)

The measured `SCW→MetaReview` gate runs the transition's **mandated impact tests**
(declared as exact, optionally sha256-pinned node ids in a manifest) and passes only
if they actually run green. It shells out to pytest, so install the runtime dep:

```bash
pip install '.[gate]'   # the measured gate needs pytest at runtime
```

**Read before relying on it.** This gate is **config-isolated defence-in-depth + a
correctness aid, NOT a security boundary.** A party that controls the working tree
can still subvert it (a `conftest.py` hook can rewrite a test outcome; the manifest
is caller-supplied). The sound use is a **trusted runner (CI) against a committed,
review-gated manifest** — see [`docs/ADR-0003`](docs/ADR-0003-trusted-runner-and-manifest-trust-root.md).
This repo dogfoods exactly that: CI's `gate` job runs `apt-engine gate SCW MetaReview
--measure tests --impact-manifest apt-impact.json` (`.github/workflows/ci.yml`), and
`apt-impact.json` pins this repo's own mandated tests (`tests/impact/`).

## Library

```python
from apt_engine import detect_phase, evaluate_transition, Verdict, CHAIN

CHAIN  # ('SA', 'SP', 'ST', 'SCW', 'MetaReview', 'Cleanup')

r = evaluate_transition("SA", "SP", precondition_met=True)
assert r.verdict is Verdict.PASS

detect_phase("/path/to/repo")["current_phase"]   # 'SCW' | 'unknown' | ...
```

## Tests

```bash
PYTHONPATH=src python3 -m pytest -q     # all green (stdlib core + ports + ooptdd fix harness)
```

The canonical-order test is **revert-proof** (mutation-tested): reordering the
chain back to the bhgman_tool skeleton's `(…SCW, Cleanup, MetaReview)` fails the
suite. See ADR-0001 §"Drift correction".
