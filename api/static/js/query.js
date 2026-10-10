document.addEventListener('auth-ready', async () => {
  await loadQueryStrategies();
  document.getElementById('query-form').addEventListener('submit', handleSubmit);
});

async function loadQueryStrategies() {
  const retrievalSelect = document.getElementById('retrieval-strategy');
  const rerankingSelect = document.getElementById('reranking-strategy');
  const status = document.getElementById('strategy-status');

  try {
    const { strategies } = await apiFetch('/api/strategies');
    populateStrategySelect(retrievalSelect, strategies.retrieval || []);
    populateStrategySelect(rerankingSelect, strategies.reranking || []);
    updateStrategyStatus();

    retrievalSelect.addEventListener('change', updateStrategyStatus);
    rerankingSelect.addEventListener('change', updateStrategyStatus);
  } catch (err) {
    retrievalSelect.innerHTML = '<option value="standard">Standard Dense Retrieval</option>';
    rerankingSelect.innerHTML = '<option value="none">No Reranking</option>';
    status.hidden = false;
    status.className = 'strategy-status is-error';
    status.textContent = `Could not load strategy configuration: ${err.message}`;
  }
}

function populateStrategySelect(select, strategies) {
  select.innerHTML = '';
  strategies.forEach((strategy) => {
    const option = document.createElement('option');
    option.value = strategy.id;
    option.textContent = strategy.implemented ? strategy.label : `${strategy.label} — coming next`;
    option.dataset.implemented = strategy.implemented ? 'true' : 'false';
    select.appendChild(option);
  });

  const defaultStrategy = strategies.find((strategy) => strategy.default) || strategies[0];
  if (defaultStrategy) select.value = defaultStrategy.id;
}

function updateStrategyStatus() {
  const status = document.getElementById('strategy-status');
  const retrievalOption = document.getElementById('retrieval-strategy').selectedOptions[0];
  const rerankingOption = document.getElementById('reranking-strategy').selectedOptions[0];
  const unavailable = [retrievalOption, rerankingOption].filter((option) => option?.dataset.implemented !== 'true');

  if (unavailable.length === 0) {
    status.hidden = false;
    status.className = 'strategy-status';
    status.textContent = `Current execution: ${retrievalOption?.textContent || 'Dense Retrieval (Semantic)'} with ${rerankingOption?.textContent || 'No Reranking'}.`;
    return;
  }

  status.hidden = false;
  status.className = 'strategy-status is-warning';
  status.textContent = 'The selected strategy is not implemented on this deployment yet. Choose an implemented strategy or update the deployment.';
}

async function handleSubmit(e) {
  e.preventDefault();
  const input = document.getElementById('query-input');
  const submitBtn = document.getElementById('query-submit');
  const query = input.value.trim();
  const retrievalStrategy = document.getElementById('retrieval-strategy').value;
  const rerankingStrategy = document.getElementById('reranking-strategy').value;
  if (!query) return;

  submitBtn.disabled = true;
  submitBtn.textContent = 'Searching…';
  document.getElementById('query-empty').hidden = true;

  try {
    const result = await apiFetch('/api/query', {
      method: 'POST',
      body: JSON.stringify({
        query,
        k: 5,
        retrievalStrategy,
        rerankingStrategy,
      }),
    });

    document.getElementById('answer-text').textContent = result.answer || 'No answer could be generated from the retrieved context.';

    const docsList = document.getElementById('answer-documents');
    docsList.innerHTML = '';
    const documents = result.sourceDocuments || dedupeDocumentsFromChunks(result.sources || []);
    if (documents.length === 0) {
      docsList.innerHTML = '<li class="source-doc-empty">No source documents were retrieved for this question.</li>';
    } else {
      documents.forEach((doc) => {
        const li = document.createElement('li');
        li.className = 'source-doc-item';
        const chunkNote = doc.chunkCount > 1 ? `${doc.chunkCount} sections used` : '1 section used';
        li.innerHTML = `
          <span class="source-doc-title">${escapeHtml(doc.documentTitle)}</span>
          <span class="source-doc-meta">${chunkNote} · ${(doc.bestSimilarity * 100).toFixed(0)}% match</span>
        `;
        docsList.appendChild(li);
      });
    }

    document.getElementById('view-trace-link').href = `/trace?requestId=${result.requestId}`;
    document.getElementById('query-result').hidden = false;
  } catch (err) {
    document.getElementById('answer-text').textContent = `Something went wrong: ${err.message}`;
    document.getElementById('answer-documents').innerHTML = '';
    document.getElementById('query-result').hidden = false;
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Ask';
  }
}

function dedupeDocumentsFromChunks(chunks) {
  const byDoc = new Map();
  chunks.forEach((chunk) => {
    const existing = byDoc.get(chunk.document_id);
    const similarity = Number(chunk.similarity || 0);
    if (!existing) {
      byDoc.set(chunk.document_id, {
        documentTitle: chunk.document_title,
        bestSimilarity: similarity,
        chunkCount: 1,
      });
      return;
    }
    existing.chunkCount += 1;
    existing.bestSimilarity = Math.max(existing.bestSimilarity, similarity);
  });
  return Array.from(byDoc.values()).sort((a, b) => b.bestSimilarity - a.bestSimilarity);
}
