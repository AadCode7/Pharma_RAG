document.addEventListener('auth-ready', loadTraceList);

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

    // Deep link from the Query page: /trace?requestId=...
    const requestedId = new URLSearchParams(window.location.search).get('requestId');
    if (requestedId) {
      const match = traces.find((t) => t.request_id === requestedId);
      if (match) {
        renderTraceDetail(match);
      } else {
        const { traces: single } = await apiFetch(`/api/traces?requestId=${requestedId}`);
        if (single && single[0]) renderTraceDetail(single[0]);
      }
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
