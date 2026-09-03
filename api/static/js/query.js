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
  submitBtn.textContent = 'Thinking…';
  document.getElementById('query-empty').hidden = true;

  try {
    const result = await apiFetch('/api/query', { method: 'POST', body: JSON.stringify({ query, k: 5 }) });

    document.getElementById('answer-text').textContent = result.answer;

    const sourcesList = document.getElementById('answer-sources');
    sourcesList.innerHTML = '';
    (result.sources || []).forEach((s, i) => {
      const li = document.createElement('li');
      li.className = 'source-chip';
      li.innerHTML = `[${i + 1}] ${escapeHtml(s.document_title)} <span class="sim">${(s.similarity * 100).toFixed(0)}%</span>`;
      sourcesList.appendChild(li);
    });

    document.getElementById('view-trace-link').href = `/trace?requestId=${result.requestId}`;
    document.getElementById('query-result').hidden = false;
  } catch (err) {
    document.getElementById('answer-text').textContent = `Something went wrong: ${err.message}`;
    document.getElementById('answer-sources').innerHTML = '';
    document.getElementById('query-result').hidden = false;
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Ask';
  }
}
