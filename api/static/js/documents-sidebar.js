document.addEventListener('auth-ready', () => {
  loadDocumentsRail();
  document.getElementById('documents-refresh')?.addEventListener('click', loadDocumentsRail);
});

async function loadDocumentsRail() {
  const list = document.getElementById('documents-rail-list');
  if (!list) return;

  list.innerHTML = '<p class="documents-rail-empty">Loading documents…</p>';

  try {
    const { documents } = await apiFetch('/api/documents');
    renderDocumentsRail(documents || []);
  } catch (err) {
    list.innerHTML = `<p class="documents-rail-empty is-error">${escapeHtml(err.message)}</p>`;
  }
}

function renderDocumentsRail(documents) {
  const list = document.getElementById('documents-rail-list');
  list.innerHTML = '';

  if (!documents.length) {
    list.innerHTML = '<p class="documents-rail-empty">No documents are currently visible to you.</p>';
    return;
  }

  documents.forEach((doc) => {
    const current = (doc.document_versions || []).find((version) => version.id === doc.current_version_id);
    const card = document.createElement('article');
    card.className = 'documents-rail-card';

    const versionSummary = current
      ? `v${current.version_number} · ${new Date(current.created_at).toLocaleDateString()}`
      : 'No published version';

    const strategySummary = current
      ? `${formatStrategy(current.chunking_strategy)} · ${formatStrategy(current.embedding_strategy, current.embedding_model)}`
      : 'Strategy configuration unavailable';

    card.innerHTML = `
      <div class="documents-rail-card-head">
        <h3>${escapeHtml(doc.title)}</h3>
        <span class="documents-rail-status ${doc.status === 'active' ? 'is-active' : ''}">${escapeHtml(doc.status)}</span>
      </div>
      <p class="documents-rail-version">${escapeHtml(versionSummary)}</p>
      <p class="documents-rail-strategy">${escapeHtml(strategySummary)}</p>
      ${renderVersionHistory(doc)}
    `;

    if (window.currentUserRole === 'manager') {
      const actions = document.createElement('div');
      actions.className = 'documents-rail-actions';

      const versionBtn = document.createElement('button');
      versionBtn.type = 'button';
      versionBtn.className = 'btn-text';
      versionBtn.textContent = 'Publish new version';
      versionBtn.addEventListener('click', () => publishNewVersion(doc));

      const repairBtn = document.createElement('button');
      repairBtn.type = 'button';
      repairBtn.className = 'btn-text';
      repairBtn.textContent = 'Repair embeddings';
      repairBtn.addEventListener('click', () => repairEmbeddings(doc, repairBtn));

      const deleteBtn = document.createElement('button');
      deleteBtn.type = 'button';
      deleteBtn.className = 'btn-text btn-text-danger';
      deleteBtn.textContent = 'Delete';
      deleteBtn.addEventListener('click', () => deleteDocumentFromRail(doc, deleteBtn));

      actions.append(versionBtn, repairBtn, deleteBtn);
      card.appendChild(actions);
    }

    list.appendChild(card);
  });
}

function renderVersionHistory(doc) {
  const versions = (doc.document_versions || []).sort((a, b) => b.version_number - a.version_number);
  if (!versions.length) return '';

  return `
    <details class="documents-rail-history">
      <summary>${versions.length} version${versions.length === 1 ? '' : 's'}</summary>
      <div class="documents-rail-history-list">
        ${versions.map((version) => `
          <div class="documents-rail-history-row">
            <span>v${version.version_number}</span>
            <span class="documents-rail-history-badge ${version.id === doc.current_version_id ? 'is-current' : ''}">
              ${version.id === doc.current_version_id ? 'current' : 'superseded'}
            </span>
          </div>
          <p class="documents-rail-history-meta">${escapeHtml(formatStrategy(version.chunking_strategy))} · ${escapeHtml(formatStrategy(version.embedding_strategy, version.embedding_model))}</p>
        `).join('')}
      </div>
    </details>
  `;
}

function formatStrategy(value, modelName = '') {
  // The stored strategy ID is a legacy UI identifier in some deployments
  // (bge_small), so use the actual persisted model name when available.
  if (modelName === 'embed-english-light-v3.0') return 'Cohere English Light';
  if (modelName === 'BAAI/bge-small-en-v1.5') return 'BGE Small';

  const labels = {
    fixed_size_v1: 'Fixed Size',
    recursive: 'Recursive',
    sentence: 'Sentence',
    semantic: 'Semantic',
    section_aware: 'Section Aware',
    parent_child: 'Parent / Child',
    bge_small: 'Cohere English Light',
    bge_base: 'BGE Base',
    e5_base: 'E5 Base',
    openai_small: 'OpenAI Small',
  };
  return labels[value] || value || 'Unknown';
}

function publishNewVersion(doc) {
  if (window.location.pathname !== '/admin') {
    const params = new URLSearchParams({ documentId: doc.id });
    window.location.href = `/admin?${params.toString()}`;
    return;
  }

  document.dispatchEvent(new CustomEvent('document-version-select', { detail: { document: doc } }));
  document.getElementById('upload-title')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function repairEmbeddings(doc, btn) {
  btn.disabled = true;
  btn.textContent = 'Repairing…';
  try {
    const result = await apiFetch(`/api/documents/${doc.id}/reembed`, { method: 'POST' });
    window.alert(
      result.repaired === 0
        ? `"${doc.title}" already has embeddings for all ${result.chunksTotal} active chunks.`
        : `Repaired "${doc.title}": embedded ${result.repaired} of ${result.chunksTotal} active chunks.`
    );
  } catch (err) {
    window.alert(`Could not repair "${doc.title}": ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Repair embeddings';
  }
}

async function deleteDocumentFromRail(doc, btn) {
  const confirmed = window.confirm(
    `Delete "${doc.title}" permanently?\n\nThis removes every version, chunk, and embedding. It cannot be undone.`
  );
  if (!confirmed) return;

  btn.disabled = true;
  btn.textContent = 'Deleting…';
  try {
    await apiFetch(`/api/documents/${doc.id}`, { method: 'DELETE' });
    await loadDocumentsRail();
    window.dispatchEvent(new CustomEvent('documents-changed'));
  } catch (err) {
    btn.disabled = false;
    btn.textContent = 'Delete';
    window.alert(`Could not delete "${doc.title}": ${err.message}`);
  }
}

document.addEventListener('documents-changed', loadDocumentsRail);
