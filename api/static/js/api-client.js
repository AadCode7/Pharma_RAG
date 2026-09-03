// Shared by every page-specific script. Always attaches the current
// session's access token — never call this before 'auth-ready' has fired
// (see guard.js), or there may not be a session to read yet.
async function apiFetch(path, options = {}) {
  const { data } = await sb.auth.getSession();
  const token = data.session?.access_token;

  const res = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...(options.headers || {}),
    },
  });

  const body = await res.json();
  if (!res.ok) throw new Error(body.error || `Request failed (${res.status})`);
  return body;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str ?? '';
  return div.innerHTML;
}

function truncate(str, n) {
  if (!str) return '';
  return str.length > n ? `${str.slice(0, n)}…` : str;
}

// Shared between sources.js and admin.js — both pages render the same
// document/version list, just with different actions attached afterward.
function renderDocList(listEl, documents) {
  listEl.innerHTML = '';
  if (!documents || documents.length === 0) {
    listEl.innerHTML = '<li style="color: var(--muted); padding: 1rem 0;">No documents visible to you yet.</li>';
    return;
  }
  documents.forEach((doc) => {
    const li = document.createElement('li');
    li.className = 'doc-item';
    const versions = (doc.document_versions || []).sort((a, b) => b.version_number - a.version_number);
    li.innerHTML = `
      <h4>${escapeHtml(doc.title)}</h4>
      ${versions.map((v) => `
        <div class="version-row">
          <span class="badge ${v.id === doc.current_version_id ? 'badge-current' : 'badge-superseded'}">
            ${v.id === doc.current_version_id ? 'current' : 'superseded'}
          </span>
          v${v.version_number} · ${new Date(v.created_at).toLocaleDateString()}
        </div>
      `).join('')}
    `;
    listEl.appendChild(li);
  });
}
