// Local workspace persistence and task lifecycle; no middleware or accounts.
const taskStatusNames={active:'进行中',paused:'已暂停',completed:'已完成',cancelled:'已取消'};
const taskActionNames={edit:'编辑信息',pause:'暂停任务',resume:'继续任务',complete:'完成任务',cancel:'取消任务',reopen:'重新打开',archive:'归档',unarchive:'移出归档',purge:'彻底删除',delete:'移入回收站',restore:'恢复任务'};
let workspaceReady=false,workspaceRevision=0,workspaceError='',workspaceDirty=false,workspaceSaving=null,workspaceTimer,workspaceStamp='',taskFilter='active',taskSearch='',taskActionBusy=false;
const originalLocalSave=save,workspaceRequest=aiRequest;
const taskLC=t=>t.lifecycle||{status:t.stage==='已完成'?'completed':'active',location:'work',history:[]};
const taskEditable=t=>taskLC(t).status==='active'&&taskLC(t).location==='work';
const taskInFlight=t=>busy||(typeof readingFiles!=='undefined'&&readingFiles)||[t.ai,t.planner,t.caseDesigner].some(p=>p&&(p.submitting||p.saving||['running','cancelling'].includes(p.job?.status)));
function syncLabel(){const el=$('#workspaceSync');if(el&&workspaceError&&!$('#workspaceRecovery'))el.insertAdjacentHTML('afterend',`<div id="workspaceRecovery" class="actions">${btn('重试保存','workspaceRetry','small')}${btn('加载后台版本','workspaceReload','small')}${btn('导出浏览器备份','workspaceBackup','small')}</div>`);if(el)el.textContent=workspaceError?'保存异常：'+workspaceError:!workspaceReady?'正在加载本地工作区…':workspaceSaving?'正在保存到本地后台…':workspaceDirty?'有修改等待保存…':'已保存到本地后台';}
save=function(){originalLocalSave();if(workspaceReady&&!workspaceError){workspaceDirty=true;clearTimeout(workspaceTimer);workspaceTimer=setTimeout(()=>flushWorkspace().catch(()=>{}),450);syncLabel();}};
async function flushWorkspace(){
 if(!workspaceReady)throw Error('本地工作区尚未加载，请稍后再试');
 if(workspaceError)throw Error(workspaceError);
 if(workspaceSaving){await workspaceSaving;return flushWorkspace();}
 const stamp=JSON.stringify(data);if(stamp===workspaceStamp){workspaceDirty=false;syncLabel();return;}
 workspaceDirty=false;
 workspaceSaving=(async()=>{try{const response=await workspaceRequest('/api/workspace',{revision:workspaceRevision,data:JSON.parse(stamp)},30000);workspaceRevision=response.revision;
  for(const saved of response.data.tasks){const t=data.tasks.find(t=>t.id===saved.id);if(t){if(taskEditable(t))t.lifecycle=saved.lifecycle;else data.tasks[data.tasks.indexOf(t)]=saved;}}
  const sent=JSON.parse(stamp);for(const t of sent.tasks)t.lifecycle=response.data.tasks.find(x=>x.id===t.id).lifecycle;
  workspaceStamp=JSON.stringify(sent);originalLocalSave();
 }catch(e){workspaceError=e.message;workspaceDirty=true;toast('未保存到后台，浏览器草稿仍保留：'+e.message);throw e}finally{workspaceSaving=null;syncLabel();}})();
 syncLabel();await workspaceSaving;if(workspaceDirty)return flushWorkspace();
}
aiRequest=async function(path,body,timeout){if(body!==undefined&&(path==='/api/jobs'||path.endsWith('/review'))){await flushWorkspace();if(!taskEditable(task()))throw Error('当前任务只读，请恢复或重新打开');}return workspaceRequest(path,body,timeout);};
async function loadWorkspace(){
 try{const response=await workspaceRequest('/api/workspace',undefined,10000);workspaceRevision=response.revision;
  if(response.data===null){const migrated=await workspaceRequest('/api/workspace',{revision:response.revision,data},30000);data=migrated.data;workspaceRevision=migrated.revision;}
  else {if(JSON.stringify(data)!==JSON.stringify(response.data)){try{if(!localStorage.getItem(KEY+'-before-server-load'))localStorage.setItem(KEY+'-before-server-load',JSON.stringify(data));}catch{}}data=response.data;}
  taskId=data.tasks.find(t=>taskLC(t).location==='work')?.id||data.tasks[0]?.id||'';
  for(const t of data.tasks)for(const p of [t.ai,t.planner,t.caseDesigner])if(p){p.submitting=false;p.saving=false;}
  workspaceStamp=JSON.stringify(response.data||data);workspaceReady=true;workspaceError='';workspaceDirty=false;originalLocalSave();page='home';render();aiSchedulePoll();schedulePlanPoll();scheduleCases();
 }catch(e){workspaceError=e.message;render();}
}
function taskActions(t){const lc=taskLC(t);if(lc.location==='trash')return ['restore','purge'];if(lc.location==='archive')return ['unarchive','delete'];return lc.status==='active'?['edit','pause','complete','cancel','delete']:lc.status==='paused'?['resume','cancel','delete']:['reopen','archive','delete'];}
function taskButtons(t){return taskActions(t).map(a=>btn(taskActionNames[a],'taskManage:'+a+':'+t.id,['delete','purge'].includes(a)?'small':'small')).join('');}
function taskRows(){const items=data.tasks.filter(t=>{const lc=taskLC(t);return (['archive','trash'].includes(taskFilter)?lc.location===taskFilter:lc.location==='work'&&(taskFilter==='all'||lc.status===taskFilter))&&(!taskSearch||(t.name+' '+(t.requirementNo||'')).toLowerCase().includes(taskSearch.toLowerCase()));});
 return items.map(t=>{const lc=taskLC(t);return `<div class="task-row"><div class="row"><div><h3>${esc(t.name)}</h3><div class="tags">${badge(taskStatusNames[lc.status])}${badge(tabs[t.activeStep]||'规格选择')}<span>${esc(t.requirementNo||'未填写需求单号')} · ${esc(t.version)}</span></div></div>${lc.location!=='trash'?btn(taskEditable(t)?'继续任务 →':'查看任务','open:'+t.id,'small'):''}</div><p class="meta">${t.cases.length} 条用例 · ${t.attempts.length} 次手工记录 · ${t.runs.length} 次自动化模拟</p><div class="actions"><details><summary>更多操作</summary><div class="actions" style="margin:12px 0">${taskButtons(t)}${btn('操作记录','taskHistory:'+t.id,'small')}</div></details></div></div>`;}).join('')||'<div class="empty">此列表暂无任务。可以新建任务、切换筛选，或从回收站恢复。</div>';
}
home=function(){const active=data.tasks.filter(t=>taskEditable(t));return title('我的测试任务','管理设计、执行与交付；完成设计不要求先执行。',btn('新建测试任务','new','primary'))+
 stats([['进行中',active.length,'个'],['已暂停',data.tasks.filter(t=>taskLC(t).location==='work'&&taskLC(t).status==='paused').length,'个'],['用例待审阅',active.flatMap(t=>t.cases).filter(c=>!c.confirmed).length,'条'],['待处理问题',active.flatMap(t=>t.issues).filter(i=>i.status!=='已关闭').length,'项']])+
 `<div class="secondary-scenes">${['design','manual','automation','regression','issues','change','summary'].map(k=>`<button class="scene-mini" data-action="scenario:${k}"><span>${journeys[k].icon}</span><div><b>${journeys[k].name}</b><small>${journeys[k].desc}</small></div></button>`).join('')}</div><div class="card pad"><div class="actions">${[['active','进行中'],['paused','已暂停'],['completed','已完成'],['cancelled','已取消'],['all','全部工作任务'],['archive','归档'],['trash','回收站']].map(([k,n])=>btn(n,'taskFilter:'+k,taskFilter===k?'primary small':'small')).join('')}</div><input id="taskSearch" aria-label="搜索任务" placeholder="搜索任务名称或需求单号" value="${esc(taskSearch)}" style="margin-top:14px"><p class="subtitle">回收站支持恢复或逐项彻底删除；彻底删除不可恢复，不影响正式用例和共享知识。</p></div><div id="taskRows" class="card">${taskRows()}</div>`;};
const originalTaskPage=taskPage;
taskPage=function(){const t=task(),lc=taskLC(t);const toolbar=`<div class="card pad"><div class="row"><div>${badge(taskStatusNames[lc.status])} ${lc.location==='archive'?badge('已归档'):''}</div><details><summary>任务管理</summary><div class="actions" style="margin-top:12px">${taskButtons(t)}${btn('操作记录','taskHistory:'+t.id,'small')}</div></details></div></div>`;
 if(taskEditable(t))return toolbar+originalTaskPage();
 return `${btn('← 返回工作台','taskHome','link')}${title(esc(t.name),'只读任务 · '+esc(t.requirementNo||'未填写需求单号'))}${toolbar}<div class="notice">${lc.location==='archive'?'先移出归档，再重新打开即可编辑。':lc.status==='paused'?'点击“继续任务”恢复工作。':'重新打开后可继续原来的工作步骤。'}完成任务不代表测试通过或批准发布。</div><div class="card pad"><h2>任务信息与交付</h2><p class="report-text">${esc(t.description||'暂无说明')}\n${esc(lc.completion?.conclusion||'')}</p><p>${t.cases.length} 条用例 · ${t.attempts.length} 次手工记录 · ${t.issues.filter(i=>i.status!=='已关闭').length} 项未关闭问题</p>${btn('导出任务备份','taskExport:'+t.id,'small')}</div><div class="card pad"><details><summary>测试方案</summary><pre class="spec-preview">${esc(t.plan||'尚未形成方案')}</pre></details><details><summary>测试用例与候选草稿</summary><pre class="spec-preview">${esc(t.caseDesigner?.draft?caseMarkdown(t.caseDesigner.draft):t.cases.map(c=>`${c.id} ${c.title}\n${c.steps}\n预期：${c.expected}`).join('\n\n'))}</pre></details><details><summary>执行与问题记录</summary><pre class="spec-preview">${esc(JSON.stringify({attempts:t.attempts,runs:t.runs,issues:t.issues},null,2))}</pre></details></div>`;
};
const originalEnterJourney=enterJourney;
enterJourney=function(key,id,part){const t=data.tasks.find(t=>t.id===id);if(!t||taskLC(t).location==='trash')return toast('任务不存在或已移入回收站');if(!taskEditable(t)){taskId=id;page='task';render();return;}return originalEnterJourney(key,id,part);};
chooseJourney=function(key){
  if(key==='design') return openNewDesignTask();
  const current=data.tasks.find(t=>t.id===taskId && taskEditable(t)) || data.tasks.find(taskEditable);
  if(current) return enterJourney(key,current.id,current.activeJourney===key?current.activeStep:undefined);
  const record={...blankTask(),id:'TASK-'+crypto.randomUUID(),name:'健康管理测试'};
  data.tasks.unshift(record);
  enterJourney(key,record.id);
  flushWorkspace().catch(()=>{/* The workspace shows its existing recovery controls. */});
};
function openNewDesignTask(){
  const findRecord = identifier => data.tasks.find(task =>
    (task.requirementNo||'').trim().toLowerCase()===identifier.trim().toLowerCase() && taskLC(task).location!=='trash');
  modal('新建测试设计任务',`
    <div class="design-task-fields">
      <label>FE/BUG 编号（必填）
        <input name="requirementNo" required maxlength="100" placeholder="例如 FE-12345 或 BUG-12345"
          aria-describedby="designTaskMatch">
      </label>
      <label id="designTaskName">任务名称（必填）
        <input name="name" required maxlength="80" placeholder="例如 健康档案保存测试">
      </label>
      <p id="designTaskMatch" class="subtitle" role="status"></p>
    </div>
  `,'创建并进入设计',form=>{
    const identifier=form.get('requirementNo').trim();
    const fields=$('#modalForm').elements;
    if(!identifier){
      fields.requirementNo.setCustomValidity('请输入 FE/BUG 编号');
      fields.requirementNo.reportValidity();
      return false;
    }

    let record=findRecord(identifier);
    if(!record){
      const taskName=form.get('name')?.trim();
      if(!taskName){
        const name=fields.namedItem('name');
        name.setCustomValidity('请输入任务名称');
        name.reportValidity();
        return false;
      }
      record={...blankTask(),id:'TASK-'+crypto.randomUUID(),name:taskName,requirementNo:identifier};
      data.tasks.unshift(record);
    }
    const step=record.activeJourney==='design'?record.activeStep:'sources';
    enterJourney('design',record.id,step||'sources');
    flushWorkspace().catch(()=>{/* 保存失败由工作区显示恢复入口。 */});
  });
  const form=$('#modalForm');
  const name=form.elements.namedItem('name');
  const identifier=form.elements.requirementNo;
  name.oninput=()=>name.setCustomValidity('');
  identifier.oninput=()=>{
    identifier.setCustomValidity('');
    const record=identifier.value.trim()?findRecord(identifier.value):null;
    name.disabled=Boolean(record);
    $('#designTaskName').hidden=Boolean(record);
    const state=record ? taskLC(record) : null;
    const action=record ? (taskEditable(record)?'继续已有任务':'查看任务') : '新建测试设计任务';
    $('#modalTitle').textContent=action;
    $('#modalSubmit').textContent=record?action:'创建并进入设计';
    $('#designTaskMatch').textContent=record
      ? `${record.name} · ${state.location==='archive'?'已归档':taskStatusNames[state.status]}`
      : '';
  };
  identifier.focus();
}
async function applyTaskAction(t,action,fields){if(taskInFlight(t))return toast('仍有生成或模拟执行进行中，请取消并等待停止后再操作');taskActionBusy=true;$('#content').inert=true;try{await flushWorkspace();const response=await workspaceRequest('/api/tasks/'+encodeURIComponent(t.id)+'/'+action,{revision:workspaceRevision,...fields});data=response.data;workspaceRevision=response.revision;workspaceStamp=JSON.stringify(data);workspaceDirty=false;originalLocalSave();if(action==='purge'){page='home';taskFilter='trash';}if(action==='delete'||action==='archive'){page='home';taskFilter=action==='delete'?'trash':'archive';}if(action==='restore')taskFilter=taskLC(data.tasks.find(x=>x.id===t.id)).location==='archive'?'archive':'all';if(action==='unarchive')taskFilter='all';render();toast(taskActionNames[action]+'成功');}catch(e){if(e.message.includes('工作区已被其他页面')){workspaceError=e.message;render();}toast(e.message)}finally{taskActionBusy=false;$('#content').inert=false;}}
function manageTask(action,id){const t=data.tasks.find(t=>t.id===id);if(!t||!taskActions(t).includes(action))return toast('当前状态不支持此操作');if(taskInFlight(t))return toast('此任务仍在生成或执行，请先取消并等待停止');
 if(action==='purge')return modal('彻底删除任务',`<p>确定彻底删除任务「<strong>${esc(t.name)}</strong>」吗？</p><div class="notice" style="margin-top:16px">任务及关联生成历史将被删除，无法恢复。<br>正式用例、独立执行报告、知识库和原始规格文件保留。</div>`,'确认删除',()=>{applyTaskAction(t,action,{confirmName:t.name});});
 if(action==='edit')return modal('编辑任务信息',`<label>任务名称<input name="name" required maxlength="80" value="${esc(t.name)}"></label><label>需求单号<input name="requirementNo" maxlength="100" value="${esc(t.requirementNo||'')}"></label><label>任务说明<textarea name="description" maxlength="5000">${esc(t.description||'')}</textarea></label><p class="subtitle">版本和业务规则变更请使用“需求变更”场景，避免误用旧测试结果。</p>`,'保存',f=>{applyTaskAction(t,action,Object.fromEntries(f));});
 const designOnly=action==='complete'&&(t.activeJourney||'design')==='design';
 if(designOnly&&!caseAccepted(t))return toast('完成本次设计前，请先确认当前方案及整套用例；不再开展可选择取消任务');
 const label=designOnly?'完成本次设计':taskActionNames[action];
 modal(label,`<h3>${esc(t.name)}</h3><p>需求单号：${esc(t.requirementNo||'未填写')} · ${t.cases.length} 条用例 · ${t.attempts.length} 次手工记录</p>${action==='delete'?'<div class="notice">任务和全部关联记录将移入回收站，可恢复。原始规格文件、共享知识和其他任务不受影响。</div>':''}${action==='complete'?`<div class="notice">${designOnly?'本次交付为测试设计，未执行不等于测试通过。':'本次工作结束不等于全部测试通过。'}仍有 ${t.cases.filter(c=>!latest(t,c.id)).length} 条未录入本版本结果的用例、${t.issues.filter(i=>i.status!=='已关闭').length} 项未关闭问题。</div>`:''}<label>${action==='complete'?'交付结论、未完成事项与遗留风险':'操作原因'}<textarea name="reason" maxlength="5000" ${['complete','cancel'].includes(action)?'required':''}></textarea></label>`,label,f=>{const reason=String(f.get('reason')||'').trim();if(['complete','cancel'].includes(action)&&!reason)return false;applyTaskAction(t,action,{reason,designOnly});});
}
const originalTaskAct=act;
act=function(action){const [name,arg,id]=action.split(':');

 if(name==='workspaceRetry'){workspaceError='';return (workspaceReady?flushWorkspace():loadWorkspace()).then(()=>render()).catch(()=>render());}
 if(name==='workspaceReload')return modal('重新加载后台版本','<p>当前浏览器草稿可先通过“导出浏览器备份”保存。加载后以后台版本为准，并保留一份加载前的浏览器备份。</p>','加载后台版本',()=>{Promise.resolve(workspaceSaving).catch(()=>{}).then(()=>{workspaceReady=false;loadWorkspace();});});
 if(name==='workspaceLegacyBackup'){const old=localStorage.getItem(KEY+'-before-server-load');return old?download('后台迁移前浏览器备份.json',old,'application/json'):toast('此浏览器没有迁移前备份');}
 if(name==='workspaceImportLegacy'){if(!workspaceReady||workspaceError)return toast('请先处理后台连接或保存冲突');let old;try{old=JSON.parse(localStorage.getItem(KEY+'-before-server-load'));}catch{}const items=(old?.tasks||[]).filter(t=>!data.tasks.some(x=>x.id===t.id));if(!items.length)return toast('没有可直接补入的旧任务。同ID任务不覆盖，可导出旧备份核对。');return modal('补入浏览器旧任务',`<p>将补入 ${items.length} 个不同ID的任务，同ID任务不会覆盖。</p><ul>${items.map(t=>`<li>${esc(t.name)}</li>`).join('')}</ul>`,'补入任务',()=>{for(const t of items){delete t.lifecycle;data.tasks.push(t);}save();render();});}
 if(name==='workspaceBackup')return download('工作区浏览器备份.json',JSON.stringify(data,null,2),'application/json');
 if(!workspaceReady||workspaceError)return toast('请先恢复后台连接或处理保存冲突，当前草稿仍保留');
 if(taskActionBusy)return toast('任务操作正在保存，请稍候');
 if(name==='taskFilter'){taskFilter=arg;render();return;}
 if(name==='taskHome'){page='home';render();return;}
 if(name==='taskManage')return manageTask(arg,id);
 if(name==='taskExport'){const t=data.tasks.find(t=>t.id===arg);return download(arg+'-任务备份.json',JSON.stringify(t,null,2),'application/json');}
 if(name==='taskHistory'){const t=data.tasks.find(t=>t.id===arg);return modal('任务操作记录',taskLC(t).history.map(h=>`<div class="list-item"><b>${esc(taskActionNames[h.action]||h.action)}</b><p>${esc(new Date(h.time).toLocaleString('zh-CN'))} · ${esc(h.reason||'未填写原因')}</p><pre class="spec-preview">${esc(JSON.stringify(h.before,null,2))} → ${esc(JSON.stringify(h.after))}</pre></div>`).join('')||'<p>暂无操作记录。</p>','关闭',()=>{});}
 if(name==='complete'||name==='reopen')return manageTask(name,taskId);
 if(name==='reset')return toast('任务已由本地后台管理，请使用回收站清理；不会整体重置工作区');
 if(page==='task'&&!taskEditable(task())&&!['open','report','scenario','backup'].includes(name))return toast('此任务只读，请先恢复或重新打开');
 return originalTaskAct(action);
};
const originalLifecycleRender=render;
render=function(){if(page==='task'&&(!data.tasks.some(t=>t.id===taskId)||taskLC(task()).location==='trash'))page='home';
 if(!workspaceReady){$('#content').innerHTML=`<div class="card pad"><h2>本地任务工作区</h2><p>${esc(workspaceError||'正在加载任务与历史记录…')}</p>${btn('重新连接','workspaceRetry','small')}${btn('导出浏览器备份','workspaceBackup','small')}</div>`;return;}
 if(page==='task'&&!taskEditable(task())){tab=task().activeStep||'sources';journey=task().activeJourney||'design';}
 originalLifecycleRender();$('#content').insertAdjacentHTML('afterbegin',`<div class="card pad"><span id="workspaceSync" role="status"></span>${workspaceError?`<div class="actions">${btn('重试保存','workspaceRetry','small')}${btn('加载后台版本','workspaceReload','small')}${btn('导出浏览器备份','workspaceBackup','small')}</div>`:''}</div>`);syncLabel();
 if($('#taskSearch'))$('#taskSearch').oninput=e=>{taskSearch=e.target.value;$('#taskRows').innerHTML=taskRows();};
 const local=$('.local');if(local)local.innerHTML='<span class="dot"></span>本地工作空间<br><span class="muted">任务与历史由本地后台保存</span>';
 if(page==='settings')$('#content').innerHTML=`<div class="card pad"><h2>本地工作区</h2><p>任务保存于 .local/workbench/workspace.json；模型记录保留在 jobs 目录。浏览器保留草稿缓存。</p><p>后台运行时可跨浏览器读取同一工作区；多页面编辑发生版本冲突时不会覆盖保存。</p><div class="actions">${btn('导出工作区备份','workspaceBackup','small')}${btn('导出迁移前浏览器备份','workspaceLegacyBackup','small')}${btn('补入浏览器旧任务','workspaceImportLegacy','small')}${btn('加载后台版本','workspaceReload','small')}</div></div>`;
};
window.addEventListener('beforeunload',e=>{if(workspaceDirty||workspaceSaving){e.preventDefault();e.returnValue='';}});
render();loadWorkspace();
