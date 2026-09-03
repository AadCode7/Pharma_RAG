document.addEventListener('auth-ready', () => {
  document.getElementById('query-form').addEventListener('submit', handleSubmit);
});

async function handleSubmit(e) {
  e.preventDefault();
  const input = document.getElementById('query-input');
  const submitBtn = document.getElementById('query-submit');
  const query = input.value.trim();
  if (!query) return;

  submitBtn.disabled = true;
  submitBtn.textContent = 'Searching…';
  document.getElementById('query-empty').hidden = true;

  try {
    const result = await apiFetch('/api/query', { method: 'POST', body: JSON.stringify({ query, k: 5 }) });

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
