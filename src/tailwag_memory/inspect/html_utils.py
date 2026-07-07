from __future__ import annotations

import json

_INSPECT_NAV_ITEMS = (
    ("affect", "Affect Scatter", "tailwag-affect.html"),
    ("person-timeline", "Person Timeline", "tailwag-person-timeline.html"),
    ("memory-items", "Memory Items", "tailwag-memory-items.html"),
)


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


def inspect_nav(current: str | None) -> str:
    """Return canonical inspect report navigation."""
    links = []
    for key, label, href in _INSPECT_NAV_ITEMS:
        current_attr = ' aria-current="page"' if key == current else ""
        links.append(f'<a href="{href}"{current_attr}>{label}</a>')
    return '<nav aria-label="Inspect reports">' + "".join(links) + "</nav>"
