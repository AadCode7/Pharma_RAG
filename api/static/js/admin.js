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

  populateStrategySelect(document.getElementById('chunking-strategy'), uploadStrategies.chunking, 'coming next');
  populateStrategySelect(document.getElementById('embedding-strategy'), uploadStrategies.embedding, 'not available');

  document.getElementById('chunking-strategy').addEventListener('change', updateSelectedUploadConfig);
  document.getElementById('embedding-strategy').addEventListener('change', updateSelectedUploadConfig);
  updateUploadStrategyStatus();
}

function populateStrategySelect(select, strategies, unavailableSuffix = 'coming next') {
  select.innerHTML = '';
  strategies.forEach((strategy) => {
    const option = document.createElement('option');
    option.value = strategy.id;
    option.textContent = strategy.implemented ? strategy.label : `${strategy.label} — ${unavailableSuffix}`;
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
    status.textContent = `Executable configuration: ${chunking.textContent.replace(/ — (coming next|not available)$/, '')} chunking with ${embedding.textContent.replace(/ — (coming next|not available)$/, '')} embeddings.`;
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
  const indexGraph = document.getElementById('graph-index-enabled').checked;

  if (!isImplemented('chunking', chunkingStrategy) || !isImplemented('embedding', embeddingStrategy)) {
    statusEl.hidden = false;
    statusEl.className = 'auth-status is-error';
    statusEl.textContent = 'That strategy is not implemented yet. Choose an executable strategy before publishing this document version.';
    return;
  }

  submitBtn.disabled = true;
  submitBtn.textContent = 'Preparing document…';
  statusEl.hidden = true;

  try {
    let text = textArea.value.trim();
    let extractionSource = 'text';
    let ocrWarning = '';
    const file = fileInput.files[0];

    if (file) {
      const name = file.name.toLowerCase();
      if (file.type === 'application/pdf' || name.endsWith('.pdf')) {
        extractionSource = 'pdf';
        submitBtn.textContent = 'Extracting PDF text…';
        text = await extractPdfText(file);
      } else if (isImageFile(file)) {
        extractionSource = 'image';
        statusEl.hidden = false;
        statusEl.className = 'auth-status';
        statusEl.textContent = 'Preparing image for local OCR…';
        submitBtn.textContent = 'Extracting image text…';
        const extracted = await extractImageText(file, (message) => {
          statusEl.hidden = false;
          statusEl.className = 'auth-status';
          statusEl.textContent = 'Local OCR: ' + describeOcrProgress(message);
        });
        text = extracted.text;
        if (extracted.confidence < 55) {
          ocrWarning = ' OCR confidence is low; review the extracted text before relying on retrieval results.';
        }
      } else {
        extractionSource = name.endsWith('.md') ? 'markdown' : 'text';
        text = await file.text();
      }
    }

    if (!text || !text.trim()) {
      throw new Error('Provide document text, upload a text-based PDF, or upload an image containing readable text.');
    }

    if (!existingDocumentId && departmentIds.length === 0) {
      throw new Error('Select at least one department for a new document.');
    }

    submitBtn.textContent = 'Publishing…';
    statusEl.hidden = true;

    const result = await apiFetch('/api/ingest', {
      method: 'POST',
      body: JSON.stringify({
        title,
        text,
        departmentIds,
        existingDocumentId,
        chunkingStrategy,
        embeddingStrategy,
        indexGraph,
        extractionSource,
      }),
    });

    statusEl.hidden = false;
    statusEl.className = result.graphIndexingStatus === 'failed' ? 'auth-status is-error' : 'auth-status';
    let graphSummary = 'Graph indexing skipped.';
    if (result.graphIndexingStatus === 'completed') {
      graphSummary = result.graphRelationships > 0
        ? 'Graph index: ' + result.graphRelationships + ' relationships across ' + result.graphEntities + ' entities.'
        : 'Graph indexing completed, but no supported relationships were extracted from this version.';
    } else if (result.graphIndexingStatus === 'failed') {
      graphSummary = result.graphIndexingError || 'Graph indexing failed; normal vector search is still available.';
    }
    const extractionSummary = extractionSource === 'image'
      ? ' Image OCR completed in the browser.'
      : '';
    statusEl.textContent = 'Published v' + result.versionNumber + ' — ' + result.chunksCreated
      + ' chunks created using ' + formatStrategy(result.chunkingStrategy) + ' and '
      + formatStrategy(result.embeddingStrategy) + '.' + extractionSummary + ' ' + graphSummary + ocrWarning;

    document.getElementById('upload-form').reset();
    document.getElementById('upload-existing-doc-id').value = '';
    resetUploadStrategyDefaults();
    window.history.replaceState({}, document.title, '/admin');
    window.dispatchEvent(new CustomEvent('documents-changed'));
    updateUploadStrategyStatus();
  } catch (err) {
    statusEl.hidden = false;
    statusEl.className = 'auth-status is-error';
    statusEl.textContent = err.message || 'Document upload failed.';
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
    bge_small: 'Cohere English Light',
    bge_base: 'BGE Base',
    e5_base: 'E5 Base',
    openai_small: 'OpenAI Small',
  };
  return labels[value] || value || 'Unknown';
}

let tesseractScriptPromise = null;
let ocrWorkerPromise = null;
let activeOcrProgress = null;

function isImageFile(file) {
  const supportedExtension = /\.(?:jpe?g|png|webp)$/i.test(file.name || '');
  const supportedMime = ['image/jpeg', 'image/png', 'image/webp'].includes((file.type || '').toLowerCase());
  return supportedExtension || supportedMime;
}

function loadTesseractLibrary() {
  if (window.Tesseract) return Promise.resolve(window.Tesseract);
  if (!tesseractScriptPromise) {
    tesseractScriptPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = 'https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js';
      script.async = true;
      script.onload = () => window.Tesseract
        ? resolve(window.Tesseract)
        : reject(new Error('Tesseract.js loaded without exposing its OCR API.'));
      script.onerror = () => reject(new Error('Could not load Tesseract.js. Check your internet connection and retry; text and PDF uploads are unaffected.'));
      document.head.appendChild(script);
    }).catch((error) => {
      tesseractScriptPromise = null;
      throw error;
    });
  }
  return tesseractScriptPromise;
}

function describeOcrProgress(message) {
  if (!message) return 'Initializing OCR…';
  const names = {
    'loading tesseract core': 'Loading OCR engine',
    'initializing tesseract': 'Starting OCR engine',
    'loading language traineddata': 'Loading English language data',
    'initializing api': 'Preparing English recognition',
    'recognizing text': 'Recognizing image text',
  };
  const label = names[message.status] || 'Preparing OCR';
  const percent = Number.isFinite(message.progress) ? ' (' + Math.round(message.progress * 100) + '%)' : '';
  return label + percent + '…';
}

async function prepareImageForOcr(file) {
  if (typeof createImageBitmap !== 'function') return file;

  const bitmap = await createImageBitmap(file);
  try {
    const longestSide = Math.max(bitmap.width, bitmap.height);
    if (!longestSide) return file;
    // Modest upscaling can help small screenshots; large photos are capped to
    // control browser memory and OCR latency.
    const scale = Math.min(1.5, 2600 / longestSide);
    const width = Math.max(1, Math.round(bitmap.width * scale));
    const height = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d');
    if (!context) return file;

    context.fillStyle = '#fff';
    context.fillRect(0, 0, width, height);
    if ('filter' in context) context.filter = 'grayscale(1) contrast(1.12)';
    context.drawImage(bitmap, 0, 0, width, height);
    return canvas;
  } finally {
    if (typeof bitmap.close === 'function') bitmap.close();
  }
}

async function getOcrWorker(progressCallback) {
  activeOcrProgress = progressCallback;
  if (!ocrWorkerPromise) {
    ocrWorkerPromise = loadTesseractLibrary()
      .then((tesseract) => tesseract.createWorker('eng', 1, {
        logger: (message) => {
          if (typeof activeOcrProgress === 'function') activeOcrProgress(message);
        },
      }))
      .then(async (worker) => {
        await worker.setParameters({ preserve_interword_spaces: '1' });
        return worker;
      })
      .catch((error) => {
        ocrWorkerPromise = null;
        throw error;
      });
  }
  return ocrWorkerPromise;
}

function getLayoutAwareOcrText(data) {
  const paragraphs = (data.paragraphs || [])
    .map((paragraph) => (paragraph.text || '').trim())
    .filter(Boolean);
  return paragraphs.length ? paragraphs.join('\n\n') : (data.text || '');
}

async function extractImageText(file, progressCallback) {
  if (file.size > 20 * 1024 * 1024) {
    throw new Error('This image is larger than 20 MB. Resize or compress it and try again to keep browser OCR responsive.');
  }

  const inputImage = await prepareImageForOcr(file);
  const worker = await getOcrWorker(progressCallback);
  let result;
  try {
    result = await worker.recognize(inputImage);
  } catch (error) {
    ocrWorkerPromise = null;
    try {
      await worker.terminate();
    } catch (cleanupError) {
      // Keep the original OCR error as the actionable failure.
    }
    throw error;
  } finally {
    activeOcrProgress = null;
  }

  const text = getLayoutAwareOcrText(result.data).trim();
  if (!text) {
    throw new Error('Tesseract could not find readable text in this image. Try a sharper, brighter image or paste the text manually.');
  }

  const confidence = Number.isFinite(result.data.confidence) ? result.data.confidence : 0;
  return { text, confidence };
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
