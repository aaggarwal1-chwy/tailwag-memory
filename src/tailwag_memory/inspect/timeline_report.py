from __future__ import annotations

from .html_utils import _html_escape, inspect_command_panel, render_inspect_report_page
from .models import InspectReport


def person_timeline_report_html(report: InspectReport) -> str:
    """Render a self-contained person timeline HTML report."""
    return render_inspect_report_page(
        report,
        current_nav="person-timeline",
        count_meta=f"Generated {_html_escape(report.generated_at)} - <span id=\"recordCount\">0</span> timeline items",
        page_css=f"""
    :root {{
      --event: #875200;
      --memory: #f4a51c;
    }}
    body {{
      height: 100vh;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }}
    header {{
      flex: 0 0 auto;
    }}
    main {{
      flex: 1 1 auto;
      display: grid;
      grid-template-columns: 260px minmax(0, 1fr);
      min-height: 0;
      overflow: hidden;
    }}
    aside {{
      position: sticky;
      top: 0;
      align-self: start;
      height: 100%;
      border-right: 1px solid var(--line);
      padding: 18px;
      background: var(--panel-soft);
      overflow-y: auto;
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
      min-height: 0;
      overflow: auto;
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
    .lane-label a, .timeline-marker a {{
      color: var(--accent);
      text-decoration: none;
    }}
    .lane-label a:hover, .timeline-marker a:hover {{ text-decoration: underline; }}
    .lane-label span {{
      color: var(--muted);
      display: block;
      margin-top: 4px;
    }}
    .timeline-lane {{
      position: relative;
      min-height: 220px;
      border-top: 1px solid var(--line);
    }}
    .timeline-lane::before {{
      content: "";
      position: absolute;
      left: 0;
      right: 0;
      top: 38px;
      border-top: 1px dashed var(--line);
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
      box-shadow: 0 5px 16px rgba(7, 53, 124, .08);
    }}
    .timeline-marker.active {{
      z-index: 30;
      box-shadow: 0 10px 28px rgba(7, 53, 124, .22);
    }}
    .timeline-marker.active .marker-text {{
      max-height: none;
    }}
    .timeline-marker.event {{ border-top-color: var(--event); }}
    .timeline-marker.with-memory {{
      border-color: rgba(244,165,28,.65);
      box-shadow: 0 5px 16px rgba(244, 165, 28, .16);
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
      text-decoration: none;
    }}
    .memory-marker::before {{
      content: "";
      width: 8px;
      height: 8px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: var(--panel-soft);
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
    .warnings {{ margin-bottom: 12px; color: var(--danger); }}
    @media (max-width: 760px) {{
      body {{
        height: auto;
        overflow: auto;
        display: block;
      }}
      main {{
        display: block;
        min-height: 0;
        overflow: visible;
      }}
      aside {{
        position: sticky;
        top: 0;
        z-index: 10;
        height: auto;
        max-height: 42vh;
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }}
      .people {{ grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }}
      .timeline {{
        padding-left: 16px;
        padding-right: 16px;
        overflow: auto;
      }}
      .timeline-marker {{ width: 190px; }}
    }}
""",
        body_html=f"""
    <aside>
      <div id="people" class="people"></div>
    </aside>
    <section class="timeline" aria-live="polite">
      <div id="warnings"></div>
      {inspect_command_panel("tailwag inspect person-timeline")}
      <div class="toolbar">
        <strong id="activePerson">All people</strong>
        <span id="filterSummary"></span>
      </div>
      <div id="items" class="timeline-canvas"></div>
    </section>
""",
        page_js=f"""
    const report = inspectReportData();
    const records = inspectReportRecords(report);
    const peopleNode = document.getElementById('people');
    const itemsNode = document.getElementById('items');
    const activePersonNode = document.getElementById('activePerson');
    inspectSetCount('recordCount', records.length);
    inspectToggleEmptyCommand(records);
    document.getElementById('filterSummary').textContent = inspectFilterText(report.filters);
    inspectRenderWarnings(report);
    renderPeople();
    renderTimeline(filtersFromHash());
    window.addEventListener('hashchange', () => renderTimeline(filtersFromHash()));

    function selectedPeopleFromHash() {{
      const params = new URLSearchParams(location.hash.slice(1));
      const ids = params.getAll('person').flatMap((value) => String(value || '').split(','));
      return [...new Set(ids.map((value) => value.trim()).filter(Boolean))];
    }}
    function filtersFromHash() {{
      const filters = inspectFilters.read();
      return {{
        people: selectedPeopleFromHash(),
        item: filters.item || filters.episode || '',
        has_memory: filters.has_memory || ''
      }};
    }}
    function setPeople(personIds) {{
      const selected = [...new Set((personIds || []).filter(Boolean))];
      if (selected.length) {{
        const params = new URLSearchParams();
        selected.forEach((personId) => params.append('person', personId));
        location.hash = params.toString();
      }} else {{
        history.pushState('', document.title, location.pathname + location.search);
        renderTimeline(filtersFromHash());
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
    function renderTimeline(filters) {{
      const personIds = (filters && filters.people) || [];
      const selected = new Set(personIds);
      const selectedItem = (filters && filters.item) || '';
      const selectedHasMemory = (filters && filters.has_memory) || '';
      document.querySelectorAll('.person-button').forEach((button) => {{
        const active = button.dataset.personId ? selected.has(button.dataset.personId) : selected.size === 0;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
      }});
      const visible = records.filter((record) => {{
        if (selected.size && !selected.has(record.person_id || '')) return false;
        if (selectedItem && !recordMatchesItem(record, selectedItem)) return false;
        if (selectedHasMemory === 'true' && !hasLinkedMemory(record)) return false;
        if (selectedHasMemory === 'false' && hasLinkedMemory(record)) return false;
        return true;
      }});
      document.getElementById('recordCount').textContent = visible.length;
      activePersonNode.textContent = activePeopleLabel([...selected], visible, selectedItem, selectedHasMemory);
      if (!visible.length) {{
        itemsNode.innerHTML = `<div class="empty">${{escapeHtml(emptyTimelineMessage(selected, selectedItem))}}</div>`;
        return;
      }}
      itemsNode.innerHTML = renderLanes(visible, selectedItem);
    }}
    function emptyTimelineMessage(selected, selectedItem) {{
      if (!selectedItem) return 'No timeline items matched this selection.';
      const itemExists = records.some((record) => recordMatchesItem(record, selectedItem));
      if (!itemExists) {{
        return `Item ${{selectedItem}} is not in this exported timeline. Regenerate the person timeline with a higher --limit or the matching --person-id to include it.`;
      }}
      if (selected && selected.size) {{
        return `Item ${{selectedItem}} is in this export, but not for the selected people. Clear the person selection or regenerate with the matching --person-id.`;
      }}
      return `Item ${{selectedItem}} did not match the current timeline filters.`;
    }}
    function activePeopleLabel(personIds, visible, selectedItem, selectedHasMemory) {{
      if (selectedItem) return `Item ${{selectedItem}}`;
      if (selectedHasMemory === 'true') return 'Items with linked memory';
      if (selectedHasMemory === 'false') return 'Items without linked memory';
      if (!personIds.length) return 'All people';
      if (personIds.length === 1) {{
        const first = visible[0];
        return (first && first.display_name) || personIds[0];
      }}
      return `${{personIds.length}} people selected`;
    }}
    function renderLanes(visible, selectedItem) {{
      const domain = timeDomain(visible);
      return `${{renderAxis(domain)}}${{personLaneGroups(visible).map((group) => renderLane(group, domain, selectedItem)).join('')}}`;
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
        <span class="axis-tick" style="left:${{timePercent(tick.value, domain)}}%">${{escapeHtml(formatDateTime(tick.value))}}</span>
      `).join('')}}</div>`;
    }}
    function renderLane(group, domain, selectedItem) {{
      const sorted = [...group.records].sort((left, right) => timeValue(left.start_time) - timeValue(right.start_time));
      const markerLayout = layoutMarkers(sorted, domain);
      const laneHeight = Math.max(220, 64 + markerLayout.rowCount * 168);
      return `
        <section class="person-lane" data-person-id="${{escapeAttr(group.person_id)}}">
          <div class="lane-label">
            <strong><a href="${{escapeHtml(memoryItemsHref({{ person: group.person_id }}))}}">${{escapeHtml(group.display_name)}}</a></strong>
            <span>${{group.records.length}} item${{group.records.length === 1 ? '' : 's'}}</span>
          </div>
          <div class="timeline-lane" style="min-height:${{laneHeight}}px">
            ${{markerLayout.items.map((item) => renderMarker(item.record, item.left, item.top, selectedItem)).join('')}}
          </div>
        </section>
      `;
    }}
    function layoutMarkers(sorted, domain) {{
      const rows = [];
      const items = sorted.map((record) => ({{
        record,
        left: timePercent(timeValue(record.start_time), domain),
        top: 16
      }}));
      items.forEach((item) => {{
        let rowIndex = rows.findIndex((row) => item.left - row.lastLeft >= 18);
        if (rowIndex === -1) {{
          rowIndex = rows.length;
          rows.push({{ lastLeft: item.left }});
        }} else {{
          rows[rowIndex].lastLeft = item.left;
        }}
        item.top = 16 + rowIndex * 168;
      }});
      return {{ items, rowCount: Math.max(1, rows.length) }};
    }}
    function renderMarker(record, left, top, selectedItem) {{
      const type = record.item_type || '';
      const memoryClass = hasLinkedMemory(record) ? 'with-memory' : '';
      const activeClass = selectedItem && recordMatchesItem(record, selectedItem) ? 'active' : '';
      const memoryLabel = hasLinkedMemory(record) ? `Linked memories ${{linkedMemoryCount(record)}}` : 'No linked memory';
      const memoryHref = memoryItemsHrefForRecord(record);
      return `
        <article class="timeline-marker ${{escapeAttr(type)}} ${{memoryClass}} ${{activeClass}}" id="${{escapeAttr(record.item_id || '')}}" tabindex="0" onclick="bringMarkerToFront(this)" onfocus="bringMarkerToFront(this)" style="left:${{left}}%; top:${{top}}px">
          <div class="marker-head">
            <strong>${{escapeHtml(formatDateTime(record.start_time))}}</strong>
            <span class="kind">${{escapeHtml(type)}}</span>
          </div>
          <p class="marker-text">${{escapeHtml(record.text || '')}}</p>
          <a class="memory-marker ${{hasLinkedMemory(record) ? 'linked' : ''}}" href="${{escapeHtml(memoryHref)}}">${{escapeHtml(memoryLabel)}}</a>
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
    function recordMatchesItem(record, itemId) {{
      return record.item_id === itemId || record.episode_id === itemId || record.event_id === itemId;
    }}
    function hasLinkedMemory(record) {{
      return linkedMemoryCount(record) > 0 || Boolean(record.has_memory_items);
    }}
    function linkedMemoryCount(record) {{
      const count = Number(record.memory_item_count || 0);
      return Number.isFinite(count) ? Math.max(0, count) : 0;
    }}
    function memoryItemIds(record) {{
      return Array.isArray(record.memory_item_ids) ? record.memory_item_ids.filter(Boolean) : [];
    }}
    function memoryItemsHrefForRecord(record) {{
      const ids = memoryItemIds(record);
      if (ids.length === 1) return memoryItemsHref({{ memory: ids[0] }});
      if (record.episode_id) return memoryItemsHref({{ person: record.person_id || '', episode: record.episode_id }});
      return memoryItemsHref({{ person: record.person_id || '' }});
    }}
    function memoryItemsHref(filters) {{
      return inspectFilters.href('tailwag-memory-items.html', filters || {{}});
    }}
""",
    )
