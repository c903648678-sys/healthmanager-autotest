// Local file reads are user initiated. Directory contents are explicitly simulated.
tabs.sources='选择规格方案';
journeys.design.steps=['sources','requirements','plan','cases'];
let sourceFolder='全部特性',directoryOpen=false,directoryPicked=new Set(),readingFiles=false;
const initialCatalog=()=>[
 {id:'dir-fields',name:'requirements.md',feature:'字段管理',path:'ai_table/field_management/requirements.md',revision:1,text:'# 字段管理需求规格（演示）\n\n## 创建字段\n编辑者可以新增文本字段。保存后刷新，字段名称和类型保持一致。\n\n## 权限\n只读用户不得新增或删除字段。\n\n## 删除\n删除目标字段不影响其他字段。\n\n## 待确认\n字段名称长度上限尚未确认。',change:'未变化'},
 {id:'dir-design',name:'design.md',feature:'字段管理',path:'ai_table/field_management/design.md',revision:1,text:'# 字段管理设计说明（演示）\n\n测试使用独立表和唯一名称。验证保存后刷新持久化，并记录测试数据清理。',change:'未变化'},
 {id:'dir-views',name:'requirements.md',feature:'视图管理',path:'ai_table/view_type/requirements.md',revision:1,text:'# 视图管理规格（演示）\n\n本文件用于体验目录选择，Demo 不会基于此内容真实生成用例。',change:'未变化'}
];
let specCatalog=[];
const chosenSources=()=>task().sources||[];
const sourceKey=t=>JSON.stringify((t.sources||[]).map(s=>[s.id,s.revision,s.status]));
const readySources=t=>(t.sources||[]).length>0&&(t.sources||[]).every(s=>s.status==='可读取');
const confirmedSources=t=>readySources(t)&&t.sourcesConfirmedKey===sourceKey(t);
function persistSourceChange(fn){const before=JSON.stringify(data);fn();try{localStorage.setItem(KEY,JSON.stringify(data));save();return true}catch{data=JSON.parse(before);toast('保存失败：浏览器存储空间不足，资料未添加。请移除不需要的文件后重试。');return false}}
function sourceStatus(s){const current=specCatalog.find(d=>d.id===s.catalogId);if(current?.missing)return '源文件不可读取';return s.origin==='特性目录'&&current&&current.revision!==s.revision?'源文件已更新':s.status}
function sources(){
 const t=task(),list=chosenSources();
 return `<div class="source-options"><div class="card pad"><span class="scenario-icon">＋</span><h2>选择本地规格方案</h2><p class="subtitle">支持 Word、Excel、PowerPoint、PDF、Markdown 和 TXT。</p>
 <p class="source-note">只登记本机位置，预览或分析时读取原文件。</p><div class="actions">
 <button type="button" class="primary" data-action="chooseLocal" ${readingFiles?'disabled':''}>选择文件</button>
 <button type="button" data-action="chooseLocalFolder" ${readingFiles?'disabled':''}>选择文件夹</button></div></div><div class="card pad"><span class="scenario-icon">▱</span><h2>从特性目录选择</h2><p class="subtitle">资料已经整理在本地特性目录下。</p><p class="source-note">读取本机 knowledge/product，刷新发现新增和修改；已选快照不会自动替换。</p>${btn('浏览特性目录','browseDirectory','')}</div></div>`+
 (directoryOpen?directoryPanel():'')+
 `<div class="card"><div class="card-head"><div><h2>已选择的方案 <span class="muted">${list.length}</span></h2><p class="subtitle">本机引用保留原文件位置。文件有变动时，重新选择后再确认。</p></div>${badge(confirmedSources(t)?'方案已确认':'待确认方案')}</div><div class="table-wrap"><table><thead><tr><th>文件名称 / 来源位置</th><th>来源</th><th>状态</th><th>操作</th></tr></thead><tbody>${list.map(s=>`<tr><td class="case-title">${esc(s.name)}<small>${esc(s.path||'本地文件')} · ${esc(s.sizeLabel||'目录示例')} · 修订 ${esc(s.revision)}</small></td><td>${esc(s.origin)}</td><td>${badge(s.localRef?'本机引用':sourceStatus(s))}${s.error?`<small>${esc(s.error)}</small>`:''}</td><td><div class="actions">${s.status==='可读取'?btn('预览','previewSource:'+s.id,'small'):''}${sourceStatus(s)==='源文件已更新'?btn('查看更新','updateSource:'+s.id,'small'):''}${btn('移除','removeSource:'+s.id,'link small')}</div></td></tr>`).join('')||'<tr><td colspan="4" class="empty">还没有选择方案。可以从上方任意一个入口添加，也可以混合选择。</td></tr>'}</tbody></table></div><div class="pad row"><span class="subtitle">最多 10 份。分析时，每份提取文本最多 200 KB，合计最多 1 MB。</span><button class="primary" data-action="confirmSources" ${!readySources(t)||readingFiles?'disabled':''}>确认方案，开始需求理解</button></div></div>`;
}
function directoryPanel(){return `<div class="card"><div class="card-head"><div><h2>特性目录 <span class="badge amber">模拟目录</span></h2><p class="subtitle">路径示意：knowledge/product · 未扫描真实磁盘</p></div><div class="actions">${btn('刷新目录（模拟）','refreshDirectory','small')}${btn('收起','closeDirectory','link')}</div></div><div class="knowledge pad"><div class="tree">${['全部特性','字段管理','视图管理','导入导出'].map(f=>`<button class="${sourceFolder===f?'active':''}" data-action="sourceFolder:${f}">▱ ${f}</button>`).join('')}</div><div><div class="table-wrap"><table><thead><tr><th>选择</th><th>文件</th><th>变更</th><th></th></tr></thead><tbody>${specCatalog.filter(d=>sourceFolder==='全部特性'||d.feature===sourceFolder).map(d=>`<tr><td><input class="check" type="checkbox" data-source-pick="${d.id}" aria-label="选择 ${d.path}" ${directoryPicked.has(d.id)?'checked':''}></td><td>${esc(d.name)}<small>${esc(d.path)} · 修订 ${d.revision}</small></td><td>${badge(d.change)}</td><td>${btn('预览','previewDirectory:'+d.id,'small')}</td></tr>`).join('')||'<tr><td colspan="4" class="empty">此特性暂无示例资料</td></tr>'}</tbody></table></div><div class="row" style="margin-top:18px"><span class="subtitle">${data.specRefreshAt?'最近刷新：'+esc(data.specRefreshAt):'尚未刷新。首次模拟刷新展示 1 份新增与 1 份更新。'}</span>${btn('加入已选方案','addDirectory','primary small')}</div></div></div></div>`}
async function previewSource(source){
  if(!source)return;
  const owner=taskId;
  try{
    const document=source.localRef
      ? await workspaceRequest('/api/source-links/preview',{localRef:source.localRef},60000)
      : source;
    if(taskId!==owner)return;
    modal('方案预览 · '+source.name,`<div class="source">${esc(source.path||source.origin||'规格资料')}</div>
      <pre class="spec-preview">${esc(document.text)}</pre>`,'关闭预览',()=>{});
  }catch(error){toast(error.message);}
}

function addLocalReferences(owner, documents){
  const existing=owner.sources||[];
  const refs=new Set(existing.map(source=>source.localRef));
  const additions=documents.filter(document=>!refs.has(document.localRef));
  if(existing.length+additions.length>10){
    toast('每个任务最多引用 10 份资料，请减少选择');
    return false;
  }
  if(!additions.length){toast('所选文件已引用');return false;}
  owner.sources=[...existing,...additions.map(document=>({...document,
    id:'src-'+crypto.randomUUID(),origin:'本机引用',revision:1,status:'可读取',
    sizeLabel:(document.size/1024).toFixed(1)+' KB'}))];
  save();
  render();
  toast('已登记 '+additions.length+' 份本机引用');
  return true;
}

async function chooseLocalReferences(mode){
  if(readingFiles)return;
  const owner=task();
  readingFiles=true;
  render();
  try{
    const response=await workspaceRequest('/api/source-links/pick',{mode},250000);
    if(taskId!==owner.id || page!=='task' || tab!=='sources')return;
    const files=response.documents;
    if(!files.length)return;
    if(mode==='files' && files.length+(owner.sources||[]).length<=10){
      addLocalReferences(owner,files);
      return;
    }
    const candidates=files.filter(file=>!(owner.sources||[]).some(source=>source.localRef===file.localRef));
    if(!candidates.length){toast('文件夹中的文件已引用');return;}
    modal('选择要引用的规格文件',`<p>勾选本任务需要的文件，最多 10 份。</p>
      <div class="spec-preview">${candidates.map(file=>`<label class="inline-check">
        <input class="check" type="checkbox" name="sourceRef" value="${esc(file.localRef)}">
        <span>${esc(file.name)}<small>${esc(file.path)}</small></span>
      </label>`).join('')}</div>`,'登记引用',form=>{
      const selected=new Set(form.getAll('sourceRef'));
      if(!selected.size){toast('请至少勾选一份文件');return false;}
      return addLocalReferences(owner,candidates.filter(file=>selected.has(file.localRef)));
    });
  }catch(error){toast(error.message);}
  finally{readingFiles=false;render();}
}

const sourcePayload=source=>({
  id:source.id,name:source.name,...(source.localRef?{localRef:source.localRef}:{text:source.text})
});
const sourceRender=render;
render=function(){sourceRender();$$('[data-source-pick]').forEach(el=>el.onchange=()=>el.checked?directoryPicked.add(el.dataset.sourcePick):directoryPicked.delete(el.dataset.sourcePick));if(page==='task'&&journey==='design'&&tab==='sources'){const next=$('[data-action="step:requirements"]');if(next)next.disabled=!readySources(task())||readingFiles}};
const sourceAct=act;
act=function(action){
 const [name,id]=action.split(':'),t=task();
 if(page==='task'&&journey==='design'&&!confirmedSources(t)&&((name==='step'&&id!=='sources'&&!(id==='requirements'&&tab==='sources'))||name==='toCases'||name==='generate')){toast('请先选择并确认规格方案');return}
 if(name==='chooseLocal'||name==='chooseLocalFolder')return chooseLocalReferences(name==='chooseLocal'?'files':'folder');
 if(name==='browseDirectory'){directoryOpen=true;render();return}
 if(name==='closeDirectory'){directoryOpen=false;render();return}
 if(name==='sourceFolder'){sourceFolder=id;render();return}
 if(name==='refreshDirectory'){
  persistSourceChange(()=>{if(!data.specRefreshed){const d=specCatalog.find(d=>d.id==='dir-fields');d.revision=2;d.text+='\n\n## 补充（模拟刷新）\n新增与删除后均须刷新页面验证持久化。';d.change='已更新';specCatalog.push({id:'dir-permissions',name:'权限补充.md',feature:'字段管理',path:'ai_table/field_management/权限补充.md',revision:1,text:'# 权限补充（模拟新增）\n\n操作被拒绝后应重新读取字段，确认数据未变化。',change:'新增'});data.specRefreshed=true}else specCatalog.forEach(d=>d.change='未变化');data.specRefreshAt=new Date().toLocaleString('zh-CN')});render();toast('模拟目录已刷新，当前任务使用的快照未替换');return;
 }
 if(name==='previewDirectory')return previewSource(specCatalog.find(d=>d.id===id));
 if(name==='previewSource')return previewSource(chosenSources().find(s=>s.id===id));
 if(name==='addDirectory'){
  const picked=specCatalog.filter(d=>!d.missing&&d.status!=='已失效'&&directoryPicked.has(d.id)&&!chosenSources().some(s=>s.catalogId===d.id));if(!picked.length){toast('请勾选未添加的方案；已添加方案通过“查看更新”更新');return}
  if([...chosenSources(),...picked].reduce((n,s)=>n+(s.localRef?0:s.size||0),0)>1024*1024){toast('已选资料超过 1 MB');return}
  if(chosenSources().length+picked.length>10){toast('每个任务最多选择 10 份方案');return}
  persistSourceChange(()=>{t.sources=[...chosenSources(),...picked.map(d=>({...structuredClone({...d,history:undefined}),id:'src-'+crypto.randomUUID(),catalogId:d.id,origin:'特性目录',status:'可读取',size:new TextEncoder().encode(d.text).length}))]});render();return;
 }
 if(name==='removeSource'){
  const s=chosenSources().find(s=>s.id===id);return modal('移除所选方案',`<p>仅取消当前任务对「${esc(s.name)}」的选择，不删除原文件。已确认资料变化后需重新确认。</p>`,'确认移除',()=>{persistSourceChange(()=>{t.sources=t.sources.filter(s=>s.id!==id)});render()})
 }
 if(name==='updateSource'){
  const old=chosenSources().find(s=>s.id===id),fresh=specCatalog.find(d=>d.id===old.catalogId);
  if(chosenSources().reduce((n,s)=>n+(s.localRef?0:s.size||0),0)-(old.size||0)+fresh.size>1024*1024){toast('更新后超过 1 MB，请先精简已选资料');return}
  return modal('更新任务资料快照',`<p>修订 ${old.revision} → ${fresh.revision}。接受后需要重新确认方案。</p><div class="change-diff"><div><small>当前任务版本</small><pre class="spec-preview">${esc(old.text)}</pre></div><div><small>目录新版本</small><pre class="spec-preview">${esc(fresh.text)}</pre></div></div>`,'接受新版本',()=>{persistSourceChange(()=>{(t.sourceHistory||=[]).push(structuredClone(old));Object.assign(old,{text:fresh.text,revision:fresh.revision,hash:fresh.hash,path:fresh.path,sizeLabel:fresh.sizeLabel,size:new TextEncoder().encode(fresh.text).length});});render()});
 }
 if(name==='confirmSources'||(name==='step'&&id==='requirements'&&tab==='sources')){
  if(!readySources(t)||readingFiles){toast('请至少选择一份可读取方案，并移除读取失败的条目');return}
  const previous=t.sourcesConfirmedKey;
  if(persistSourceChange(()=>{t.activeStep='requirements';t.sourcesConfirmedKey=sourceKey(t);t.sourcesConfirmedAt=new Date().toISOString();if(previous&&previous!==t.sourcesConfirmedKey){t.sourcesReviewNotice=true;t.cases.forEach(c=>{c.confirmed=false;c.reviewNeeded=true;if(c.script!=='未实现')c.script='需重新验证'})}})){tab='requirements';render()}return;
 }
 if(name==='referenceSources'){tab='sources';journey='design';render();return}
 if(name==='analyze'&&(t.sources||[]).length)return modal('需求理解 · 本次参考资料',`<div class="notice info">已关联真实文件内容，但 Demo 尚未接入 AI；不会把固定字段示例冒充这些资料的分析结果。</div><ul>${t.sources.map(s=>`<li>${esc(s.name)} · ${esc(s.origin)} · 修订 ${s.revision}</li>`).join('')}</ul><p>可返回预览原文、记录业务疑问，或继续体验固定测试方案与用例示例。</p>`,'了解了',()=>{});
 return sourceAct(action);
};
const priorRequirements=requirements;
requirements=function(){const t=task();if(!(t.sources||[]).length)return `<div class="notice">这个旧任务尚未关联规格方案，请先选择资料。</div>${btn('选择规格方案','referenceSources','primary')}`;return `<div class="card"><div class="card-head"><h2>本次参考方案 · ${t.sources.length} 份</h2>${btn('查看 / 补充方案','referenceSources','small')}</div><div class="pad">${t.sources.map(s=>`<div class="list-item row"><div><b>${esc(s.name)}</b><p class="subtitle">${esc(s.origin)} · 修订 ${s.revision} · ${esc(sourceStatus(s))}</p></div>${btn('预览','previewSource:'+s.id,'small')}</div>`).join('')}</div></div><div class="notice info">资料已关联到当前任务。以下业务规则、风险和后续生成仍是固定字段管理示例，不是对所选资料的 AI 分析。</div>${t.sourcesReviewNotice?'<div class="notice">参考资料已变化，已有用例已标记待复核。请核对方案和用例后再执行。</div>':''}`+priorRequirements().replace('关联需求','固定示例需求');};
// Guard direct tab jumps, not only the Next button.
document.addEventListener('click',e=>{if(page!=='task'||journey!=='design')return;const tabButton=e.target.closest('[data-tab]');if(tabButton&&tabButton.dataset.tab!=='sources'&&!confirmedSources(task())){e.preventDefault();e.stopImmediatePropagation();toast('请先选择并确认规格方案');}},true);
const priorEnterJourney=enterJourney;
enterJourney=function(key,id,part){const t=data.tasks.find(x=>x.id===id);priorEnterJourney(key,id,key==='design'&&!confirmedSources(t)?'sources':part)};
render();
