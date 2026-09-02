const sb = supabase.createClient(window.APP_CONFIG.SUPABASE_URL, window.APP_CONFIG.SUPABASE_ANON_KEY);

const authScreen = document.getElementById('auth-screen');
const appShell = document.getElementById('app-shell');
let currentSession = null;
let currentRole = 'employee';
let lastQueryRequestId = null;

// ---------------------------------------------------------------
// Auth
// ---------------------------------------------------------------

sb.auth.onAuthStateChange((_event, session) => {
  currentSession = session;
  if (session) {
    enterApp(session);
  } else {
    authScreen.hidden = false;
    appShell.hidden = true;
  }
});

document.getElementById('btn-google').addEventListener('click', () => {
  sb.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: window.location.origin } });
});

document.getElementById('btn-apple').addEventListener('click', () => {
  sb.auth.signInWithOAuth({ provider: 'apple', options: { redirectTo: window.location.origin } });
});

document.getElementById('magic-link-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = document.getElementById('magic-link-email').value;
  const statusEl = document.getElementById('magic-link-status');
  const { error } = await sb.auth.signInWithOtp({ email, options: { emailRedirectTo: window.location.origin } });
  statusEl.hidden = false;
  statusEl.className = error ? 'auth-status is-error' : 'auth-status';
  statusEl.textContent = error ? error.message : `Check ${email} for a sign-in link.`;
});

document.getElementById('btn-sign-out').addEventListener('click', () => sb.auth.signOut());

async function enterApp(session) {
  authScreen.hidden = true;
  appShell.hidden = false;

  const { data: profile } = await sb
    .from('profiles')
    .select('role, full_name')
    .eq('id', session.user.id)
    .single();

  currentRole = profile?.role || 'employee';
  document.getElementById('user-name').textContent = profile?.full_name || session.user.email;
  document.getElementById('user-role').textContent = currentRole;
  document.getElementById('nav-admin').hidden = currentRole !== 'manager';

  if (currentRole === 'manager') loadDepartmentCheckboxes();
}

// ---------------------------------------------------------------
// API helper — always attaches the current session's access token
// ---------------------------------------------------------------

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

// ---------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------

const sectionLoaders = {
  trace: loadTraceList,
  sources: loadSources,
  admin: loadAdminDocs,
};

document.querySelectorAll('.nav-item').forEach((btn) => {
  btn.addEventListener('click', () => showSection(btn.dataset.section));
});

function showSection(name) {
  document.querySelectorAll('.nav-item').forEach((b) => b.classList.toggle('is-active', b.dataset.section === name));
  document.querySelectorAll('.panel').forEach((p) => {
    p.hidden = p.id !== `section-${name}`;
  });
  if (sectionLoaders[name]) sectionLoaders[name]();
}

// ---------------------------------------------------------------
// Query section
// ---------------------------------------------------------------

document.getElementById('query-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const input = document.getElementById('query-input');
  const submitBtn = document.getElementById('query-submit');
  const query = input.value.trim();
  if (!query) return;

  submitBtn.disabled = true;
  submitBtn.textContent = 'Thinking…';
  document.getElementById('query-empty').hidden = true;

  try {
    const result = await apiFetch('/api/query', { method: 'POST', body: JSON.stringify({ query, k: 5 }) });
    lastQueryRequestId = result.requestId;

    document.getElementById('answer-text').textContent = result.answer;
    const sourcesList = document.getElementById('answer-sources');
    sourcesList.innerHTML = '';
    (result.sources || []).forEach((s, i) => {
      const li = document.createElement('li');
      li.className = 'source-chip';
      li.innerHTML = `[${i + 1}] ${escapeHtml(s.document_title)} <span class="sim">${(s.similarity * 100).toFixed(0)}%</span>`;
      sourcesList.appendChild(li);
    });

    document.getElementById('query-result').hidden = false;
  } catch (err) {
    document.getElementById('answer-text').textContent = `Something went wrong: ${err.message}`;
    document.getElementById('answer-sources').innerHTML = '';
    document.getElementById('query-result').hidden = false;
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Ask';
  }
});

document.getElementById('view-trace-btn').addEventListener('click', async () => {
  showSection('trace');
  if (lastQueryRequestId) {
    const { traces } = await apiFetch(`/api/traces?requestId=${lastQueryRequestId}`);
    if (traces && traces[0]) renderTraceDetail(traces[0]);
  }
});

// ---------------------------------------------------------------
// Pipeline Trace section
// ---------------------------------------------------------------

async function loadTraceList() {
  const list = document.getElementById('trace-list');
  list.innerHTML = '<li>Loading…</li>';
  try {
    const { traces } = await apiFetch('/api/traces');
    list.innerHTML = '';
    if (!traces || traces.length === 0) {
      list.innerHTML = '<li style="padding: 0.75em 0.25em; color: var(--muted);">No queries yet.</li>';
      return;
    }
    traces.forEach((t) => {
      const li = document.createElement('li');
      const btn = document.createElement('button');
      btn.innerHTML = `<span class="trace-q">${escapeHtml(truncate(t.query_text, 60))}</span><span class="trace-t">${new Date(t.created_at).toLocaleString()}</span>`;
      btn.addEventListener('click', () => renderTraceDetail(t));
      li.appendChild(btn);
      list.appendChild(li);
    });
    if (lastQueryRequestId) {
      const match = traces.find((t) => t.request_id === lastQueryRequestId);
      if (match) renderTraceDetail(match);
    }
  } catch (err) {
    list.innerHTML = `<li style="color: var(--error);">${escapeHtml(err.message)}</li>`;
  }
}

function renderTraceDetail(trace) {
  const el = document.getElementById('trace-detail');
  const stage = trace.stage || {};
  const chunks = stage.retrieved_chunks || [];
  const lat = trace.latency_breakdown || {};

  el.innerHTML = `
    <div class="stage-block">
      <span class="stage-num">Stage 1</span>
      <h4>Chunking</h4>
      <p>Strategy: <code>${escapeHtml(stage.chunking_strategy || 'unknown')}</code></p>
    </div>

    <div class="stage-block">
      <span class="stage-num">Stage 2</span>
      <h4>Retrieval — ${chunks.length} chunk(s), embedding model <code>${escapeHtml(stage.embedding_model || 'unknown')}</code></h4>
      ${chunks.map((c) => `
        <div class="chunk-row">
          ${escapeHtml(truncate(c.content, 220))}
          <span class="chunk-meta">${escapeHtml(c.document_title)} · similarity ${(c.similarity * 100).toFixed(1)}%</span>
        </div>
      `).join('') || '<p style="color: var(--muted);">No chunks retrieved.</p>'}
    </div>

    <div class="stage-block">
      <span class="stage-num">Stage 3</span>
      <h4>Generation — <code>${escapeHtml(stage.llm_model || 'unknown')}</code></h4>
      ${stage.generation_prompt ? `<pre class="prompt-block">${escapeHtml(stage.generation_prompt)}</pre>` : ''}
      <p>${escapeHtml(stage.generation_output || '')}</p>
    </div>

    <div class="stage-block">
      <span class="stage-num">Timing</span>
      <div class="latency-row">
        <span>embed ${lat.embedding_ms ?? '—'}ms</span>
        <span>retrieve ${lat.retrieval_ms ?? '—'}ms</span>
        <span>generate ${lat.generation_ms ?? '—'}ms</span>
        <span>total ${lat.total_ms ?? '—'}ms</span>
      </div>
    </div>
  `;
}

// ---------------------------------------------------------------
// Sources section
// ---------------------------------------------------------------

async function loadSources() {
  const list = document.getElementById('sources-list');
  list.innerHTML = '<li>Loading…</li>';
  try {
    const { documents } = await apiFetch('/api/documents');
    renderDocList(list, documents);
  } catch (err) {
    list.innerHTML = `<li style="color: var(--error);">${escapeHtml(err.message)}</li>`;
  }
}

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

// ---------------------------------------------------------------
// Admin section
// ---------------------------------------------------------------

async function loadDepartmentCheckboxes() {
  const container = document.getElementById('dept-checkboxes');
  try {
    const { departments } = await apiFetch('/api/departments');
    container.innerHTML = (departments || [])
      .map((d) => `<label><input type="checkbox" value="${d.id}" name="dept" /> ${escapeHtml(d.name)}</label>`)
      .join('');
  } catch (err) {
    container.innerHTML = `<p style="color: var(--error);">${escapeHtml(err.message)}</p>`;
  }
}

async function loadAdminDocs() {
  const list = document.getElementById('admin-doc-list');
  list.innerHTML = '<li>Loading…</li>';
  try {
    const { documents } = await apiFetch('/api/documents');
    renderDocList(list, documents);
    // manager view: allow clicking a doc to publish a new version against it
    Array.from(list.children).forEach((li, i) => {
      const doc = documents[i];
      if (!doc) return;
      const btn = document.createElement('button');
      btn.className = 'btn-text';
      btn.style.marginTop = '0.5rem';
      btn.textContent = 'Publish new version of this document';
      btn.addEventListener('click', () => {
        document.getElementById('upload-existing-doc-id').value = doc.id;
        document.getElementById('upload-title').value = doc.title;
        document.getElementById('upload-title').scrollIntoView({ behavior: 'smooth' });
      });
      li.appendChild(btn);
    });
  } catch (err) {
    list.innerHTML = `<li style="color: var(--error);">${escapeHtml(err.message)}</li>`;
  }
}

document.getElementById('upload-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const submitBtn = document.getElementById('upload-submit');
  const statusEl = document.getElementById('upload-status');
  const title = document.getElementById('upload-title').value.trim();
  const fileInput = document.getElementById('upload-file');
  const textArea = document.getElementById('upload-text');
  const existingDocumentId = document.getElementById('upload-existing-doc-id').value || null;
  const departmentIds = Array.from(document.querySelectorAll('input[name="dept"]:checked')).map((i) => i.value);

  let text = textArea.value.trim();
  if (fileInput.files[0]) {
    text = await fileInput.files[0].text();
  }
  if (!text) {
    statusEl.hidden = false;
    statusEl.className = 'auth-status is-error';
    statusEl.textContent = 'Provide document text via file upload or the text box.';
    return;
  }

  submitBtn.disabled = true;
  submitBtn.textContent = 'Publishing…';
  statusEl.hidden = true;

  try {
    const result = await apiFetch('/api/ingest', {
      method: 'POST',
      body: JSON.stringify({ title, text, departmentIds, existingDocumentId }),
    });
    statusEl.hidden = false;
    statusEl.className = 'auth-status';
    statusEl.textContent = `Published v${result.versionNumber} — ${result.chunksCreated} chunks created and embedded.`;
    document.getElementById('upload-form').reset();
    document.getElementById('upload-existing-doc-id').value = '';
    loadAdminDocs();
  } catch (err) {
    statusEl.hidden = false;
    statusEl.className = 'auth-status is-error';
    statusEl.textContent = err.message;
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Publish document';
  }
});

// ---------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str ?? '';
  return div.innerHTML;
}

function truncate(str, n) {
  if (!str) return '';
  return str.length > n ? `${str.slice(0, n)}…` : str;
}
