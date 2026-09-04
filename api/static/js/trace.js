document.addEventListener('auth-ready', loadTraceList);

async function loadTraceList() {
  const list = document.getElementById('trace-list');
  list.innerHTML = '<li>Loading…</li>';

  try {
    const { traces } = await apiFetch('/api/traces');
    list.innerHTML = '';

    if (!traces || traces.length === 0) {
      list.innerHTML = '<li style="padding: 0.75em 0.25em; color: var(--muted);">No queries yet.</li>';
      document.getElementById('trace-gen-panel').hidden = true;
      return;
    }

    traces.forEach((t) => {
      const li = document.createElement('li');
      const btn = document.createElement('button');
      btn.innerHTML = `<span class="trace-q">${escapeHtml(truncate(t.query_text, 60))}</span><span class="trace-t">${new Date(t.created_at).toLocaleString()}</span>`;
      btn.addEventListener('click', () => {
        document.querySelectorAll('.trace-list button.is-selected').forEach((el) => el.classList.remove('is-selected'));
        btn.classList.add('is-selected');
        renderTraceDetail(t);
      });
      li.appendChild(btn);
      list.appendChild(li);
    });

    const requestedId = new URLSearchParams(window.location.search).get('requestId');
    if (requestedId) {
      const match = traces.find((t) => t.request_id === requestedId);
      if (match) {
        const idx = traces.indexOf(match);
        list.children[idx]?.querySelector('button')?.classList.add('is-selected');
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
  const detailEl = document.getElementById('trace-detail');
  const genPanel = document.getElementById('trace-gen-panel');
  const genContent = document.getElementById('trace-gen-content');
  const stage = trace.stage || {};
  const chunks = stage.retrieved_chunks || [];
  const lat = trace.latency_breakdown || {};
  const usage = stage.token_usage || {};
  const groundedAnswer = stage.grounded_answer || '';
  const reasoning = stage.generation_reasoning || '';
  const rawOutput = stage.generation_output || '';

  detailEl.innerHTML = `
    <header class="trace-detail-header">
      <p class="label">Question</p>
      <p class="trace-question">${escapeHtml(trace.query_text || '')}</p>
    </header>

    <div class="stage-block">
      <span class="stage-num">Stage 1</span>
      <h4>Chunking</h4>
      <p>Strategy: <code>${escapeHtml(stage.chunking_strategy || 'unknown')}</code></p>
    </div>

    <div class="stage-block">
      <span class="stage-num">Stage 2</span>
      <h4>Retrieval</h4>
      <p class="stage-sub">
        Strategy <code>${escapeHtml(stage.retrieval_strategy || 'standard')}</code> ·
        reranking <code>${escapeHtml(stage.reranking_strategy || 'none')}</code> ·
        ${chunks.length} chunk(s) retrieved · embedding model
        <code>${escapeHtml(stage.embedding_model || 'unknown')}</code>
      </p>
      <div class="chunk-list">
        ${chunks.map((c, i) => `
          <article class="chunk-card">
            <div class="chunk-card-head">
              <span class="chunk-ref">[${i + 1}]</span>
              <span class="chunk-doc">${escapeHtml(c.document_title)}</span>
              <span class="chunk-sim">${(c.similarity * 100).toFixed(1)}%</span>
            </div>
            <p class="chunk-body">${escapeHtml(truncate(c.content, 280))}</p>
          </article>
        `).join('') || '<p class="stage-empty">No chunks retrieved.</p>'}
      </div>
    </div>

    <div class="stage-block stage-block-compact">
      <span class="stage-num">Timing</span>
      <div class="latency-row">
        <span>embed ${lat.embedding_ms ?? '—'}ms</span>
        <span>retrieve ${lat.retrieval_ms ?? '—'}ms</span>
        <span>generate ${lat.generation_ms ?? '—'}ms</span>
        <span>total ${lat.total_ms ?? '—'}ms</span>
      </div>
    </div>
  `;

  genPanel.hidden = false;
  genContent.innerHTML = `
    <section class="gen-section">
      <h4>Model</h4>
      <p><code>${escapeHtml(stage.llm_model || 'unknown')}</code></p>
      ${usage.prompt_tokens != null ? `
        <p class="gen-meta">
          ${usage.prompt_tokens} prompt · ${usage.completion_tokens ?? '—'} completion · ${usage.total_tokens ?? '—'} total tokens
        </p>
      ` : ''}
    </section>

    ${groundedAnswer ? `
      <section class="gen-section">
        <h4>Grounded answer <span class="gen-tag">shown on Query page</span></h4>
        <div class="gen-answer-box">${escapeHtml(groundedAnswer)}</div>
      </section>
    ` : ''}

    ${reasoning ? `
      <section class="gen-section">
        <h4>Model reasoning</h4>
        <div class="gen-reasoning-box">${escapeHtml(reasoning)}</div>
      </section>
    ` : ''}

    <section class="gen-section">
      <h4>System prompt</h4>
      <pre class="prompt-block prompt-block-compact">${escapeHtml(stage.system_prompt || 'Not recorded for this trace.')}</pre>
    </section>

    <section class="gen-section">
      <h4>User prompt <span class="gen-tag">context sent to LLM</span></h4>
      <pre class="prompt-block">${escapeHtml(stage.generation_prompt || 'Not recorded for this trace.')}</pre>
    </section>

    ${rawOutput && rawOutput !== groundedAnswer ? `
      <section class="gen-section">
        <h4>Raw model output</h4>
        <pre class="prompt-block prompt-block-muted">${escapeHtml(rawOutput)}</pre>
      </section>
    ` : ''}
  `;
}
