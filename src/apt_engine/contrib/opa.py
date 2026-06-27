"""OPA policy evaluation (ported from gate_endpoint_prototype/opa_client.py).

The authoritative layer-2 verdict can defer to an OPA (Open Policy Agent) Rego
policy. `OPAPolicy` is a Protocol so the gate is decoupled from the transport:
`StaticOPAPolicy` (stdlib) makes the allow/deny decision testable with no OPA
server; `HTTPOPAClient` talks to a real OPA sidecar (lazy `httpx`, `opa` extra).

A decision is normalized to `OPADecision(allow: bool, reason: str)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

__all__ = ["OPADecision", "OPAPolicy", "StaticOPAPolicy", "HTTPOPAClient"]


@dataclass(frozen=True)
class OPADecision:
    allow: bool
    reason: str = ""


@runtime_checkable
class OPAPolicy(Protocol):
    def evaluate(self, policy_path: str, input_doc: dict[str, Any]) -> OPADecision:
        ...


class StaticOPAPolicy:
    """In-memory policy: a callable per policy_path -> bool. stdlib, testable.

    Default-deny: an unknown policy_path is denied (fail-closed), matching the
    gate's fail-closed posture.
    """

    def __init__(self, rules: dict[str, Any] | None = None, *, default_allow: bool = False) -> None:
        self._rules = dict(rules or {})
        self._default_allow = default_allow

    def evaluate(self, policy_path: str, input_doc: dict[str, Any]) -> OPADecision:
        rule = self._rules.get(policy_path)
        if rule is None:
            return OPADecision(self._default_allow, f"no policy for {policy_path!r} (default)")
        allow = rule(input_doc) if callable(rule) else bool(rule)
        return OPADecision(bool(allow), f"policy {policy_path!r} -> {allow}")


class HTTPOPAClient:
    """OPA Data API client over httpx (needs the `opa` extra).

    POST /v1/data/<policy_path>  with {"input": input_doc}; the boolean at
    `result` is the allow decision. Synchronous (the engine's gate is sync).
    """

    def __init__(self, base_url: str = "http://localhost:8181", timeout_s: float = 0.5) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def evaluate(self, policy_path: str, input_doc: dict[str, Any]) -> OPADecision:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - serve-time only
            raise SystemExit("OPA HTTP client needs the 'opa' extra: pip install -e '.[opa]'") from exc

        path = policy_path.replace(".", "/")
        resp = httpx.post(
            f"{self.base_url}/v1/data/{path}",
            json={"input": input_doc},
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        result = resp.json().get("result")
        return OPADecision(bool(result), f"opa {policy_path!r} -> {result}")
