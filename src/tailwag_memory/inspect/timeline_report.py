from __future__ import annotations

from dataclasses import asdict

from .html_utils import _html_escape, _safe_json
from .reports import InspectReport


def person_timeline_report_html(report: InspectReport) -> str:
    """Render a self-contained person timeline HTML report."""
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
      --bg: #f6f7f4;
      --ink: #172026;
      --muted: #64707a;
      --line: #d4d9d2;
      --panel: #ffffff;
      --accent: #256f6c;
      --event: #8a5a00;
      --episode: #245f93;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }}
    header {{
      padding: 18px 24px 12px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfa;
    }}
    h1 {{
      margin: 0;
      font-size: 24px;
      line-height: 1.2;
      letter-spacing: 0;
    }}
    nav {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 12px;
      font-size: 13px;
    }}
    nav a {{
      color: var(--accent);
      text-decoration: none;
      border-bottom: 1px solid transparent;
    }}
    nav a[aria-current="page"] {{ color: var(--ink); border-color: var(--ink); }}
    .meta {{
      margin-top: 6px;
      color: var(--muted);
      font-size: 13px;
    }}
    main {{
      display: grid;
      grid-template-columns: 260px minmax(0, 1fr);
      min-height: calc(100vh - 105px);
    }}
    aside {{
      border-right: 1px solid var(--line);
      padding: 18px;
      background: #fbfcfa;
      overflow: auto;
    }}
    .people {{
      display: grid;
      gap: 8px;
    }}
    .person-button {{
      appearance: none;
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      color: var(--ink);
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      gap: 10px;
      padding: 9px 10px;
      text-align: left;
      font: inherit;
      font-size: 13px;
    }}
    .person-button.active {{
      border-color: var(--accent);
      box-shadow: inset 3px 0 0 var(--accent);
    }}
    .count {{
      color: var(--muted);
      white-space: nowrap;
    }}
    .timeline {{
      padding: 18px 24px 32px;
      min-width: 0;
    }}
    .toolbar {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 14px;
      color: var(--muted);
      font-size: 13px;
    }}
    .items {{
      display: grid;
      gap: 10px;
    }}
    .item {{
      border: 1px solid var(--line);
      border-left: 5px solid var(--episode);
      border-radius: 8px;
      background: var(--panel);
      padding: 12px 14px;
    }}
    .item.event {{ border-left-color: var(--event); }}
    .item-head {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
    }}
    h2 {{
      margin: 0;
      font-size: 16px;
      line-height: 1.25;
      letter-spacing: 0;
      overflow-wrap: anywhere;
    }}
    .kind {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .04em;
      white-space: nowrap;
    }}
    .text {{
      margin: 0;
      font-size: 14px;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }}
    dl {{
      display: grid;
      grid-template-columns: 92px 1fr;
      gap: 5px 10px;
      margin: 10px 0 0;
      font-size: 12px;
    }}
    dt {{ color: var(--muted); }}
    dd {{ margin: 0; overflow-wrap: anywhere; }}
    .snippets {{
      margin: 10px 0 0;
      display: grid;
      gap: 6px;
    }}
    .snippet {{
      border-left: 2px solid var(--line);
      padding-left: 8px;
      color: #2f3b43;
      font-size: 13px;
      line-height: 1.4;
    }}
    .empty, .warnings {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      color: var(--muted);
      padding: 12px;
      font-size: 13px;
    }}
    .warnings {{ margin-bottom: 12px; color: #8a3a22; }}
    @media (max-width: 760px) {{
      main {{ grid-template-columns: 1fr; }}
      aside {{ border-right: 0; border-bottom: 1px solid var(--line); }}
      .people {{ grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{_html_escape(report.title)}</h1>
    <div class="meta">Generated {_html_escape(report.generated_at)} - <span id="recordCount">0</span> timeline items</div>
    <nav aria-label="Inspect reports">
      <a href="tailwag-person-timeline.html" aria-current="page">Person Timeline</a>
      <a href="tailwag-affect.html">Affect Scatter</a>
      <a href="tailwag-memory-items.html">Memory Items</a>
    </nav>
  </header>
  <main>
    <aside>
      <div id="people" class="people"></div>
    </aside>
    <section class="timeline" aria-live="polite">
      <div id="warnings"></div>
      <div class="toolbar">
        <strong id="activePerson">All people</strong>
        <span id="filterSummary"></span>
      </div>
      <div id="items" class="items"></div>
    </section>
  </main>
  <script id="report-data" type="application/json">{payload}</script>
  <script>
    const report = JSON.parse(document.getElementById('report-data').textContent);
    const records = report.records || [];
    const peopleNode = document.getElementById('people');
    const itemsNode = document.getElementById('items');
    const activePersonNode = document.getElementById('activePerson');
    document.getElementById('recordCount').textContent = records.length;
    document.getElementById('filterSummary').textContent = Object.entries(report.filters || {{}})
      .filter(([, value]) => value !== null && value !== undefined && value !== '')
      .map(([key, value]) => `${{key}}=${{value}}`)
      .join(' - ');
    const warnings = report.warnings || [];
    if (warnings.length) {{
      document.getElementById('warnings').innerHTML = `<div class="warnings">${{warnings.map(escapeHtml).join('<br>')}}</div>`;
    }}
    renderPeople();
    renderTimeline(selectedPersonFromHash());
    window.addEventListener('hashchange', () => renderTimeline(selectedPersonFromHash()));

    function selectedPersonFromHash() {{
      const params = new URLSearchParams(location.hash.slice(1));
      return params.get('person') || '';
    }}
    function setPerson(personId) {{
      if (personId) {{
        location.hash = `person=${{encodeURIComponent(personId)}}`;
      }} else {{
        history.pushState('', document.title, location.pathname + location.search);
        renderTimeline('');
      }}
    }}
    function personSummaries() {{
      const people = new Map();
      records.forEach((record) => {{
        const id = record.person_id || '';
        if (!id) return;
        const existing = people.get(id) || {{
          person_id: id,
          display_name: record.display_name || id,
          count: 0
        }};
        existing.count += 1;
        people.set(id, existing);
      }});
      return Array.from(people.values()).sort((a, b) => a.display_name.localeCompare(b.display_name));
    }}
    function renderPeople() {{
      const summaries = personSummaries();
      peopleNode.innerHTML = '';
      const allButton = personButton('', 'All people', records.length);
      peopleNode.appendChild(allButton);
      summaries.forEach((person) => {{
        peopleNode.appendChild(personButton(person.person_id, person.display_name, person.count));
      }});
    }}
    function personButton(personId, label, count) {{
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'person-button';
      button.dataset.personId = personId;
      button.innerHTML = `<span>${{escapeHtml(label)}}</span><span class="count">${{count}}</span>`;
      button.addEventListener('click', () => setPerson(personId));
      return button;
    }}
    function renderTimeline(personId) {{
      document.querySelectorAll('.person-button').forEach((button) => {{
        button.classList.toggle('active', button.dataset.personId === personId);
      }});
      const visible = personId ? records.filter((record) => record.person_id === personId) : records;
      const first = visible[0];
      activePersonNode.textContent = personId ? ((first && first.display_name) || personId) : 'All people';
      if (!visible.length) {{
        itemsNode.innerHTML = '<div class="empty">No timeline items matched this selection.</div>';
        return;
      }}
      itemsNode.innerHTML = visible.map(renderItem).join('');
    }}
    function renderItem(record) {{
      const type = record.item_type || '';
      const itemClass = type === 'event' ? 'item event' : 'item';
      const title = record.display_name || record.person_id || 'Unknown person';
      return `
        <article class="${{itemClass}}" id="${{escapeHtml(record.item_id || '')}}">
          <div class="item-head">
            <h2>${{escapeHtml(title)}}</h2>
            <span class="kind">${{escapeHtml(type)}}</span>
          </div>
          <p class="text">${{escapeHtml(record.text || '')}}</p>
          ${{renderSnippets(record.transcript_snippets || [])}}
          <dl>
            <dt>Item</dt><dd>${{escapeHtml(record.item_id || '')}}</dd>
            <dt>Time</dt><dd>${{escapeHtml(formatTimeRange(record.start_time, record.end_time))}}</dd>
            <dt>Place</dt><dd>${{escapeHtml([record.building_code, record.room_id].filter(Boolean).join(' / '))}}</dd>
            <dt>Role</dt><dd>${{escapeHtml(record.role || '')}}</dd>
            <dt>Source</dt><dd>${{escapeHtml(record.source || '')}}</dd>
          </dl>
        </article>
      `;
    }}
    function renderSnippets(snippets) {{
      if (!snippets.length) return '';
      return `<div class="snippets">${{snippets.map((snippet) => `
        <div class="snippet">${{escapeHtml([snippet.timestamp, snippet.speaker].filter(Boolean).join(' '))}}${{snippet.speaker || snippet.timestamp ? ': ' : ''}}${{escapeHtml(snippet.text || '')}}</div>
      `).join('')}}</div>`;
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
      return new Intl.DateTimeFormat('en-US', {{
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit'
      }}).format(date);
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


