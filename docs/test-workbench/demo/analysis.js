// Real local-backend integration; provider-neutral UI, no credentials in the browser.
let aiHealth=null,aiConnection='正在检测本地后台',aiPollTimer,aiConnecting=false,aiCheckedAt='';
const aiState=t=>t.ai||(t.ai={provider:'codex',model:'',instructions:'',answers:[],history:[]});
const aiSourcesKey=t=>JSON.stringify({sources:(t.sources||[]).map(s=>[s.id,s.revision,s.text]),instructions:t.ai?.instructions||'',...(t.ai?.assist?.mapping?.review?.accepted?{mappingReview:t.ai.assist.mapping.reviewDigest}:{}),...((t.ai?.historyRefs||[]).length?{historyRefs:t.ai.historyRefs.map(r=>[r.id,r.hash])}:{})});
let aiStale=t=>aiState(t).job&&aiState(t).sourceKey!==aiSourcesKey(t);
let aiRunning=t=>['running','cancelling'].includes(aiState(t).job?.status)||aiState(t).submitting;
const aiAccepted=t=>!aiStale(t)&&confirmedSources(t)&&aiState(t).job?.review?.accepted;
async function aiRequest(path,body,timeoutMs=15000){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs);
 try{const r=await fetch(path,{method:body===undefined?'GET':'POST',cache:'no-store',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal:controller.signal});if(!r.headers.get('Content-Type')?.includes('application/json'))throw Error(`当前地址未提供工作台接口（HTTP ${r.status}），可能打开了静态预览`);const v=await r.json();if(!r.ok){const error=Error(v.error||'本地服务返回错误');error.status=r.status;error.path=path;throw error;}return v}
 catch(e){if(e.name==='AbortError')throw Error('本地服务响应超时；请检查后台状态');throw e}
 finally{clearTimeout(timer)}
}
async function aiConnect(notify=false){
 if(aiConnecting)return;
 aiConnecting=true;aiConnection='正在检测本地后台…（最多等待 5 秒）';
 if(page==='task'&&['requirements','plan','cases'].includes(tab))render();
 try{if(location.protocol==='file:')throw Error('当前直接打开了 HTML 文件，请从工作台地址进入');const health=await aiRequest('/api/health',undefined,5000);if(health.service!=='healthmanager-workbench'||!Array.isArray(health.providers))throw Error('当前地址不是工作台后台');aiHealth=health;aiConnection='本地后台已连接。此检测仅确认后台与 CLI 安装状态，不调用模型。'}
 catch(e){aiHealth=null;aiConnection='连接失败：'+(e.message==='Failed to fetch'?'无法访问当前地址的后台，请确认启动窗口仍在运行':e.message)}
 finally{aiConnecting=false;aiCheckedAt=new Date().toLocaleTimeString('zh-CN');if(page==='task'&&['requirements','plan','cases'].includes(tab))render();if(notify)toast(aiHealth?'连接检测成功':'连接检测失败，请查看下方原因和工作台入口')}
}
function aiConnectionPanel(){return `<p class="subtitle" role="status">${esc(aiConnection)}</p><p class="subtitle">当前入口：${esc(location.protocol==='file:'?'本地 HTML 文件':location.origin)}${aiCheckedAt?' · 最近检测：'+esc(aiCheckedAt):''}</p>${!aiHealth&&!aiConnecting?'<div class="notice">请双击仓库根目录的 start-workbench.cmd，并保持启动窗口运行。<br><a href="http://127.0.0.1:8878/">打开工作台（8878）</a> · 旧端口 8876 仅为静态预览。不同入口的浏览器任务数据分别保存，不会自动迁移。</div>':''}`}
function aiCitations(refs){return refs.map(r=>`<div class="source"><b>依据：${esc(task().sources?.find(s=>s.id===r.sourceId)?.name||aiState(task()).job?.references?.find(s=>s.id===r.sourceId)?.name||r.sourceId)}</b><p class="report-text">${esc(r.quote)}</p></div>`).join('')}
requirements=function(){
 const t=task(),a=aiState(t),j=a.job,r=j?.result,stale=aiStale(t),running=aiRunning(t);
 const names={running:'分析中',cancelling:'取消中',succeeded:'待审阅',failed:'分析失败',cancelled:'已取消',interrupted:'分析中断'};
 return `<div class="card"><div class="card-head"><h2>分析依据 · ${t.sources?.length||0} 份规格</h2>${btn('查看 / 补充方案','referenceSources','small')}</div><div class="pad"><div class="tags">${(t.sources||[]).map(s=>btn(esc(s.name)+' · 修订 '+s.revision,'previewSource:'+s.id,'small')).join('')}</div><p class="subtitle" style="margin-top:12px">专家：需求分析专家 · 结合当前规格和所选历史参考审视；通用测试方法参考已有专家包。</p></div></div>
 ${typeof hrPanel==='function'?hrPanel(t):''}<div class="card pad"><div class="row"><h2>需求分析</h2><button class="small" data-action="aiConnect" ${aiConnecting?'disabled':''}>${aiConnecting?'正在检测…':'检测连接'}</button></div>${aiConnectionPanel()}<div class="form-grid" style="margin-top:16px"><label>分析引擎<select id="aiProvider" ${running?'disabled':''}>${['codex','claude'].map(p=>`<option value="${p}" ${a.provider===p?'selected':''}>${p==='codex'?'Codex':'Claude'}${aiHealth&&!aiHealth.providers.find(v=>v.id===p)?.installed?'（未检测到原生程序）':''}</option>`).join('')}</select></label><label>模型（留空使用 CLI 默认）<input id="aiModel" value="${esc(a.model)}" maxlength="150" ${running?'disabled':''}></label></div><label>本次分析范围 / 补充说明<textarea id="aiInstructions" maxlength="10000" placeholder="例如：重点分析权限和数据一致性，不包含性能测试" ${running?'disabled':''}>${esc(a.instructions)}</textarea></label><p id="aiScopeHint" class="subtitle" role="status"></p><p class="source">点击开始将通过所选 CLI 的模型服务分析这些资料，可能消耗账号额度。本机运行客户端不代表离线模型；资料与人工结论会作为模型输入。</p><div class="actions" style="margin-top:16px"><button class="primary" data-action="aiStart" ${running||!aiHealth||!confirmedSources(t)||!aiHealth?.providers.find(v=>v.id===a.provider)?.installed?'disabled':''}>${running?'正在分析…':j?'补充后重新分析':'开始需求分析'}</button>${running?btn('取消分析','aiCancel','small'):''}${btn('保存审阅草稿','aiDraft','small')}${a.history?.length?btn('分析历史（'+a.history.length+'）','aiHistory','link'):''}</div></div>
 ${a.error?`<div class="notice">${esc(a.error)}</div>`:''}${stale?'<div class="notice">规格资料、历史参考选择或分析范围已变化，本结果基于旧输入。请核对资料并重新分析，不能确认旧结果。</div>':''}
 <div id="aiProgress">${aiProgressPanel(j)}</div>
 ${r?`<div class="card pad"><h2>需求理解 · 模型分析快照</h2><p class="subtitle">人工结论见下方疑问处理记录；补充后重新分析才会更新本段模型理解。</p><p class="report-text">${esc(r.summary)}</p>${r.requirements.map(x=>`<div class="list-item"><h3>${esc(x.id)} · ${esc(x.title)}</h3><p class="report-text">${esc(x.understanding)}</p><p class="report-text"><b>验收依据：</b>${esc(x.acceptance)}</p>${aiCitations(x.citations)}</div>`).join('')}${r.warnings.map(w=>`<p class="notice">${esc(w)}</p>`).join('')}</div>
 <div class="card pad"><h2>业务疑问 · ${r.questions.length} 项</h2>${r.questions.map(q=>{const answer=a.answers?.find(x=>x.questionId===q.id);return `<div class="list-item"><div class="row"><h3>${esc(q.id)} · ${esc(q.title)}</h3>${badge(q.blocking?'关键疑问':'一般疑问')}</div><p class="report-text">原因：${esc(q.reason)}\n影响：${esc(q.impact)}\nAI 建议（非结论）：${esc(q.suggestion)}</p>${aiCitations(q.citations)}${answer?`<div class="source">${answer.status==='answered'?'人工结论':'暂缓原因'}：${esc(answer.answer)}<br>依据：${esc(answer.basis)}</div>`:''}<button class="small" data-action="aiAnswer:${esc(q.id)}" ${running||stale?'disabled':''}>${answer?'修改处理记录':'回答 / 暂缓'}</button></div>`}).join('')||'<p class="subtitle">模型未提出疑问，仍需人工审阅完整性。</p>'}</div>
 <div class="card pad"><h2>风险与测试方向</h2>${r.risks.filter(x=>!/【历史冲突】|【影响分析】|【复用建议】/.test(x.title)).map(x=>`<div class="list-item"><h3>${esc(x.title)}</h3><p class="report-text">影响：${esc(x.impact)}\n建议：${esc(x.testDirection)}</p>${aiCitations(x.citations)}</div>`).join('')||'<p class="subtitle">暂无建议。</p>'}</div>
 ${typeof hrFindings==='function'?hrFindings(r):''}${aiReviewGate(t)}`:'<div class="empty">开始分析后，这里将展示真实模型返回的需求点、原文依据、疑问和风险。</div>'}`;
};
async function aiStart(){
 const t=task(),a=aiState(t);if(aiRunning(t)||!confirmedSources(t))return;
 a.submitting=true;a.error='';const key=aiSourcesKey(t);save();render();
 try{
  const request={taskId:t.id,provider:a.provider,model:a.model,instructions:a.instructions,sources:t.sources.map(sourcePayload),answers:a.answers||[],historyRefs:(a.historyRefs||[]).map(r=>({id:r.id,hash:r.hash}))};
  if(typeof daMappingCurrent==='function'&&daMappingCurrent(t))Object.assign(request,{mappingJobId:t.ai.assist.mapping.id,mappingReviewDigest:t.ai.assist.mapping.reviewDigest});
  const job=await aiRequest('/api/jobs',request,30000);
  if(a.job)(a.history||=[]).push({jobId:a.job.id,createdAt:a.job.createdAt,status:a.job.status});
  a.job=job;a.sourceKey=key;a.answers=[];
 }catch(e){a.error=e.message}
 finally{a.submitting=false;save();if(taskId===t.id)render();aiSchedulePoll()}
}
function aiSchedulePoll(){clearTimeout(aiPollTimer);aiPollTimer=setTimeout(aiPoll,1500)}
function reviewChanged(previous,current){
 return Boolean(current.review && previous?.reviewDigest!==current.reviewDigest);
}
function useUpdatedReview(){
 return window.confirm('后台审阅已更新。载入最新审阅会替换本页草稿；取消可保留当前编辑。');
}
function updateAnalysisJob(state,job){
 if(reviewChanged(state.job,job)){
  if(!useUpdatedReview())return false;
  state.answers=structuredClone(job.review.answers||[]);
 }
 state.job=job;state.error='';return true;
}
function aiProgressPanel(j,refreshAction="aiRefresh"){
 if(!j)return '';
 const running=['running','cancelling'].includes(j.status),end=j.finishedAt?Date.parse(j.finishedAt):Date.now();
 const elapsed=Math.max(0,Math.floor((end-Date.parse(j.createdAt))/1000));
 const duration=n=>`${Math.floor(n/60)} 分 ${n%60} 秒`;
 const names={preparing:'准备资料',starting:'启动引擎',connecting:'连接模型',waiting:'等待模型响应',analyzing:'模型处理中',reconnecting:'连接重试中',receiving:'接收结果',validating:'校验结果',succeeded:j.kind==='test-cases'?'用例生成完成':j.kind==='test-plan'?'方案生成完成':'分析完成',failed:j.kind==='test-plan'?'方案生成失败':j.kind==='test-cases'?'用例生成失败':'分析失败',cancelled:'已取消',interrupted:'分析中断'};
 const stage=j.status==='cancelling'?'正在取消':names[j.stage||j.status]||'等待模型响应';
 const age=j.lastActivityAt?Math.max(0,Math.floor((Date.now()-Date.parse(j.lastActivityAt))/1000)):null;
 return `<section class="card pad" aria-label="分析进展"><div class="row"><h2>${running?'◷ ':''}${esc(stage)}</h2>${badge(j.review?.accepted?(j.kind==='test-cases'?'用例集已确认':j.kind==='test-plan'?'测试方案已确认':'需求基线已确认'):running?'进行中':j.status==='succeeded'?'待人工审阅':stage)}</div><p class="report-text" role="status">${esc(j.review?.accepted?'人工审阅与结论已保存':j.message)}</p><div class="tags">${btn("刷新进展",refreshAction,"small")}<span>已耗时 ${duration(elapsed)}</span>${running?`<span>超时上限 ${duration(j.timeoutSeconds||180)}</span>`:''}</div><p class="subtitle">${esc(j.provider)} / ${esc(j.model)} · 专家 ${esc(j.expert?.version||'')} · 开始于 ${esc(new Date(j.createdAt).toLocaleString('zh-CN'))}</p>${running?`<p class="source">${age===null?'等待引擎进度事件':`距最近阶段活动 ${duration(age)}`}。进程存活不代表模型持续生成；没有新事件时会明确显示等待，可随时取消。</p>`:''}<ol class="ai-event-log">${(j.events||[]).slice(-8).map(e=>`<li><time>${esc(new Date(e.time).toLocaleTimeString('zh-CN'))}</time> ${esc(e.message)}</li>`).join('')||'<li>此记录尚无阶段事件；新版本后台启动后的分析会记录详细进展。</li>'}</ol></section>`;
}
function aiRefreshProgress(){const el=$('#aiProgress');if(el&&page==='task'&&tab==='requirements')el.innerHTML=aiProgressPanel(aiState(task()).job)}
setInterval(()=>{if(page==='task'&&tab==='requirements'&&aiRunning(task()))aiRefreshProgress()},1000);
async function aiPoll(){
 for(const t of data.tasks){const a=t.ai;if(!a?.job||!['running','cancelling'].includes(a.job.status))continue;
  try{const j=await aiRequest('/api/jobs/'+a.job.id);if(a.job.id!==j.id)continue;const changed=j.status!==a.job.status;if(!updateAnalysisJob(a,j))continue;save();if(taskId===t.id&&tab==='requirements'){if(changed)render();else aiRefreshProgress()}}
  catch(e){a.error=e.message;if(taskId===t.id&&tab==='requirements'&&!$('#aiInstructions')?.matches(':focus'))render()}
 }
 if(data.tasks.some(t=>t.ai?.job&&['running','cancelling'].includes(t.ai.job.status)))aiSchedulePoll();
}
// Keep transient confirmation feedback out of persisted task data.
const aiReviewPending=new Set(),aiReviewErrors=new Map();
function aiReviewIssues(t){
 const a=aiState(t),issues=[];
 if(a.job?.status!=='succeeded')issues.push({text:'需求分析尚未成功完成，请先完成分析。'});
 if(!confirmedSources(t))issues.push({text:'规格资料尚未确认，请先检查并确认分析资料。'});
 if(aiStale(t))issues.push({text:'资料、分析范围或资产对照已变化，请重新分析后确认。'});
 for(const q of a.job?.result?.questions||[]){
  const answer=a.answers?.find(x=>x.questionId===q.id),missing=[];
  if(q.blocking&&answer?.status!=='answered')missing.push(answer?.status==='deferred'?'关键疑问已暂缓，需改为已确认结论':'关键疑问尚未回答');
  if(answer){
   if(!answer.answer?.trim())missing.push(answer.status==='deferred'?'缺少暂缓原因':'缺少结论');
   if(answer.status==='answered'&&!answer.basis?.trim())missing.push('缺少确认依据');
  }
  if(missing.length)issues.push({id:q.id,text:q.id+' · '+q.title+'：'+missing.join('；')});
 }
 return issues;
}
function aiReviewGate(t){
 const issues=aiReviewIssues(t),pending=aiReviewPending.has(t.id),error=aiReviewErrors.get(t.id);
 return `<div class="card pad" id="aiReviewGate" tabindex="-1"><h2>确认需求理解</h2><p class="subtitle">关键疑问必须填写结论和确认依据；一般疑问可稍后处理。确认后进入测试方案。</p>
 <div role="status">${issues.length?`<div class="notice"><b>还有 ${issues.length} 项需要处理</b>${issues.map(x=>`<div class="list-item"><span>${esc(x.text)}</span> ${x.id?btn('去填写','aiAnswer:'+x.id,'small'):''}</div>`).join('')}</div>`:'<p class="source">必填项已齐全，可以确认需求理解。</p>'}</div>
 ${error?`<div class="notice" role="alert">确认未完成：${esc(error)}<br>处理后可再次点击确认；当前审阅内容仍保留。</div>`:''}
 <button class="primary" data-action="aiAccept" ${aiRunning(t)||pending?'disabled':''}>${pending?'正在保存并确认…':'确认需求理解，进入测试方案'}</button></div>`;
}
function aiFocusReview(t){requestAnimationFrame(()=>requestAnimationFrame(()=>{
 if(taskId===t.id&&page==='task'&&tab==='requirements'){$('#aiReviewGate')?.focus({preventScroll:true});$('#aiReviewGate')?.scrollIntoView({block:'nearest'})}
}))}
async function aiReview(accepted){
 const t=task(),a=aiState(t);if(aiReviewPending.has(t.id))return;
 aiReviewErrors.delete(t.id);
 if(accepted&&aiReviewIssues(t).length){render();aiFocusReview(t);toast('请处理确认区域列出的待办项');return}
 save();
 if(!a.job||a.job.status!=='succeeded'){toast('草稿已保存到浏览器');return}
 aiReviewPending.add(t.id);render();
 try{
  a.job=await aiRequest('/api/jobs/'+a.job.id+'/review',{expectedReviewDigest:a.job.reviewDigest,inputDigest:a.job.inputDigest,answers:a.answers||[],accepted});
  a.error='';save();if(taskId===t.id&&page==='task'&&accepted)tab='plan';
  toast(accepted?'需求基线已确认':'审阅草稿已保存到本地后台');
 }catch(e){aiReviewErrors.set(t.id,e.message);toast('保存未完成，请查看确认区域的原因')}
 finally{aiReviewPending.delete(t.id);if(taskId===t.id&&page==='task'){render();if(aiReviewErrors.has(t.id))aiFocusReview(t)}}
}
const preAiAct=act;
act=function(action){
 const a=aiState(task());
 if(action==='aiConnect')return aiConnect(true);
 if(action==='aiRefresh'){const t=task();if(!a.job)return;return aiRequest('/api/jobs/'+a.job.id).then(j=>{if(!updateAnalysisJob(a,j))return;save();if(taskId===t.id)render();toast('进展已刷新');aiSchedulePoll()}).catch(e=>{a.error=e.message;if(taskId===t.id)render()})}
 if(action==='aiStart'||action==='analyze')return aiStart();
 if(action==='aiDraft')return aiReview(false);
 if(action==='aiAccept')return aiReview(true);
 if(action==='aiCancel'){if(!a.job)return;return aiRequest('/api/jobs/'+a.job.id+'/cancel',{}).then(j=>{a.job=j;save();render();aiSchedulePoll()}).catch(e=>toast(e.message))}
 if(action==='aiHistory')return modal('分析历史',`<p>历史结果保留在本地后台，每次分析均有独立输入快照。</p>${(a.history||[]).map(h=>`<div class="list-item">${esc(h.createdAt)} · ${esc(h.status)}${btn('查看结果','aiHistoryView:'+h.jobId,'small')}</div>`).join('')}`,'关闭',()=>{});
 if(action.startsWith('aiHistoryView:'))return aiRequest('/api/jobs/'+action.slice(14)).then(j=>modal('历史分析（只读）',`<pre class="spec-preview">${esc(JSON.stringify({createdAt:j.createdAt,provider:j.provider,status:j.status,references:j.references||[],result:j.result,review:j.review},null,2))}</pre>`,'关闭',()=>{})).catch(e=>toast(e.message));
 if(action.startsWith('aiAnswer:')){
  const id=action.slice(9),q=a.job?.result?.questions.find(q=>q.id===id);if(!q)return;
  const previous=a.answers.find(x=>x.questionId===id)||{};
  return modal('处理业务疑问',`<p>${esc(q.title)}</p><label>处理方式<select name="status"><option value="answered">已确认结论</option><option value="deferred" ${previous.status==='deferred'?'selected':''}>暂缓处理</option></select></label><label>结论 / 暂缓原因<textarea name="answer" required maxlength="10000">${esc(previous.answer||'')}</textarea></label><label>确认依据（已确认结论时必填）<input name="basis" maxlength="10000" value="${esc(previous.basis||'')}" placeholder="例如：产品确认记录、规格章节"></label><p class="subtitle">关键疑问暂缓后可保存草稿，不能确认需求基线。</p>`,'保存处理记录',f=>{const status=f.get('status'),answer=f.get('answer').trim(),basis=f.get('basis').trim();if(!answer||(status==='answered'&&!basis)){const field=document.querySelector('#modalForm [name="'+(!answer?'answer':'basis')+'"]');field.setCustomValidity(!answer?'请填写结论或暂缓原因':'已确认结论必须填写确认依据');field.reportValidity();field.oninput=()=>field.setCustomValidity('');return false}a.answers=a.answers.filter(x=>x.questionId!==id);a.answers.push({questionId:id,question:q.title,status,answer,basis});if(a.job.review)a.job.review.accepted=false;aiReviewErrors.delete(taskId);save();render()});
 }
 if(page==='task'&&journey==='design'&&['step:plan','step:cases','toCases','generate'].includes(action)&&!aiAccepted(task()))return toast('请先完成需求分析并确认需求理解');
 return preAiAct(action);
};
const preAiRender=render;
render=function(){
 preAiRender();
 if(page==='task'&&tab==='requirements'){
  const a=aiState(task());
  if($('#aiProvider'))$('#aiProvider').onchange=e=>{a.provider=e.target.value;save();render()};
  if($('#aiModel'))$('#aiModel').oninput=e=>{a.model=e.target.value;save()};
  if($('#aiInstructions'))$('#aiInstructions').oninput=e=>{a.instructions=e.target.value;save();const stale=aiStale(task());$('#aiScopeHint').textContent=stale?'分析范围已变化，请重新分析':'';const next=$('[data-action="step:plan"]');if(next)next.disabled=!aiAccepted(task());const accept=$('[data-action="aiAccept"]');if(accept)accept.disabled=aiRunning(task())||aiReviewPending.has(taskId)};
  const next=$('[data-action="step:plan"]');if(next)next.disabled=!aiAccepted(task());
 }
};
document.addEventListener('click',e=>{if(page==='task'&&journey==='design'&&['plan','cases'].includes(e.target.closest('[data-tab]')?.dataset.tab)&&!aiAccepted(task())){e.preventDefault();e.stopImmediatePropagation();toast('请先完成需求分析并确认需求理解')}},true);
// Refresh recovers job IDs from existing browser data, then polls durable server records.
for(const t of data.tasks)if(t.ai){t.ai.submitting=false;
 // Compatibility with the first source-only signature, when no scope was supplied.
 if(!t.ai.instructions&&t.ai.sourceKey===JSON.stringify((t.sources||[]).map(s=>[s.id,s.revision,s.text])))t.ai.sourceKey=aiSourcesKey(t);
}
aiConnect();aiSchedulePoll();render();
