from __future__ import annotations

from .html_utils import _html_escape, inspect_command_panel, render_inspect_report_page
from .memory_overview_report import memory_overview_css, memory_overview_script, memory_overview_section
from .reports import InspectReport


def memory_items_report_html(report: InspectReport) -> str:
    """Render a self-contained memory item inspection HTML report."""
    return render_inspect_report_page(
        report,
        current_nav="memory-items",
        count_meta=f"Generated {_html_escape(report.generated_at)} - <span id=\"count\">0</span> memory items",
        page_css=f"""
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
{memory_overview_css().strip()}
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
    .bar {{ grid-column: 1 / -1; height: 5px; }}
    .board {{
      display: grid;
      grid-template-columns: repeat(5, minmax(120px, 1fr));
      gap: 10px;
    }}
    .state {{
      appearance: none;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-soft);
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
      background: var(--panel-soft);
      font-weight: 650;
      white-space: nowrap;
    }}
    tr:last-child td {{ border-bottom: 0; }}
    td.summary-cell {{
      min-width: 280px;
      max-width: 520px;
    }}
    .pill {{ margin: 0 4px 4px 0; }}
    td a {{
      color: var(--accent);
      text-decoration: none;
    }}
    td a:hover {{ text-decoration: underline; }}
    .pill.followup {{ border-color: rgba(244,165,28,.45); color: #875200; }}
    .pill.addressed {{ border-color: rgba(0,115,207,.45); color: var(--accent-3); }}
    .pill.expired, .pill.superseded {{ border-color: rgba(180,35,24,.45); color: var(--danger); }}
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
""",
        body_html=f"""
    <div id="warnings"></div>
    {inspect_command_panel("tailwag inspect memory-items")}
{memory_overview_section().strip()}
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
""",
        page_js=f"""
    const report = inspectReportData();
    const records = inspectReportRecords(report);
    const overviewLinks = (report.metadata && report.metadata.overview_links) || [];
    const distributionKeys = [
      ['kind', 'Kind'],
      ['status', 'Status'],
      ['source', 'Source'],
      ['person', 'Person']
    ];
    const followupStates = ['visible_now', 'not_yet_due', 'expired_active', 'addressed', 'invalid'];
    const clearFilters = document.getElementById('clearFilters');
    inspectToggleEmptyCommand(records);
    clearFilters.addEventListener('click', () => {{
      history.pushState('', document.title, window.location.pathname + window.location.search);
      render();
    }});
    window.addEventListener('hashchange', render);
    inspectRenderWarnings(report);
    render();
    function render() {{
      const filters = hashFilters();
      const visible = applyFilters(records, filters);
      inspectSetCount('count', visible.length);
      document.getElementById('filterSummary').textContent = filterSummary(filters) || inspectFilterText(report.filters);
      clearFilters.disabled = !hasFilters(filters);
      renderSummary(visible, filters);
      renderOverviewSankey();
      renderFollowupBoard(applyFilters(records, filters, new Set(['followup_state'])), filters.followup_state);
      renderTable(visible);
    }}
{memory_overview_script().strip()}
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
          <td data-label="Person"><a href="${{escapeHtml(timelineHref({{ person: record.person_id || '' }}))}}">${{escapeHtml(person)}}</a><br><code>${{escapeHtml(record.person_id || '')}}</code></td>
          <td data-label="Kind">${{filterPill(record.kind || 'unknown', record.kind, 'kind', record.kind || 'unknown')}}<br><code>${{escapeHtml(record.key || '')}}</code></td>
          <td data-label="Status">${{filterPill(displayStatus(record), displayStatus(record), 'status', displayStatus(record))}}${{record.kind === 'followup' ? filterPill(record.followup_state || 'unknown', record.followup_state, 'followup_state', record.followup_state || 'unknown') : ''}}</td>
          <td data-label="Summary" class="summary-cell">${{escapeHtml(record.summary || '')}}<br><span class="meta">${{filterPill(record.source || 'unknown', record.source, 'source', record.source || 'unknown')}}${{record.source_ref ? ' / ' + escapeHtml(record.source_ref) : ''}}</span></td>
          <td data-label="Evidence">${{evidenceHtml(record, supported, addressed, supersededBy, supersedes)}}</td>
          <td data-label="Timing">${{timeHtml(record)}}</td>
          <td data-label="ID"><a href="#${{hashWith({{ memory: record.memory_id || '' }})}}"><code>${{escapeHtml(record.memory_id || '')}}</code></a></td>
        </tr>
      `;
    }}
    function evidenceHtml(record, supported, addressed, supersededBy, supersedes) {{
      const lines = [];
      if (supported.length) lines.push(`Supported by ${{supported.map((itemId) => timelineItemLink(itemId, record.person_id)).join(', ')}}`);
      if (addressed.length) lines.push(`Addressed by ${{addressed.map((entry) => timelineItemLink(entry.episode_id, record.person_id)).join(', ')}}`);
      if (supersededBy.length) lines.push(`Superseded by ${{supersededBy.map(memoryLink).join(', ')}}`);
      if (supersedes.length) lines.push(`Supersedes ${{supersedes.map(memoryLink).join(', ')}}`);
      return lines.length ? lines.join('<br>') : '<span class="meta">No linked evidence</span>';
    }}
    function timeHtml(record) {{
      const parts = [];
      if (record.observed_at) parts.push(`Observed ${{escapeHtml(formatDateTime(record.observed_at))}}`);
      if (record.due_at) parts.push(`Due ${{escapeHtml(formatDateTime(record.due_at))}}`);
      if (record.expires_at) parts.push(`Expires ${{escapeHtml(formatDateTime(record.expires_at))}}`);
      if (record.updated_at) parts.push(`Updated ${{escapeHtml(formatDateTime(record.updated_at))}}`);
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
        if (!omitted.has('memory') && filters.memory && record.memory_id !== filters.memory) return false;
        if (!omitted.has('episode') && filters.episode && !recordMatchesEpisode(record, filters.episode)) return false;
        if (!omitted.has('person') && filters.person && record.person_id !== filters.person) return false;
        if (!omitted.has('kind') && filters.kind && String(record.kind || 'unknown') !== filters.kind) return false;
        if (!omitted.has('status') && filters.status && displayStatus(record) !== filters.status) return false;
        if (!omitted.has('source') && filters.source && String(record.source || 'unknown') !== filters.source) return false;
        if (!omitted.has('validity_bucket') && filters.validity_bucket && validityBucket(record) !== filters.validity_bucket) return false;
        if (!omitted.has('followup_state') && filters.followup_state) {{
          return record.kind === 'followup' && String(record.followup_state || 'unknown') === filters.followup_state;
        }}
        return true;
      }});
    }}
    function recordMatchesEpisode(record, episodeId) {{
      const supported = record.supported_episode_ids || [];
      const addressed = record.addressed_by || [];
      return supported.includes(episodeId)
        || addressed.some((entry) => entry && entry.episode_id === episodeId)
        || String(record.source_ref || '') === episodeId;
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
    function validityBucket(record) {{
      if (record.kind !== 'followup') return 'not_followup';
      const start = timeValue(record.due_at || record.observed_at || record.created_at || record.updated_at);
      const end = timeValue(record.expires_at);
      if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return 'invalid';
      const days = (end - start) / 86400000;
      if (days < 1) return 'under_1_day';
      if (days <= 3) return '1_to_3_days';
      if (days <= 7) return '4_to_7_days';
      if (days <= 14) return '8_to_14_days';
      if (days <= 30) return '15_to_30_days';
      return 'over_30_days';
    }}
    function timeValue(value) {{
      const date = new Date(value || '');
      return date.getTime();
    }}
    function hashFilters() {{
      const hash = String(window.location.hash || '').replace(/^#/, '');
      const params = new URLSearchParams(hash);
      return {{
        memory: params.get('memory') || '',
        episode: params.get('episode') || '',
        person: params.get('person') || '',
        kind: params.get('kind') || '',
        status: params.get('status') || '',
        source: params.get('source') || '',
        followup_state: params.get('followup_state') || '',
        validity_bucket: params.get('validity_bucket') || ''
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
      if (merged.memory) params.set('memory', merged.memory);
      if (merged.episode) params.set('episode', merged.episode);
      if (merged.kind) params.set('kind', merged.kind);
      if (merged.status) params.set('status', merged.status);
      if (merged.source) params.set('source', merged.source);
      if (merged.followup_state) params.set('followup_state', merged.followup_state);
      if (merged.validity_bucket) params.set('validity_bucket', merged.validity_bucket);
      return params.toString();
    }}
    function filterSummary(filters) {{
      const parts = [];
      if (filters.memory) parts.push(`memory=${{filters.memory}}`);
      if (filters.episode) parts.push(`episode=${{filters.episode}}`);
      if (filters.person) parts.push(`person=${{filters.person}}`);
      if (filters.kind) parts.push(`kind=${{filters.kind}}`);
      if (filters.status) parts.push(`status=${{filters.status}}`);
      if (filters.source) parts.push(`source=${{filters.source}}`);
      if (filters.followup_state) parts.push(`followup_state=${{filters.followup_state}}`);
      if (filters.validity_bucket) parts.push(`validity_bucket=${{filters.validity_bucket}}`);
      return parts.join(' - ');
    }}
    function hasFilters(filters) {{
      return Boolean(filters.memory || filters.episode || filters.person || filters.kind || filters.status || filters.source || filters.followup_state || filters.validity_bucket);
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
    function memoryLink(memoryId) {{
      return `<a href="#${{hashWith({{ memory: memoryId || '' }})}}">${{code(memoryId)}}</a>`;
    }}
    function timelineItemLink(itemId, personId) {{
      return `<a href="${{escapeHtml(timelineHref({{ person: personId || '', item: itemId || '' }}))}}">${{code(itemId)}}</a>`;
    }}
    function timelineHref(filters) {{
      return inspectFilters.href('tailwag-person-timeline.html', filters || {{}});
    }}
""",
    )
