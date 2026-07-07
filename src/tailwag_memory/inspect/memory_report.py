from __future__ import annotations

from dataclasses import asdict

from .html_utils import _html_escape, _safe_json, inspect_nav
from .reports import InspectReport


def memory_items_report_html(report: InspectReport) -> str:
    """Render a self-contained memory item inspection HTML report."""

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
      --bg: #f6f7f2;
      --ink: #20242a;
      --muted: #66707a;
      --line: #d7dccf;
      --panel: #ffffff;
      --accent: #176b5f;
      --accent-2: #a8551c;
      --accent-3: #3c6f9f;
      --danger: #a33a35;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }}
    header {{
      padding: 20px 28px 16px;
      border-bottom: 1px solid var(--line);
      background: #fffef9;
      position: sticky;
      top: 0;
      z-index: 20;
    }}
    .topline {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 18px;
      flex-wrap: wrap;
    }}
    h1 {{
      margin: 0;
      font-size: 24px;
      line-height: 1.2;
      letter-spacing: 0;
    }}
    nav {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      font-size: 13px;
      margin-bottom: 12px;
    }}
    nav a {{
      color: var(--accent);
      text-decoration: none;
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 6px;
      padding: 6px 9px;
    }}
    .meta {{
      margin-top: 7px;
      color: var(--muted);
      font-size: 13px;
    }}
    main {{
      padding: 20px 28px 30px;
      display: grid;
      gap: 20px;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(4, minmax(160px, 1fr));
      gap: 12px;
    }}
    .panel {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 13px;
      min-width: 0;
    }}
    h2 {{
      margin: 0 0 9px;
      font-size: 16px;
      line-height: 1.25;
      letter-spacing: 0;
    }}
    .dist-list {{
      display: grid;
      gap: 7px;
      margin: 0;
    }}
    .dist-row {{
      appearance: none;
      border: 0;
      background: transparent;
      cursor: pointer;
      font: inherit;
      padding: 0;
      width: 100%;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      color: var(--muted);
      font-size: 13px;
      text-align: left;
    }}
    .dist-row.active strong {{ color: var(--accent); }}
    .dist-row strong {{
      color: var(--ink);
      font-weight: 650;
      overflow-wrap: anywhere;
    }}
    .dist-row a {{
      color: var(--accent);
      text-decoration: none;
    }}
    .bar {{
      grid-column: 1 / -1;
      height: 5px;
      border-radius: 999px;
      background: #e5e9df;
      overflow: hidden;
    }}
    .bar span {{
      display: block;
      height: 100%;
      background: var(--accent);
    }}
    .board {{
      display: grid;
      grid-template-columns: repeat(5, minmax(120px, 1fr));
      gap: 10px;
    }}
    .state {{
      appearance: none;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcf8;
      color: var(--ink);
      cursor: pointer;
      font: inherit;
      padding: 10px;
      min-height: 72px;
      text-align: left;
      width: 100%;
    }}
    .state.active {{
      border-color: var(--accent);
      box-shadow: inset 0 -3px 0 var(--accent);
    }}
    .state strong {{
      display: block;
      font-size: 22px;
      line-height: 1;
      margin-top: 6px;
    }}
    .controls {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 13px;
    }}
    .controls button {{
      appearance: none;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      color: var(--ink);
      font: inherit;
      padding: 6px 10px;
      cursor: pointer;
    }}
    .controls button:disabled {{
      color: var(--muted);
      cursor: default;
      opacity: .55;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    th, td {{
      text-align: left;
      vertical-align: top;
      border-bottom: 1px solid var(--line);
      padding: 10px;
      font-size: 13px;
      line-height: 1.4;
    }}
    th {{
      color: var(--muted);
      background: #fbfcf8;
      font-weight: 650;
      white-space: nowrap;
    }}
    tr:last-child td {{ border-bottom: 0; }}
    td.summary-cell {{
      min-width: 280px;
      max-width: 520px;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      border: 1px solid var(--line);
      padding: 2px 7px;
      margin: 0 4px 4px 0;
      background: #fbfcf8;
      color: var(--ink);
      white-space: nowrap;
      text-decoration: none;
      font: inherit;
    }}
    .pill[href] {{ cursor: pointer; }}
    .pill.followup {{ border-color: rgba(168,85,28,.45); color: var(--accent-2); }}
    .pill.addressed {{ border-color: rgba(60,111,159,.45); color: var(--accent-3); }}
    .pill.expired, .pill.superseded {{ border-color: rgba(163,58,53,.45); color: var(--danger); }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    .empty, .warnings {{
      color: var(--muted);
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 12px;
      font-size: 13px;
    }}
    .warnings {{ color: var(--danger); }}
    @media (max-width: 1100px) {{
      .summary {{ grid-template-columns: repeat(2, minmax(160px, 1fr)); }}
      .board {{ grid-template-columns: repeat(2, minmax(120px, 1fr)); }}
      table, thead, tbody, th, td, tr {{ display: block; }}
      thead {{ display: none; }}
      tr {{ border-bottom: 1px solid var(--line); }}
      td {{
        border-bottom: 0;
        display: grid;
        grid-template-columns: 96px minmax(0, 1fr);
        gap: 10px;
      }}
      td::before {{
        content: attr(data-label);
        color: var(--muted);
        font-weight: 650;
      }}
    }}
    @media (max-width: 620px) {{
      header, main {{ padding-left: 16px; padding-right: 16px; }}
      .summary, .board {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    {inspect_nav("memory-items")}
    <div class="topline">
      <div>
        <h1>{_html_escape(report.title)}</h1>
        <div class="meta">Generated {_html_escape(report.generated_at)} - <span id="count">0</span> memory items</div>
      </div>
    </div>
  </header>
  <main>
    <div id="warnings"></div>
    <section class="summary" id="summary" aria-label="Memory item distributions"></section>
    <section class="panel">
      <h2>Follow-Up State</h2>
      <div class="board" id="followupBoard"></div>
    </section>
    <section class="controls">
      <span id="filterSummary"></span>
      <button type="button" id="clearFilters">Clear Filters</button>
    </section>
    <section id="tableWrap"></section>
  </main>
  <script id="report-data" type="application/json">{payload}</script>
  <script>
    const report = JSON.parse(document.getElementById('report-data').textContent);
    const records = report.records || [];
    const distributionKeys = [
      ['kind', 'Kind'],
      ['status', 'Status'],
      ['source', 'Source'],
      ['person', 'Person']
    ];
    const followupStates = ['visible_now', 'not_yet_due', 'expired_active', 'addressed', 'invalid'];
    const clearFilters = document.getElementById('clearFilters');
    clearFilters.addEventListener('click', () => {{
      history.pushState('', document.title, window.location.pathname + window.location.search);
      render();
    }});
    window.addEventListener('hashchange', render);
    const warnings = report.warnings || [];
    if (warnings.length) {{
      document.getElementById('warnings').innerHTML = `<div class="warnings">${{warnings.map(escapeHtml).join('<br>')}}</div>`;
    }}
    render();
    function render() {{
      const filters = hashFilters();
      const visible = applyFilters(records, filters);
      document.getElementById('count').textContent = visible.length;
      document.getElementById('filterSummary').textContent = filterSummary(filters) || filterText(report.filters || {{}});
      clearFilters.disabled = !hasFilters(filters);
      renderSummary(visible, filters);
      renderFollowupBoard(applyFilters(records, filters, new Set(['followup_state'])), filters.followup_state);
      renderTable(visible);
    }}
    function renderSummary(visible, filters) {{
      const summary = document.getElementById('summary');
      summary.innerHTML = distributionKeys.map(([key, label]) => {{
        const rows = key === 'person'
          ? personDistributionRows(visible, filters.person)
          : distributionRows(countBy(visible, key), key, filters[key] || '');
        return `<section class="panel"><h2>${{label}}</h2><div class="dist-list">${{rows.join('') || '<div class="empty">No records</div>'}}</div></section>`;
      }}).join('');
      document.querySelectorAll('[data-filter-key][data-filter-value]').forEach((button) => {{
        button.addEventListener('click', () => {{
          const key = button.dataset.filterKey || '';
          const value = button.dataset.filterValue || '';
          setHashFilter(key, hashFilters()[key] === value ? '' : value);
        }});
      }});
    }}
    function renderFollowupBoard(visible, activeState) {{
      const distribution = countBy(visible.filter((record) => record.kind === 'followup'), 'followup_state');
      document.getElementById('followupBoard').innerHTML = followupStates.map((state) => `
        <button type="button" class="state ${{state === activeState ? 'active' : ''}}" data-followup-state="${{escapeAttr(state)}}">
          <span>${{titleCase(state)}}</span>
          <strong>${{distribution[state] || 0}}</strong>
        </button>
      `).join('');
      document.querySelectorAll('[data-followup-state]').forEach((button) => {{
        button.addEventListener('click', () => setHashFilter('followup_state', button.dataset.followupState === activeState ? '' : button.dataset.followupState));
      }});
    }}
    function renderTable(visible) {{
      const tableWrap = document.getElementById('tableWrap');
      if (!visible.length) {{
        tableWrap.innerHTML = '<div class="empty">No memory items matched this view.</div>';
        return;
      }}
      tableWrap.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>Person</th>
              <th>Kind</th>
              <th>Status</th>
              <th>Summary</th>
              <th>Evidence</th>
              <th>Timing</th>
              <th>ID</th>
            </tr>
          </thead>
          <tbody>
            ${{visible.map(rowHtml).join('')}}
          </tbody>
        </table>
      `;
    }}
    function rowHtml(record) {{
      const person = record.display_name || record.person_id || '';
      const supported = record.supported_episode_ids || [];
      const addressed = record.addressed_by || [];
      const supersededBy = record.superseded_by_memory_ids || [];
      const supersedes = record.supersedes_memory_ids || [];
      return `
        <tr id="${{escapeAttr(record.memory_id || '')}}">
          <td data-label="Person"><a href="#${{hashWith({{ person: record.person_id || '' }})}}">${{escapeHtml(person)}}</a><br><code>${{escapeHtml(record.person_id || '')}}</code></td>
          <td data-label="Kind">${{filterPill(record.kind || 'unknown', record.kind, 'kind', record.kind || 'unknown')}}<br><code>${{escapeHtml(record.key || '')}}</code></td>
          <td data-label="Status">${{filterPill(displayStatus(record), displayStatus(record), 'status', displayStatus(record))}}${{record.kind === 'followup' ? filterPill(record.followup_state || 'unknown', record.followup_state, 'followup_state', record.followup_state || 'unknown') : ''}}</td>
          <td data-label="Summary" class="summary-cell">${{escapeHtml(record.summary || '')}}<br><span class="meta">${{filterPill(record.source || 'unknown', record.source, 'source', record.source || 'unknown')}}${{record.source_ref ? ' / ' + escapeHtml(record.source_ref) : ''}}</span></td>
          <td data-label="Evidence">${{evidenceHtml(supported, addressed, supersededBy, supersedes)}}</td>
          <td data-label="Timing">${{timeHtml(record)}}</td>
          <td data-label="ID"><code>${{escapeHtml(record.memory_id || '')}}</code></td>
        </tr>
      `;
    }}
    function evidenceHtml(supported, addressed, supersededBy, supersedes) {{
      const lines = [];
      if (supported.length) lines.push(`Supported by ${{supported.map(code).join(', ')}}`);
      if (addressed.length) lines.push(`Addressed by ${{addressed.map((entry) => code(entry.episode_id)).join(', ')}}`);
      if (supersededBy.length) lines.push(`Superseded by ${{supersededBy.map(code).join(', ')}}`);
      if (supersedes.length) lines.push(`Supersedes ${{supersedes.map(code).join(', ')}}`);
      return lines.length ? lines.join('<br>') : '<span class="meta">No linked evidence</span>';
    }}
    function timeHtml(record) {{
      const parts = [];
      if (record.observed_at) parts.push(`Observed ${{escapeHtml(formatDate(record.observed_at))}}`);
      if (record.due_at) parts.push(`Due ${{escapeHtml(formatDate(record.due_at))}}`);
      if (record.expires_at) parts.push(`Expires ${{escapeHtml(formatDate(record.expires_at))}}`);
      if (record.updated_at) parts.push(`Updated ${{escapeHtml(formatDate(record.updated_at))}}`);
      return parts.length ? parts.join('<br>') : '<span class="meta">No timing</span>';
    }}
    function distributionRows(distribution, key, activeValue) {{
      const entries = Object.entries(distribution).sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]));
      const max = Math.max(1, ...entries.map(([, count]) => count));
      return entries.slice(0, 8).map(([value, count]) => {{
        const label = escapeHtml(value);
        const active = value === activeValue ? ' active' : '';
        return `<button type="button" class="dist-row${{active}}" data-filter-key="${{escapeHtml(key)}}" data-filter-value="${{escapeHtml(value)}}"><strong>${{label}}</strong><span>${{count}}</span><div class="bar"><span style="width:${{Math.round(count / max * 100)}}%"></span></div></button>`;
      }});
    }}
    function personDistributionRows(values, activePerson) {{
      const people = new Map();
      values.forEach((record) => {{
        const id = String(record.person_id || 'unknown');
        const existing = people.get(id) || {{
          person_id: id,
          label: record.display_name || id,
          count: 0
        }};
        if (!existing.label || existing.label === existing.person_id) existing.label = record.display_name || id;
        existing.count += 1;
        people.set(id, existing);
      }});
      const entries = Array.from(people.values()).sort((left, right) => right.count - left.count || left.label.localeCompare(right.label));
      const max = Math.max(1, ...entries.map((entry) => entry.count));
      return entries.slice(0, 8).map((entry) => {{
        const active = entry.person_id === activePerson ? ' active' : '';
        return `<button type="button" class="dist-row${{active}}" data-filter-key="person" data-filter-value="${{escapeHtml(entry.person_id)}}"><strong>${{escapeHtml(entry.label)}}</strong><span>${{entry.count}}</span><div class="bar"><span style="width:${{Math.round(entry.count / max * 100)}}%"></span></div></button>`;
      }});
    }}
    function applyFilters(values, filters, omitted = new Set()) {{
      return values.filter((record) => {{
        if (!omitted.has('person') && filters.person && record.person_id !== filters.person) return false;
        if (!omitted.has('kind') && filters.kind && String(record.kind || 'unknown') !== filters.kind) return false;
        if (!omitted.has('status') && filters.status && displayStatus(record) !== filters.status) return false;
        if (!omitted.has('source') && filters.source && String(record.source || 'unknown') !== filters.source) return false;
        if (!omitted.has('followup_state') && filters.followup_state) {{
          return record.kind === 'followup' && String(record.followup_state || 'unknown') === filters.followup_state;
        }}
        return true;
      }});
    }}
    function countBy(values, key) {{
      return values.reduce((counts, record) => {{
        const value = key === 'status' ? displayStatus(record) : String(record[key] || 'unknown');
        counts[value] = (counts[value] || 0) + 1;
        return counts;
      }}, {{}});
    }}
    function displayStatus(record) {{
      const supersededBy = record.superseded_by_memory_ids || [];
      if (record.status === 'superseded' || supersededBy.length) return 'superseded';
      return record.status || 'unknown';
    }}
    function hashFilters() {{
      const hash = String(window.location.hash || '').replace(/^#/, '');
      const params = new URLSearchParams(hash);
      return {{
        person: params.get('person') || '',
        kind: params.get('kind') || '',
        status: params.get('status') || '',
        source: params.get('source') || '',
        followup_state: params.get('followup_state') || ''
      }};
    }}
    function setHashFilter(key, value) {{
      const next = hashFilters();
      next[key] = value || '';
      const hash = hashWith(next);
      if (hash) {{
        location.hash = hash;
      }} else {{
        history.pushState('', document.title, window.location.pathname + window.location.search);
        render();
      }}
    }}
    function hashWith(next) {{
      const current = hashFilters();
      const merged = {{ ...current, ...next }};
      const params = new URLSearchParams();
      if (merged.person) params.set('person', merged.person);
      if (merged.kind) params.set('kind', merged.kind);
      if (merged.status) params.set('status', merged.status);
      if (merged.source) params.set('source', merged.source);
      if (merged.followup_state) params.set('followup_state', merged.followup_state);
      return params.toString();
    }}
    function filterSummary(filters) {{
      const parts = [];
      if (filters.person) parts.push(`person=${{filters.person}}`);
      if (filters.kind) parts.push(`kind=${{filters.kind}}`);
      if (filters.status) parts.push(`status=${{filters.status}}`);
      if (filters.source) parts.push(`source=${{filters.source}}`);
      if (filters.followup_state) parts.push(`followup_state=${{filters.followup_state}}`);
      return parts.join(' - ');
    }}
    function hasFilters(filters) {{
      return Boolean(filters.person || filters.kind || filters.status || filters.source || filters.followup_state);
    }}
    function filterText(filters) {{
      return Object.entries(filters)
        .filter(([, value]) => value !== null && value !== undefined && value !== '')
        .map(([key, value]) => `${{key}}=${{value}}`)
        .join(' - ');
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
    function pill(value, className) {{
      return `<span class="pill ${{escapeAttr(className || '')}}">${{escapeHtml(value || '')}}</span>`;
    }}
    function filterPill(value, className, key, filterValue) {{
      return `<a class="pill ${{escapeAttr(className || '')}}" href="#${{hashWith({{ [key]: filterValue || '' }})}}">${{escapeHtml(value || '')}}</a>`;
    }}
    function code(value) {{
      return `<code>${{escapeHtml(value || '')}}</code>`;
    }}
    function titleCase(value) {{
      return String(value || '').replace(/_/g, ' ').replace(/\\b\\w/g, (char) => char.toUpperCase());
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
