const state = { runs: [], tasks: [], messages: [], promptExposureIndices: [], promptExposureNumbers: [], attackObservationIndices: [], attackObservationKind: null, runId: null, taskId: null };
const $ = (id) => document.getElementById(id);

async function api(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}
function esc(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function pretty(value) {
  if (typeof value === 'string') {
    try { return JSON.stringify(JSON.parse(value), null, 2); } catch (_) { return value; }
  }
  return JSON.stringify(value, null, 2);
}
function normalizePayload(value) {
  let normalized = value;
  if (typeof normalized === 'string') {
    try { normalized = JSON.parse(normalized); } catch (_) { return normalized; }
  }
  if (Array.isArray(normalized) && normalized.length && normalized.every(item => item && typeof item === 'object' && item.type === 'text' && typeof item.text === 'string')) {
    return normalizePayload(normalized.map(item => item.text).join('\n'));
  }
  if (normalized && typeof normalized === 'object' && Array.isArray(normalized.content)) {
    const content = normalizePayload(normalized.content);
    if (typeof content === 'string') return content;
  }
  return normalized;
}
function payloadText(value) {
  const normalized = normalizePayload(value);
  if (typeof normalized === 'string') return normalized;
  if (normalized === undefined) return '';
  return JSON.stringify(normalized, null, 2);
}
function looksLikeCode(key, value) {
  if (typeof value !== 'string' || !value.includes('\n')) return false;
  if (/^(code|script|command|cmd|query|sql|source|program)$/i.test(key)) return true;
  return /(^|\n)\s*(import |from .+ import |def |class |function |const |let |var |SELECT |WITH |#!|cat .+<<|python\b)/m.test(value);
}
function renderCode(value) {
  const lines = value.split('\n').map(line => `<span class="code-line">${esc(line) || ' '}</span>`).join('');
  return `<div class="code-shell"><button class="copy-code" type="button">Copy</button><pre class="code-payload"><code>${lines}</code></pre></div>`;
}
function renderFieldValue(value, key = '') {
  const normalized = normalizePayload(value);
  if (normalized && typeof normalized === 'object' && !Array.isArray(normalized)) {
    const nested = Object.entries(normalized).map(([nestedKey, nestedValue]) => `<div class="payload-field nested"><div class="payload-key">${esc(nestedKey)}</div>${renderFieldValue(nestedValue, nestedKey)}</div>`).join('');
    return `<div class="nested-payload">${nested}</div>`;
  }
  const text = payloadText(normalized);
  return looksLikeCode(key, text) ? renderCode(text) : `<pre>${esc(text)}</pre>`;
}
function renderPayload(value, extraClass = '') {
  const normalized = normalizePayload(value);
  if (normalized && typeof normalized === 'object' && !Array.isArray(normalized)) {
    const fields = Object.entries(normalized).map(([key, fieldValue]) => `<div class="payload-field"><div class="payload-key">${esc(key)}</div>${renderFieldValue(fieldValue, key)}</div>`).join('');
    return `<div class="tool-call structured ${extraClass}">${fields}</div>`;
  }
  const text = payloadText(normalized);
  if (looksLikeCode('', text)) return `<div class="tool-call structured ${extraClass}">${renderCode(text)}</div>`;
  return `<pre class="tool-call payload ${extraClass}">${esc(text)}</pre>`;
}
function summarizePayload(value, key = '') {
  const normalized = normalizePayload(value);
  if (normalized && typeof normalized === 'object' && !Array.isArray(normalized)) {
    return Object.entries(normalized).map(([nestedKey, nestedValue]) => `${nestedKey}: ${summarizePayload(nestedValue, nestedKey)}`).join(', ');
  }
  const text = payloadText(normalized);
  if (looksLikeCode(key, text)) return `[code: ${text.split('\n').length} lines]`;
  return text.replace(/\s+/g, ' ');
}
function previewMarkup(message) {
  if (message.role === 'assistant' && message.tool_calls?.length) {
    const calls = message.tool_calls.map(call => {
      const name = call.name || call.function?.name || 'tool';
      const args = summarizePayload(call.arguments ?? call.function?.arguments ?? {});
      return `<strong class="preview-tool-name">${esc(name)}</strong><span class="preview-tool-args">(${esc(args)})</span>`;
    });
    return `<span class="preview-prefix">Tool call:</span> ${calls.join(' <span class="preview-separator">·</span> ')}`;
  }
  const text = payloadText(message.content ?? '').replace(/\s+/g, ' ').slice(0, 300);
  const prefix = message.role === 'tool' ? 'Tool result: ' : '';
  return esc(prefix + (text || 'Empty message'));
}
async function loadRuns() {
  $('run-list').innerHTML = '<div class="loading">Scanning…</div>';
  try { state.runs = (await api('/api/runs')).runs; renderRuns(); }
  catch (e) { $('run-list').innerHTML = `<div class="loading">${esc(e.message)}</div>`; }
}
function renderRuns() {
  const query = $('run-search').value.toLowerCase();
  const runs = state.runs.filter(r => r.id.toLowerCase().includes(query));
  $('run-list').innerHTML = runs.length ? runs.map(r => `<button class="run-item ${r.id === state.runId ? 'active' : ''}" data-run="${esc(r.id)}"><div class="item-title">${esc(r.id)}</div></button>`).join('') : '<div class="loading">No matching runs</div>';
  document.querySelectorAll('[data-run]').forEach(el => el.onclick = () => selectRun(el.dataset.run));
}
function formatDuration(totalSeconds) {
  const seconds = Math.max(0, Number(totalSeconds) || 0);
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = Math.floor(seconds % 60);
  const parts = [];
  if (days) parts.push(`${days}d`);
  if (hours || days) parts.push(`${hours}h`);
  if (minutes || hours || days) parts.push(`${minutes}m`);
  if (!days && !hours) parts.push(`${remainingSeconds}s`);
  return parts.join(' ');
}
function renderScoreSummary(summary, modelInfo = null, jobTiming = null) {
  const container = $('run-score-summary');
  const chips = [];
  if (modelInfo?.model) {
    const effort = modelInfo.reasoning_effort ? ` (${modelInfo.reasoning_effort})` : '';
    chips.push(`<span class="score-chip model-chip"><b>${esc(modelInfo.model + effort)}</b><small>Model</small></span>`);
  }
  if (jobTiming) {
    const suffix = jobTiming.status === 'running' ? ' · running' : jobTiming.status === 'interrupted' ? ' · interrupted' : '';
    chips.push(`<span class="score-chip duration-chip"><b>${esc(formatDuration(jobTiming.duration_seconds))}</b><small>Job duration${esc(suffix)}</small></span>`);
  }
  if (summary) {
    const metrics = [
      ['Completed', summary.completed_task_count ?? '—'],
      ['Mean score', summary.average_mean_score == null ? '—' : Number(summary.average_mean_score).toFixed(4)],
      ['Pass@1', summary.average_pass_at_1_percent == null ? '—' : (Number(summary.average_pass_at_1_percent) * 100).toFixed(2) + '%'],
      ['Pass@1 count', summary.pass_at_1_count ?? '—'],
    ];
    if (summary.attack_evaluated_count != null) {
      metrics.push(
        ['Attack ASR', (Number(summary.average_attack_success || 0) * 100).toFixed(2) + '%'],
        ['Attack success', `${summary.attack_success_count ?? 0}/${summary.attack_evaluated_count}`],
      );
    }
    if (summary.prompt_exposure_task_count != null) {
      metrics.push(['Prompt exposure', `${summary.prompt_exposure_count ?? 0}/${summary.prompt_exposure_task_count}`]);
    }
    chips.push(...metrics.map(([label, value]) => `<span class="score-chip"><b>${esc(value)}</b><small>${esc(label)}</small></span>`));
  }
  container.innerHTML = chips.join('') || '<span class="score-loading">Run metadata unavailable</span>';
}
async function selectRun(runId) {
  state.runId = runId; state.taskId = null; state.messages = []; renderRuns();
  $('empty').classList.add('hidden'); $('run-view').classList.remove('hidden'); $('run-title').textContent = runId;
  $('trajectory-view').classList.add('hidden'); $('trajectory-empty').classList.remove('hidden');
  $('task-list').innerHTML = '<div class="loading">Loading tasks…</div>';
  $('run-score-summary').innerHTML = '<span class="score-loading">Loading score summary…</span>';
  try {
    const data = await api(`/api/runs/${encodeURIComponent(runId)}/tasks`);
    state.tasks = data.tasks;
    renderScoreSummary(data.score_summary, data.model_info, data.job_timing);
    renderTasks();
  } catch (e) {
    $('task-list').innerHTML = `<div class="loading">${esc(e.message)}</div>`;
    renderScoreSummary(null);
  }
}
function renderTasks() {
  const query = $('task-search').value.toLowerCase();
  const tasks = state.tasks.filter(t => t.id.toLowerCase().includes(query));
  $('task-count').textContent = `${tasks.length}/${state.tasks.length}`;
  $('task-list').innerHTML = tasks.length ? tasks.map(t => {
    const score = t.score == null ? '—' : Number(t.score).toFixed(4);
    const attack = t.attack_success == null ? '' : `<span class="task-score attack-score attack-${Number(t.attack_success) === 1 ? 'pass' : 'fail'}">Attack ${esc(t.attack_success)}</span>`;
    const exposureNumbers = t.prompt_exposure_message_numbers || [];
    const exposure = t.prompt_exposure === 1 ? `<span class="exposure-label">Prompt exposure · Message ${exposureNumbers.map(number => '#' + number).join(', ') || 'detected'}</span>` : '';
    const observedNumbers = t.attack_observation_message_numbers || [];
    const observed = t.attack_observation === 1 ? `<span class="observation-label">${t.attack_observation_kind === 'lure_text_seen' ? 'Lure seen' : 'Script executed'} · Message ${observedNumbers.map(number => '#' + number).join(', ')}</span>` : '';
    const rules = Object.entries(t.attack_rules || {}).map(([name, rule]) => `<span class="rule-result rule-${Number(rule.passed) === 1 ? 'pass' : 'fail'}" title="${esc(rule.description || '')}">${esc(name)} ${Number(rule.passed) === 1 ? '✓' : '×'}</span>`).join('');
    return `<button class="task-item ${t.id === state.taskId ? 'active' : ''}" data-task="${esc(t.id)}" ${t.status !== 'ready' ? 'title="No trajectory.json yet"' : ''}><div class="task-item-head"><div class="item-title">${esc(t.id.replace('task_', ''))}</div><div class="task-badges"><span class="task-score">Score ${esc(score)}</span>${attack}</div></div><div class="item-meta"><span><i class="dot ${t.status}"></i>${t.status === 'ready' ? 'Ready' : 'No trajectory'}</span>${exposure}${observed}</div>${rules ? `<div class="rule-results">${rules}</div>` : ''}</button>`;
  }).join('') : '<div class="loading">No matching tasks</div>';
  document.querySelectorAll('[data-task]').forEach(el => el.onclick = () => selectTask(el.dataset.task));
}
async function selectTask(taskId) {
  const task = state.tasks.find(t => t.id === taskId);
  if (!task || task.status !== 'ready') return;
  state.taskId = taskId; renderTasks(); $('trajectory-empty').classList.add('hidden'); $('trajectory-view').classList.remove('hidden');
  $('task-title').textContent = taskId; $('messages').innerHTML = '<div class="loading">Loading trajectory…</div>';
  try {
    const data = await api(`/api/runs/${encodeURIComponent(state.runId)}/tasks/${encodeURIComponent(taskId)}/trajectory`);
    state.messages = data.messages;
    state.promptExposureIndices = data.results?.prompt_exposure_message_indices || [];
    state.promptExposureNumbers = data.results?.prompt_exposure_message_numbers || [];
    state.attackObservationIndices = data.results?.attack_observation_message_indices || [];
    state.attackObservationKind = data.results?.attack_observation_kind || null;
    const security = [];
    if (data.results?.attack_success != null) security.push(`Attack ${data.results.attack_success}`);
    if (data.results?.prompt_exposure === 1) {
      const numbers = state.promptExposureNumbers.map(number => `#${number}`);
      security.push(`Prompt exposure · Message ${numbers.join(', ') || 'detected'}`);
    }
    if (data.results?.attack_observation === 1) {
      const label = state.attackObservationKind === 'lure_text_seen' ? 'Lure seen' : 'Script executed';
      security.push(`${label} · Message ${(data.results.attack_observation_message_numbers || []).map(number => '#' + number).join(', ')}`);
    }
    const rules = Object.entries(data.results?.attack_rules || {}).map(([name, rule]) => `<span class="security-pill rule-${Number(rule.passed) === 1 ? 'pass' : 'fail'}" title="${esc(rule.description || '')}">${esc(name)} ${Number(rule.passed) === 1 ? 'passed' : 'failed'}</span>`);
    $('task-security-summary').innerHTML = security.map(value => `<span class="security-pill">${esc(value)}</span>`).concat(rules).join('');
    renderMessageSummaries();
  } catch (e) { $('messages').innerHTML = `<div class="notice error">${esc(e.message)}</div>`; }
}
function renderMessageSummaries() {
  $('message-count').textContent = `${state.messages.length} messages`;
  // Only lightweight summaries are created up front. Large bodies are rendered on first expansion.
  $('messages').innerHTML = state.messages.map((m, i) => {
    const observed = state.attackObservationIndices.includes(i);
    const exposed = state.promptExposureIndices.includes(i);
    const labels = [];
    if (observed) labels.push(state.attackObservationKind === 'lure_text_seen' ? 'Lure text seen' : 'Script execution');
    if (exposed) labels.push('Prompt exposure');
    const badge = labels.length ? `<span class="message-exposure">${esc(labels.join(' · '))}</span>` : '';
    return `<details class="message ${observed ? 'attack-observation' : ''} ${exposed ? 'prompt-exposure' : ''}" data-message-index="${i}"><summary><span class="msg-number">#${String(i + 1).padStart(3, '0')}</span><span class="role ${esc(m.role || 'unknown')}">${esc(m.role || 'unknown')}</span><span class="preview">${previewMarkup(m)}</span>${badge}<span class="chevron">›</span></summary><div class="message-body"><span class="loading">Expand to load</span></div></details>`;
  }).join('');
  $('messages').scrollTop = 0;
}
function renderMessageBody(message) {
  let body = '';
  if (message.role === 'tool') {
    body = `<div class="block"><div class="block-label">TOOL RESULT</div>${renderPayload(message.content ?? '', 'result')}</div>`;
  } else {
    if (message.reasoning_content) body += `<div class="block"><div class="block-label">REASONING</div><div class="content">${esc(message.reasoning_content)}</div></div>`;
    if (message.content !== undefined && message.content !== null && message.content !== '') body += `<div class="block"><div class="block-label">CONTENT</div><div class="content">${esc(typeof message.content === 'string' ? message.content : pretty(message.content))}</div></div>`;
    if (message.tool_calls?.length) {
      body += `<div class="block"><div class="block-label">TOOL CALL ARGUMENTS · ${message.tool_calls.length}</div>`;
      body += message.tool_calls.map((call, index) => `<div class="tool-entry"><div class="tool-name">#${index + 1} ${esc(call.function?.name || call.name || 'tool')}</div>${renderPayload(call.function?.arguments ?? call.arguments ?? {})}</div>`).join('');
      body += '</div>';
    }
  }
  return body || '<span class="loading">Empty message</span>';
}
$('messages').addEventListener('toggle', event => {
  const detail = event.target;
  if (!detail.matches?.('.message') || !detail.open || detail.dataset.loaded) return;
  detail.querySelector('.message-body').innerHTML = renderMessageBody(state.messages[Number(detail.dataset.messageIndex)]);
  detail.dataset.loaded = 'true';
}, true);
document.getElementById("messages").addEventListener("click", async event => {
  const button = event.target.closest?.(".copy-code");
  if (!button) return;
  const text = button.parentElement.querySelector(".code-payload").innerText;
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = "Copied";
    setTimeout(() => { button.textContent = "Copy"; }, 1200);
  } catch (_) {
    button.textContent = "Copy failed";
  }
});

async function generateAnalytics() {
  const button = $('generate-analytics'); button.disabled = true; button.textContent = 'Running…';
  $('analytics-status').className = 'notice'; $('analytics-status').textContent = 'Running both analytics scripts. This may take a few seconds…';
  try {
    const data = await api(`/api/runs/${encodeURIComponent(state.runId)}/analytics`, {method:'POST'});
    const failures = data.commands.filter(c => !c.ok);
    $('analytics-status').className = `notice ${failures.length ? 'error' : ''}`;
    $('analytics-status').textContent = failures.length ? `${failures.length} script(s) failed. Expand the output below for details.` : 'Analytics generated.';
    const s = data.round_summary;
    $('summary-cards').innerHTML = s ? [['Completed tasks',s.completed_tasks],['Successful tasks',s.successful_tasks],['Total rounds',s.total_rounds],['Mean rounds',Number(s.mean_rounds).toFixed(2)],['Median rounds',Number(s.median_rounds).toFixed(1)],['P90 rounds',Number(s.p90_rounds).toFixed(1)],['Minimum rounds',s.min_rounds],['Maximum rounds',s.max_rounds]].map(([k,v]) => `<div class="metric"><strong>${esc(v)}</strong><span>${esc(k)}</span></div>`).join('') : '';
    document.getElementById("round-plot-wrap").classList.toggle("hidden", !data.has_round_plot);
    if (data.has_round_plot) document.getElementById("round-plot").src = "/api/runs/" + encodeURIComponent(state.runId) + "/round-plot?t=" + Date.now();
    document.getElementById("plot-wrap").classList.toggle("hidden", !data.has_duration_plot);
    if (data.has_duration_plot) $('duration-plot').src = `/api/runs/${encodeURIComponent(state.runId)}/duration-plot?t=${Date.now()}`;
    $('command-output').innerHTML = data.commands.map(c => `<details class="command-card"><summary>${c.ok ? '✓' : '×'} ${esc(c.script)}</summary><pre class="json">${esc([c.stdout,c.stderr].filter(Boolean).join('\n') || '(no output)')}</pre></details>`).join('');
  } catch (e) { $('analytics-status').className = 'notice error'; $('analytics-status').textContent = e.message; }
  finally { button.disabled = false; button.textContent = 'Generate / Refresh'; }
}

document.querySelectorAll('.tab').forEach(tab => tab.onclick = () => {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t === tab));
  $('trajectories-panel').classList.toggle('hidden', tab.dataset.tab !== 'trajectories');
  $('analytics-panel').classList.toggle('hidden', tab.dataset.tab !== 'analytics');
});
$('refresh').onclick = async () => {
  const currentRun = state.runId;
  const currentTask = state.taskId;
  await loadRuns();
  if (currentRun) await selectRun(currentRun);
  if (currentTask) await selectTask(currentTask);
}; $('run-search').oninput = renderRuns; $('task-search').oninput = renderTasks; $('generate-analytics').onclick = generateAnalytics;
loadRuns();
