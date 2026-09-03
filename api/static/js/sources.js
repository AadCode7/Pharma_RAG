document.addEventListener('auth-ready', loadSources);

async function loadSources() {
  const list = document.getElementById('sources-list');
  list.innerHTML = '<li>Loading…</li>';
  try {
    const { documents } = await apiFetch('/api/documents');
    renderDocList(list, documents); // defined in api-client.js — shared with admin.js
  } catch (err) {
    list.innerHTML = `<li style="color: var(--error);">${escapeHtml(err.message)}</li>`;
  }
}
