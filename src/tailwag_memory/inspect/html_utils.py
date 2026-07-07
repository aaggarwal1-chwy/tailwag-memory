from __future__ import annotations

import json


def _safe_json(payload: dict[str, object]) -> str:
    """Serialize JSON safely for an inline script tag."""
    return json.dumps(payload, sort_keys=True).replace("<", "\\u003c")


def _html_escape(value: object) -> str:
    """Escape a small HTML text value."""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
