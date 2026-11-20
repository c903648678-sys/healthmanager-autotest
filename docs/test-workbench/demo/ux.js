// Tester-focused presentation. Workflow and backend validation remain authoritative.
const uxOpen=new Map();
function uxReviewCount(t){const p=t.caseDesigner;if(p?.draft&&p.job?.status==='succeeded')return caseAccepted(t)?0:p.draft.cases.length;return t.cases.filter(c=>!c.confirmed||c.reviewNeeded).length;}
function uxNext(t){
 const lc=taskLC(t);
 if(lc.location==='trash')return {label:'恢复任务',action:'taskManage:restore:'+t.id,hint:'恢复原状态和记录'};
 if(lc.location==='archive')return {label:'查看归档',action:'open:'+t.id,hint:'只读保留，可移出归档'};
 if(lc.status==='paused')return {label:'继续任务',action:'taskManage:resume:'+t.id,hint:'已暂停，继续后回到原工作步骤'};
 if(lc.status!=='active')return {label:'查看成果',action:'open:'+t.id,hint:lc.status==='completed'?'本次工作已结束，完成不代表测试通过':'已取消，成果与操作记录仍保留'};
 for(const [p,step] of [[t.ai,'requirements'],[t.planner,'plan'],[t.caseDesigner,'cases']])if(['running','cancelling'].includes(p?.job?.status))return {label:'查看生成进展',action:'uxStep:'+t.id+':'+step,hint:p.job.message||'模型正在处理'};
 if(t.activeJourney&&t.activeJourney!=='design')return {label:'继续'+(journeys[t.activeJourney]?.name||'任务'),action:'open:'+t.id,hint:'上次停留在'+(tabs[t.activeStep]||'当前步骤')};
 if(!confirmedSources(t))return {label:'选择规格方案',action:'uxStep:'+t.id+':sources',hint:'先关联本次需求的规格文件'};
 if(!aiAccepted(t))return {label:t.ai?.job?.status==='succeeded'?'审阅需求与疑问':'分析需求',action:'uxStep:'+t.id+':requirements',hint:'确认需求理解和关键问题后，再设计方案'};
 if(!planConfirmed(t))return {label:t.planner?.draft?'审阅测试方案':'生成测试方案',action:'uxStep:'+t.id+':plan',hint:'明确范围、策略和需求覆盖安排'};
 if(!caseAccepted(t))return {label:t.caseDesigner?.draft?'审阅测试用例':'生成测试用例',action:'uxStep:'+t.id+':cases',hint:t.caseDesigner?.draft?'在思维导图中核对步骤与预期，再确认整套用例':'方案已确认，可以生成用例'};
 return {label:'完成本次设计',action:'taskManage:complete:'+t.id,hint:'方案和用例已确认，可交付设计；无需先执行'};
}
function uxMatches(t,filter){const lc=taskLC(t);if(['archive','trash'].includes(filter))return lc.location===filter;return lc.location==='work'&&(filter==='all'||(filter==='review'?lc.status==='active'&&uxReviewCount(t)>0:lc.status===filter));}
function taskButtons(t){return taskActions(t).map(a=>`<button type="button" class="small ${['delete','purge'].includes(a)?'danger-action':''}" data-action="taskManage:${a}:${esc(t.id)}">${esc(a==='complete'&&(t.activeJourney||'design')==='design'?'完成本次设计':taskActionNames[a])}</button>`).join('');}
taskRows=function(){const items=data.tasks.filter(t=>uxMatches(t,taskFilter)&&(!taskSearch||(t.name+' '+(t.requirementNo||'')).toLowerCase().includes(taskSearch.toLowerCase())));
 if(!items.length)return `<div class="empty ux-empty"><h3>${taskSearch?'没有找到匹配的任务':taskFilter==='trash'?'回收站是空的':taskFilter==='archive'?'暂无归档任务':'当前列表暂无任务'}</h3><p>${taskSearch?'试试任务名称或需求单号，也可以清空搜索。':taskFilter==='trash'?'移入回收站的任务会出现在这里，可随时恢复。':'可以切换状态查看已有任务，或新建一个测试任务。'}</p><div class="actions">${taskSearch?btn('清空搜索','uxClearSearch','small'):btn('查看全部工作任务','taskFilter:all','small')}${!['trash','archive'].includes(taskFilter)?btn('新建测试任务','new','primary small'):''}</div></div>`;
 const trash=taskFilter==='trash';
 return `<div class="ux-task-table-wrap"><table class="ux-task-table"><thead><tr><th>任务 / 需求单号</th><th>${trash?'删除前状态':'状态'}</th><th>工作阶段</th><th>用例</th><th>${trash?'移入时间':'最近更新'}</th><th>操作</th></tr></thead><tbody>${items.map(t=>{const lc=taskLC(t),next=uxNext(t),pending=uxReviewCount(t),count=t.caseDesigner?.draft?.cases.length??t.cases.length,time=trash?[...(lc.history||[])].reverse().find(h=>h.action==='delete')?.time:lc.updatedAt,date=time?new Date(time):null;return `<tr><td><strong title="${esc(t.name)}">${esc(t.name)}</strong><small>${esc(t.requirementNo||'无需求单号')} · ${esc(t.version||'未指定版本')}</small></td><td>${badge(taskStatusNames[lc.status])}</td><td>${esc(tabs[t.activeStep]||'选择规格方案')}</td><td><b class="ux-case-count">${count}</b><small>${pending?pending+' 条待审阅':count?'已审阅':'暂无用例'}</small></td><td><span class="ux-task-time">${date&&!isNaN(date)?esc(date.toLocaleDateString('zh-CN')):'—'}</span><small>${date&&!isNaN(date)?esc(date.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})):''}</small></td><td><div class="ux-row-ops">${btn(next.label,next.action,taskEditable(t)?'primary small':'small')}${trash?btn('彻底删除','taskManage:purge:'+t.id,'link small danger-action'):btn('更多','uxTaskMenu:'+t.id,'link small')}${btn('记录','taskHistory:'+t.id,'link small')}</div></td></tr>`}).join('')}</tbody></table></div><div class="ux-task-total">共 ${items.length} 个任务${trash?' · 删除前状态仅供恢复参考':''}</div>`;

};
home=function(){const active=data.tasks.filter(taskEditable),review=active.reduce((n,t)=>n+uxReviewCount(t),0);return title('我的测试任务','继续当前工作，或从一份新规格开始。',btn('＋ 新建测试任务','new','primary'))+
 `<details class="card pad ux-scenes" data-ux-open="scenes" ${(uxOpen.get('scenes')??true)?'open':''}><summary>按工作场景开始 <span class="subtitle">测试设计、需求变更、问题处理等</span></summary><div class="secondary-scenes">${Object.entries(journeys).filter(([k])=>!['regression','manual'].includes(k)).map(([k,j])=>`<button class="scene-mini" data-action="scenario:${k}"><div><b>${esc(j.name)}${k==='automation'?' · 演示':''}</b><small>${esc(j.desc)}</small></div></button>`).join('')}</div></details><div class="ux-metrics" aria-label="工作概况">${btn('进行中 '+active.length,'taskFilter:active','')}${btn('待审阅用例 '+review,'taskFilter:review','')}${btn('已暂停 '+data.tasks.filter(t=>uxMatches(t,'paused')).length,'taskFilter:paused','')}<span>待处理问题 ${active.flatMap(t=>t.issues).filter(i=>i.status!=='已关闭').length+(typeof executionOverview!=='undefined'?(executionOverview?.issues||[]).filter(i=>i.status!=='已关闭'&&active.some(t=>t.id===i.taskId)).length:0)}</span></div><section class="card ux-task-list"><div class="ux-list-tools"><label class="ux-search">查找任务<input id="taskSearch" placeholder="任务名称 / 需求单号" value="${esc(taskSearch)}" type="search"></label><div class="ux-filters" aria-label="任务状态筛选">${[['active','进行中'],['review','待审阅'],['paused','已暂停'],['completed','已完成'],['cancelled','已取消'],['all','全部'],['archive','归档'],['trash','回收站']].map(([k,n])=>`<button class="small ${taskFilter===k?'primary':''}" data-action="taskFilter:${k}" aria-pressed="${taskFilter===k}">${n}<span class="ux-count">${data.tasks.filter(t=>uxMatches(t,k)).length}</span></button>`).join('')}</div>${taskFilter==='trash'?'<p class="subtitle">恢复后保留原状态和记录；彻底删除不可恢复。正式用例和共享知识不受影响。</p>':''}</div><div id="taskRows">${taskRows()}</div></section>`;};
// Collapse detailed progress, retaining the current stage and failures in plain sight.
const uxOriginalProgress=aiProgressPanel;
aiProgressPanel=function(j,action){if(!j)return '';const html=uxOriginalProgress(j,action),key='progress-'+j.id;
 return html.replace('<ol class="ai-event-log">',`<details data-ux-open="${esc(key)}" ${uxOpen.get(key)?'open':''}><summary>查看详细进展与日志</summary><ol class="ai-event-log">`).replace('</ol></section>','</ol></details></section>');
};
document.addEventListener('toggle',e=>{if(e.target.matches?.('[data-ux-open]')&&e.target.isConnected)uxOpen.set(e.target.dataset.uxOpen,e.target.open);},true);
const uxPreviousAct=act;
act=function(action){const [name,id,step]=action.split(':');if(name==='uxClearSearch'){taskSearch='';render();$('#taskSearch')?.focus();return;}if(name==='uxStep'){if(!workspaceReady||workspaceError)return toast('请先处理工作区连接或保存问题');return enterJourney('design',id,step);}return uxPreviousAct(action);};
const uxPreviousRender=render;
render=function(){const focused=document.activeElement;const focusAction=focused?.dataset?.action;uxPreviousRender();
 const sync=$('#workspaceSync');if(sync){sync.parentElement.classList.add('ux-save-status');sync.parentElement.setAttribute('aria-label','工作区保存状态');}
 const demo=$('header .demo');if(demo)demo.textContent='设计支持真实模型 · 自动化执行为演示';
 // A generated result makes review the primary task; regeneration remains available.
 for(const [action,draft,job] of [['planGenerate',task().planner?.draft,task().planner?.job],['caseGenerate',task().caseDesigner?.draft,task().caseDesigner?.job]]){
  const b=$(`[data-action="${action}"]`);if(b&&draft&&job?.status==='succeeded'&&!(action==='planGenerate'?planStale(task()):caseStale(task())))b.classList.remove('primary');
 }
 if(page==='task'&&journey==='design'&&taskEditable(task())){
  const subtitle=$('.title .subtitle');if(subtitle)subtitle.textContent=subtitle.textContent.replace(' · '+taskId,'');
  const footer=$('.journey-footer');if(footer){footer.classList.add('ux-sticky-footer');if(tab==='cases'&&caseAccepted(task()))footer.querySelector('.actions').insertAdjacentHTML('beforeend',btn('完成本次设计','taskManage:complete:'+taskId,'primary'));}if(sync)sync.insertAdjacentHTML('afterend','<span class="ux-save-note"> · 保存不代表已审阅确认</span>');
  const next=uxNext(task());const banner=$('.journey-banner');if(banner){banner.querySelector('b').textContent='当前目标：'+next.hint;banner.querySelector('p').textContent='工作步骤可保存后继续；生成结果需要人工审阅确认。';}
 }
 if(focusAction){const target=$$('[data-action]').find(el=>el.dataset.action===focusAction&&!el.disabled);if(target)target.focus({preventScroll:true});}
};
render();

const uxTaskMenuAct=act;
act=function(action){if(action.startsWith('uxTaskMenu:')){const t=data.tasks.find(x=>x.id===action.slice(11));if(!t)return;return modal('任务操作 · '+t.name,`<div class="actions">${taskButtons(t)}</div>`,'关闭',()=>{})}return uxTaskMenuAct(action)};
