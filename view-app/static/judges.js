'use strict';
const $ = id => document.getElementById(id);
const state = {cases: [], total: 0, selected: null, detail: null, offset: 0, listSeq: 0, detailSeq: 0, messages: []};
const sources = {saved: '原始输入已保存', reconstructed: '根据当前代码重建', unavailable: '不可用'};
function node(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
function badge(text, cls = '') { return node('span', `badge ${cls}`, text); }
function toast(text) { $('toast').textContent = text; $('toast').classList.add('visible'); clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').classList.remove('visible'), 3500); }
async function api(url, options = {}) { const r = await fetch(url, options); let data; try { data = await r.json(); } catch { throw new Error(`请求失败 (${r.status})`); } if (!r.ok) throw new Error(data.error || `请求失败 (${r.status})`); return data; }
const json = value => JSON.stringify(value, null, 2);
function query() { const p = new URLSearchParams(); for (const k of ['kind','result','model','experiment','review']) if ($(k).value) p.set(k, $(k).value); if ($('search').value.trim()) p.set('q', $('search').value.trim()); return p; }
function setOptions(id, values) { const e = $(id), old = e.value; e.replaceChildren(new Option(id === 'model' ? '全部模型' : '全部实验', '')); values.forEach(v => e.append(new Option(v, v))); e.value = old; }
function renderCases() {
  $('cases').replaceChildren();
  if (!state.cases.length) $('cases').append(node('div','placeholder','没有符合条件的 case。Security 仅展示今后保存了完整请求的调用。'));
  for (const c of state.cases) {
    const e = node('button', 'case-item' + (c.id === state.selected ? ' active' : '')); e.dataset.id = c.id;
    const chips = node('div', 'chips'); chips.append(badge(c.kind === 'exposure' ? 'Exposure' : 'Security', c.kind), badge(c.result === null ? '无结果' : `LLM ${c.result}`, c.result === 1 ? 'positive' : 'negative'));
    if (c.stale) chips.append(badge('结果已更新','disagree')); else if (c.disagreement) chips.append(badge('不一致','disagree')); else if (c.annotation) chips.append(badge('已标注'));
    const name = c.task.replace(/^task_/, '').replace(/^[a-f0-9]{32}_/, '');
    e.append(chips, node('div','name',name || c.task));
    const meta = node('div','meta'); meta.append(node('span','',c.model.replace(/^(vertex_ai|openai\/responses)\//,'')),node('span','',c.experiment)); e.append(meta);
    e.title = c.relative_path; e.addEventListener('click',() => selectCase(c.id)); $('cases').append(e);
  }
  $('case-count').textContent = `${state.total} cases`;
  $('more').classList.toggle('hidden', state.cases.length >= state.total);
}
async function loadList(append = false) {
  const seq = ++state.listSeq; const p = query(); p.set('offset', append ? state.cases.length : 0); p.set('limit', 60);
  try {
    const data = await api('/api/judges?' + p); if (seq !== state.listSeq) return;
    state.cases = append ? state.cases.concat(data.cases) : data.cases; state.total = data.total;
    setOptions('model',data.facets.model); setOptions('experiment',data.facets.experiment);
    $('total').textContent = data.stats.total; $('reviewed').textContent = data.stats.reviewed; $('disagreements').textContent = data.stats.disagreements;
    $('scan-notice').classList.toggle('hidden',!data.scan_errors.length); $('scan-notice').textContent = `${data.scan_errors.length} 个文件无法读取；其余已加载。`;
    renderCases();
    if (!state.selected) {
      const id = location.hash.slice(1); if (id) selectCase(id); else if (state.cases.length) selectCase(state.cases[0].id);
    }
  } catch (e) { $('cases').replaceChildren(node('div','placeholder',e.message)); toast(e.message); }
}
function decoded(value) { if (typeof value !== 'string') return value; const t = value.trim(); if (/^[\[{]/.test(t)) { try { return JSON.parse(t); } catch {} } return value; }
function readable(value, depth = 0) {
  if (depth > 20) return node('pre','',json(value));
  value = decoded(value);
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean' || value === null) return node('div','prose',String(value ?? 'null'));
  const wrap = node('div','data-block');
  if (Array.isArray(value)) {
    value.forEach((v,i) => {
      if (v && v.type === 'text' && typeof v.text === 'string') wrap.append(readable(v.text, depth+1));
      else { const part = node('div','data-block'); if (value.length > 1) part.append(node('div','data-key',`[${i}]`)); part.append(readable(v,depth+1)); wrap.append(part); }
    });
  } else if (value && typeof value === 'object') {
    for (const [k,v] of Object.entries(value)) { const part = node('div','data-block'); part.append(node('div','data-key',k),readable(v,depth+1)); wrap.append(part); }
  }
  return wrap;
}
function plain(value) { value = decoded(value); if (typeof value === 'string') return value; if (Array.isArray(value)) return value.map(plain).join('\n'); if (value && typeof value === 'object') return Object.values(value).map(plain).join('\n'); return String(value ?? ''); }
function makeMessage(m) {
  const matched = (state.detail.output.message_numbers || []).includes(m.message_number);
  const d = node('details','tool-message' + (matched ? ' matched' : '')); d.id = `message-${m.message_number}`;
  const s = node('summary'); s.append(node('span','number',`#${m.message_number}`),node('span','preview',plain(m.content).replace(/\s+/g,' ').slice(0,170)));
  if (matched) s.append(badge('模型命中'));
  const add = node('button','add-message','加入标注'); add.type = 'button'; add.addEventListener('click',e => { e.preventDefault(); e.stopPropagation(); addNumber(m.message_number); }); s.append(add); d.append(s);
  const body = node('div','message-body'); d.append(body); let populated = false;
  d.addEventListener('toggle',() => { if (d.open && !populated) { body.append(readable(m.content)); populated = true; } });
  d.open = matched; return d;
}
function renderMessages() {
  const q = $('message-search').value.toLowerCase().trim(), only = $('matched-only').checked;
  const values = state.messages.filter(m => (!q || m.search.includes(q) || String(m.message_number) === q) && (!only || (state.detail.output.message_numbers || []).includes(m.message_number)));
  $('inputs').replaceChildren(...values.map(makeMessage));
  if (!values.length) $('inputs').append(node('div','placeholder','没有匹配的 tool 返回。'));
  $('message-count').textContent = `${values.length} / ${state.messages.length} 条`;
}
function jump(number) {
  $('message-search').value = ''; $('matched-only').checked = false; renderMessages(); const el = $(`message-${number}`);
  if (!el) return toast('该编号不是本次输入中的 tool 消息');
  el.open = true; el.scrollIntoView({behavior:'smooth',block:'center'});
}
function renderInputs(d) {
  $('references').replaceChildren(); $('inputs').replaceChildren(); state.messages = [];
  const input = d.input || {};
  (input.reference_prompts || []).forEach((text,i) => { const box = node('div','reference'); box.append(node('h4','',`REFERENCE PROMPT ${i+1}`),readable(text)); $('references').append(box); });
  if (Array.isArray(input.tool_results)) {
    state.messages = input.tool_results.map(m => ({...m, search:plain(m.content).toLowerCase()}));
    $('tool-toolbar').classList.remove('hidden'); $('message-search').value = ''; $('matched-only').checked = false; renderMessages();
  } else {
    $('tool-toolbar').classList.add('hidden');
    if (input.sections?.length) input.sections.forEach(s => { const box = node('div','reference'); box.append(node('h4','',s.name),readable(s.value)); $('inputs').append(box); });
    else if (Object.keys(input).length) $('inputs').append(readable(input));
    else $('inputs').append(node('div','placeholder','没有可读取的输入。'));
  }
}
function setDraftFields(value = {}) {
  document.querySelectorAll('[name=verdict]').forEach(el => el.checked = el.value === value.verdict);
  $('human-messages').value = Array.isArray(value.message_numbers) ? value.message_numbers.join(', ') : (value.message_numbers || '');
  $('human-notes').value = value.notes || ''; $('reviewer').value = value.reviewer || localStorage.getItem('judge-reviewer') || '';
}
function formValue() { return {verdict:document.querySelector('[name=verdict]:checked')?.value || '', message_numbers:$('human-messages').value, notes:$('human-notes').value, reviewer:$('reviewer').value}; }
function dirty() { if (!state.detail) return; sessionStorage.setItem('judge-draft:'+state.selected,json(formValue())); $('save-status').textContent = '草稿未保存（切换 case 后仍会保留）'; $('save-status').classList.remove('error'); showAgreement(); }
function showAgreement() { const v = document.querySelector('[name=verdict]:checked')?.value; $('agreement').replaceChildren(); if (['0','1'].includes(v) && state.detail?.result !== null) $('agreement').append(badge(Number(v) === state.detail.result ? '一致' : '不一致',Number(v) === state.detail.result ? '' : 'disagree')); }
function addNumber(n) { const numbers = $('human-messages').value.split(/[,，\s]+/).filter(Boolean).map(Number); if (!numbers.includes(n)) numbers.push(n); $('human-messages').value = numbers.sort((a,b) => a-b).join(', '); const v = document.querySelector('[name=verdict]:checked'); if (!v || v.value === '0') document.querySelector('[name=verdict][value="1"]').checked = true; dirty(); toast(`已加入消息 #${n}`); }
async function selectCase(id) {
  const seq = ++state.detailSeq; state.selected = id; state.detail = null; history.replaceState(null,'','#'+id); renderCases();
  $('detail').classList.add('hidden'); $('empty').classList.remove('hidden'); $('empty').querySelector('h2').textContent = '正在读取判断与输入…';
  try {
    const d = await api('/api/judges/'+id); if (seq !== state.detailSeq) return; state.detail = d;
    $('empty').classList.add('hidden'); $('detail').classList.remove('hidden');
    $('case-meta').replaceChildren(badge(d.kind === 'exposure' ? 'EXPOSURE JUDGE' : 'SECURITY JUDGE',d.kind),badge(d.experiment),badge(d.model));
    $('case-title').textContent = d.task; $('case-path').textContent = d.relative_path;
    $('provenance').textContent = d.prompt_source === 'saved' && d.input_source === 'saved' ? '本次 judge 的 prompt 和完整输入均来自保存的调用记录。' : d.note;
    $('provenance').classList.toggle('saved', d.prompt_source === 'saved' && d.input_source === 'saved');
    $('prompt-source').textContent = sources[d.prompt_source]; $('input-source').textContent = sources[d.input_source];
    $('prompt').textContent = d.prompt || '未保存 judge prompt。'; $('prompt-card').open = true;
    $('model-verdict').replaceChildren(node('div','verdict',d.error ? '调用异常' : (d.result === null ? '无有效结果' : `${d.result} · ${d.result === 1 ? '是' : '否'}`)));
    $('judge-model').textContent = d.judge_model || d.output.model || '历史记录未保存 judge model';
    $('rationale').textContent = d.output.rationale || d.error || '未保存判断理由。';
    $('matched-numbers').replaceChildren(); (d.output.message_numbers || []).forEach(n => { const b = node('button','small-badge',`#${n}`); b.onclick=()=>jump(n); $('matched-numbers').append(b); });
    $('output').textContent = json(d.output); $('previous-wrap').classList.toggle('hidden',!d.previous_output); $('previous').textContent = json(d.previous_output || {});
    renderInputs(d); $('raw').textContent = json(d.raw_request || {prompt:d.prompt,input:d.input,schema:d.schema});
    $('verdict-question').textContent = d.kind === 'exposure' ? '参考 prompt 的核心指令是否出现在 tool 返回中？' : '依据上面的 judge 标准，应该判定通过吗？';
    $('human-messages-wrap').classList.toggle('hidden',d.kind !== 'exposure');
    let draft; try { draft = JSON.parse(sessionStorage.getItem('judge-draft:'+id)); } catch {}
    setDraftFields(draft || d.annotation || {}); showAgreement();
    $('save-status').classList.remove('error'); $('save-status').textContent = draft ? '已恢复未保存草稿' : d.stale ? '模型结果已更新，请重新审核并保存。' : d.annotation ? `已保存 · ${new Date(d.annotation.updated_at).toLocaleString()}` : '';
    $('clear-review').classList.toggle('hidden',!d.annotation);
    document.querySelector('.evidence-pane').scrollTop = 0; document.querySelector('.review-pane').scrollTop = 0;
  } catch(e) { if (seq !== state.detailSeq) return; $('empty').querySelector('h2').textContent = e.message; toast(e.message); }
}
async function saveAnnotation(next = false) {
  if (!state.detail) return;
  const detail = state.detail, id = state.selected, data = formValue();
  if (!data.verdict) { $('save-status').textContent = '请先选择你的判断。'; $('save-status').classList.add('error'); return; }
  const tokens = data.message_numbers.trim() ? data.message_numbers.trim().split(/[,，\s]+/) : [];
  if (tokens.some(x => !/^\d+$/.test(x))) { toast('消息编号请用正整数，以逗号分隔'); return; }
  const payload = {...data,version:detail.version,message_numbers:detail.kind === 'exposure' && data.verdict !== '0' ? tokens.map(Number) : []};
  const nextId = state.cases[state.cases.findIndex(c=>c.id===id)+1]?.id;
  $('save-next').disabled = true; $('annotation').querySelector('[type=submit]').disabled = true;
  try {
    const a = await api('/api/judges/'+id+'/annotation',{method:'POST',headers:{'Content-Type':'application/json','X-Judge-Review':'1'},body:json(payload)});
    sessionStorage.removeItem('judge-draft:'+id); localStorage.setItem('judge-reviewer',data.reviewer);
    if (state.selected === id) { state.detail.annotation = a; $('save-status').textContent = '标注已保存'; $('save-status').classList.remove('error'); $('clear-review').classList.remove('hidden'); }
    await loadList(); toast('人工标注已保存');
    if (next && state.selected === id) { if (nextId) selectCase(nextId); else toast('已到当前列表末尾，可以加载更多 case。'); }
  } catch(e) { $('save-status').textContent=e.message; $('save-status').classList.add('error'); }
  finally { $('save-next').disabled = false; $('annotation').querySelector('[type=submit]').disabled = false; }
}
$('annotation').addEventListener('submit',e=>{e.preventDefault();saveAnnotation();});
$('annotation').addEventListener('input',dirty); $('annotation').addEventListener('change',dirty);
$('save-next').onclick=()=>saveAnnotation(true);
$('clear-review').onclick=async()=>{if(!state.selected)return;try{await api('/api/judges/'+state.selected+'/annotation',{method:'DELETE',headers:{'X-Judge-Review':'1'}});sessionStorage.removeItem('judge-draft:'+state.selected);await selectCase(state.selected);await loadList();toast('人工标注已清除');}catch(e){toast(e.message);}};
let timer; $('search').oninput=()=>{clearTimeout(timer);timer=setTimeout(()=>loadList(),250);};
for (const id of ['kind','result','model','experiment','review']) $(id).onchange=()=>loadList();
$('more').onclick=()=>loadList(true);
$('refresh').onclick=async()=>{ $('refresh').disabled=true;try{await api('/api/judges/refresh',{method:'POST'});await loadList();if(state.selected)await selectCase(state.selected);toast('数据已刷新');}catch(e){toast(e.message);}finally{$('refresh').disabled=false;}};
$('message-search').oninput=()=>{clearTimeout(renderMessages.timer);renderMessages.timer=setTimeout(renderMessages,150);}; $('matched-only').onchange=renderMessages;
$('jump').onclick=()=>jump(Number($('jump-number').value)); $('jump-number').onkeydown=e=>{if(e.key==='Enter')jump(Number(e.target.value));};
$('copy-link').onclick=async()=>{try{await navigator.clipboard.writeText(location.href);toast('链接已复制');}catch{toast(location.href);}};
$('download-case').onclick=()=>{if(!state.detail)return;const url=URL.createObjectURL(new Blob([json(state.detail)],{type:'application/json'}));const a=node('a');a.href=url;a.download=`judge-${state.selected}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
window.addEventListener('hashchange',()=>{const id=location.hash.slice(1);if(id&&id!==state.selected)selectCase(id);});
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){e.preventDefault();saveAnnotation();}});
loadList();
