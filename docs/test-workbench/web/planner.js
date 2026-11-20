// Test plans use the same jobs, adapters and progress protocol as requirements.
const planFields={title:'方案名称',objective:'测试目标',scope:'测试范围',outOfScope:'不测 / 暂缓范围',strategy:'分层策略与测试方法',environmentAndData:'环境、角色与测试数据',entryCriteria:'准入条件',exitCriteria:'结束条件',risksAndDependencies:'风险与依赖'};
const plannerState=t=>t.planner||(t.planner={provider:aiState(t).provider,model:aiState(t).model,instructions:'',history:[]});
const planBasis=t=>JSON.stringify({analysisId:t.ai?.job?.id,review:t.ai?.job?.review,answers:t.ai?.answers,sources:aiSourcesKey(t),...(t.planner?.templateIds?{templateIds:t.planner.templateIds}:{})});
const planBusy=t=>['running','cancelling'].includes(plannerState(t).job?.status)||plannerState(t).submitting||plannerState(t).saving;
const planStale=t=>!aiAccepted(t)||plannerState(t).basisKey!==planBasis(t)||plannerState(t).generationInstructions!==plannerState(t).instructions||plannerState(t).job?.basisCurrent===false;
const planConfirmed=t=>!planStale(t)&&plannerState(t).job?.review?.accepted&&JSON.stringify(plannerState(t).draft)===JSON.stringify(plannerState(t).job.review.draft);
let plannerTimer;
function planText(d){return Object.entries(planFields).map(([key,title])=>`## ${title}\n${d[key]}`).join('\n\n')+'\n\n## 需求覆盖安排\n'+d.coverage.map(r=>`${r.requirementId} · ${r.disposition}\n${r.approach}\n依据：${r.reason}`).join('\n\n')+'\n\n## 未决问题\n'+(d.openItems.map(i=>`${i.questionId}：${i.handling}`).join('\n')||'无');}
const planReviewViews=new Map();
function planReviewWorkspace(t){
 const p=plannerState(t),d=p.draft,locked=planBusy(t)||planStale(t),disabled=locked?'disabled':'',v=planReviewViews.get(t.id)||{section:'objective',row:0};
 const section=v.section,rows=section==='coverage'?d.coverage:d.openItems,index=Math.max(0,Math.min(v.row,rows.length-1));
 const chapters=Object.entries(planFields);
 let body='';
 if(planFields[section])body=`<label class="pr-editor-label">${esc(planFields[section])}<textarea class="pr-chapter" data-plan-field="${section}" maxlength="20000" ${disabled}>${esc(d[section])}</textarea></label>`;
 else {
 const coverage=section==='coverage';
 body=`<div class="pr-split"><div class="pr-items" aria-label="${coverage?'需求列表':'疑问列表'}">${rows.map((r,i)=>{const id=coverage?r.requirementId:r.questionId,title=(coverage?t.ai.job.result.requirements:t.ai.job.result.questions).find(x=>x.id===id)?.title||id;return `<button data-action="planReviewRow:${i}" aria-pressed="${i===index}" class="${i===index?'active':''}"><b>${esc(id)} · ${esc(title)}</b><small>${coverage?({included:'纳入',deferred:'暂缓',excluded:'排除'})[r.disposition]:'待落实处理安排'}</small></button>`}).join('')||'<p class="subtitle">没有未决问题</p>'}</div><div class="pr-detail">${rows.length?coverage?`<h3>${esc(rows[index].requirementId)} · 覆盖安排</h3><label>安排<select data-plan-row="${index}" data-plan-key="disposition" ${disabled}>${[['included','纳入'],['deferred','暂缓'],['excluded','排除']].map(([key,label])=>`<option value="${key}" ${rows[index].disposition===key?'selected':''}>${label}</option>`).join('')}</select></label><label>验证方向<textarea data-plan-row="${index}" data-plan-key="approach" maxlength="20000" ${disabled}>${esc(rows[index].approach)}</textarea></label><label>安排依据<textarea data-plan-row="${index}" data-plan-key="reason" maxlength="20000" ${disabled}>${esc(rows[index].reason)}</textarea></label>`:`<h3>${esc(rows[index].questionId)} · 处理安排</h3><label>影响范围、后续确认或暂缓策略<textarea class="pr-chapter" data-plan-open="${index}" maxlength="20000" ${disabled}>${esc(rows[index].handling)}</textarea></label>`:'<div class="empty">当前需求基线无未决疑问。</div>'}</div></div>`;
 }
 return `<section class="card pr-workspace"><div class="card-head"><div><h2>方案评审</h2><p class="subtitle">逐章审阅与修改 · ${d.coverage.length} 项需求覆盖 · ${d.openItems.length} 项未决问题</p></div><span id="planReviewStatus">${badge(planConfirmed(t)?'方案已确认':'待人工审阅')}</span></div><div class="pr-layout"><nav class="pr-nav" aria-label="方案评审目录">${[...chapters,['coverage','需求覆盖安排'],['openItems','未决问题']].map(([key,label])=>`<button data-action="planReviewSection:${key}" ${section===key?'aria-current="page"':''} class="${section===key?'active':''}">${esc(label)}${key==='coverage'?` <small>${d.coverage.length}</small>`:key==='openItems'?` <small>${d.openItems.length}</small>`:''}</button>`).join('')}</nav><div class="pr-body"><p class="subtitle pr-hint">${section==='coverage'?'覆盖安排是测试计划，不代表实际覆盖已达成。选择左侧需求后编辑。':'修改实时保留在当前草稿中，切换章节不会丢失内容。'}</p>${body}</div></div><footer class="pr-footer"><span id="planReviewNotice" role="status">${p.error?esc(p.error):planStale(t)?'方案依据已变化，请重新生成。':planConfirmed(t)?'当前方案已确认':'请核对章节、需求覆盖和未决问题后确认。'}</span><div class="actions"><button data-action="planSave" ${disabled}>${p.saving?'正在保存…':'保存方案草稿'}</button><button class="primary" data-action="planAccept" ${disabled}>确认方案，进入用例设计</button></div></footer></section>`;
}
plan=function(){
 const t=task(),p=plannerState(t),j=p.job,d=p.draft,busy=planBusy(t),stale=j&&planStale(t);
 if(!aiAccepted(t))return `<div class="notice">请先确认当前规格的需求理解和人工澄清结论。已有方案保留，不能作为新基线继续使用。</div>${btn('返回需求与疑问','step:requirements','primary')}`;
 return `<div class="card pad"><h2>测试方案设计</h2><p class="subtitle">依据：已确认需求分析 · ${esc(t.ai.job.result?.requirements.length||0)} 个需求点 · ${t.ai.answers?.length||0} 条人工处理记录</p><p class="subtitle">需求基线：${esc(t.ai.job.id)}。模型原始理解与人工结论共同作为输入；已回答问题以人工结论补全。</p>${btn('查看需求与疑问','step:requirements','small')}</div>
 <div class="card pad"><div class="row"><h2>生成方案</h2>${btn('检测连接','aiConnect','small')}</div>${aiConnectionPanel()}<div class="form-grid"><label>方案引擎<select id="planProvider" ${busy?'disabled':''}>${['codex','claude'].map(v=>`<option value="${v}" ${p.provider===v?'selected':''}>${v}${aiHealth&&!aiHealth.providers.find(x=>x.id===v)?.installed?'（未安装）':''}</option>`).join('')}</select></label><label>方案模型（可留空）<input id="planModel" value="${esc(p.model)}" maxlength="150" ${busy?'disabled':''}></label></div><label>方案约束与侧重点<textarea id="planInstructions" maxlength="10000" ${busy?'disabled':''} placeholder="例如：本次仅覆盖桌面端，优先权限与数据一致性；环境待准备">${esc(p.instructions)}</textarea></label><p id="planEditNotice" class="subtitle">生成内容为候选，请逐项审阅。点击生成会将已确认资料与结论发送给所选模型服务。</p><div class="actions"><button class="primary" data-action="planGenerate" ${busy||!aiHealth||!aiHealth?.providers.find(x=>x.id===p.provider)?.installed?'disabled':''}>${p.saving?'正在保存…':busy?(j?.stage==='reconnecting'?'连接重试中…':'方案生成中…'):j?'重新生成方案':'生成测试方案'}</button>${['running','cancelling'].includes(j?.status)?btn('取消生成','planCancel','small'):''}${p.history.length?btn('历史方案（'+p.history.length+'）','planHistory','small'):''}</div></div>
 ${p.error?`<div class="notice">${esc(p.error)}</div>`:''}${stale?'<div class="notice">需求基线或方案约束已变化，当前方案已过期，请重新生成。</div>':''}<div id="planProgress">${aiProgressPanel(j,'planRefresh')}</div>
 ${d?planReviewWorkspace(t):`<div class="empty">${busy?(j?.stage==='reconnecting'?'模型连接正在重试，可查看上方进展或取消本次生成。':'正在生成，完成后将在这里展示可编辑方案。'):j?.status==='failed'?'本次方案生成失败，原因见上方进展。已确认的需求和人工回答仍保留，可重新生成。':'点击“生成测试方案”，根据当前需求基线生成可编辑方案。'}</div>`}`;
};
async function planGenerate(){
 const t=task(),p=plannerState(t);if(planBusy(t)||!aiAccepted(t))return;
 p.submitting=true;p.error='';save();render();
 try{
  const parent=await aiRequest('/api/jobs/'+t.ai.job.id);
  if(!parent.review?.accepted||JSON.stringify(parent.review.answers)!==JSON.stringify(t.ai.answers||[]))throw Error('人工结论与后台基线不一致，请返回需求页保存并确认');
  t.ai.job=parent;
  const key=planBasis(t),instructions=p.instructions;
  const job=await aiRequest('/api/jobs',{kind:'test-plan',taskId:t.id,analysisJobId:parent.id,analysisReviewDigest:parent.reviewDigest,provider:p.provider,model:p.model,instructions,templateIds:p.templateIds||['e2e']});
  if(p.job)p.history.push({jobId:p.job.id,createdAt:p.job.createdAt,draft:structuredClone(p.draft||null)});
  p.job=job;p.basisKey=key;p.generationInstructions=instructions;p.draft=null;
 }catch(e){p.error=e.message}
 finally{p.submitting=false;save();if(taskId===t.id)render();schedulePlanPoll()}
}
function schedulePlanPoll(){clearTimeout(plannerTimer);plannerTimer=setTimeout(pollPlans,1500)}
function updatePlanJob(p,j){
 if(reviewChanged(p.job,j) && p.draft){
  if(!useUpdatedReview())return;
  p.draft=structuredClone(j.review.draft);
 }
 p.job=j;if(j.status==='succeeded'&&!p.draft)p.draft=structuredClone(j.review?.draft||j.result);p.error='';}
async function pollPlans(){
 for(const t of data.tasks){const p=t.planner;if(!p?.job||!['running','cancelling'].includes(p.job.status))continue;
  try{const j=await aiRequest('/api/jobs/'+p.job.id);if(p.job.id!==j.id)continue;const changed=p.job.status!==j.status;updatePlanJob(p,j);save();if(taskId===t.id&&tab==='plan'){if(changed)render();else refreshPlanProgress()}}
  catch(e){p.error=e.message;if(taskId===t.id&&tab==='plan')render()}
 }
 if(data.tasks.some(t=>t.planner?.job&&['running','cancelling'].includes(t.planner.job.status)))schedulePlanPoll();
}
function refreshPlanProgress(){if(page==='task'&&tab==='plan'){const j=plannerState(task()).job,b=$('[data-action="planGenerate"]');if(b&&['running','cancelling'].includes(j?.status))b.textContent=j.status==='cancelling'?'正在取消…':j.stage==='reconnecting'?'连接重试中…':'方案生成中…'}const el=$('#planProgress');if(el&&page==='task'&&tab==='plan')el.innerHTML=aiProgressPanel(plannerState(task()).job,'planRefresh')}
setInterval(()=>{if(page==='task'&&tab==='plan'&&planBusy(task()))refreshPlanProgress()},1000);
async function savePlanReview(accepted){
 const t=task(),p=plannerState(t);if(!p.job||!p.draft||planBusy(t))return;
 if(planStale(t))return toast('方案依据已变化，请重新生成');
 const snapshot=structuredClone(p.draft);
 p.saving=true;render();
 try{const job=await aiRequest('/api/jobs/'+p.job.id+'/review',{expectedReviewDigest:p.job.reviewDigest,inputDigest:p.job.inputDigest,draft:snapshot,accepted});p.job=job;p.error='';t.plan=planText(snapshot);save();if(taskId===t.id){if(accepted&&JSON.stringify(p.draft)===JSON.stringify(snapshot))tab='cases';render()}toast(accepted?'测试方案已确认':'方案草稿已保存到本地后台')}
 catch(e){p.error=e.message}
 finally{p.saving=false;save();if(taskId===t.id)render()}
}
const beforePlannerAct=act;
act=function(action){const t=task(),p=plannerState(t);
 if(action.startsWith('planReviewSection:')||action.startsWith('planReviewRow:')){const v=planReviewViews.get(t.id)||{section:'objective',row:0};if(action.startsWith('planReviewSection:')){v.section=action.split(':')[1];v.row=0}else v.row=Number(action.split(':')[1]);planReviewViews.set(t.id,v);const y=window.scrollY;render();window.scrollTo(0,y);return}
 if(action==='planGenerate')return planGenerate();
 if(action==='planSave'||action==='savePlan')return savePlanReview(false);
 if(action==='planAccept')return savePlanReview(true);
 if(action==='planCancel')return aiRequest('/api/jobs/'+p.job.id+'/cancel',{}).then(j=>{p.job=j;save();render();schedulePlanPoll()}).catch(e=>toast(e.message));
 if(action==='planRefresh')return aiRequest('/api/jobs/'+p.job.id).then(j=>{updatePlanJob(p,j);save();if(taskId===t.id)render();toast('方案进展已刷新');schedulePlanPoll()}).catch(e=>toast(e.message));
 if(action==='planHistory')return modal('历史方案（只读）',p.history.map(h=>`<details><summary>${esc(new Date(h.createdAt).toLocaleString('zh-CN'))}</summary><pre class="spec-preview">${esc(h.draft?planText(h.draft):'该次生成没有可用草稿')}\n记录：${esc(h.jobId)}</pre></details>`).join(''),'关闭',()=>{});
 if(page==='task'&&journey==='design'&&['step:cases','toCases','generate'].includes(action)&&!planConfirmed(t))return toast('请先生成、审阅并确认测试方案');
 return beforePlannerAct(action);
};
const beforePlannerRender=render;
render=function(){beforePlannerRender();if(page!=='task'||tab!=='plan')return;
 const t=task(),p=plannerState(t),notice=()=>{if(p.job?.review)p.job.review.accepted=false;save();$('#planEditNotice').textContent='有修改未确认，请保存草稿或重新确认方案';if($('#planReviewNotice'))$('#planReviewNotice').textContent='有修改未确认，请保存草稿或确认方案';if($('#planReviewStatus'))$('#planReviewStatus').textContent='有未确认修改';const next=$('[data-action="step:cases"]');if(next)next.disabled=true;};
 if($('#planProvider'))$('#planProvider').onchange=e=>{p.provider=e.target.value;save();render()};
 if($('#planModel'))$('#planModel').oninput=e=>{p.model=e.target.value;save()};
 if($('#planInstructions'))$('#planInstructions').oninput=e=>{p.instructions=e.target.value;save();$('#planEditNotice').textContent=planStale(t)?'方案约束已变化，需重新生成':'方案约束与当前候选一致';for(const b of $$('[data-action="planAccept"],[data-action="planSave"]'))b.disabled=planStale(t);const next=$('[data-action="step:cases"]');if(next)next.disabled=!planConfirmed(t);};
 $$('[data-plan-field]').forEach(el=>el.oninput=()=>{p.draft[el.dataset.planField]=el.value;notice()});
 $$('[data-plan-row]').forEach(el=>el.oninput=()=>{p.draft.coverage[Number(el.dataset.planRow)][el.dataset.planKey]=el.value;notice()});
 $$('[data-plan-open]').forEach(el=>el.oninput=()=>{p.draft.openItems[Number(el.dataset.planOpen)].handling=el.value;notice()});
 const next=$('[data-action="step:cases"]');if(next)next.disabled=!planConfirmed(t);
};
document.addEventListener('click',e=>{if(page==='task'&&journey==='design'&&e.target.closest('[data-tab]')?.dataset.tab==='cases'&&!planConfirmed(task())){e.preventDefault();e.stopImmediatePropagation();toast('请先确认测试方案')}},true);
for(const t of data.tasks)if(t.planner){t.planner.submitting=false;t.planner.saving=false;}
schedulePlanPoll();render();
