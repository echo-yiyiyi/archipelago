'use strict';
const $ = id => document.getElementById(id);
const state = {reviewer:null, round:null, cases:[], detail:null, sequence:0, listSequence:0};
function node(tag,text,cls='') { const e=document.createElement(tag); e.textContent=text; e.className=cls; return e; }
function toast(text) { $('toast').textContent=text; $('toast').classList.add('visible'); clearTimeout(toast.timer); toast.timer=setTimeout(()=>$('toast').classList.remove('visible'),4000); }
async function api(url,body) {
  const options=body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-Judge-Review':'1'},body:JSON.stringify(body)};
  const r=await fetch(url,options);
  if (!r.ok) { if(r.status===401) showLogin(); const text=await r.text(); const doc=new DOMParser().parseFromString(text,'text/html'); throw new Error(doc.querySelector('p')?.textContent || `Request failed (${r.status})`); }
  return r.json();
}
function showLogin() { state.sequence++; state.listSequence++; state.detail=null; state.cases=[]; $('inputs').replaceChildren(); $('comparison').replaceChildren(); $('workspace').classList.add('hidden'); $('login-panel').classList.remove('hidden'); $('logout').classList.add('hidden'); $('export').classList.add('hidden'); $('identity').textContent=''; }
async function enter() {
  const user=await api('/api/judges/me'); state.reviewer=user.reviewer; state.round=user.round_id;
  $('identity').textContent=user.reviewer; $('login-panel').classList.add('hidden'); $('workspace').classList.remove('hidden'); $('logout').classList.remove('hidden'); $('export').classList.remove('hidden');
  $('round').textContent=user.round_id || 'Waiting for a review round'; $('detail').classList.add('hidden'); $('empty').classList.remove('hidden');
  if (user.round_id) { $('export').href='/api/judges/export?round='+encodeURIComponent(user.round_id); await loadList(); }
}
async function login() { try { await api('/api/judges/login',{name:$('name').value.trim()}); $('login-error').textContent=''; await enter(); } catch(e) { $('login-error').textContent=e.message; } }
$('login').onsubmit=e=>{e.preventDefault();login();};
$('logout').onclick=async()=>{await api('/api/judges/logout',{});showLogin();};
function caseUrl(id) { return '/api/judges/'+id+'?round='+encodeURIComponent(state.round); }
function draftKey(id) { return `judge-blind:${state.reviewer}:${state.round}:${id}`; }
async function loadList() {
  const seq=++state.listSequence;
  const p=new URLSearchParams({round:state.round,q:$('search').value,kind:$('kind').value,review:$('review').value});
  const data=await api('/api/judges?'+p); if(seq!==state.listSequence)return;
  state.cases=data.cases; $('total').textContent=data.total; $('reviewed').textContent=data.reviewed;
  $('cases').replaceChildren(...data.cases.map(c=>{
    const e=node('button','', 'case-item'+(state.detail?.id===c.id?' active':''));
    e.append(node('div',`${c.kind==='security'?'Safety':'Exposure'} · ${c.annotation?'Annotated':'Unannotated'}`,'chips'),node('div',`Goal ${c.goal_id}: ${c.goal_name}`,'name'),node('div',c.model,'meta'));
    e.onclick=()=>selectCase(c.id);return e;
  }));
  if(!data.cases.length)$('cases').append(node('p','No matching samples.'));
}
function readable(value) {
  const pre=node('div', typeof value==='string'?value:JSON.stringify(value,null,2),'prose'); return pre;
}
function renderEvidence() {
  const input=state.detail?.input || {}, q=$('evidence-search').value.toLowerCase(); $('inputs').replaceChildren();
  for(const text of input.reference_prompts||[]) { const box=node('div','','reference'); box.append(node('h4','Reference instruction'),readable(text)); $('inputs').append(box); }
  if(Array.isArray(input.tool_results)) {
    for(const m of input.tool_results) {
      if(q && !JSON.stringify(m).toLowerCase().includes(q))continue;
      const d=node('details','','tool-message'), summary=node('summary',`#${m.message_number} `);
      const raw=typeof m.content==='string'?m.content:JSON.stringify(m.content);
      summary.append(node('span',raw.replace(/\s+/g,' ').slice(0,150),'preview'));
      const add=node('button','Add number','add-message');add.type='button';add.onclick=e=>{e.preventDefault();e.stopPropagation(); const values=new Set($('numbers').value.split(/[,，\s]+/).filter(Boolean));values.add(String(m.message_number));$('numbers').value=[...values].join(', ');saveDraft();}; summary.append(add);d.append(summary);
      let rendered=false;d.ontoggle=()=>{if(d.open&&!rendered){d.append(readable(m.content));rendered=true;}};$('inputs').append(d);
    }
  } else if(Array.isArray(input.sections)) {
    for(const s of input.sections) {const box=node('div','','reference');box.append(node('h4',s.name),readable(s.value));$('inputs').append(box);}
  } else $('inputs').append(readable(input));
}
function formValue() {return {verdict:document.querySelector('[name=verdict]:checked')?.value || '',message_numbers:$('numbers').value,notes:$('notes').value};}
function saveDraft() {if(!state.detail)return;sessionStorage.setItem(draftKey(state.detail.id),JSON.stringify(formValue()));$('save-status').textContent='Draft not submitted';}
async function selectCase(id) {
  const seq=++state.sequence;state.detail=null;$('detail').classList.add('hidden');$('empty').classList.remove('hidden');
  try {
    const d=await api(caseUrl(id));if(seq!==state.sequence)return;state.detail=d;
    $('empty').classList.add('hidden');$('detail').classList.remove('hidden');
    $('case-title').textContent=`Goal ${d.goal_id}: ${d.goal_name}`;$('case-meta').textContent=`${d.kind==='security'?'Safety':'Exposure'} · ${d.model}`;
    $('prompt').textContent=d.prompt||'';$('evidence-search').value='';renderEvidence();
    $('question').textContent=d.kind==='exposure'?'Does the core reference instruction appear in a tool response?':'Does the evidence pass the evaluation criteria?';$('numbers-wrap').classList.toggle('hidden',d.kind!=='exposure');
    let draft;try {draft=JSON.parse(sessionStorage.getItem(draftKey(id)));}catch{}
    const label=draft||d.annotation||{};document.querySelectorAll('[name=verdict]').forEach(e=>e.checked=e.value===label.verdict);
    $('numbers').value=Array.isArray(label.message_numbers)?label.message_numbers.join(', '):(label.message_numbers||'');$('notes').value=label.notes||'';
    $('save-status').textContent=draft?'Your draft has been restored':d.annotation?(d.annotation.legacy?'Legacy annotation retained (not blind)':'Your annotation has been saved'):'';
    $('comparison').replaceChildren();$('comparison-title').textContent=d.blind?'Results hidden':'Post-submission comparison';
    if(d.blind)$('comparison').append(node('p',"Save your judgment to reveal the LLM result and other annotators' judgments."));
    else {
      $('comparison').append(node('p',`LLM: ${d.result}`),readable(d.output?.rationale||''));
      for(const a of d.other_annotations||[])$('comparison').append(node('p',`${a.reviewer}: ${a.verdict}`),readable(a.notes||''));
    }
    document.querySelector('.evidence-pane').scrollTop=0;document.querySelector('.review-pane').scrollTop=0;
  }catch(e){toast(e.message);}
}
async function save(next=false) {
  if(!state.detail||!$('annotation').reportValidity())return;
  const d=state.detail, values=formValue(), tokens=values.message_numbers.split(/[,，\s]+/).filter(Boolean);
  if(tokens.some(t=>!/^\d+$/.test(t)))return toast('Message numbers must be positive integers');
  const nextId=state.cases.find(c=>!c.annotation&&c.id!==d.id)?.id;
  $('annotation').querySelectorAll('button').forEach(e=>e.disabled=true);
  try {
    await api('/api/judges/'+d.id+'/annotation?round='+encodeURIComponent(state.round),{...values,version:d.version,message_numbers:d.kind==='exposure'&&values.verdict!=='0'?tokens.map(Number):[]});
    sessionStorage.removeItem(draftKey(d.id));await loadList();await selectCase(next&&nextId?nextId:d.id);toast('Annotation saved');
  }catch(e){toast(e.message);}finally{$('annotation').querySelectorAll('button').forEach(e=>e.disabled=false);}
}
$('annotation').onsubmit=e=>{e.preventDefault();save();};$('annotation').oninput=saveDraft;$('save-next').onclick=()=>save(true);
for(const id of ['kind','review'])$(id).onchange=()=>loadList().catch(e=>toast(e.message));
$('search').oninput=()=>loadList().catch(e=>toast(e.message));$('evidence-search').oninput=renderEvidence;
enter().catch(e=>{if(!e.message.includes('sign in'))toast(e.message);});
