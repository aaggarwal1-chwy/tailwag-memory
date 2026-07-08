from __future__ import annotations

from dataclasses import asdict

from .html_utils import _html_escape, _safe_json, inspect_nav, inspect_script_tag, inspect_style_link
from .reports import InspectReport


def followup_validity_report_html(report: InspectReport) -> str:
    """Render a self-contained follow-up validity duration report."""

    payload = _safe_json(asdict(report))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_html_escape(report.title)}</title>
  {inspect_style_link()}
  <style>
    main {{ padding: 20px 28px 32px; display: grid; gap: 16px; }}
    .groups {{ display: grid; gap: 14px; }}
    .group {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 12px;
    }}
    .group-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 10px;
    }}
    .group h2 {{ margin: 0; }}
    .group h2 a, .item a {{
      color: var(--accent);
      text-decoration: none;
    }}
    .group h2 a:hover, .item a:hover {{ text-decoration: underline; }}
    .bar {{ height: 8px; margin-bottom: 10px; }}
    .items {{ display: grid; gap: 8px; }}
    .item {{
      border-top: 1px solid var(--line);
      padding-top: 8px;
      display: grid;
      grid-template-columns: minmax(180px, 240px) minmax(0, 1fr) auto;
      gap: 12px;
      align-items: start;
      font-size: 13px;
    }}
    .item strong {{ display: block; overflow-wrap: anywhere; }}
    .summary {{ overflow-wrap: anywhere; }}
    .pill {{ color: var(--muted); }}
    .pill.expired_active {{ color: var(--danger); border-color: rgba(180,35,24,.45); }}
    .pill.visible_now {{ color: var(--accent); border-color: rgba(11,77,179,.45); }}
    .pill.not_yet_due {{ color: var(--warning-color); border-color: rgba(244,165,28,.55); }}
    .warnings {{ color: var(--danger); }}
    @media (max-width: 820px) {{
      header, main {{ padding-left: 16px; padding-right: 16px; }}
      .item {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    {inspect_nav("followup-validity")}
    <h1>{_html_escape(report.title)}</h1>
    <div class="meta">Generated {_html_escape(report.generated_at)} - <span id="count">0</span> follow-ups</div>
  </header>
  <main>
    <div id="warnings"></div>
    <section class="panel command-panel" id="emptyCommand">
      <h2>Generate This Report</h2>
      <p><code>tailwag inspect followup-validity</code></p>
    </section>
    <section id="groups" class="groups" aria-label="Follow-ups grouped by validity duration"></section>
  </main>
  <script id="report-data" type="application/json">{payload}</script>
  {inspect_script_tag()}
  <script>
    const report = JSON.parse(document.getElementById('report-data').textContent);
    const records = report.records || [];
    const bucketOrder = (report.metadata && report.metadata.bucket_order) || [];
    const labels = {{
      invalid: 'Invalid or Unknown Duration',
      under_1_day: 'Under 1 Day',
      '1_to_3_days': '1-3 Days',
      '4_to_7_days': '4-7 Days',
      '8_to_14_days': '8-14 Days',
      '15_to_30_days': '15-30 Days',
      over_30_days: 'Over 30 Days'
    }};
    document.getElementById('count').textContent = records.length;
    document.getElementById('emptyCommand').hidden = records.length > 0;
    const warnings = report.warnings || [];
    if (warnings.length) {{
      document.getElementById('warnings').innerHTML = `<div class="warnings">${{warnings.map(escapeHtml).join('<br>')}}</div>`;
    }}
    renderGroups();
    function renderGroups() {{
      const node = document.getElementById('groups');
      if (!records.length) {{
        node.innerHTML = '<div class="empty">No follow-up memory items matched this export.</div>';
        return;
      }}
      const grouped = groupBy(records, 'validity_bucket');
      const max = Math.max(1, ...Object.values(grouped).map((items) => items.length));
      node.innerHTML = bucketOrder
        .filter((bucket) => grouped[bucket] && grouped[bucket].length)
        .map((bucket) => groupHtml(bucket, grouped[bucket], max))
        .join('');
    }}
    function groupHtml(bucket, items, max) {{
      return `
        <section class="group">
          <div class="group-head">
            <h2><a href="${{escapeHtml(memoryItemsHref({{ kind: 'followup', validity_bucket: bucket }}))}}">${{escapeHtml(labels[bucket] || bucket)}}</a></h2>
            <strong>${{items.length}}</strong>
          </div>
          <div class="bar" aria-hidden="true"><span style="width:${{Math.round(items.length / max * 100)}}%"></span></div>
          <div class="items">${{items.map(itemHtml).join('')}}</div>
        </section>
      `;
    }}
    function itemHtml(record) {{
      const person = record.display_name || record.person_id || '';
      return `
        <article class="item">
          <div>
            <strong><a href="${{escapeHtml(timelineHref(record))}}">${{escapeHtml(person)}}</a></strong>
            <a href="${{escapeHtml(memoryItemsHref({{ memory: record.memory_id || '' }}))}}"><code>${{escapeHtml(record.memory_id || '')}}</code></a>
          </div>
          <div class="summary">
            ${{escapeHtml(record.summary || '')}}
            <div class="meta">${{escapeHtml(timeRange(record))}}</div>
          </div>
          <a class="pill ${{escapeAttr(record.followup_state || '')}}" href="${{escapeHtml(memoryItemsHref({{ kind: 'followup', followup_state: record.followup_state || 'unknown' }}))}}">${{escapeHtml(titleCase(record.followup_state || 'unknown'))}}</a>
        </article>
      `;
    }}
    function memoryItemsHref(filters) {{
      return inspectFilters.href('tailwag-memory-items.html', filters || {{}});
    }}
    function timelineHref(record) {{
      return inspectFilters.href('tailwag-person-timeline.html', {{ person: record.person_id || '' }});
    }}
    function groupBy(values, key) {{
      return values.reduce((groups, record) => {{
        const value = record[key] || 'unknown';
        groups[value] = groups[value] || [];
        groups[value].push(record);
        return groups;
      }}, {{}});
    }}
    function timeRange(record) {{
      const parts = [];
      if (record.due_at) parts.push(`due ${{formatDateTime(record.due_at)}}`);
      if (record.expires_at) parts.push(`expires ${{formatDateTime(record.expires_at)}}`);
      return parts.join(' / ');
    }}
  </script>
</body>
</html>
"""
