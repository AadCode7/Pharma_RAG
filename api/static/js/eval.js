document.addEventListener('auth-ready', initEvaluation);

let evaluationTraces = [];
const selectedTraceIds = new Set();

async function initEvaluation() {
  document.getElementById('eval-refresh').addEventListener('click', loadEvaluationTraces);
  document.getElementById('eval-select-visible').addEventListener('click', function () {
    evaluationTraces.forEach(function (trace) { selectedTraceIds.add(String(trace.id)); });
    renderEvaluationTraces();
  });
  document.getElementById('eval-clear-selection').addEventListener('click', function () {
    selectedTraceIds.clear();
    renderEvaluationTraces();
  });
  document.getElementById('eval-run').addEventListener('click', runEvaluation);
  await loadEvaluationTraces();
}

async function loadEvaluationTraces() {
  const status = document.getElementById('eval-trace-status');
  status.textContent = 'Loading recent traces…';
  status.className = 'eval-status';
  try {
    const data = await apiFetch('/api/evaluation/traces?limit=100');
    evaluationTraces = data.traces || [];
    const visibleIds = new Set(evaluationTraces.map(function (trace) { return String(trace.id); }));
    Array.from(selectedTraceIds).forEach(function (id) { if (!visibleIds.has(id)) selectedTraceIds.delete(id); });
    status.textContent = evaluationTraces.length
      ? evaluationTraces.length + ' recent traces loaded. Add labels to selected rows if available.'
      : 'No pipeline traces are available yet. Submit queries on the Query page first.';
    renderEvaluationTraces();
  } catch (err) {
    status.className = 'eval-status is-error';
    status.textContent = 'Could not load traces: ' + err.message;
  }
}

function renderEvaluationTraces() {
  const list = document.getElementById('eval-trace-list');
  list.innerHTML = '';
  evaluationTraces.forEach(function (trace) {
    const id = String(trace.id);
    const stage = trace.stage || {};
    const chunks = Array.isArray(stage.retrieved_chunks) ? stage.retrieved_chunks : [];
    const article = document.createElement('article');
    article.className = 'eval-trace-card' + (selectedTraceIds.has(id) ? ' is-selected' : '');

    const head = document.createElement('div');
    head.className = 'eval-trace-head';
    const checkboxLabel = document.createElement('label');
    checkboxLabel.className = 'eval-trace-check';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = selectedTraceIds.has(id);
    checkbox.addEventListener('change', function () {
      if (checkbox.checked) selectedTraceIds.add(id);
      else selectedTraceIds.delete(id);
      renderEvaluationTraces();
    });
    const query = document.createElement('span');
    query.className = 'eval-trace-query';
    query.textContent = trace.query_text || '(empty query)';
    checkboxLabel.append(checkbox, query);
    const date = document.createElement('time');
    date.className = 'eval-trace-date';
    date.textContent = trace.created_at ? new Date(trace.created_at).toLocaleString() : '';
    head.append(checkboxLabel, date);

    const meta = document.createElement('p');
    meta.className = 'eval-trace-meta';
    meta.textContent = (stage.retrieval_strategy || 'unknown retrieval') + ' · ' +
      (stage.reranking_strategy || 'unknown reranking') + ' · ' + chunks.length + ' retrieved chunks';

    const labels = document.createElement('div');
    labels.className = 'eval-reference-fields';
    const relevantLabel = document.createElement('label');
    relevantLabel.textContent = 'Relevant document IDs (comma-separated, optional)';
    const relevantInput = document.createElement('input');
    relevantInput.type = 'text';
    relevantInput.className = 'eval-relevant-docs';
    relevantInput.placeholder = 'Paste known-relevant document UUIDs';
    relevantInput.dataset.traceId = id;
    relevantInput.value = trace._evalRelevantDocumentIds || '';
    relevantInput.disabled = !selectedTraceIds.has(id);
    relevantLabel.appendChild(relevantInput);

    const answerLabel = document.createElement('label');
    answerLabel.textContent = 'Expected answer (optional)';
    const answerInput = document.createElement('textarea');
    answerInput.rows = 2;
    answerInput.className = 'eval-reference-answer';
    answerInput.placeholder = 'Enter a verified reference answer for text-overlap metrics';
    answerInput.dataset.traceId = id;
    answerInput.value = trace._evalReferenceAnswer || '';
    answerInput.disabled = !selectedTraceIds.has(id);
    answerLabel.appendChild(answerInput);
    labels.append(relevantLabel, answerLabel);

    const sources = document.createElement('details');
    sources.className = 'eval-trace-sources';
    const sourceSummary = document.createElement('summary');
    sourceSummary.textContent = 'Inspect retrieved sources';
    sources.appendChild(sourceSummary);
    const sourceList = document.createElement('ol');
    chunks.forEach(function (chunk) {
      const li = document.createElement('li');
      const title = chunk.document_title || chunk.document_id || 'Unknown source';
      const content = chunk.content || '';
      li.textContent = title + (chunk.document_id ? ' [' + chunk.document_id + ']' : '') + ': ' + content.slice(0, 240);
      sourceList.appendChild(li);
    });
    if (!chunks.length) {
      const li = document.createElement('li');
      li.textContent = 'No chunks were recorded for this trace.';
      sourceList.appendChild(li);
    }
    sources.appendChild(sourceList);
    article.append(head, meta, labels, sources);
    list.appendChild(article);
  });
  updateSelectedCount();
}

function updateSelectedCount() {
  const count = selectedTraceIds.size;
  document.getElementById('eval-selected-count').textContent = count + ' selected';
  document.getElementById('eval-run').disabled = count === 0;
}

async function runEvaluation() {
  const button = document.getElementById('eval-run');
  const status = document.getElementById('eval-trace-status');
  const selected = evaluationTraces.filter(function (trace) { return selectedTraceIds.has(String(trace.id)); });
  if (!selected.length) return;

  const items = selected.map(function (trace) {
    const id = String(trace.id);
    const relevantInput = document.querySelector('.eval-relevant-docs[data-trace-id="' + id + '"]');
    const answerInput = document.querySelector('.eval-reference-answer[data-trace-id="' + id + '"]');
    const relevant = relevantInput ? relevantInput.value : '';
    const answer = answerInput ? answerInput.value : '';
    trace._evalRelevantDocumentIds = relevant;
    trace._evalReferenceAnswer = answer;
    return {
      trace_id: id,
      relevant_document_ids: relevant.split(',').map(function (value) { return value.trim(); }).filter(Boolean),
      reference_answer: answer.trim() || null
    };
  });

  button.disabled = true;
  button.textContent = 'Evaluating…';
  status.className = 'eval-status';
  status.textContent = 'Calculating deterministic metrics from stored traces…';
  try {
    const data = await apiFetch('/api/evaluation/run', {
      method: 'POST',
      body: JSON.stringify({ items: items, k: Number(document.getElementById('eval-k').value) })
    });
    renderEvaluationResults(data);
    status.textContent = 'Evaluation run ' + data.run_id + ' completed for ' + data.count + ' queries.';
  } catch (err) {
    status.className = 'eval-status is-error';
    status.textContent = 'Evaluation failed: ' + err.message;
  } finally {
    button.disabled = selectedTraceIds.size === 0;
    button.textContent = 'Run evaluation';
  }
}

function formatMetric(value, unit) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  if (unit === 'ms') return Math.round(Number(value)) + ' ms';
  return (Number(value) * 100).toFixed(1) + '%';
}

function renderEvaluationResults(data) {
  document.getElementById('eval-results-section').hidden = false;
  document.getElementById('eval-run-meta').textContent =
    data.count + ' queries · K=' + document.getElementById('eval-k').value + ' · run ' + data.run_id;
  const summary = data.summary || {};
  const cards = [
    ['Recall@K', summary.recall_at_k, summary.recall_at_k_coverage, 'labeled queries'],
    ['Precision@K', summary.precision_at_k, summary.precision_at_k_coverage, 'labeled queries'],
    ['MRR@K', summary.mrr_at_k, summary.mrr_at_k_coverage, 'labeled queries'],
    ['Context token recall', summary.context_token_recall, summary.context_token_recall_coverage, 'reference answers'],
    ['Answer token F1', summary.answer_token_f1, summary.answer_token_f1_coverage, 'reference answers'],
    ['ROUGE-L', summary.answer_rouge_l, summary.answer_rouge_l_coverage, 'reference answers'],
    ['Average latency', summary.latency_ms, summary.latency_ms_coverage, 'traces']
  ];
  const grid = document.getElementById('eval-summary');
  grid.innerHTML = '';
  cards.forEach(function (entry) {
    const card = document.createElement('article');
    card.className = 'eval-metric-card';
    const title = document.createElement('p');
    title.className = 'eval-metric-label';
    title.textContent = entry[0];
    const score = document.createElement('strong');
    score.className = 'eval-metric-value';
    score.textContent = entry[1] == null ? 'N/A' : formatMetric(entry[1], entry[0] === 'Average latency' ? 'ms' : '');
    const detail = document.createElement('p');
    detail.className = 'eval-metric-coverage';
    detail.textContent = (entry[2] || 0) + ' ' + entry[3];
    card.append(title, score, detail);
    grid.appendChild(card);
  });

  const tbody = document.getElementById('eval-results-body');
  tbody.innerHTML = '';
  (data.results || []).forEach(function (row) {
    const tr = document.createElement('tr');
    const values = [
      row.query_text || '',
      row.retrieval_strategy + ' / ' + row.reranking_strategy,
      formatMetric(row.recall_at_k),
      formatMetric(row.precision_at_k),
      formatMetric(row.mrr_at_k),
      formatMetric(row.context_token_recall),
      formatMetric(row.answer_token_f1),
      formatMetric(row.answer_rouge_l),
      formatMetric(row.latency_ms, 'ms')
    ];
    values.forEach(function (value, index) {
      const td = document.createElement('td');
      td.textContent = value;
      if (index === 0) td.className = 'eval-query-cell';
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}
