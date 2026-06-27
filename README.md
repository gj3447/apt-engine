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
| `apt_engine.gate_override` | audited escape hatch — no silent override; 24h TTL; permanent needs the literal phrase; only a FAIL is overridable. |
| `apt_engine.frontends.mcp_server` | MCP frontend (`pip install -e '.[mcp]'`): `apt_chain / apt_detect / apt_gate / apt_reconcile / apt_legion`. |
| `apt_engine.resolver` | config-resolver drift detection (stdlib core) + KG/jinja render (`.[resolver]`). Ported from SYMPOSIUM `resolver_prototype`. |
| `apt_engine.gate_policy` | enforcement mode mapping (INFORMATIONAL advisory / BLOCKER fail-closed → PASS/FAIL/WOULD_FAIL/OPEN_REFUSED). |
| `apt_engine.circuit_breaker` | 3-state breaker (CLOSED/OPEN/HALF_OPEN); redis-free `InMemoryStore` default, injectable clock. |
| `apt_engine.opa` | OPA Rego policy gate — `StaticOPAPolicy` (fail-closed, testable) + HTTP client (`.[opa]`). |

The resolver/gate-resilience modules are ported from the dgx-only SYMPOSIUM
prototypes (`gj3447/symposium` `THEORY/APT/{resolver,gate_endpoint}_prototype`),
re-layered so the deterministic cores (drift detection, breaker FSM, enforcement
mapping, policy decision) are stdlib + unit-testable, and the I/O (neo4j, jinja,
redis, OPA HTTP) is optional/pluggable.

Both `phases` and `gate` are transcribed from the canonical contract ADRs:
- `bhgman_tool/ADRs/apt-phase-contract-2026-05-25.md`
- `bhgman_tool/ADRs/apt-gate-semantics-2026-05-25.md`

The scope/extraction decision is recorded in
[`docs/ADR-0001-apt-engine-standalone-extraction.md`](docs/ADR-0001-apt-engine-standalone-extraction.md),
which reopens the 2026-05-25 `bhgman_tool` "engine out-of-scope" ADR exactly as
that ADR's reopen clause anticipated.

### What this engine is NOT (yet)

KG-backed precondition resolution, OPA policy, GateOverride lifecycle, and the
Claude Code hook layer stay on dgx (`SYMPOSIUM/THEORY/APT/*_prototype/`). This
engine is the deterministic, KG-free layer those assume.

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
apt-engine gate SA SP                  # evaluate a transition -> PASS
apt-engine gate SP ST --skip           # -> SKIP (never PASS)
apt-engine gate ST SCW --precondition-unmet   # -> FAIL + v27_phase_scw_dispatch_guard
apt-engine gate MetaReview MetaReview  # -> FAIL (self_application_forbidden)
```

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
