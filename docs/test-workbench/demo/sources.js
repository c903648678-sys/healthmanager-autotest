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
function persistSourceChange(fn){const before=JSON.stringify(data);fn();try{localStorage.setItem(KEY,JSON.stringify(data));return true}catch{data=JSON.parse(before);toast('保存失败：浏览器存储空间不足，资料未添加。请移除不需要的文件后重试。');return false}}
function sourceStatus(s){const current=specCatalog.find(d=>d.id===s.catalogId);if(current?.missing)return '源文件不可读取';return s.origin==='特性目录'&&current&&current.revision!==s.revision?'源文件已更新':s.status}
function sources(){
 const t=task(),list=chosenSources();
 return `<div class="source-options"><div class="card pad"><span class="scenario-icon">＋</span><h2>选择本地规格方案</h2><p class="subtitle">资料还在桌面、下载目录或其他位置。</p><p class="source-note">选择时在浏览器读取 Markdown / TXT，不移动原文件。</p><button class="primary" data-action="chooseLocal" ${readingFiles?'disabled':''}>${readingFiles?'正在读取…':'选择文件'}</button><input type="file" id="specFiles" accept=".md,.markdown,.txt" multiple hidden></div><div class="card pad"><span class="scenario-icon">▱</span><h2>从特性目录选择</h2><p class="subtitle">资料已经整理在本地特性目录下。</p><p class="source-note">读取本机 knowledge/product，刷新发现新增和修改；已选快照不会自动替换。</p>${btn('浏览特性目录','browseDirectory','')}</div></div>`+
 (directoryOpen?directoryPanel():'')+
 `<div class="card"><div class="card-head"><div><h2>已选择的方案 <span class="muted">${list.length}</span></h2><p class="subtitle">同名不同内容保留为不同条目；确认后固定本任务使用的资料版本。</p></div>${badge(confirmedSources(t)?'方案已确认':'待确认方案')}</div><div class="table-wrap"><table><thead><tr><th>文件名称 / 来源位置</th><th>来源</th><th>状态</th><th>操作</th></tr></thead><tbody>${list.map(s=>`<tr><td class="case-title">${esc(s.name)}<small>${esc(s.path||'浏览器选择的本地文件')} · ${esc(s.sizeLabel||'目录示例')} · 修订 ${esc(s.revision)}</small></td><td>${esc(s.origin)}</td><td>${badge(sourceStatus(s))}${s.error?`<small>${esc(s.error)}</small>`:''}</td><td><div class="actions">${s.status==='可读取'?btn('预览','previewSource:'+s.id,'small'):''}${sourceStatus(s)==='源文件已更新'?btn('查看更新','updateSource:'+s.id,'small'):''}${btn('移除','removeSource:'+s.id,'link small')}</div></td></tr>`).join('')||'<tr><td colspan="4" class="empty">还没有选择方案。可以从上方任意一个入口添加，也可以混合选择。</td></tr>'}</tbody></table></div><div class="pad row"><span class="subtitle">最多 10 份，每份 200 KB，总计 1 MB。读取失败的条目请移除或重新选择。</span><button class="primary" data-action="confirmSources" ${!readySources(t)||readingFiles?'disabled':''}>确认方案，开始需求理解</button></div></div>`;
}
function directoryPanel(){return `<div class="card"><div class="card-head"><div><h2>特性目录 <span class="badge amber">模拟目录</span></h2><p class="subtitle">路径示意：knowledge/product · 未扫描真实磁盘</p></div><div class="actions">${btn('刷新目录（模拟）','refreshDirectory','small')}${btn('收起','closeDirectory','link')}</div></div><div class="knowledge pad"><div class="tree">${['全部特性','字段管理','视图管理','导入导出'].map(f=>`<button class="${sourceFolder===f?'active':''}" data-action="sourceFolder:${f}">▱ ${f}</button>`).join('')}</div><div><div class="table-wrap"><table><thead><tr><th>选择</th><th>文件</th><th>变更</th><th></th></tr></thead><tbody>${specCatalog.filter(d=>sourceFolder==='全部特性'||d.feature===sourceFolder).map(d=>`<tr><td><input class="check" type="checkbox" data-source-pick="${d.id}" aria-label="选择 ${d.path}" ${directoryPicked.has(d.id)?'checked':''}></td><td>${esc(d.name)}<small>${esc(d.path)} · 修订 ${d.revision}</small></td><td>${badge(d.change)}</td><td>${btn('预览','previewDirectory:'+d.id,'small')}</td></tr>`).join('')||'<tr><td colspan="4" class="empty">此特性暂无示例资料</td></tr>'}</tbody></table></div><div class="row" style="margin-top:18px"><span class="subtitle">${data.specRefreshAt?'最近刷新：'+esc(data.specRefreshAt):'尚未刷新。首次模拟刷新展示 1 份新增与 1 份更新。'}</span>${btn('加入已选方案','addDirectory','primary small')}</div></div></div></div>`}
function previewSource(s){modal('方案预览 · '+s.name,`<div class="source">来源：${esc(s.origin||'本地特性目录')} · ${esc(s.path||'本地文件')}<br>本次快照修订：${esc(s.revision)}</div><pre class="spec-preview">${esc(s.text)}</pre>`,'关闭预览',()=>{})}
async function readLocalFiles(files){
 const owner=task(),ownerId=owner.id;readingFiles=true;
 const queue=[...files];const additions=[];const existing=owner.sources||[];
 if(existing.length+queue.length>10){readingFiles=false;toast('每个任务最多选择 10 份方案');return}
 render();
 for(const file of queue){
  const item={id:'src-'+crypto.randomUUID(),name:file.name,origin:'本地选择',path:'',revision:1,size:file.size,sizeLabel:(file.size/1024).toFixed(1)+' KB',modifiedAt:new Date(file.lastModified).toISOString(),status:'读取失败',text:''};
  try{
   if(!/\.(md|markdown|txt)$/i.test(file.name))throw Error('暂不支持此格式，请提供 Markdown 或 TXT');
   if(file.size>200*1024)throw Error('文件超过 200 KB，请精简或拆分');
   const raw=await file.arrayBuffer();const decoded=new TextDecoder('utf-8',{fatal:true}).decode(raw);
   if(!decoded.trim())throw Error('文件内容为空');
   if(decoded.includes('\u0000'))throw Error('文件不是可读取文本');
   const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',raw))].map(x=>x.toString(16).padStart(2,'0')).join('');
   if([...existing,...additions].some(s=>s.hash===hash&&s.name===file.name)){toast('已忽略相同名称和内容的重复文件');continue}
   item.hash=hash;item.text=decoded;item.status='可读取';
  }catch(err){item.error=err.message}
  additions.push(item);
 }
 readingFiles=false;
 const target=data.tasks.find(t=>t.id===ownerId);if(!target)return;
 const total=[...(target.sources||[]),...additions].reduce((n,s)=>n+(s.status==='可读取'?s.size||0:0),0);
 if(total>1024*1024){toast('已选资料总计超过 1 MB，本次未添加');render();return}
 if(!additions.length){toast('所选文件已存在，未重复添加');render();return}
 if(persistSourceChange(()=>{target.sources=[...(target.sources||[]),...additions]})){const failed=additions.filter(s=>s.status!=='可读取').length;toast(failed?'已添加资料，其中 '+failed+' 份读取失败，请查看原因':'已读取 '+additions.length+' 份本地资料；请预览后确认')}
 render();
}
const sourceRender=render;
render=function(){sourceRender();if($('#specFiles'))$('#specFiles').onchange=e=>readLocalFiles(e.target.files);$$('[data-source-pick]').forEach(el=>el.onchange=()=>el.checked?directoryPicked.add(el.dataset.sourcePick):directoryPicked.delete(el.dataset.sourcePick));if(page==='task'&&journey==='design'&&tab==='sources'){const next=$('[data-action="step:requirements"]');if(next)next.disabled=!readySources(task())||readingFiles}};
const sourceAct=act;
act=function(action){
 const [name,id]=action.split(':'),t=task();
 if(page==='task'&&journey==='design'&&!confirmedSources(t)&&((name==='step'&&id!=='sources'&&!(id==='requirements'&&tab==='sources'))||name==='toCases'||name==='generate')){toast('请先选择并确认规格方案');return}
 if(name==='chooseLocal'){$('#specFiles').click();return}
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
  if([...chosenSources(),...picked].reduce((n,s)=>n+(s.size||0),0)>1024*1024){toast('已选资料超过 1 MB');return}
  if(chosenSources().length+picked.length>10){toast('每个任务最多选择 10 份方案');return}
  persistSourceChange(()=>{t.sources=[...chosenSources(),...picked.map(d=>({...structuredClone({...d,history:undefined}),id:'src-'+crypto.randomUUID(),catalogId:d.id,origin:'特性目录',status:'可读取',size:new TextEncoder().encode(d.text).length}))]});render();return;
 }
 if(name==='removeSource'){
  const s=chosenSources().find(s=>s.id===id);return modal('移除所选方案',`<p>仅取消当前任务对「${esc(s.name)}」的选择，不删除原文件。已确认资料变化后需重新确认。</p>`,'确认移除',()=>{persistSourceChange(()=>{t.sources=t.sources.filter(s=>s.id!==id)});render()})
 }
 if(name==='updateSource'){
  const old=chosenSources().find(s=>s.id===id),fresh=specCatalog.find(d=>d.id===old.catalogId);
  if(chosenSources().reduce((n,s)=>n+(s.size||0),0)-(old.size||0)+fresh.size>1024*1024){toast('更新后超过 1 MB，请先精简已选资料');return}
  return modal('更新任务资料快照',`<p>修订 ${old.revision} → ${fresh.revision}。接受后需要重新确认方案。</p><div class="change-diff"><div><small>当前任务版本</small><pre class="spec-preview">${esc(old.text)}</pre></div><div><small>目录新版本</small><pre class="spec-preview">${esc(fresh.text)}</pre></div></div>`,'接受新版本',()=>{persistSourceChange(()=>{(t.sourceHistory||=[]).push(structuredClone(old));Object.assign(old,{text:fresh.text,revision:fresh.revision,hash:fresh.hash,path:fresh.path,sizeLabel:fresh.sizeLabel,size:new TextEncoder().encode(fresh.text).length});});render()});
 }
 if(name==='confirmSources'||(name==='step'&&id==='requirements'&&tab==='sources')){
  if(!readySources(t)||readingFiles){toast('请至少选择一份可读取方案，并移除读取失败的条目');return}
  const previous=t.sourcesConfirmedKey;
  if(persistSourceChange(()=>{t.sourcesConfirmedKey=sourceKey(t);t.sourcesConfirmedAt=new Date().toISOString();if(previous&&previous!==t.sourcesConfirmedKey){t.sourcesReviewNotice=true;t.cases.forEach(c=>{c.confirmed=false;c.reviewNeeded=true;if(c.script!=='未实现')c.script='需重新验证'})}})){tab='requirements';render()}return;
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
