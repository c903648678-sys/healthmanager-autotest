// Structured test cases, rendered as a mind map; no external runtime required.
const caseState=t=>t.caseDesigner||(t.caseDesigner={provider:plannerState(t).provider,model:plannerState(t).model,instructions:'',history:[],collapsed:[],zoom:70,detailsHidden:true});
const caseBasis=t=>JSON.stringify({planId:t.planner?.job?.id,review:t.planner?.job?.review,draft:t.planner?.draft,requirements:planBasis(t),...(t.designModel?{designModel:t.designModel}:{})});
const caseBusy=t=>['running','cancelling'].includes(caseState(t).job?.status)||caseState(t).submitting||caseState(t).saving;
const caseStale=t=>!planConfirmed(t)||caseState(t).basis!==caseBasis(t)||caseState(t).generationInstructions!==caseState(t).instructions||caseState(t).job?.basisCurrent===false;
const caseAccepted=t=>!caseStale(t)&&caseState(t).job?.review?.accepted&&JSON.stringify(caseState(t).draft)===JSON.stringify(caseState(t).job.review.draft);
let caseTimer;
function caseInvalidate(t){for(const c of t.cases)if(c.designJobId){c.confirmed=false;c.reviewNeeded=true;if(c.script!=='未实现')c.script='需重新验证';}}
function caseMarkdown(d){return '# '+d.title+'\n\n'+d.cases.map(c=>`## ${c.group} / ${c.id} ${c.title}\n\n- 需求：${c.requirementIds.join('、')}\n- 层级 / 优先级：${c.layer} / ${c.priority}\n- 前置条件：${c.preconditions}\n- 测试数据：${c.testData}\n\n${c.steps.map((s,i)=>`${i+1}. ${s.action}\n   预期：${s.expected}`).join('\n')}\n\n清理：${c.cleanup}\n\n依赖：${c.dependencies}`).join('\n\n')+'\n\n## 未决问题\n'+(d.openItems.map(i=>`${i.questionId}：${i.handling}`).join('\n')||'无');}
function caseDetail(c,locked){return `<aside class="case-detail card pad"><h2>用例详情 · ${esc(c.id)}</h2><p class="subtitle">关联需求：${c.requirementIds.map(esc).join('、')}</p><fieldset ${locked?'disabled':''}><label>场景分组<input data-case-field="group" value="${esc(c.group)}" maxlength="20000"></label><label>用例标题<input data-case-field="title" value="${esc(c.title)}" maxlength="20000"></label><div class="form-grid"><label>测试层<select data-case-field="layer">${['UI','API','端侧','手工'].map(v=>`<option ${c.layer===v?'selected':''}>${v}</option>`).join('')}</select></label><label>优先级<select data-case-field="priority">${['P0','P1','P2'].map(v=>`<option ${c.priority===v?'selected':''}>${v}</option>`).join('')}</select></label></div>${[['preconditions','前置条件'],['testData','测试数据']].map(([k,n])=>`<label>${n}<textarea data-case-field="${k}" maxlength="20000">${esc(c[k])}</textarea></label>`).join('')}<h3>操作步骤与预期</h3>${c.steps.map((s,i)=>`<div class="case-step"><label>步骤 ${i+1}<textarea data-case-step="${i}" data-step-key="action" maxlength="20000">${esc(s.action)}</textarea></label><label>预期结果<textarea data-case-step="${i}" data-step-key="expected" maxlength="20000">${esc(s.expected)}</textarea></label>${c.steps.length>1?btn('移除本步骤','caseRemoveStep:'+i,'small'):''}</div>`).join('')}${btn('添加步骤','caseAddStep','small')}${[['cleanup','数据清理'],['dependencies','执行依赖 / 阻塞条件']].map(([k,n])=>`<label>${n}<textarea data-case-field="${k}" maxlength="20000">${esc(c[k])}</textarea></label>`).join('')}</fieldset><p class="subtitle">编辑会自动保存到任务；“保存用例草稿”记录审阅版本，“确认整套用例”表示审阅完成。</p></aside>`;}
const legacyCases=cases;
cases=function(){
 const t=task();if(journey!=='design')return legacyCases();
 const p=caseState(t),d=p.draft,j=p.job,busy=caseBusy(t),stale=!!j&&caseStale(t);
 if(!planConfirmed(t))return `<div class="notice">请先确认当前测试方案。已有用例仍保留，但不能作为新方案的确认结果。</div>${btn('返回测试方案','step:plan','primary')}`;
 const groups=d?[...new Set(d.cases.map(c=>c.group))]:[],current=d?.cases.find(c=>c.id===p.selected)||d?.cases[0];
 if(current)p.selected=current.id;
 return `<div class="card pad"><div class="row"><div><h2>测试用例设计 · 思维导图</h2><p class="subtitle">已确认方案：${esc(t.planner.draft.title)} · 场景 → 用例 → 步骤与预期</p></div>${btn('返回测试方案','step:plan','small')}</div><details id="caseGenerationSettings" ${(p.settingsOpen??!j)?'open':''}><summary>生成设置</summary>${aiConnectionPanel()}${btn('检测连接','aiConnect','small')}<fieldset ${busy?'disabled':''}><div class="form-grid"><label>用例引擎<select id="caseProvider">${['codex','claude'].map(v=>`<option ${p.provider===v?'selected':''}>${v}</option>`).join('')}</select></label><label>模型（留空使用 CLI 默认）<input id="caseModel" maxlength="150" value="${esc(p.model)}"></label></div><label>设计侧重点<textarea id="caseInstructions" maxlength="10000" placeholder="例如：优先正常、边界、权限和失败重试，步骤明确可执行">${esc(p.instructions)}</textarea></label></fieldset><p class="subtitle">生成会将已确认规格、人工结论和测试方案发送至所选模型服务。</p></details><div class="actions"><button class="primary" data-action="caseGenerate" ${busy||!aiHealth?.providers.find(v=>v.id===p.provider)?.installed?'disabled':''}>${busy?'正在处理…':j?'重新生成用例':'生成测试用例'}</button>${['running','cancelling'].includes(j?.status)?btn('取消生成','caseCancel','small'):''}${p.history.length?btn('历史用例集（'+p.history.length+'）','caseHistory','small'):''}</div></div>
 ${p.error?`<div class="notice">${esc(p.error)}</div>`:''}${stale?'<div class="notice">方案、需求或生成约束已变化，当前用例集已过期，请重新生成。</div>':''}<div id="caseProgress">${aiProgressPanel(j,'caseRefresh')}</div>
 ${d?`<div class="card pad"><div class="row"><h2>${esc(d.title)}</h2><span id="caseReviewStatus">${badge(caseAccepted(t)?'用例集已确认':'待审阅')}</span></div><p class="subtitle">${groups.length} 个场景 · ${d.cases.length} 条用例 · 点击场景折叠，点击用例编辑；导图可横向滚动。</p><div class="actions">${btn('全部展开','caseExpand','small')}${btn('全部折叠','caseCollapse','small')}${btn('−','caseZoomOut','small')}<span>${p.zoom||100}%</span>${btn('＋','caseZoomIn','small')}${btn('重置视图','caseZoomReset','small')}${btn(p.detailsHidden?'显示用例详情':'导图全宽','caseToggleDetails','small')}${btn('导出 Markdown','caseExport','small')}</div></div><div class="case-workspace ${p.detailsHidden?'map-wide':''}"><div class="mindmap-viewport card" aria-label="测试用例思维导图"><div class="mindmap-tree" style="zoom:${(p.zoom||100)/100}"><div class="mindmap-root">${esc(d.title)}<small>${d.cases.length} 条用例</small></div><div class="mindmap-groups">${groups.map((g,i)=>`<div class="mindmap-branch" style="--branch:${['#6257d9','#168b88','#cf8c28','#cb5885','#498bd0'][i%5]}"><button class="mindmap-group" data-action="caseGroup:${i}" aria-expanded="${!p.collapsed.includes(g)}">${esc(g)}<small>${d.cases.filter(c=>c.group===g).length} 条 · ${p.collapsed.includes(g)?'＋':'−'}</small></button>${p.collapsed.includes(g)?'':`<div class="mindmap-leaves">${d.cases.filter(c=>c.group===g).map(c=>`<button class="mindmap-case ${c.id===current?.id?'selected':''}" data-case-select="${esc(c.id)}" aria-pressed="${c.id===current?.id}"><small>${esc(c.id)} · ${esc(c.layer)} · ${esc(c.priority)}</small>${esc(c.title)}</button>`).join('')}</div>`}</div>`).join('')}</div></div></div>${current&&!p.detailsHidden?caseDetail(current,busy||stale):''}</div><div class="card pad"><h2>未决问题</h2>${d.openItems.map(i=>`<p>${esc(i.questionId)}：${esc(i.handling)}</p>`).join('')||'<p class="subtitle">当前方案无未决问题。各用例仍需核对执行依赖。</p>'}<div class="actions"><button data-action="caseSave" ${busy||stale?'disabled':''}>保存用例草稿</button><button class="primary" data-action="caseAccept" ${busy||stale?'disabled':''}>确认整套用例</button></div><p class="subtitle">确认表示你已审阅全部用例，不代表已执行通过。自动化脚本和 CI 执行仍为示例。</p></div>`:'<div class="empty">生成完成后，将在这里按场景展示用例思维导图。</div>'}`;
};
async function caseGenerate(){
 const t=task(),p=caseState(t);if(caseBusy(t)||!planConfirmed(t))return;
 p.submitting=true;p.error='';render();
 try{const parent=await aiRequest('/api/jobs/'+t.planner.job.id);
  if(!parent.review?.accepted||!parent.basisCurrent||JSON.stringify(parent.review.draft)!==JSON.stringify(t.planner.draft))throw Error('方案与后台确认版本不一致，请先保存并确认测试方案');
  t.planner.job=parent;const basis=caseBasis(t),instructions=p.instructions;
  const job=await aiRequest('/api/jobs',{kind:'test-cases',taskId:t.id,planJobId:parent.id,planReviewDigest:parent.reviewDigest,provider:p.provider,model:p.model,instructions,useDesignModel:!!t.designModel?.confirmed});
  if(p.job)p.history.push({jobId:p.job.id,createdAt:p.job.createdAt,draft:structuredClone(p.draft)});
  p.job=job;p.basis=basis;p.generationInstructions=instructions;p.draft=null;p.selected=null;p.collapsed=[];caseInvalidate(t);
 }catch(e){p.error=e.message}finally{p.submitting=false;save();if(taskId===t.id)render();scheduleCases()}
}
function updateCases(p,j){
 if(reviewChanged(p.job,j) && p.draft){
  if(!useUpdatedReview())return;
  p.draft=structuredClone(j.review.draft);
 }
 p.job=j;if(j.status==='succeeded'&&!p.draft)p.draft=structuredClone(j.review?.draft||j.result);p.error='';}
function scheduleCases(){clearTimeout(caseTimer);caseTimer=setTimeout(pollCases,1500)}
async function pollCases(){for(const t of data.tasks){const p=t.caseDesigner;if(!p?.job||!['running','cancelling'].includes(p.job.status))continue;try{const j=await aiRequest('/api/jobs/'+p.job.id);if(p.job.id!==j.id)continue;const changed=j.status!==p.job.status;updateCases(p,j);save();if(taskId===t.id&&tab==='cases'){if(changed)render();else refreshCaseProgress()}}catch(e){p.error=e.message;if(taskId===t.id&&tab==='cases')render()}}if(data.tasks.some(t=>['running','cancelling'].includes(t.caseDesigner?.job?.status)))scheduleCases()}
function refreshCaseProgress(){const el=$('#caseProgress');if(el&&page==='task'&&tab==='cases')el.innerHTML=aiProgressPanel(caseState(task()).job,'caseRefresh')}
setInterval(()=>{if(page==='task'&&tab==='cases'&&caseBusy(task()))refreshCaseProgress()},1000);
async function saveCases(accepted){const t=task(),p=caseState(t);if(caseBusy(t)||!p.draft||caseStale(t))return;const draft=structuredClone(p.draft);p.saving=true;render();try{
 p.job=await aiRequest('/api/jobs/'+p.job.id+'/review',{expectedReviewDigest:p.job.reviewDigest,inputDigest:p.job.inputDigest,draft,accepted});p.error='';
 if(accepted){t.caseArchive=t.caseArchive||[];if(t.cases.length)t.caseArchive.push({time:new Date().toISOString(),cases:structuredClone(t.cases)});
 const manualCases=t.cases.filter(c=>c.origin==='manual');
 t.cases=draft.cases.map(c=>({...c,id:p.job.id.slice(0,8)+'-'+c.id,designCaseId:c.id,designJobId:p.job.id,confirmed:true,reviewNeeded:false,script:'未实现',source:c.requirementIds.join('、'),steps:'前置条件：'+c.preconditions+'\n测试数据：'+c.testData+'\n'+c.steps.map((s,i)=>`${i+1}. ${s.action}`).join('\n')+'\n清理：'+c.cleanup+'\n依赖：'+c.dependencies,expected:c.steps.map((s,i)=>`${i+1}. ${s.expected}`).join('\n')})).concat(manualCases);selected.clear();}
 toast(accepted?'整套用例已确认，可进入手工执行场景':'用例草稿已保存到本地后台');
 }catch(e){p.error=e.message}finally{p.saving=false;save();if(taskId===t.id)render()}}
const beforeCaseAct=act;
act=function(action){const t=task(),p=caseState(t),[name,arg]=action.split(':');
 if(name==='edit'&&t.cases.find(c=>c.id===arg)?.designJobId){const c=t.cases.find(c=>c.id===arg);p.selected=c.designCaseId;journey='design';tab='cases';render();return}
 if(action==='caseGenerate'||(action==='generate'&&journey==='design'))return caseGenerate();
 if(name==='caseSave')return saveCases(false);if(name==='caseAccept')return saveCases(true);
 if(name==='caseCancel')return aiRequest('/api/jobs/'+p.job.id+'/cancel',{}).then(j=>{p.job=j;save();render();scheduleCases()}).catch(e=>toast(e.message));
 if(name==='caseRefresh')return aiRequest('/api/jobs/'+p.job.id).then(j=>{updateCases(p,j);save();render();scheduleCases()}).catch(e=>toast(e.message));
 if(name==='caseExport')return download(t.id+'-测试用例.md',caseMarkdown(p.draft));
 if(name==='caseHistory')return modal('历史用例集（只读）',p.history.map(h=>`<details><summary>${esc(new Date(h.createdAt).toLocaleString('zh-CN'))}</summary><pre class="spec-preview">${esc(h.draft?caseMarkdown(h.draft):'该次未生成可用结果')}</pre></details>`).join(''),'关闭',()=>{});
 if(name==='caseToggleDetails'){p.detailsHidden=!p.detailsHidden;save();render();return}
 if(name==='caseGroup'){const g=[...new Set(p.draft.cases.map(c=>c.group))][Number(arg)];p.collapsed=p.collapsed.includes(g)?p.collapsed.filter(v=>v!==g):[...p.collapsed,g];save();render();return}
 if(name==='caseExpand'||name==='caseCollapse'){p.collapsed=name==='caseExpand'?[]:[...new Set(p.draft.cases.map(c=>c.group))];save();render();return}
 if(name.startsWith('caseZoom')){p.zoom=name==='caseZoomReset'?70:Math.max(60,Math.min(140,(p.zoom||100)+(name==='caseZoomIn'?10:-10)));save();render();return}
 if(name==='caseAddStep'||name==='caseRemoveStep'){if(caseBusy(t)||caseStale(t))return;const c=p.draft.cases.find(c=>c.id===p.selected);if(name==='caseAddStep')c.steps.push({action:'',expected:''});else if(c.steps.length>1)c.steps.splice(Number(arg),1);if(p.job.review)p.job.review.accepted=false;caseInvalidate(t);save();render();return}
 return beforeCaseAct(action);
};
const beforeCaseRender=render;
render=function(){for(const t of data.tasks)if(t.caseDesigner?.job&&!caseAccepted(t))caseInvalidate(t);beforeCaseRender();if(page!=='task'||tab!=='cases'||journey!=='design')return;const t=task(),p=caseState(t);
 const settings=$('#caseGenerationSettings');
 if(settings)settings.ontoggle=()=>{if(settings.isConnected){p.settingsOpen=settings.open;save();}};
 if($('#caseProvider'))$('#caseProvider').onchange=e=>{p.provider=e.target.value;save();render()};
 if($('#caseModel'))$('#caseModel').oninput=e=>{p.model=e.target.value;save()};
 if($('#caseInstructions'))$('#caseInstructions').oninput=e=>{p.instructions=e.target.value;if(p.job){caseInvalidate(t);for(const b of $$('[data-action="caseSave"],[data-action="caseAccept"]'))b.disabled=caseStale(t);if($('#caseReviewStatus'))$('#caseReviewStatus').innerHTML=badge(caseStale(t)?'约束已变化，请重新生成':'待审阅');}save();};
 $$('[data-case-select]').forEach(el=>el.onclick=()=>{p.selected=el.dataset.caseSelect;p.detailsHidden=false;save();render()});
 const changed=()=>{if(p.job.review)p.job.review.accepted=false;caseInvalidate(t);save();$('#caseReviewStatus').innerHTML=badge('有修改待确认');};
 $$('[data-case-field]').forEach(el=>el.oninput=()=>{const c=p.draft.cases.find(c=>c.id===p.selected);c[el.dataset.caseField]=el.value;changed();});
 $$('[data-case-field="title"],[data-case-field="group"]').forEach(el=>el.onchange=()=>render());
 $$('[data-case-step]').forEach(el=>el.oninput=()=>{p.draft.cases.find(c=>c.id===p.selected).steps[Number(el.dataset.caseStep)][el.dataset.stepKey]=el.value;changed()});
};
for(const t of data.tasks)if(t.caseDesigner){t.caseDesigner.submitting=false;t.caseDesigner.saving=false;}
scheduleCases();render();
