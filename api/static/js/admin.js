document.addEventListener('auth-ready', (e) => {
  // Every route in api/main.py is reachable by URL regardless of role —
  // RLS/require_manager() on the API stops an employee from actually
  // reading or writing manager-only data, but the /admin page itself has
  // no reason to render for them at all. Bounce them to the query page.
  if (e.detail.role !== 'manager') {
    window.location.replace('/');
    return;
  }

  loadDepartmentCheckboxes();
  loadAdminDocs();
  document.getElementById('upload-form').addEventListener('submit', handleUploadSubmit);
});

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
    renderDocList(list, documents); // defined in api-client.js — shared with sources.js

    // Manager-only extra actions per document: publish a new version, or delete it entirely.
    Array.from(list.children).forEach((li, i) => {
      const doc = documents[i];
      if (!doc) return;

      const actions = document.createElement('div');
      actions.className = 'doc-actions';

      const versionBtn = document.createElement('button');
      versionBtn.className = 'btn-text';
      versionBtn.textContent = 'Publish new version';
      versionBtn.addEventListener('click', () => {
        document.getElementById('upload-existing-doc-id').value = doc.id;
        document.getElementById('upload-title').value = doc.title;
        document.getElementById('upload-title').scrollIntoView({ behavior: 'smooth' });
      });

      const deleteBtn = document.createElement('button');
      deleteBtn.className = 'btn-text btn-text-danger';
      deleteBtn.textContent = 'Delete';
      deleteBtn.addEventListener('click', () => handleDeleteDocument(doc, deleteBtn));

      actions.append(versionBtn, deleteBtn);
      li.appendChild(actions);
    });
  } catch (err) {
    list.innerHTML = `<li style="color: var(--error);">${escapeHtml(err.message)}</li>`;
  }
}

async function handleDeleteDocument(doc, btn) {
  // Hard delete — every version, chunk, and embedding goes with it (see
  // delete_document() in ingestion_service.py). Nothing is kept for audit,
  // which is why this asks for confirmation instead of being one click.
  const confirmed = window.confirm(
    `Delete "${doc.title}" permanently?\n\nThis removes every version, chunk, and embedding. ` +
      `It cannot be undone and nothing is kept for audit.`
  );
  if (!confirmed) return;

  btn.disabled = true;
  btn.textContent = 'Deleting…';

  try {
    await apiFetch(`/api/documents/${doc.id}`, { method: 'DELETE' });
    loadAdminDocs();
  } catch (err) {
    btn.disabled = false;
    btn.textContent = 'Delete';
    window.alert(`Could not delete "${doc.title}": ${err.message}`);
  }
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

  let text = textArea.value.trim();
  if (fileInput.files[0]) {
    const file = fileInput.files[0];
    if (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) {
      text = await extractPdfText(file);
    } else {
      text = await file.text();
    }
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
