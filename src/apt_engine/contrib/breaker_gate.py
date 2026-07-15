"""Optional circuit-breaker adapter for the measured mandated gate.

This is the ADR-0002-honouring INTEGRATION ADAPTER, not a core wiring. ADR-0002
CUT the layer-2 ports out of the core and its Reversibility clause forbids
re-promoting a single port piecemeal ("Re-promote in the core, not piecemeal ...
only together with the composition root WIRE requires"). Wiring the breaker into
`gate.evaluate_transition` / `precondition` would be exactly that piecemeal core
promotion — and would break the `.importlinter` core->contrib prohibition. So the
breaker stays where crash/resume + loop policy belongs (the runtime layer,
`adr-apt-dgx-runtime-delegation-2026-05-25`): here in `apt_engine.contrib`, which
may import the core (the forbidden direction is core->contrib, never the reverse).

`guarded_measured_gate` composes the core measured gate
(`precondition.evaluate_measured_mandated_from_with_receipt`) with the contrib
`CircuitBreaker`:

  * `breaker=None` (the default) => IDENTICAL to calling the core gate directly
    (zero behaviour change when the breaker is absent — the opt-in contract).
  * breaker OPEN => the gate SHORT-CIRCUITS to a typed, fail-closed `ERROR`
    verdict (`reason` / `error` = `CIRCUIT_OPEN_REASON`) WITHOUT running the gate,
    recorded in the returned `GateReceipt` (`can_advance(ERROR) is False`).
  * otherwise the gate runs; a could-not-evaluate `ERROR` verdict (source outage /
    unreadable manifest) trips the breaker (`record_failure`); any *evaluated*
    verdict (PASS/FAIL/SKIP/CONDITIONAL) is a healthy source and resets it
    (`record_success`). A FAIL is an evaluated red, NOT an outage, so it does not
    trip the breaker — only repeated ERRORs do.

Stdlib only (the breaker's default `InMemoryStore` is redis-free); nothing in the
deterministic core imports this module.

# KG: adr-apt-engine-scope-decision-2026-05-25, apt-engine ADR-0002 (scope-fork CUT),
#     adr-apt-dgx-runtime-delegation-2026-05-25
"""

from __future__ import annotations

from ..gate import GateResult, Verdict
from ..precondition import ManifestSource, evaluate_measured_mandated_from_with_receipt
from ..receipt import GateReceipt, build_gate_receipt
from .circuit_breaker import CircuitBreaker

__all__ = ["CIRCUIT_OPEN_REASON", "guarded_measured_gate"]

#: Fail-closed reason/error code stamped on the receipt when the breaker is OPEN
#: and the gate is short-circuited. A typed, greppable terminal marker — never a
#: bare exception surfaced as the loop terminal.
CIRCUIT_OPEN_REASON = "circuit_open"


def guarded_measured_gate(
    from_phase: str,
    to_phase: str,
    *,
    target: str,
    source: ManifestSource,
    breaker: CircuitBreaker | None = None,
    conditional: bool = False,
    skipped: bool = False,
) -> tuple[GateResult, GateReceipt]:
    """Run the measured mandated gate, optionally guarded by a `CircuitBreaker`.

    With `breaker=None` this is a pass-through to
    `evaluate_measured_mandated_from_with_receipt` (identical verdict + receipt).
    With a breaker, repeated could-not-evaluate ERRORs (e.g. a KG/manifest source
    outage) trip it; while OPEN the gate short-circuits to a fail-closed ERROR
    verdict recorded on the receipt, so the caller never blocks on a dead source
    yet never advances either.
    """
    if breaker is None:
        return evaluate_measured_mandated_from_with_receipt(
            from_phase,
            to_phase,
            target=target,
            source=source,
            conditional=conditional,
            skipped=skipped,
        )

    decision = breaker.check()
    if not decision.allow_request:
        # OPEN and not yet elapsed to HALF_OPEN: refuse without touching the
        # source. Typed fail-closed terminal — ERROR, not a raised exception.
        result = GateResult(
            from_phase,
            to_phase,
            Verdict.ERROR,
            f"{CIRCUIT_OPEN_REASON}: measured gate short-circuited ({decision.reason})",
        )
        receipt = build_gate_receipt(
            result,
            gate_kind="measured-mandated",
            target=target,
            manifest_source_kind=type(source).__name__,
            error=CIRCUIT_OPEN_REASON,
        )
        return result, receipt

    result, receipt = evaluate_measured_mandated_from_with_receipt(
        from_phase,
        to_phase,
        target=target,
        source=source,
        conditional=conditional,
        skipped=skipped,
    )
    if result.verdict is Verdict.ERROR:
        # Could-not-evaluate (outage) — count it toward the trip threshold.
        breaker.record_failure()
    else:
        # An evaluated verdict (incl. FAIL) means the source was reachable; the
        # circuit is healthy, so reset the failure counter / close a trial.
        breaker.record_success()
    return result, receipt
