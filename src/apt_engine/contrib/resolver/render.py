"""Marker rendering — lazy jinja2 (needs the `resolver` extra).

`render(body, cfg)` substitutes `{{cfg.X}}` markers from the resolved config.
A StrictUndefined environment turns an unresolved marker into an explicit error
rather than a silent empty string (the prototype's UnresolvedMarkerError).
"""

from __future__ import annotations

from typing import Any

__all__ = ["render", "UnresolvedMarkerError"]


class UnresolvedMarkerError(RuntimeError):
    """A `{{cfg.X}}` marker had no value in cfg — refuse to emit a partial render."""


def render(body: str, cfg: dict[str, Any]) -> str:
    try:
        from jinja2 import Environment, StrictUndefined
        from jinja2.exceptions import UndefinedError
    except ImportError as exc:  # pragma: no cover - serve-time only
        raise SystemExit("resolver render needs the 'resolver' extra: pip install -e '.[resolver]'") from exc

    env = Environment(undefined=StrictUndefined, autoescape=False)
    template = env.from_string(body)
    try:
        return template.render(cfg=cfg)
    except UndefinedError as exc:
        raise UnresolvedMarkerError(str(exc)) from exc
