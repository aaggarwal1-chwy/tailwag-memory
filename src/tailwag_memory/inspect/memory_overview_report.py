from __future__ import annotations


def memory_overview_css() -> str:
    """Return page-specific CSS for the memory overview Sankey."""

    return """
    .sankey-wrap { overflow-x: auto; }
    svg {
      min-width: 1040px;
      width: 100%;
      height: 440px;
      display: block;
    }
    .link {
      fill: none;
      stroke: var(--accent-3);
      stroke-opacity: .28;
      stroke-linecap: round;
      cursor: pointer;
    }
    .link.terminal-addressed { stroke: var(--accent); }
    .link.terminal-superseded, .link.terminal-expired-active, .link.terminal-invalid { stroke: var(--danger); }
    .node { cursor: pointer; }
    .node a { text-decoration: none; }
    .node a:focus rect {
      stroke: var(--accent);
      stroke-width: 2;
    }
    .node rect {
      fill: #fff;
      stroke: var(--line);
      stroke-width: 1;
      rx: 7;
    }
    .node text {
      fill: var(--ink);
      font-size: 13px;
      font-weight: 650;
    }
    .node .count {
      fill: var(--muted);
      font-size: 12px;
      font-weight: 500;
    }
"""


def memory_overview_section() -> str:
    """Return the memory overview Sankey section."""

    return """
    <section class="panel sankey-wrap" aria-label="Memory overview Sankey diagram">
      <h2>Memory Overview</h2>
      <svg id="overviewSankey" viewBox="0 0 1120 440" role="img" aria-label="Memory overview Sankey diagram"></svg>
    </section>"""


def memory_overview_script() -> str:
    """Return JavaScript helpers for the memory overview Sankey."""

    return """
    function renderOverviewSankey() {
      const svg = document.getElementById('overviewSankey');
      if (!overviewLinks.length) {
        svg.innerHTML = '<text x="24" y="40" fill="#5f6f89">No memory overview data was returned.</text>';
        return;
      }
      const nodes = overviewNodeLayout(overviewLinks);
      const maxCount = Math.max(1, ...overviewLinks.map((link) => Number(link.count || 0)));
      const linkSvg = overviewLinks.map((link) => {
        const source = nodes[link.source];
        const target = nodes[link.target];
        if (!source || !target) return '';
        const width = Math.max(8, Math.round(Number(link.count || 0) / maxCount * 54));
        const href = overviewHrefForLink(link);
        return `<a href="${escapeHtml(href)}"><path class="link terminal-${escapeAttr(link.target)}" d="${sankeyPath(source, target)}" stroke-width="${width}"><title>${escapeHtml(link.source)} to ${escapeHtml(link.target)}: ${link.count}</title></path></a>`;
      }).join('');
      const nodeSvg = Object.values(nodes).map((node) => `
        <g class="node">
          <a href="${escapeHtml(overviewHrefForNode(node.label))}">
            <rect x="${node.x}" y="${node.y}" width="${node.width}" height="${node.height}"></rect>
            <text x="${node.x + 12}" y="${node.y + 24}">${escapeHtml(node.label)}</text>
            <text class="count" x="${node.x + 12}" y="${node.y + 44}">${node.count}</text>
          </a>
        </g>
      `).join('');
      svg.innerHTML = linkSvg + nodeSvg;
    }
    function overviewNodeLayout(values) {
      const activeTotal = overviewCountFor('Created', 'Active');
      const memoryItemCount = Math.max(overviewCountFor('Episodes With Memories', 'Created'), activeTotal);
      const terminals = values.filter((link) => link.source === 'Active');
      const nodes = {};
      const allEpisodeCount = overviewCountFor('All Episodes', 'Episodes With Memories') + overviewCountFor('All Episodes', 'Episodes Without Memories');
      if (allEpisodeCount) {
        nodes['All Episodes'] = { label: 'All Episodes', count: allEpisodeCount, x: 40, y: 180, width: 160, height: 70 };
      }
      if (overviewCountFor('All Episodes', 'Episodes With Memories')) {
        nodes['Episodes With Memories'] = { label: 'Episodes With Memories', count: overviewCountFor('All Episodes', 'Episodes With Memories'), x: 260, y: 130, width: 190, height: 66 };
      }
      if (overviewCountFor('All Episodes', 'Episodes Without Memories')) {
        nodes['Episodes Without Memories'] = { label: 'Episodes Without Memories', count: overviewCountFor('All Episodes', 'Episodes Without Memories'), x: 260, y: 245, width: 190, height: 66 };
      }
      if (memoryItemCount) {
        nodes.Created = { label: 'Created', count: memoryItemCount, x: 520, y: 180, width: 150, height: 70 };
      }
      if (activeTotal) {
        nodes.Active = { label: 'Active', count: activeTotal, x: 760, y: 180, width: 150, height: 70 };
      }
      const startY = Math.max(34, 210 - terminals.length * 38);
      terminals.forEach((link, index) => {
        nodes[link.target] = {
          label: link.target,
          count: Number(link.count || 0),
          x: 950,
          y: startY + index * 76,
          width: 170,
          height: 60
        };
      });
      return nodes;
    }
    function overviewCountFor(source, target) {
      const link = overviewLinks.find((entry) => entry.source === source && entry.target === target);
      return link ? Number(link.count || 0) : 0;
    }
    function sankeyPath(source, target) {
      const x1 = source.x + source.width;
      const y1 = source.y + source.height / 2;
      const x2 = target.x;
      const y2 = target.y + target.height / 2;
      const mid = (x1 + x2) / 2;
      return `M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`;
    }
    function overviewHrefForLink(link) {
      if (link.source === 'All Episodes' || link.target === 'Episodes With Memories') {
        return timelineHref({ has_memory: 'true' });
      }
      if (link.target === 'Episodes Without Memories') {
        return timelineHref({ has_memory: 'false' });
      }
      return '#' + hashWith(overviewFilters(link.target));
    }
    function overviewHrefForNode(label) {
      if (label === 'All Episodes') return timelineHref({});
      if (label === 'Episodes With Memories') return timelineHref({ has_memory: 'true' });
      if (label === 'Episodes Without Memories') return timelineHref({ has_memory: 'false' });
      return '#' + hashWith(overviewFilters(label));
    }
    function overviewFilters(label) {
      const normalized = String(label || '').toLowerCase();
      if (normalized === 'superseded') return { status: 'superseded' };
      if (normalized === 'addressed') return { status: 'addressed' };
      if (normalized === 'expired active') return { kind: 'followup', followup_state: 'expired_active' };
      if (normalized === 'invalid') return { kind: 'followup', followup_state: 'invalid' };
      if (normalized === 'still active' || normalized === 'active' || normalized === 'created') return { status: 'active' };
      if (normalized === 'other inactive') return { status: 'inactive' };
      return {};
    }
"""
