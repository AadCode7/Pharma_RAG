document.addEventListener('document-version-select', handleDocumentVersionSelect);

document.addEventListener('auth-ready', async (e) => {
  // The API still enforces manager permissions. This page-level check keeps
  // the manager-only upload UI out of the employee experience.
  if (e.detail.role !== 'manager') {
    window.location.replace('/');
    return;
  }

  try {
    await Promise.all([loadDepartmentCheckboxes(), loadUploadStrategies()]);
    document.getElementById('upload-form').addEventListener('submit', handleUploadSubmit);
    await selectDocumentFromUrl();
    updateSelectedUploadConfig();
  } catch (err) {
    const statusEl = document.getElementById('upload-strategy-status');
    statusEl.hidden = false;
    statusEl.className = 'strategy-status is-error';
    statusEl.textContent = `Could not initialize document configuration: ${err.message}`;
  }
});

let uploadStrategies = {
  chunking: [],
  embedding: [],
};

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

async function loadUploadStrategies() {
  const { strategies } = await apiFetch('/api/strategies');
  uploadStrategies.chunking = strategies.chunking || [];
  uploadStrategies.embedding = strategies.embedding || [];

  populateStrategySelect(document.getElementById('chunking-strategy'), uploadStrategies.chunking);
  populateStrategySelect(document.getElementById('embedding-strategy'), uploadStrategies.embedding);

  document.getElementById('chunking-strategy').addEventListener('change', updateSelectedUploadConfig);
  document.getElementById('embedding-strategy').addEventListener('change', updateSelectedUploadConfig);
  updateUploadStrategyStatus();
}

function populateStrategySelect(select, strategies) {
  select.innerHTML = '';
  strategies.forEach((strategy) => {
    const option = document.createElement('option');
    option.value = strategy.id;
    option.textContent = strategy.implemented ? strategy.label : `${strategy.label} — coming next`;
    option.dataset.implemented = strategy.implemented ? 'true' : 'false';
    option.dataset.description = strategy.description || '';
    select.appendChild(option);
  });

  const defaultStrategy = strategies.find((strategy) => strategy.default) || strategies[0];
  if (defaultStrategy) select.value = defaultStrategy.id;
}

function updateUploadStrategyStatus() {
  const chunking = document.getElementById('chunking-strategy').selectedOptions[0];
  const embedding = document.getElementById('embedding-strategy').selectedOptions[0];
  const status = document.getElementById('upload-strategy-status');

  if (!chunking || !embedding) {
    status.hidden = true;
    return;
  }

  const unavailable = [chunking, embedding].filter((option) => option.dataset.implemented !== 'true');
  status.hidden = false;

  if (unavailable.length === 0) {
    status.className = 'strategy-status';
    status.textContent = 'Current executable configuration: Fixed Size chunking with BGE Small embeddings.';
  } else {
    status.className = 'strategy-status is-warning';
    status.textContent = 'The selected strategy is visible here so its configuration contract is ready, but its implementation will be added in a later milestone.';
  }

  updateSelectedUploadConfig();
}

function updateSelectedUploadConfig() {
  const chunking = document.getElementById('chunking-strategy')?.selectedOptions[0];
  const embedding = document.getElementById('embedding-strategy')?.selectedOptions[0];
  const summary = document.getElementById('selected-upload-config');
  if (!chunking || !embedding || !summary) return;

  summary.textContent = `${chunking.textContent.replace(' — coming next', '')} · ${embedding.textContent.replace(' — coming next', '')}`;
}

function handleDocumentVersionSelect(e) {
  const doc = e.detail.document;
  document.getElementById('upload-existing-doc-id').value = doc.id;
  document.getElementById('upload-title').value = doc.title;

  const current = (doc.document_versions || []).find((version) => version.id === doc.current_version_id);
  if (current) {
    const chunkingSelect = document.getElementById('chunking-strategy');
    const embeddingSelect = document.getElementById('embedding-strategy');
    if ([...chunkingSelect.options].some((option) => option.value === current.chunking_strategy)) {
      chunkingSelect.value = current.chunking_strategy;
    }
    if ([...embeddingSelect.options].some((option) => option.value === current.embedding_strategy)) {
      embeddingSelect.value = current.embedding_strategy;
    }
  }

  updateUploadStrategyStatus();
}

async function selectDocumentFromUrl() {
  const documentId = new URLSearchParams(window.location.search).get('documentId');
  if (!documentId) return;

  const { documents } = await apiFetch('/api/documents');
  const doc = (documents || []).find((item) => item.id === documentId);
  if (doc) handleDocumentVersionSelect({ detail: { document: doc } });
}

async function handleUploadSubmit(e) {
  e.preventDefault();
  const submitBtn = document.getElementById('upload-submit');
  const statusEl = document.getElementById('upload-status');
  const title = document.getElementById('upload-title').value.trim();
  const fileInput = document.getElementById('upload-file');
  const textArea = document.getElementById('upload-text');
  const existingDocumentId = document.getElementById('upload-existing-doc-id').value || null;
  const departmentIds = Array.from(document.querySelectorAll('input[name="dept"]:checked')).map((i) => i.value);
  const chunkingStrategy = document.getElementById('chunking-strategy').value;
  const embeddingStrategy = document.getElementById('embedding-strategy').value;

  if (!isImplemented('chunking', chunkingStrategy) || !isImplemented('embedding', embeddingStrategy)) {
    statusEl.hidden = false;
    statusEl.className = 'auth-status is-error';
    statusEl.textContent = 'That strategy is not implemented yet. Choose an executable strategy before publishing this document version.';
    return;
  }

  let text = textArea.value.trim();
  try {
    if (fileInput.files[0]) {
      const file = fileInput.files[0];
      if (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) {
        text = await extractPdfText(file);
      } else {
        text = await file.text();
      }
    }
  } catch (err) {
    statusEl.hidden = false;
    statusEl.className = 'auth-status is-error';
    statusEl.textContent = err.message;
    return;
  }

  if (!text) {
    statusEl.hidden = false;
    statusEl.className = 'auth-status is-error';
    statusEl.textContent = 'Provide document text via file upload or the text box.';
    return;
  }

  if (!existingDocumentId && departmentIds.length === 0) {
    statusEl.hidden = false;
    statusEl.className = 'auth-status is-error';
    statusEl.textContent = 'Select at least one department for a new document.';
    return;
  }

  submitBtn.disabled = true;
  submitBtn.textContent = 'Publishing…';
  statusEl.hidden = true;

  try {
    const result = await apiFetch('/api/ingest', {
      method: 'POST',
      body: JSON.stringify({
        title,
        text,
        departmentIds,
        existingDocumentId,
        chunkingStrategy,
        embeddingStrategy,
      }),
    });

    statusEl.hidden = false;
    statusEl.className = 'auth-status';
    statusEl.textContent = `Published v${result.versionNumber} — ${result.chunksCreated} chunks created using ${formatStrategy(result.chunkingStrategy)} and ${formatStrategy(result.embeddingStrategy)}.`;

    document.getElementById('upload-form').reset();
    document.getElementById('upload-existing-doc-id').value = '';
    resetUploadStrategyDefaults();
    window.history.replaceState({}, document.title, '/admin');
    window.dispatchEvent(new CustomEvent('documents-changed'));
    updateUploadStrategyStatus();
  } catch (err) {
    statusEl.hidden = false;
    statusEl.className = 'auth-status is-error';
    statusEl.textContent = err.message;
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Publish document';
  }
}

function resetUploadStrategyDefaults() {
  const chunking = uploadStrategies.chunking.find((strategy) => strategy.default) || uploadStrategies.chunking[0];
  const embedding = uploadStrategies.embedding.find((strategy) => strategy.default) || uploadStrategies.embedding[0];
  if (chunking) document.getElementById('chunking-strategy').value = chunking.id;
  if (embedding) document.getElementById('embedding-strategy').value = embedding.id;
}

function isImplemented(group, id) {
  return uploadStrategies[group].some((strategy) => strategy.id === id && strategy.implemented);
}

function formatStrategy(value) {
  const labels = {
    fixed_size_v1: 'Fixed Size',
    recursive: 'Recursive',
    sentence: 'Sentence Based',
    semantic: 'Semantic',
    section_aware: 'Section Aware',
    parent_child: 'Parent / Child',
    bge_small: 'BGE Small',
    bge_base: 'BGE Base',
    e5_base: 'E5 Base',
    openai_small: 'OpenAI Small',
  };
  return labels[value] || value || 'Unknown';
}

async function extractPdfText(file) {
  if (!window.pdfjsLib) {
    throw new Error('PDF support is unavailable. Refresh the page and try again.');
  }

  window.pdfjsLib.GlobalWorkerOptions.workerSrc =
    'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
  const pdf = await window.pdfjsLib.getDocument({ data: await file.arrayBuffer() }).promise;
  const pages = [];

  for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
    const page = await pdf.getPage(pageNumber);
    const content = await page.getTextContent();
    pages.push(content.items.map((item) => item.str).join(' '));
  }

  const text = pages.join('\n\n').trim();
  if (!text) {
    throw new Error('This PDF contains no selectable text. Upload a text-based PDF or paste its text below.');
  }
  return text;
}
