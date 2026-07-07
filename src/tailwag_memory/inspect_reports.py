from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import timezone
import json

from .models import PersonEpisodeAffectPoint, utc_now_iso


@dataclass(frozen=True)
class InspectReport:
    """Common report envelope for Tailwag inspect utilities."""

    title: str
    generated_at: str
    filters: dict[str, object] = field(default_factory=dict)
    records: list[dict[str, object]] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def affect_report(
    points: list[PersonEpisodeAffectPoint],
    *,
    filters: dict[str, object] | None = None,
    metadata: dict[str, object] | None = None,
    warnings: list[str] | None = None,
) -> InspectReport:
    """Build a report envelope for affect scatter exports."""
    return InspectReport(
        title="Tailwag Affect Scatter",
        generated_at=utc_now_iso(),
        filters=filters or {},
        records=[asdict(point) for point in points],
        metadata=metadata or {},
        warnings=warnings or [],
    )


def report_json(report: InspectReport) -> str:
    """Serialize an inspect report as stable JSON."""
    return json.dumps(asdict(report), indent=2, sort_keys=True)


def affect_report_html(report: InspectReport) -> str:
    """Render a self-contained affect scatter HTML report."""
    payload = _safe_json(asdict(report))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_html_escape(report.title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f5ef;
      --ink: #1f2933;
      --muted: #65717f;
      --line: #d9d4c7;
      --panel: #ffffff;
      --accent: #1f7a8c;
      --accent-2: #d94f30;
      --accent-3: #5a7d2b;
      --accent-4: #7a4e9d;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }}
    header {{
      padding: 22px 28px 14px;
      border-bottom: 1px solid var(--line);
      background: #fffdf8;
    }}
    h1 {{
      margin: 0;
      font-size: 24px;
      line-height: 1.2;
      letter-spacing: 0;
    }}
    .meta {{
      margin-top: 6px;
      color: var(--muted);
      font-size: 13px;
    }}
    main {{
      display: grid;
      grid-template-columns: minmax(360px, 1fr) minmax(320px, 430px);
      min-height: calc(100vh - 78px);
    }}
    .plot-wrap {{
      padding: 20px 24px 28px;
      min-width: 0;
    }}
    .toolbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
      color: var(--muted);
      font-size: 13px;
    }}
    .plot {{
      position: relative;
      width: min(100%, 820px);
      aspect-ratio: 1 / 1;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 8px 22px rgba(31, 41, 51, 0.08);
    }}
    .grid {{
      position: absolute;
      inset: 48px 44px 44px 58px;
      border-left: 2px solid var(--ink);
      border-bottom: 2px solid var(--ink);
      background-image:
        linear-gradient(to right, rgba(101,113,127,.18) 1px, transparent 1px),
        linear-gradient(to top, rgba(101,113,127,.18) 1px, transparent 1px);
      background-size: 25% 100%, 100% 25%;
    }}
    .axis-label {{
      position: absolute;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }}
    .x-label {{ left: 50%; bottom: 12px; transform: translateX(-50%); }}
    .y-label {{ left: 14px; top: 50%; transform: translateY(-50%) rotate(-90deg); }}
    .tick {{
      position: absolute;
      color: var(--muted);
      font-size: 11px;
    }}
    .point {{
      position: absolute;
      width: 14px;
      height: 14px;
      border-radius: 50%;
      border: 2px solid #ffffff;
      box-shadow: 0 2px 7px rgba(31,41,51,.26);
      cursor: pointer;
      transform: translate(-50%, -50%);
    }}
    .point:focus {{
      outline: 3px solid rgba(31,122,140,.35);
      outline-offset: 2px;
    }}
    aside {{
      border-left: 1px solid var(--line);
      background: #fffdf8;
      padding: 20px 22px;
      overflow: auto;
    }}
    h2 {{
      margin: 0 0 10px;
      font-size: 18px;
      line-height: 1.25;
      letter-spacing: 0;
    }}
    .score-row {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin: 12px 0;
    }}
    .score {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: var(--panel);
    }}
    .score strong {{
      display: block;
      font-size: 22px;
      line-height: 1;
      margin-top: 5px;
    }}
    dl {{
      display: grid;
      grid-template-columns: 105px 1fr;
      gap: 7px 10px;
      margin: 12px 0;
      font-size: 13px;
    }}
    dt {{ color: var(--muted); }}
    dd {{ margin: 0; overflow-wrap: anywhere; }}
    pre {{
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 12px;
      font-size: 13px;
      line-height: 1.45;
    }}
    .empty, .warnings {{
      color: var(--muted);
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 12px;
      font-size: 13px;
    }}
    .warnings {{ margin-bottom: 14px; color: #8a3a22; }}
    @media (max-width: 860px) {{
      main {{ grid-template-columns: 1fr; }}
      aside {{ border-left: 0; border-top: 1px solid var(--line); }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{_html_escape(report.title)}</h1>
    <div class="meta">Generated {_html_escape(report.generated_at)} - <span id="count">0</span> scored points</div>
  </header>
  <main>
    <section class="plot-wrap">
      <div class="toolbar">
        <span>Valence and arousal are normalized from 0 to 1.</span>
        <span id="filterSummary"></span>
      </div>
      <div class="plot" id="plot" role="img" aria-label="Valence arousal scatter plot">
        <div class="grid" id="grid"></div>
        <div class="axis-label x-label">Valence</div>
        <div class="axis-label y-label">Arousal</div>
      </div>
    </section>
    <aside>
      <div id="warnings"></div>
      <h2 id="detailTitle">Select a point</h2>
      <div id="detail" class="empty">Click a point to inspect the evaluated text and metadata.</div>
    </aside>
  </main>
  <script id="report-data" type="application/json">{payload}</script>
  <script>
    const report = JSON.parse(document.getElementById('report-data').textContent);
    const records = report.records || [];
    const colors = ['#1f7a8c', '#d94f30', '#5a7d2b', '#7a4e9d', '#9b6b1f', '#25735f'];
    const colorByPerson = new Map();
    const plot = document.getElementById('plot');
    const grid = document.getElementById('grid');
    const detail = document.getElementById('detail');
    const detailTitle = document.getElementById('detailTitle');
    document.getElementById('count').textContent = records.length;
    document.getElementById('filterSummary').textContent = Object.entries(report.filters || {{}})
      .filter(([, value]) => value !== null && value !== undefined && value !== '')
      .map(([key, value]) => `${{key}}=${{value}}`)
      .join(' - ');
    const warnings = report.warnings || [];
    if (warnings.length) {{
      document.getElementById('warnings').innerHTML = `<div class="warnings">${{warnings.map(escapeHtml).join('<br>')}}</div>`;
    }}
    if (!records.length) {{
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.style.position = 'absolute';
      empty.style.left = '50%';
      empty.style.top = '50%';
      empty.style.transform = 'translate(-50%, -50%)';
      empty.textContent = 'No scored transcript points matched this export.';
      plot.appendChild(empty);
    }}
    addTicks();
    records.forEach((record, index) => {{
      const transcript = record.transcript || {{}};
      const person = transcript.person_id || 'unknown';
      if (!colorByPerson.has(person)) {{
        colorByPerson.set(person, colors[colorByPerson.size % colors.length]);
      }}
      const point = document.createElement('button');
      point.className = 'point';
      point.style.background = colorByPerson.get(person);
      point.style.left = `${{58 + clamp(record.valence) * (plot.clientWidth - 102)}}px`;
      point.style.top = `${{48 + (1 - clamp(record.arousal)) * (plot.clientHeight - 92)}}px`;
      point.title = `${{transcript.display_name || transcript.person_id}} - valence ${{format(record.valence)}} - arousal ${{format(record.arousal)}}`;
      point.setAttribute('aria-label', point.title);
      point.addEventListener('click', () => renderDetail(record));
      point.addEventListener('keydown', (event) => {{
        if (event.key === 'Enter' || event.key === ' ') {{
          event.preventDefault();
          renderDetail(record);
        }}
      }});
      plot.appendChild(point);
      if (index === 0) renderDetail(record);
    }});
    window.addEventListener('resize', () => {{
      document.querySelectorAll('.point').forEach((node) => node.remove());
      records.forEach((record) => {{
        const transcript = record.transcript || {{}};
        const person = transcript.person_id || 'unknown';
        const point = document.createElement('button');
        point.className = 'point';
        point.style.background = colorByPerson.get(person);
        point.style.left = `${{58 + clamp(record.valence) * (plot.clientWidth - 102)}}px`;
        point.style.top = `${{48 + (1 - clamp(record.arousal)) * (plot.clientHeight - 92)}}px`;
        point.title = `${{transcript.display_name || transcript.person_id}} - valence ${{format(record.valence)}} - arousal ${{format(record.arousal)}}`;
        point.setAttribute('aria-label', point.title);
        point.addEventListener('click', () => renderDetail(record));
        plot.appendChild(point);
      }});
    }});
    function renderDetail(record) {{
      const transcript = record.transcript || {{}};
      detailTitle.textContent = transcript.display_name || transcript.person_id || 'Unknown person';
      detail.className = '';
      detail.innerHTML = `
        <div class="score-row">
          <div class="score">Valence<strong>${{format(record.valence)}}</strong></div>
          <div class="score">Arousal<strong>${{format(record.arousal)}}</strong></div>
        </div>
        <dl>
          <dt>Person</dt><dd>${{escapeHtml(transcript.person_id || '')}}</dd>
          <dt>Episode</dt><dd>${{escapeHtml(transcript.episode_id || '')}}</dd>
          <dt>Time</dt><dd>${{escapeHtml([transcript.start_time, transcript.end_time].filter(Boolean).join(' to '))}}</dd>
          <dt>Place</dt><dd>${{escapeHtml([transcript.building_code, transcript.room_id].filter(Boolean).join(' / '))}}</dd>
          <dt>Role</dt><dd>${{escapeHtml(transcript.role || '')}}</dd>
          <dt>Source</dt><dd>${{escapeHtml(transcript.source || '')}}</dd>
          <dt>Lines</dt><dd>${{escapeHtml(String(transcript.line_count || 0))}}</dd>
        </dl>
        <pre>${{escapeHtml(transcript.text || '')}}</pre>
        <pre>${{escapeHtml(JSON.stringify(record.metadata || {{}}, null, 2))}}</pre>
      `;
    }}
    function addTicks() {{
      [[0, '0'], [0.5, '0.5'], [1, '1']].forEach(([value, label]) => {{
        const x = document.createElement('div');
        x.className = 'tick';
        x.style.left = `${{58 + value * (plot.clientWidth - 102)}}px`;
        x.style.bottom = '28px';
        x.textContent = label;
        plot.appendChild(x);
        const y = document.createElement('div');
        y.className = 'tick';
        y.style.left = '28px';
        y.style.top = `${{48 + (1 - value) * (plot.clientHeight - 92)}}px`;
        y.textContent = label;
        plot.appendChild(y);
      }});
    }}
    function clamp(value) {{
      return Math.max(0, Math.min(1, Number(value) || 0));
    }}
    function format(value) {{
      return Number(value).toFixed(3);
    }}
    function escapeHtml(value) {{
      return String(value).replace(/[&<>"']/g, (char) => ({{
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      }}[char]));
    }}
  </script>
</body>
</html>
"""


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
