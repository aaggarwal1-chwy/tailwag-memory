from __future__ import annotations

from dataclasses import asdict

from .html_utils import _html_escape, _safe_json, inspect_nav
from .reports import InspectReport


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
      --memory: #c2410c;
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
      position: sticky;
      top: 0;
      z-index: 20;
    }}
    nav {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 12px;
      font-size: 13px;
    }}
    nav a {{
      color: var(--accent);
      text-decoration: none;
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 6px;
      padding: 6px 9px;
    }}
    nav a[aria-current="page"] {{
      border-color: var(--accent);
      font-weight: 650;
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
      min-height: calc(100vh - 78px);
      display: flex;
      flex-direction: column;
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
    .toolbar button {{
      appearance: none;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      color: var(--ink);
      font: inherit;
      padding: 6px 10px;
      cursor: pointer;
    }}
    .toolbar button:disabled {{
      color: var(--muted);
      cursor: default;
      opacity: .55;
    }}
    .toolbar-actions {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .legend {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .legend-item {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      white-space: nowrap;
    }}
    .swatch {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--accent);
      border: 1px solid #ffffff;
      box-shadow: 0 1px 3px rgba(31,41,51,.22);
    }}
    .swatch-memory {{ background: var(--memory); }}
    .plot {{
      position: relative;
      width: 100%;
      flex: 1 1 auto;
      min-height: 420px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 8px 22px rgba(31, 41, 51, 0.08);
    }}
    .grid {{
      position: absolute;
      inset: 48px 44px 44px 58px;
      background-image:
        linear-gradient(to right, rgba(101,113,127,.18) 1px, transparent 1px),
        linear-gradient(to top, rgba(101,113,127,.18) 1px, transparent 1px);
      background-size: 25% 100%, 100% 25%;
    }}
    .axis-line {{
      position: absolute;
      background: var(--ink);
      pointer-events: none;
    }}
    .axis-line-y {{
      top: 48px;
      bottom: 44px;
      width: 2px;
      transform: translateX(-1px);
    }}
    .axis-line-x {{
      left: 58px;
      right: 44px;
      height: 2px;
      transform: translateY(-1px);
    }}
    .axis-label {{
      position: absolute;
      color: var(--muted);
      font-size: 17px;
      font-weight: 650;
    }}
    .x-label {{ left: 50%; bottom: 12px; transform: translateX(-50%); }}
    .y-label {{ left: 14px; top: 50%; transform: translateY(-50%) rotate(-90deg); }}
    .tick {{
      position: absolute;
      color: var(--muted);
      font-size: 15px;
      font-weight: 600;
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
    .selection {{
      position: absolute;
      border: 1px solid var(--accent-2);
      background: rgba(217, 79, 48, .12);
      pointer-events: none;
      display: none;
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
      .plot-wrap {{ min-height: 70vh; }}
      aside {{ border-left: 0; border-top: 1px solid var(--line); }}
    }}
  </style>
</head>
<body>
  <header>
    {inspect_nav("affect")}
    <h1>{_html_escape(report.title)}</h1>
    <div class="meta">Generated {_html_escape(report.generated_at)} - <span id="count">0</span> scored points</div>
  </header>
  <main>
    <section class="plot-wrap">
      <div class="toolbar">
        <span>Valence and arousal are displayed from -1 to 1, centered from the model's native 0 to 1 scores.</span>
        <span class="toolbar-actions">
          <span class="legend" aria-label="Point colors">
            <span class="legend-item"><span class="swatch"></span>No linked memory</span>
            <span class="legend-item"><span class="swatch swatch-memory"></span>Linked memory item</span>
          </span>
          <span id="filterSummary"></span>
          <button type="button" id="resetZoom" disabled>Reset Zoom</button>
        </span>
      </div>
      <div class="plot" id="plot" role="img" aria-label="Valence arousal scatter plot">
        <div class="grid" id="grid"></div>
        <div class="axis-line axis-line-y" id="axisY"></div>
        <div class="axis-line axis-line-x" id="axisX"></div>
        <div class="axis-label x-label">Valence</div>
        <div class="axis-label y-label">Arousal</div>
        <div class="selection" id="selection"></div>
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
    const pointColor = '#1f7a8c';
    const memoryPointColor = '#c2410c';
    const plot = document.getElementById('plot');
    const axisX = document.getElementById('axisX');
    const axisY = document.getElementById('axisY');
    const selection = document.getElementById('selection');
    const resetZoom = document.getElementById('resetZoom');
    const detail = document.getElementById('detail');
    const detailTitle = document.getElementById('detailTitle');
    const fullDomain = {{ xMin: -1, xMax: 1, yMin: -1, yMax: 1 }};
    let domain = {{ ...fullDomain }};
    let dragStart = null;
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
    renderTicks();
    renderPoints();
    records.forEach((record, index) => {{
      if (index === 0) renderDetail(record);
    }});
    window.addEventListener('resize', () => {{
      renderTicks();
      renderPoints();
    }});
    resetZoom.addEventListener('click', () => {{
      domain = {{ ...fullDomain }};
      resetZoom.disabled = true;
      renderTicks();
      renderPoints();
    }});
    plot.addEventListener('pointerdown', (event) => {{
      if (event.button !== 0 || event.target.classList.contains('point')) return;
      const bounds = plotAreaBounds();
      const point = pointerPoint(event);
      if (!pointInBounds(point, bounds)) return;
      dragStart = point;
      selection.style.display = 'block';
      updateSelection(point, point);
      plot.setPointerCapture(event.pointerId);
    }});
    plot.addEventListener('pointermove', (event) => {{
      if (!dragStart) return;
      updateSelection(dragStart, pointerPoint(event));
    }});
    plot.addEventListener('pointerup', (event) => {{
      if (!dragStart) return;
      const dragEnd = pointerPoint(event);
      selection.style.display = 'none';
      plot.releasePointerCapture(event.pointerId);
      applyZoom(dragStart, dragEnd);
      dragStart = null;
    }});
    plot.addEventListener('pointercancel', () => {{
      dragStart = null;
      selection.style.display = 'none';
    }});
    function renderPoints() {{
      document.querySelectorAll('.point').forEach((node) => node.remove());
      records.forEach((record) => {{
        const transcript = record.transcript || {{}};
        const xValue = centered(record.valence);
        const yValue = centered(record.arousal);
        if (xValue < domain.xMin || xValue > domain.xMax || yValue < domain.yMin || yValue > domain.yMax) return;
        const point = document.createElement('button');
        point.className = 'point';
        point.style.background = hasLinkedMemory(record) ? memoryPointColor : pointColor;
        const screenPoint = valueToScreen(xValue, yValue);
        point.style.left = `${{screenPoint.x}}px`;
        point.style.top = `${{screenPoint.y}}px`;
        const memoryLabel = hasLinkedMemory(record) ? ` - linked memories ${{linkedMemoryCount(record)}}` : '';
        point.title = `${{transcript.display_name || transcript.person_id}} - valence ${{format(centered(record.valence))}} - arousal ${{format(centered(record.arousal))}}${{memoryLabel}}`;
        point.setAttribute('aria-label', point.title);
        point.addEventListener('click', () => renderDetail(record));
        point.addEventListener('keydown', (event) => {{
          if (event.key === 'Enter' || event.key === ' ') {{
            event.preventDefault();
            renderDetail(record);
          }}
        }});
        plot.appendChild(point);
      }});
    }}
    function renderDetail(record) {{
      const transcript = record.transcript || {{}};
      detailTitle.textContent = transcript.display_name || transcript.person_id || 'Unknown person';
      detail.className = '';
      detail.innerHTML = `
        <div class="score-row">
          <div class="score">Valence<strong>${{format(centered(record.valence))}}</strong></div>
          <div class="score">Arousal<strong>${{format(centered(record.arousal))}}</strong></div>
        </div>
        <dl>
          <dt>Person</dt><dd>${{escapeHtml(transcript.person_id || '')}}</dd>
          <dt>Speaker</dt><dd>${{escapeHtml(speakerNames(transcript).join(', '))}}</dd>
          <dt>Episode</dt><dd>${{escapeHtml(transcript.episode_id || '')}}</dd>
          <dt>Time</dt><dd>${{escapeHtml(formatTimeRange(transcript.start_time, transcript.end_time))}}</dd>
          <dt>Place</dt><dd>${{escapeHtml([transcript.building_code, transcript.room_id].filter(Boolean).join(' / '))}}</dd>
          <dt>Lines</dt><dd>${{escapeHtml(String(transcript.line_count || 0))}}</dd>
          <dt>Linked memories</dt><dd>${{escapeHtml(String(linkedMemoryCount(record)))}}</dd>
          <dt>Model scores</dt><dd>valence ${{format(record.valence)}} / arousal ${{format(record.arousal)}}</dd>
        </dl>
        <pre>${{escapeHtml(transcript.text || '')}}</pre>
      `;
    }}
    function renderTicks() {{
      renderAxes();
      document.querySelectorAll('.tick').forEach((node) => node.remove());
      tickValues(domain.xMin, domain.xMax).forEach((value) => {{
        const x = document.createElement('div');
        x.className = 'tick';
        x.style.left = `${{valueToScreen(value, domain.yMin).x}}px`;
        x.style.bottom = '28px';
        x.textContent = tickLabel(value);
        plot.appendChild(x);
      }});
      tickValues(domain.yMin, domain.yMax).forEach((value) => {{
        const y = document.createElement('div');
        y.className = 'tick';
        y.style.left = '28px';
        y.style.top = `${{valueToScreen(domain.xMin, value).y}}px`;
        y.textContent = tickLabel(value);
        plot.appendChild(y);
      }});
    }}
    function renderAxes() {{
      const origin = valueToScreen(0, 0);
      axisY.style.left = `${{origin.x}}px`;
      axisX.style.top = `${{origin.y}}px`;
    }}
    function hasLinkedMemory(record) {{
      return linkedMemoryCount(record) > 0;
    }}
    function linkedMemoryCount(record) {{
      const transcript = record.transcript || {{}};
      const count = Math.max(0, Number(transcript.memory_item_count || 0));
      if (count > 0) return count;
      return transcript.has_memory_items ? 1 : 0;
    }}
    function speakerNames(transcript) {{
      const lines = transcript.transcript_lines || [];
      const names = [];
      lines.forEach((line) => {{
        const speaker = String(line.speaker || '').trim();
        if (speaker && !names.includes(speaker)) names.push(speaker);
      }});
      return names.length ? names : [transcript.display_name || transcript.person_id || ''];
    }}
    function formatTimeRange(start, end) {{
      const formattedStart = formatDate(start);
      const formattedEnd = formatDate(end);
      if (formattedStart && formattedEnd && formattedStart !== formattedEnd) return `${{formattedStart}} to ${{formattedEnd}}`;
      return formattedStart || formattedEnd || '';
    }}
    function formatDate(value) {{
      if (!value) return '';
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      const parts = new Intl.DateTimeFormat('en-US', {{
        month: 'short',
        day: 'numeric',
        year: 'numeric'
      }}).formatToParts(date);
      const month = (parts.find((part) => part.type === 'month') || {{ value: '' }}).value;
      const day = (parts.find((part) => part.type === 'day') || {{ value: '' }}).value;
      const year = (parts.find((part) => part.type === 'year') || {{ value: '' }}).value;
      return `${{month}}. ${{day}}, ${{year}}`;
    }}
    function centered(value) {{
      return clamp(Number(value) * 2 - 1, -1, 1);
    }}
    function normalizeForPlot(value) {{
      return (clamp(value, -1, 1) + 1) / 2;
    }}
    function plotAreaBounds() {{
      return {{
        left: 58,
        right: plot.clientWidth - 44,
        top: 48,
        bottom: plot.clientHeight - 44
      }};
    }}
    function valueToScreen(xValue, yValue) {{
      const bounds = plotAreaBounds();
      const xRatio = (xValue - domain.xMin) / (domain.xMax - domain.xMin);
      const yRatio = (yValue - domain.yMin) / (domain.yMax - domain.yMin);
      return {{
        x: bounds.left + xRatio * (bounds.right - bounds.left),
        y: bounds.bottom - yRatio * (bounds.bottom - bounds.top)
      }};
    }}
    function screenToValue(point) {{
      const bounds = plotAreaBounds();
      const xRatio = (point.x - bounds.left) / (bounds.right - bounds.left);
      const yRatio = (bounds.bottom - point.y) / (bounds.bottom - bounds.top);
      return {{
        x: domain.xMin + xRatio * (domain.xMax - domain.xMin),
        y: domain.yMin + yRatio * (domain.yMax - domain.yMin)
      }};
    }}
    function pointerPoint(event) {{
      const rect = plot.getBoundingClientRect();
      return {{
        x: event.clientX - rect.left,
        y: event.clientY - rect.top
      }};
    }}
    function pointInBounds(point, bounds) {{
      return point.x >= bounds.left && point.x <= bounds.right && point.y >= bounds.top && point.y <= bounds.bottom;
    }}
    function updateSelection(start, end) {{
      const bounds = plotAreaBounds();
      const x1 = clamp(start.x, bounds.left, bounds.right);
      const y1 = clamp(start.y, bounds.top, bounds.bottom);
      const x2 = clamp(end.x, bounds.left, bounds.right);
      const y2 = clamp(end.y, bounds.top, bounds.bottom);
      selection.style.left = `${{Math.min(x1, x2)}}px`;
      selection.style.top = `${{Math.min(y1, y2)}}px`;
      selection.style.width = `${{Math.abs(x2 - x1)}}px`;
      selection.style.height = `${{Math.abs(y2 - y1)}}px`;
    }}
    function applyZoom(start, end) {{
      const bounds = plotAreaBounds();
      const clampedStart = {{
        x: clamp(start.x, bounds.left, bounds.right),
        y: clamp(start.y, bounds.top, bounds.bottom)
      }};
      const clampedEnd = {{
        x: clamp(end.x, bounds.left, bounds.right),
        y: clamp(end.y, bounds.top, bounds.bottom)
      }};
      if (Math.abs(clampedEnd.x - clampedStart.x) < 12 || Math.abs(clampedEnd.y - clampedStart.y) < 12) return;
      const first = screenToValue(clampedStart);
      const second = screenToValue(clampedEnd);
      domain = {{
        xMin: Math.min(first.x, second.x),
        xMax: Math.max(first.x, second.x),
        yMin: Math.min(first.y, second.y),
        yMax: Math.max(first.y, second.y)
      }};
      resetZoom.disabled = false;
      renderTicks();
      renderPoints();
    }}
    function tickValues(min, max) {{
      if (Math.abs(min + 1) < 0.001 && Math.abs(max - 1) < 0.001) return [-1, 0, 1];
      return [min, (min + max) / 2, max];
    }}
    function tickLabel(value) {{
      return Number(value).toFixed(2).replace(/\\.00$/, '');
    }}
    function clamp(value, min, max) {{
      return Math.max(min, Math.min(max, Number(value) || 0));
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

