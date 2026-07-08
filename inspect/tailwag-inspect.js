window.inspectFilters = {
  href(path, filters) {
    const params = new URLSearchParams();
    Object.entries(filters || {}).forEach(([key, raw]) => {
      const values = Array.isArray(raw) ? raw : [raw];
      values.forEach((value) => {
        if (value !== null && value !== undefined && String(value) !== '') {
          params.append(key, String(value));
        }
      });
    });
    const hash = params.toString();
    return hash ? `${path}#${hash}` : path;
  },
  read() {
    const params = new URLSearchParams(String(window.location.hash || '').replace(/^#/, ''));
    const first = (key) => params.get(key) || '';
    return {
      person: first('person'),
      kind: first('kind'),
      status: first('status'),
      source: first('source'),
      followup_state: first('followup_state'),
      memory: first('memory'),
      episode: first('episode'),
      item: first('item'),
      validity_bucket: first('validity_bucket'),
      has_memory: first('has_memory')
    };
  }
};

function titleCase(value) {
  return String(value || '').replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[char]));
}

function escapeAttr(value) {
  return String(value || '').replace(/[^a-zA-Z0-9_-]/g, '-');
}

function formatDateTime(value) {
  if (!value) return '';
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit'
  }).format(date);
}
