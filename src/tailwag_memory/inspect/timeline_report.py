from __future__ import annotations

from dataclasses import asdict

from .html_utils import _html_escape, _safe_json, inspect_nav
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
      background: #fbfcfa;
      position: sticky;
      top: 0;
      z-index: 20;
    }}
    h1 {{
      margin: 0;
      font-size: 24px;
      line-height: 1.2;
      letter-spacing: 0;
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
    .meta {{
      margin-top: 6px;
      color: var(--muted);
      font-size: 13px;
    }}
    main {{
      display: grid;
      grid-template-columns: 260px minmax(0, 1fr);
      min-height: calc(100vh - 112px);
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
      overflow: visible;
    }}
    .toolbar {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 14px;
      color: var(--muted);
      font-size: 13px;
      min-width: 780px;
    }}
    .timeline-canvas {{
      min-width: 780px;
      display: grid;
      gap: 14px;
    }}
    .timeline-axis {{
      position: relative;
      height: 38px;
      margin-left: 170px;
      border-bottom: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
    }}
    .axis-tick {{
      position: absolute;
      bottom: 0;
      transform: translateX(-50%);
      display: grid;
      gap: 4px;
      justify-items: center;
      white-space: nowrap;
    }}
    .axis-tick::before {{
      content: "";
      width: 1px;
      height: 8px;
      background: var(--line);
      display: block;
    }}
    .person-lane {{
      display: grid;
      grid-template-columns: 150px minmax(620px, 1fr);
      gap: 18px;
      align-items: stretch;
    }}
    .lane-label {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 10px;
      font-size: 13px;
      min-width: 0;
    }}
    .lane-label strong {{
      display: block;
      overflow-wrap: anywhere;
    }}
    .lane-label span {{
      color: var(--muted);
      display: block;
      margin-top: 4px;
    }}
    .timeline-lane {{
      position: relative;
      min-height: 132px;
      border-top: 1px solid var(--line);
    }}
    .timeline-lane::before {{
      content: "";
      position: absolute;
      left: 0;
      right: 0;
      top: 38px;
      border-top: 1px dashed #c3cbc1;
    }}
    .timeline-marker {{
      position: absolute;
      transform: translateX(-50%);
      z-index: 1;
      width: min(230px, 28vw);
      min-width: 160px;
      border: 1px solid var(--line);
      border-top: 4px solid var(--episode);
      border-radius: 8px;
      background: var(--panel);
      color: var(--ink);
      padding: 8px 9px;
      font-size: 12px;
      line-height: 1.35;
      box-shadow: 0 5px 16px rgba(31, 41, 51, .08);
    }}
    .timeline-marker.active {{
      z-index: 30;
      box-shadow: 0 10px 28px rgba(31, 41, 51, .22);
    }}
    .timeline-marker.active .marker-text {{
      max-height: none;
    }}
    .timeline-marker.event {{ border-top-color: var(--event); }}
    .timeline-marker.with-memory {{
      border-color: rgba(194,65,12,.55);
      box-shadow: 0 5px 16px rgba(194, 65, 12, .13);
    }}
    .marker-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      margin-bottom: 5px;
    }}
    .kind {{
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: .04em;
      font-size: 11px;
      white-space: nowrap;
    }}
    .memory-marker {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      color: var(--muted);
      margin-top: 6px;
    }}
    .memory-marker::before {{
      content: "";
      width: 8px;
      height: 8px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #eef1ed;
    }}
    .memory-marker.linked {{
      color: var(--memory);
    }}
    .memory-marker.linked::before {{
      background: var(--memory);
      border-color: var(--memory);
    }}
    .marker-text {{
      margin: 0;
      overflow-wrap: anywhere;
      max-height: 4.1em;
      overflow: hidden;
    }}
    dl {{
      display: grid;
      grid-template-columns: 58px 1fr;
      gap: 4px 8px;
      margin: 8px 0 0;
      font-size: 12px;
    }}
    dt {{ color: var(--muted); }}
    dd {{ margin: 0; overflow-wrap: anywhere; }}
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
      .timeline {{ padding-left: 16px; padding-right: 16px; }}
      .timeline-marker {{ width: 190px; }}
    }}
  </style>
</head>
<body>
  <header>
    {inspect_nav("person-timeline")}
    <h1>{_html_escape(report.title)}</h1>
    <div class="meta">Generated {_html_escape(report.generated_at)} - <span id="recordCount">0</span> timeline items</div>
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
      <div id="items" class="timeline-canvas"></div>
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
    renderTimeline(selectedPeopleFromHash());
    window.addEventListener('hashchange', () => renderTimeline(selectedPeopleFromHash()));

    function selectedPeopleFromHash() {{
      const params = new URLSearchParams(location.hash.slice(1));
      const ids = params.getAll('person').flatMap((value) => String(value || '').split(','));
      return [...new Set(ids.map((value) => value.trim()).filter(Boolean))];
    }}
    function setPeople(personIds) {{
      const selected = [...new Set((personIds || []).filter(Boolean))];
      if (selected.length) {{
        const params = new URLSearchParams();
        selected.forEach((personId) => params.append('person', personId));
        location.hash = params.toString();
      }} else {{
        history.pushState('', document.title, location.pathname + location.search);
        renderTimeline([]);
      }}
    }}
    function togglePerson(personId) {{
      if (!personId) {{
        setPeople([]);
        return;
      }}
      const selected = new Set(selectedPeopleFromHash());
      if (selected.has(personId)) {{
        selected.delete(personId);
      }} else {{
        selected.add(personId);
      }}
      setPeople([...selected]);
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
        if (!existing.display_name || existing.display_name === existing.person_id) existing.display_name = record.display_name || id;
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
      button.setAttribute('aria-pressed', 'false');
      button.innerHTML = `<span>${{escapeHtml(label)}}</span><span class="count">${{count}}</span>`;
      button.addEventListener('click', () => togglePerson(personId));
      return button;
    }}
    function renderTimeline(personIds) {{
      const selected = new Set(personIds || []);
      document.querySelectorAll('.person-button').forEach((button) => {{
        const active = button.dataset.personId ? selected.has(button.dataset.personId) : selected.size === 0;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
      }});
      const visible = selected.size ? records.filter((record) => selected.has(record.person_id || '')) : records;
      document.getElementById('recordCount').textContent = visible.length;
      activePersonNode.textContent = activePeopleLabel([...selected], visible);
      if (!visible.length) {{
        itemsNode.innerHTML = '<div class="empty">No timeline items matched this selection.</div>';
        return;
      }}
      itemsNode.innerHTML = renderLanes(visible);
    }}
    function activePeopleLabel(personIds, visible) {{
      if (!personIds.length) return 'All people';
      if (personIds.length === 1) {{
        const first = visible[0];
        return (first && first.display_name) || personIds[0];
      }}
      return `${{personIds.length}} people selected`;
    }}
    function renderLanes(visible) {{
      const domain = timeDomain(visible);
      return `${{renderAxis(domain)}}${{personLaneGroups(visible).map((group) => renderLane(group, domain)).join('')}}`;
    }}
    function personLaneGroups(visible) {{
      const groups = new Map();
      visible.forEach((record) => {{
        const id = record.person_id || 'unknown';
        const group = groups.get(id) || {{
          person_id: id,
          display_name: record.display_name || id,
          records: []
        }};
        if (!group.display_name || group.display_name === group.person_id) group.display_name = record.display_name || id;
        group.records.push(record);
        groups.set(id, group);
      }});
      return Array.from(groups.values()).sort((a, b) => a.display_name.localeCompare(b.display_name));
    }}
    function renderAxis(domain) {{
      const ticks = axisTicks(domain);
      return `<div class="timeline-axis">${{ticks.map((tick) => `
        <span class="axis-tick" style="left:${{timePercent(tick.value, domain)}}%">${{escapeHtml(formatDate(tick.value))}}</span>
      `).join('')}}</div>`;
    }}
    function renderLane(group, domain) {{
      const sorted = [...group.records].sort((left, right) => timeValue(left.start_time) - timeValue(right.start_time));
      return `
        <section class="person-lane" data-person-id="${{escapeAttr(group.person_id)}}">
          <div class="lane-label">
            <strong>${{escapeHtml(group.display_name)}}</strong>
            <span>${{group.records.length}} item${{group.records.length === 1 ? '' : 's'}}</span>
          </div>
          <div class="timeline-lane">
            ${{sorted.map((record) => renderMarker(record, domain)).join('')}}
          </div>
        </section>
      `;
    }}
    function renderMarker(record, domain) {{
      const type = record.item_type || '';
      const memoryClass = hasLinkedMemory(record) ? 'with-memory' : '';
      const left = timePercent(timeValue(record.start_time), domain);
      const memoryLabel = hasLinkedMemory(record) ? `Linked memories ${{linkedMemoryCount(record)}}` : 'No linked memory';
      return `
        <article class="timeline-marker ${{escapeAttr(type)}} ${{memoryClass}}" id="${{escapeAttr(record.item_id || '')}}" tabindex="0" onclick="bringMarkerToFront(this)" onfocus="bringMarkerToFront(this)" style="left:${{left}}%; top:16px">
          <div class="marker-head">
            <strong>${{escapeHtml(formatDate(record.start_time))}}</strong>
            <span class="kind">${{escapeHtml(type)}}</span>
          </div>
          <p class="marker-text">${{escapeHtml(record.text || '')}}</p>
          <span class="memory-marker ${{hasLinkedMemory(record) ? 'linked' : ''}}">${{escapeHtml(memoryLabel)}}</span>
          <dl>
            <dt>Item</dt><dd>${{escapeHtml(record.item_id || '')}}</dd>
            <dt>Place</dt><dd>${{escapeHtml([record.building_code, record.room_id].filter(Boolean).join(' / '))}}</dd>
            <dt>Role</dt><dd>${{escapeHtml(record.role || '')}}</dd>
            <dt>Source</dt><dd>${{escapeHtml(record.source || '')}}</dd>
          </dl>
        </article>
      `;
    }}
    function bringMarkerToFront(marker) {{
      document.querySelectorAll('.timeline-marker.active').forEach((node) => node.classList.remove('active'));
      marker.classList.add('active');
    }}
    function timeDomain(values) {{
      const times = values.map((record) => timeValue(record.start_time)).filter((value) => Number.isFinite(value));
      if (!times.length) {{
        const now = Date.now();
        return {{ min: now - 1, max: now + 1 }};
      }}
      let min = Math.min(...times);
      let max = Math.max(...times);
      if (min === max) {{
        min -= 3600000;
        max += 3600000;
      }}
      const padding = Math.max(1, (max - min) * 0.04);
      return {{ min: min - padding, max: max + padding }};
    }}
    function axisTicks(domain) {{
      const ticks = [];
      for (let index = 0; index < 5; index += 1) {{
        ticks.push({{ value: domain.min + ((domain.max - domain.min) * index / 4) }});
      }}
      return ticks;
    }}
    function timePercent(value, domain) {{
      if (!Number.isFinite(value)) return 0;
      return Math.max(0, Math.min(100, ((value - domain.min) / (domain.max - domain.min)) * 100));
    }}
    function timeValue(value) {{
      const date = new Date(value || '');
      return date.getTime();
    }}
    function hasLinkedMemory(record) {{
      return linkedMemoryCount(record) > 0 || Boolean(record.has_memory_items);
    }}
    function linkedMemoryCount(record) {{
      const count = Number(record.memory_item_count || 0);
      return Number.isFinite(count) ? Math.max(0, count) : 0;
    }}
    function formatDate(value) {{
      if (!value) return '';
      const date = value instanceof Date ? value : new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      return new Intl.DateTimeFormat('en-US', {{
        month: 'short',
        day: 'numeric',
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
    function escapeAttr(value) {{
      return String(value || '').replace(/[^a-zA-Z0-9_-]/g, '-');
    }}
  </script>
</body>
</html>
"""
