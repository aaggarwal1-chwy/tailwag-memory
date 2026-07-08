from __future__ import annotations

from dataclasses import asdict
from functools import lru_cache
from importlib.resources import files
import json

INSPECT_CSS_FILENAME = "tailwag-inspect.css"
INSPECT_JS_FILENAME = "tailwag-inspect.js"

_INSPECT_NAV_ITEMS = (
    ("followup-validity", "Follow-Up Validity", "tailwag-followup-validity.html"),
    ("affect", "Affect Scatter", "tailwag-affect.html"),
    ("person-timeline", "Person Timeline", "tailwag-person-timeline.html"),
    ("memory-items", "Memory Items", "tailwag-memory-items.html"),
)


@lru_cache(maxsize=None)
def inspect_asset_text(filename: str) -> str:
    """Return packaged inspect browser asset text."""
    if filename not in {INSPECT_CSS_FILENAME, INSPECT_JS_FILENAME}:
        raise ValueError(f"unknown inspect asset: {filename}")
    return files(__package__).joinpath("assets", filename).read_text(encoding="utf-8")


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


def inspect_style_link() -> str:
    """Return the shared inspect stylesheet link tag."""
    return f'<link rel="stylesheet" href="{INSPECT_CSS_FILENAME}">'


def inspect_script_tag() -> str:
    """Return the shared inspect JavaScript tag."""
    return f'<script src="{INSPECT_JS_FILENAME}"></script>'


def inspect_nav(current: str | None) -> str:
    """Return canonical inspect report navigation."""
    links = []
    for key, label, href in _INSPECT_NAV_ITEMS:
        current_attr = ' aria-current="page"' if key == current else ""
        links.append(f'<a href="{href}"{current_attr}>{label}</a>')
    return '<nav aria-label="Inspect reports">' + "".join(links) + "</nav>"


def inspect_command_panel(command: str) -> str:
    """Return the common empty-report command panel."""
    return f"""<section class="panel command-panel" id="emptyCommand">
      <h2>Generate This Report</h2>
      <p><code>{_html_escape(command)}</code></p>
    </section>"""


def render_inspect_report_page(
    report: object,
    *,
    current_nav: str,
    count_meta: str,
    page_css: str,
    body_html: str,
    page_js: str,
) -> str:
    """Render the shared HTML shell for one inspect report."""
    payload = _safe_json(asdict(report))
    rendered_css = page_css.strip()
    style_tag = f"\n  <style>\n{rendered_css}\n  </style>" if rendered_css else ""
    rendered_js = page_js.strip()
    page_script = f"\n  <script>\n{rendered_js}\n  </script>" if rendered_js else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_html_escape(report.title)}</title>
  {inspect_style_link()}{style_tag}
</head>
<body>
  <header>
    {inspect_nav(current_nav)}
    <h1>{_html_escape(report.title)}</h1>
    <div class="meta">{count_meta}</div>
  </header>
  <main>
{body_html.strip()}
  </main>
  <script id="report-data" type="application/json">{payload}</script>
  {inspect_script_tag()}{page_script}
</body>
</html>
"""
