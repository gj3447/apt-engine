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
`gate.py` (`PASS / FAIL / SKIP / CONDITIONAL / ERROR`), and hades only realizes
after a PASS — mirroring `can_advance`. So **`apt_engine` is the deterministic
phase-and-gate substrate**; the legion runtime (commander dispatch, LLM agents)
layers on top and is out of scope for this stdlib core (see ADR-0001).

## What it is

| module | role |
|---|---|
| `apt_engine.phases` | canonical SA→SP→ST→SCW→MetaReview→Cleanup chain + per-phase precondition/postcondition + canonical `APT_GATE_VERSION` strings. Single source of truth. |
| `apt_engine.gate`   | gate verdict algebra: `PASS / FAIL / SKIP / CONDITIONAL / ERROR`. **SKIP is never PASS.** `ERROR` = could-not-evaluate (unreadable manifest / source outage), distinct from `FAIL` = evaluated-to-no; both fail-closed. Self-application (MetaReview→MetaReview) is forbidden. Passing both `--conditional` and `--skip` is a caller error (they are mutually exclusive). |
| `apt_engine.detect` | on-disk phase detection from `apt-progress.md` / `feature-spans.json`. Returns `unknown` rather than fabricating a phase. |
| `apt_engine.phase_map` | (a) v9 ↔ v27 phase-taxonomy reconciliation (KG's older 6-phase set ↔ the v27 chain). |
| `apt_engine.legion` | (b) the 7 legion commanders + KG canonical node map; naesengmoon emits the gate verdict, hades realizes iff PASS. |
| `apt_engine.precondition` | measured precondition — establishes truth from a real pytest exit code (`evaluate_measured_default`, mandated `evaluate_measured_mandated_default`), never a caller bool. |
| `apt_engine.receipt` | replay-checkable JSON receipt for asserted and measured gate outcomes; records evidence but is not a security attestation. |
| `apt_engine.replay` | deterministic replay verifier for a stored `GateReceipt` (`verify --replay`): structural validation + sha256 pin re-check + `audit_key` recomputation + a (scoped) verdict-consistency check. Fail-closed; does NOT re-run pytest. |
| `apt_engine.frontends.mcp_server` | MCP frontend (`pip install -e '.[mcp]'`): `apt_chain / apt_detect / apt_gate / apt_gate_measured / apt_reconcile / apt_legion`. |

### `apt_engine.contrib` — layer-2 ports (NOT the core)

`gate_policy`, `circuit_breaker`, `opa`, `gate_override`, and `resolver` were ported
from the dgx-only SYMPOSIUM prototypes (`gj3447/symposium`
`THEORY/APT/{resolver,gate_endpoint}_prototype`); `kg_manifest` was added later as
the optional KG-backed `ManifestSource`. None of the six is wired into
`evaluate_transition` or belongs to the core public surface — import them
from `apt_engine.contrib`. The gate-server / OPA / config-resolver runtime is
the dgx/SYMPOSIUM layer's job (`adr-apt-dgx-runtime-delegation-2026-05-25`); the
scope-fork decision (CUT, not WIRE) is recorded in
[`docs/ADR-0002-scope-fork-cut-belt.md`](docs/ADR-0002-scope-fork-cut-belt.md).

`contrib.breaker_gate` (`guarded_measured_gate`) is the ADR-0002-honouring **opt-in
integration adapter** for the circuit breaker: it composes the core measured gate
with the contrib `CircuitBreaker` *without* wiring the breaker into the core
(ADR-0002 forbids piecemeal core promotion, and crash/resume + loop policy is
delegated to the runtime). It lives in `contrib` — which may import the core, never
the reverse — so with no breaker supplied the core path is unchanged. When a breaker
is supplied, repeated could-not-evaluate `ERROR`s (a source/manifest outage) trip it
and, while OPEN, the gate short-circuits to a fail-closed `ERROR` verdict
(`reason='circuit_open'`) recorded on the `GateReceipt`. A FAIL is an *evaluated* red,
not an outage, so it does not trip the breaker.

A gate **PASS is a necessary, not a sufficient, condition** for the transition
being *right*: it certifies the mandated tests ran green under isolation, not
that the design is correct or that the execution environment was trusted (see the
TRUST BOUNDARY note in `precondition.py`). Promotion of a `contrib` port into the
core is gated on [`docs/PROMOTION_CHECKLIST.md`](docs/PROMOTION_CHECKLIST.md);
`.importlinter` structurally forbids the reverse coupling.

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

The measured gate is stricter than that development loop: its three pytest
subprocesses run as `python -I -m pytest`, so `PYTHONPATH` and user-site injection
are ignored. Install the gated package in the runner environment first (an editable
install is fine).

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
apt-engine gate SCW MetaReview --measure tests --impact-manifest apt-impact.json \
           --receipt-out receipt.json      # emit an auditable GateReceipt
apt-engine verify --replay receipt.json    # replay-verify it against the checkout
                                           #   (structural + sha256 pin re-check +
                                           #    audit_key recompute + verdict re-eval;
                                           #    NO pytest re-run). exit 0 iff verified
```

### Replay verification (`verify --replay`)

A `GateReceipt` (from `gate --receipt-out`) is replay-checkable: `verify --replay`
re-derives the gate decision from the receipt's own recorded inputs and the current
checkout — WITHOUT re-running pytest — and reports `replay_verified` plus a typed
`mismatches` list. It (1) structurally validates the receipt (schema v1 + required
fields, and rejects a mistyped optional field such as a non-string `target`), (2)
re-hashes each recorded mandated test file and compares to the recorded sha256, (3)
recomputes the `audit_key` fingerprint from the re-derived verdict + re-observed shas
and diffs it against the stored one, and (4) checks the stored verdict against the
set of verdicts the recorded pytest exit code / error / phase adjacency can actually
produce. It is **fail-closed on every I/O and structural fault**: an unreadable
receipt, invalid JSON, a missing OR mistyped field, an unsupported schema, an unknown
phase, or a missing/drifted test file all yield `replay_verified=false` (exit 1),
never an exception. `--checkout ROOT` resolves the mandated files against a different
working tree.

**Scope of the verdict check (read before trusting it).** The verdict check catches
an exit-code-pinned inconsistency (exit-0-but-FAIL, exit-nonzero-but-PASS/CONDITIONAL),
a non-adjacent/self-application transition that is not FAIL, and an ERROR verdict
whose `error` field is absent (or vice versa). It does **not** distinguish PASS vs
SKIP vs CONDITIONAL at the same exit code (nor FAIL vs SKIP at a nonzero one): the
`--skip` / `--conditional` caller flags are not recorded on a v1 receipt, so a tamper
that only swaps among those flag-explained verdicts at a fixed exit code is not
caught. Same trust boundary as the receipt otherwise: replay checks internal
consistency + on-disk content pins, not a re-execution — a forged recorded exit code
is out of scope (that needs the trusted CI runner of ADR-0003).

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
is project-supplied). The intended deployment contract is a **trusted runner (CI)
against a committed manifest on a protected branch that requires owner review** —
see [`docs/ADR-0003`](docs/ADR-0003-trusted-runner-and-manifest-trust-root.md).
`CODEOWNERS` routes the relevant changes for review but does not enforce that rule
by itself; the repository host must enable the matching ruleset/branch protection.
This repo defines the CI half: its `gate` job runs `apt-engine gate SCW MetaReview
--measure tests --impact-manifest apt-impact.json` (`.github/workflows/ci.yml`), and
`apt-impact.json` pins this repo's own mandated tests (`tests/impact/`).

The manifest trust root is **pluggable** via the `ManifestSource` seam:
`FileManifestSource` (the caller / committed file) or — the *non-caller* trust root —
`apt_engine.contrib.kg_manifest.KgManifestSource` (`pip install '.[kg]'`), which
resolves the mandated node ids + shas from the KG contract
`(:AptEngine)-[:MANDATES_IMPACT]->(:AptImpactTest)`. It runs wherever the KG is
reachable — via `neo4j_kg_client` (bolt) or `http_kg_client` (the neo4j HTTP API,
stdlib, for topologies where bolt is firewalled). See
[`docs/ADR-0004`](docs/ADR-0004-kg-manifest-source.md) for the measured deployment
topology.

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

The canonical `main` checkout was re-run at commit `05fa737` on 2026-07-15
(Python 3.10):

```bash
PYTHONPATH=src python3 -m pytest -q
# 233 passed
```

Requires Python ≥3.10; the measured-gate tests shell out to `python -I -m pytest`,
so install `.[dev]` (or `.[gate]`) in the runner first. This receipt covers the
local self-test path; it is not evidence for the runtime / OPA / KG layers that
stay on dgx (see the contrib table and ADR-0002).

The canonical-order test is **revert-proof** (mutation-tested): reordering the
chain back to the bhgman_tool skeleton's `(…SCW, Cleanup, MetaReview)` fails the
suite. See ADR-0001 §"Drift correction".
