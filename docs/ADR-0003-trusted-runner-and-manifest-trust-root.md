# ADR-0003 — Trusted runner (CI) + the manifest trust root

- **Status:** Accepted (2026-06-28)
- **Builds on:** the measured-precondition gate (H-C, PR #1) and its TRUST BOUNDARY
  notes in `apt_engine.precondition`.

## Context

Five adversarial red-team rounds on the measured `SCW→MetaReview` gate converged on
one structural fact: **a gate that runs tests on a working tree the gated party
controls cannot be forge-proof.** Each fix closed a channel and revealed the next —
caller bool → injectable runner → name match → content sha → config injection →
basename shadow → warning phantom → env injection → conftest hook code. The two
irreducible channels are:

1. **Execution environment.** A target `conftest.py` runs arbitrary hook code (a
   `pytest_runtest_makereport` wrapper can rewrite a RED outcome to passed); the
   test bodies and sibling modules also run as code. `_PYTEST_ISOLATION` isolates
   *config*, not *code*.
2. **The manifest.** Node ids + shas are caller-supplied (`--impact-manifest`); a
   forger who writes the manifest pins their own forged test's sha.

So the engine's measured gate is **config-isolated defence-in-depth + a correctness
aid**, NOT a security boundary. The sound guarantee needs (a) a trusted execution
environment and (b) a non-caller manifest.

## Decision

Resolve the trust root *outside* the stdlib engine, consistent with ADR-0002 and
`adr-apt-dgx-runtime-delegation` (the KG/runtime layer is not the stdlib core's job):

1. **Trusted execution environment = CI.** `.github/workflows/ci.yml` adds a `gate`
   job that runs `apt-engine gate SCW MetaReview --measure tests --impact-manifest
   apt-impact.json`. CI — not the developer's machine — is the runner: the gated
   party does not control the environment, and config/env are isolated. This is the
   execution-environment half of the close.
2. **Non-caller manifest = the committed, review-gated `apt-impact.json`.** At gate
   time CI uses the manifest committed to the repo; changing the mandated node ids
   or their shas requires a reviewed PR. It is not caller-supplied at the moment the
   gate runs. (A **KG-sourced** manifest is the stronger trust root and remains a
   dgx/SYMPOSIUM plug at the existing `manifest_path` seam — out of scope for the
   stdlib engine, per ADR-0002 / dgx-runtime-delegation.)
3. **Runtime dependency made explicit.** The measured gate shells out to pytest, so
   pytest is declared as the `gate` optional extra (`pip install '.[gate]'`); the
   stdlib core itself stays dep-free.
4. **CI also enforces ADR-0002** via an `import-linter` contract (`.importlinter`):
   the deterministic core must not import `apt_engine.contrib`.

## Consequences

- For its intended use — **CI-enforced, against the committed manifest** — the gate
  is sound: the mandated impact tests must actually run green in a runner the gated
  party does not control.
- On a developer's own machine the gate remains **defence-in-depth only** (documented
  in `_PYTEST_ISOLATION` / the precondition TRUST BOUNDARY notes).
- Honest residual: even in CI the impact tests (and any conftest) run as code from
  the PR's tree. A malicious `conftest.py` in a PR could subvert a gate run — but it
  is visible in review, the same trust basis as the committed manifest. Defending
  against a malicious *reviewed-and-merged* change is a code-review/threat-model
  question, not the gate's to solve. The full close (KG-pinned manifest + sandboxed
  runner) is future dgx/SYMPOSIUM work.

## Reversibility

CI and the committed manifest are additive and trivially reversible. The
`manifest_path` seam is unchanged, so a future KG/SYMPOSIUM manifest source plugs in
without touching the gate.
