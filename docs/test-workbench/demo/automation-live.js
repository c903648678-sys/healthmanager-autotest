// The durable execution path replaces browser-only demo plans. Old demo data remains archived.
let lpData=null,lpEnvs=null,lpBusy=false,lpError='',lpTab='suites',lpType='全部',lpPage=0,lpSize=20,lpQuery='',lpSelectedRun='',lpRun=null;
const lpStatus={pending:'等待执行',preparing:'执行前检查',running:'执行中',pausing:'等待暂停',paused:'已暂停',cancelling:'停止中',passed:'通过',failed:'用例失败',blocked:'执行前阻塞',cancelled:'已取消',interrupted:'已中断',incomplete:'未完整通过',unknown:'执行情况未知',not_run:'未执行',skipped:'跳过',error:'脚本/环境错误',auth:'登录异常'};
const lpContent=x=>x.versions.at(-1).content;
const lpList=key=>lpData?.[key]||[];
async function lpExportAssets(){
 try{
  const data=await workspaceRequest('/api/automation/export-assets',{},60000);
  const blob=new Blob([JSON.stringify(data)],{type:'application/json'});
  if(blob.size>31*1024*1024)throw new Error('资产包超过 31 MB，请先整理资产历史');
  const url=URL.createObjectURL(blob),link=document.createElement('a');
  link.href=url;link.download='workbench-assets-'+new Date().toISOString().slice(0,10)+'.json';
  link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  toast('已导出全部正式用例与套件，可在另一台电脑导入');
 }catch(e){toast(e.status===404?'请重启工作台后台后使用资产迁移':e.message)}
}
function lpImportAssets(){
 let preview=null,assetPackage=null,busy=false;
 modal('导入用例与套件',
  '<p>请选择另一台电脑导出的 JSON 文件。包含全部正式用例、套件及其版本。导入前请同步项目代码并刷新测试资产。</p><label>资产包<input id="assetTransferFile" type="file" accept=".json,application/json" required></label><p>执行计划、登录态和运行历史由各电脑独立保存。设计用例保留来源标识，原需求与审阅任务可通过工作台备份迁移。</p><div id="assetTransferPreview" role="status"></div>',
  '确认导入',()=>{
   if(!preview||preview.conflicts.length||busy)return false;
   busy=true;$('#modalSubmit').disabled=true;
   workspaceRequest('/api/automation/import-assets',{package:assetPackage,commit:true,expectedRevision:preview.revision,packageDigest:preview.packageDigest},60000)
    .then(async result=>{closeModal();await lpLoad();toast('导入完成：新增 '+result.added+'，更新 '+result.updated+'，重复跳过 '+result.unchanged)})
    .catch(e=>{const target=$('#assetTransferPreview');if(target)target.textContent=e.message+'。请重新选择文件预览。';preview=null})
    .finally(()=>{busy=false});
   return false;
  });
 $('#modalSubmit').disabled=true;
 $('#assetTransferFile').onchange=async event=>{
  const file=event.target.files[0],target=$('#assetTransferPreview');
  preview=null;assetPackage=null;$('#modalSubmit').disabled=true;
  if(!file)return;
  event.target.disabled=true;target.textContent='正在校验文件与本机资产…';
  try{
   if(file.size>31*1024*1024)throw new Error('资产包最多 31 MB');
   const parsed=JSON.parse(await file.text());
   const result=await workspaceRequest('/api/automation/import-assets',{package:parsed},60000);
   if(!target.isConnected)return;
   assetPackage=parsed;preview=result;
   target.innerHTML='<p>新增 '+result.added+' · 更新 '+result.updated+' · 重复跳过 '+result.unchanged+'</p>'+
    (result.conflicts.length?'<h3>请先处理以下冲突（共 '+result.conflicts.length+' 项）</h3>':'')+
    result.conflicts.slice(0,100).map(x=>'<p>'+esc(x)+'</p>').join('')+
    result.warnings.slice(0,20).map(x=>'<p>'+esc(x)+'</p>').join('');
   $('#modalSubmit').disabled=Boolean(result.conflicts.length);
  }catch(e){target.textContent=e.status===404?'请重启工作台后台后使用资产迁移':e.message}
  finally{event.target.disabled=false}
 };
}
async function lpPrepareScreenshots(r){
 // Older local backends already return evidence paths, but no screenshots field.
 // Hash the complete nodeid exactly as the UI engine does; never match titles.
 await Promise.all((r.results||[]).map(async c=>{
  if(Array.isArray(c.screenshots)||!c.nodeid)return;
  try{
   const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(c.nodeid));
   const suffix='--'+Array.from(new Uint8Array(bytes)).map(b=>b.toString(16).padStart(2,'0')).join('').slice(0,16);
   c.screenshots=(r.artifacts||[]).filter(name=>name.startsWith('evidence/')&&!name.split('/').includes('..')&&name.endsWith('/failure.png')&&name.split('/').at(-2).endsWith(suffix));
  }catch(e){c.screenshotIssue='截图关联失败，请刷新后重试';}
 }));return r;
}
function lpScreenshotUrl(r,name){return '/api/automation/runs/'+encodeURIComponent(r.id)+'/artifacts/'+name.split('/').map(encodeURIComponent).join('/')}
document.addEventListener('error',e=>{if(e.target instanceof HTMLImageElement&&e.target.matches('[data-failure-image]')){e.target.hidden=true;const hint=e.target.nextElementSibling;if(hint)hint.textContent='截图加载失败，请刷新后重新预览';}},true);
// Older running servers expose the same records through the full index only.
async function lpReadIndex(kind){
 try{return await workspaceRequest('/api/automation/'+kind)}
 catch(e){if(e.status!==404)throw e}
 const state=await workspaceRequest('/api/automation');
 return kind==='runs'?state.runs:state;
}
async function lpLoad(runsOnly=false){if(lpBusy)return;lpBusy=true;try{if(runsOnly===true&&lpData){lpData.runs=await lpReadIndex('runs')}else{const [state,envs]=await Promise.all([lpReadIndex('summary'),lpEnvs?Promise.resolve(lpEnvs):workspaceRequest('/api/automation/environments',undefined,30000)]);lpData=state;lpEnvs=envs}lpError='';if(lpSelectedRun&&!lpData.runs.some(r=>r.id===lpSelectedRun)){lpSelectedRun='';lpRun=null}if(lpSelectedRun)lpRun=await lpPrepareScreenshots(await workspaceRequest('/api/automation/runs/'+lpSelectedRun))}catch(e){lpError=e.message}finally{lpBusy=false;if(!$('#overlay')?.classList.contains('hidden'))return;if(['automation','assets','reports'].includes(page))render()}}
async function lpWrite(kind,raw){if(lpBusy)return;lpBusy=true;try{if(kind==='publish'||kind==='model')await flushWorkspace();const result=await workspaceRequest('/api/automation/'+kind,raw,30000);closeModal();lpBusy=false;await lpLoad();render();return result}catch(e){lpError=e.message;toast(e.message)}finally{lpBusy=false}}
function lpSelect(name,label,items,value=''){return `<label>${label}<select name="${name}" required>${items.map(([id,text])=>`<option value="${esc(id)}" ${id===value?'selected':''}>${esc(text)}</option>`).join('')}</select></label>`}
function lpInput(name,label,value=''){return `<label>${label}<input name="${name}" value="${esc(value)}" required maxlength="300"></label>`}
function lpVersionReview(kind,raw,old,proposed){return modal('确认保存 · '+(old?'生成新版本':'新增记录'),`<p>保存后保留原版本；已有套件与运行快照不会被覆盖。</p><div class="form-grid"><div><h3>当前版本</h3><pre class="spec-preview">${esc(old?JSON.stringify(lpContent(old),null,2):'无')}</pre></div><div><h3>本次提交</h3><pre class="spec-preview">${esc(JSON.stringify(proposed||raw,null,2))}</pre></div></div>`,'确认保存',()=>{lpWrite(kind,raw);return false})}
async function lpSuiteDialog(id){
 let inventory;try{inventory=await workspaceRequest('/api/assets')}catch(e){toast('无法读取用例执行范围，请刷新后重试：'+e.message);return}
 const old=lpList('suites').find(s=>s.id===id),c=old?lpContent(old):{},assets=lpList('assets');
 if(!assets.length)return toast('请先在正式用例库纳入用例');
 const tierById=new Map((inventory.cases||[]).map(x=>[x.assetId,x.suiteTier]));
 const assetTier=a=>{const v=lpContent(a);return v.suiteTier||v.spec?.suiteTier||tierById.get(v.binding?.inventoryId||v.source?.inventoryId)||''};
 const inTier=a=>{const tier=$('#modalForm [name="tier"]').value,value=assetTier(a);return tier==='custom'||tier==='full'||(tier==='daily'?['smoke','daily'].includes(value):value==='smoke')};
 const products=[...new Set([...abProducts,...assets.map(a=>lpContent(a).product)])].filter(Boolean),selected=new Map();
 for(const a of assets)if(c.cases?.some(r=>r.assetId===a.id))selected.set(a.id,{assetId:a.id,revision:a.revision});
 let product=c.product||products[0],layer=c.layer||(lpType==='全部'?'UI':lpType),sub='',query='',pageIndex=0,saving=false,nameManual=Boolean(old),suggestedName='';
 modal(old?'更新套件版本':'新建自动化套件',`<div class="suite-picker">${lpInput('name','套件名称',c.name||'')}<div class="suite-name-help"><p class="subtitle">建议按“产品-子产品-类型-范围”命名，可自行修改。</p><div class="actions"><span id="suiteSuggestedName"></span><button type="button" id="suiteUseName" class="link small">使用建议名称</button></div><p id="suiteNameWarning" class="subtitle" role="status"></p></div><div class="form-grid">${lpSelect('product','产品',products.map(x=>[x,x]),product)}<label>子产品<select id="suiteSub"><option value="">全部子产品</option></select></label>${lpSelect('layer','自动化类型',Object.entries(axTypes),layer)}${lpSelect('tier','执行范围',[['smoke','冒烟'],['daily','日构建'],['full','全量'],['custom','自选']],c.tier||'smoke')}</div><label>默认执行环境<select name="environment" id="suiteEnvironment"></select></label><p class="subtitle" id="suiteEnvironmentHint">套件执行时默认带入，可在执行前调整；执行计划使用计划中固定的环境。</p><label>查找用例<input id="suiteSearch" type="search" placeholder="用例名称、编号或特性"></label><div class="suite-selection"><label class="suite-select-all"><input type="checkbox" class="check" id="suiteSelectAll">全选当前筛选结果</label><span id="suiteCount" role="status"></span><button type="button" id="suiteClear" class="link small">清空已选</button></div><p class="subtitle" id="suiteHint" role="status">日构建包含冒烟用例；切换执行范围会移除不符项。子产品筛选保留已选。</p><div id="suiteCandidates" class="suite-candidates"></div><div class="suite-pager"><button type="button" id="suitePrev" class="small">上一页</button><span id="suitePage"></span><button type="button" id="suiteNext" class="small">下一页</button></div><p class="subtitle">使用正式用例的最新版本；保存后固定版本。更新套件时请核对版本变化。</p></div>`,old?'保存新版本':'创建套件',f=>{
  if(saving)return false;
  if(!selected.size){$('#suiteHint').textContent='请至少选择一条用例';return false}
  const raw={name:f.get('name'),layer,product,tier:f.get('tier'),environment:f.get('environment')||'',cases:[...selected.values()],...(old?{id:old.id,expectedRevision:old.revision}:{})};saving=true;const submit=$('#modalSubmit'),form=$('#modalForm');submit.disabled=true;submit.textContent='正在保存…';form.inert=true;
  lpWrite('suite',raw).then(result=>{if(result)toast(old?'套件新版本已保存':'套件已创建');else if($('#suiteHint'))$('#suiteHint').textContent=lpError||'保存未完成，请重试'}).finally(()=>{saving=false;form.inert=false;submit.disabled=false;submit.textContent=old?'保存新版本':'创建套件'});return false;
 });
 const nameInput=$('#modalForm [name="name"]');nameInput.placeholder='请输入名称，或使用下方建议';
 function nameWarning(){const duplicate=lpList('suites').some(s=>s.id!==old?.id&&lpContent(s).name.trim()===nameInput.value.trim());$('#suiteNameWarning').textContent=duplicate?'已存在同名套件，建议补充用途以便区分。':nameManual?'已保留手动名称，筛选变化不会覆盖。':'';}
 function updateName(){
  const chosenSubs=[...new Set(assets.filter(a=>selected.has(a.id)).map(a=>lpContent(a).subproduct||'__none__'))];
  const key=chosenSubs.length===1?chosenSubs[0]:sub;
  const label=chosenSubs.length>1?'多子产品':key==='__none__'?'未分类':key?(typeof abSubproductLabel==='function'?abSubproductLabel(key):key).replace(/\s*[（(][^）)]*[）)]\s*$/,''):'全部子产品';
  const tier=$('#modalForm [name="tier"]').value;
  suggestedName=[product,label,layer==='API'?'接口':layer,({smoke:'冒烟',daily:'日构建',full:'全量',custom:'专项'})[tier]].join('-');
  $('#suiteSuggestedName').textContent='建议：'+suggestedName;
  if(!nameManual)nameInput.value=suggestedName;
  $('#suiteUseName').textContent=nameManual?'恢复建议名称':'使用建议名称';nameWarning();
 }
 nameInput.oninput=()=>{nameManual=true;nameWarning()};
 nameInput.onblur=()=>{if(!nameInput.value.trim()){nameManual=false;updateName()}};
 $('#suiteUseName').onclick=()=>{nameManual=false;updateName()};
 $('#modalForm [name="tier"]').onchange=()=>{const removed=[...selected.keys()].filter(id=>!inTier(assets.find(a=>a.id===id)));removed.forEach(id=>selected.delete(id));pageIndex=0;paint();$('#suiteHint').textContent=(removed.length?'已移除 '+removed.length+' 条不符合新执行范围的已选用例。':'')+'冒烟仅含冒烟；日构建含冒烟和日构建；全量/自选显示全部。'};
 const updateEnvironment=(value='')=>{const envs=(lpEnvs?.environments||[]).filter(e=>e.product===product),select=$('#suiteEnvironment');select.innerHTML='<option value="">执行时选择环境</option>'+envs.map(e=>`<option value="${esc(e.id)}">${esc(e.id)}${e.authAvailable?'':' · 缺少登录态'}</option>`).join('');if(value&&!envs.some(e=>e.id===value))select.insertAdjacentHTML('beforeend',`<option value="${esc(value)}" disabled>${esc(value)}（已失效，请重新选择）</option>`);select.value=value;$('#suiteEnvironmentHint').textContent=!envs.length?'当前产品暂无配置环境，可先保存套件，再到执行环境中检查配置。':'套件执行时默认带入，可在执行前调整；执行计划使用计划中固定的环境。'};
 updateEnvironment(c.environment||'');
 const scope=()=>assets.filter(a=>{const v=lpContent(a);return v.product===product&&v.layer===layer});
 const updateSubs=()=>{const subs=[...new Set(scope().map(a=>lpContent(a).subproduct||''))].sort();$('#suiteSub').innerHTML='<option value="">全部子产品</option>'+subs.map(x=>`<option value="${esc(x||'__none__')}">${esc(x?(typeof abSubproductLabel==='function'?abSubproductLabel(x):x):'未分类')}</option>`).join('');sub=''};
 function paint(){
  const q=query.trim().toLowerCase(),rows=scope().filter(a=>{const v=lpContent(a);return inTier(a)&&(!sub||(v.subproduct||'__none__')===sub)&&(!q||[v.title,v.feature,v.spec?.id,a.id].join(' ').toLowerCase().includes(q))});
  pageIndex=Math.min(pageIndex,Math.max(0,Math.ceil(rows.length/20)-1));
  const syncSelection=()=>{const chosen=rows.filter(a=>selected.has(a.id)).length;$('#suiteSelectAll').checked=rows.length>0&&chosen===rows.length;$('#suiteSelectAll').indeterminate=chosen>0&&chosen<rows.length;$('#suiteSelectAll').disabled=!rows.length;$('#suiteCount').textContent=`匹配 ${rows.length} 条 · 已选 ${selected.size} / 10000 条`;updateName()};
  syncSelection();
  $('#suiteSelectAll').onchange=e=>{if(e.target.checked){const additions=rows.filter(a=>!selected.has(a.id));if(selected.size+additions.length>10000){syncSelection();$('#suiteHint').textContent=`全选后将超过 10000 条上限，请缩小子产品或搜索范围。当前已选项未改变。`;return}for(const a of additions)selected.set(a.id,{assetId:a.id,revision:a.revision})}else for(const a of rows)selected.delete(a.id);const top=$('#suiteCandidates').scrollTop;paint();$('#suiteCandidates').scrollTop=top;$('#suiteHint').textContent='已更新当前筛选结果的选择（包含其他页），其他筛选范围的已选项保持不变。'};
  $('#suiteCandidates').innerHTML=rows.slice(pageIndex*20,(pageIndex+1)*20).map(a=>{const v=lpContent(a);return `<label class="suite-candidate"><input type="checkbox" class="check" data-suite-asset="${esc(a.id)}" ${selected.has(a.id)?'checked':''}><span><b>${esc(v.title)}</b><small>${esc(v.subproduct?(typeof abSubproductLabel==='function'?abSubproductLabel(v.subproduct):v.subproduct):'未分类')} · ${esc(({smoke:'冒烟',daily:'日构建',full:'全量'})[assetTier(a)]||'未标记范围')} · v${a.revision} · ${v.binding?'已关联脚本':'未关联脚本'}</small></span></label>`}).join('')||'<div class="empty">当前产品、子产品或类型下没有匹配的正式用例，请调整筛选。</div>';
  $('#suitePage').textContent=`${pageIndex+1} / ${Math.max(1,Math.ceil(rows.length/20))} 页 · 每页 20 条`;$('#suitePrev').disabled=pageIndex===0;$('#suiteNext').disabled=(pageIndex+1)*20>=rows.length;
  $('#suiteCandidates').scrollTop=0;
  document.querySelectorAll('[data-suite-asset]').forEach(el=>el.onchange=()=>{const a=assets.find(x=>x.id===el.dataset.suiteAsset);if(el.checked){if(selected.size>=10000){el.checked=false;$('#suiteHint').textContent='最多选择 10000 条，请先移除部分已选用例';return}selected.set(a.id,{assetId:a.id,revision:a.revision})}else selected.delete(a.id);syncSelection()});
 }
 const changeScope=()=>{product=$('#modalForm [name="product"]').value;layer=$('#modalForm [name="layer"]').value;const had=selected.size;selected.clear();pageIndex=0;updateEnvironment();updateSubs();paint();$('#suiteHint').textContent=had?'产品或类型已切换，已清空之前的选择。':'日构建包含冒烟用例；切换执行范围会移除不符项。子产品筛选保留已选。'};
 $('#modalForm [name="product"]').onchange=changeScope;$('#modalForm [name="layer"]').onchange=changeScope;
 $('#suiteSub').onchange=e=>{sub=e.target.value;pageIndex=0;paint()};$('#suiteSearch').oninput=e=>{query=e.target.value;pageIndex=0;paint()};
 $('#suiteClear').onclick=()=>{selected.clear();paint()};$('#suitePrev').onclick=()=>{pageIndex--;paint()};$('#suiteNext').onclick=()=>{pageIndex++;paint()};updateSubs();paint();
}

function lpWorkers(value){
 if(!lpData?.parallelUI)return '';
 const options=Array.from({length:lpData.maxUIWorkers||2},(_,i)=>[String(i+1),i===0?'1 · 串行（默认）':(i+1)+' · 无头并行']);
 return lpSelect('workers','同时执行的用例数',options,String(value||1));
}
function lpPlanDialog(id){const old=lpList('plans').find(p=>p.id===id),c=old?lpContent(old):{};if(!lpList('suites').length)return toast('请先创建测试套件');modal(old?'更新执行计划':'新建执行计划',lpInput('name','计划名称',c.name||'')+lpSelect('suiteId','测试套件（固定最新版本）',lpList('suites').map(s=>[s.id,lpContent(s).name+' · v'+s.revision]),c.suiteId)+lpSelect('environment','真实执行环境',[], '')+lpSelect('browserMode','浏览器模式',[['headless','无头模式（后台执行，不显示窗口）'],['headed','有头模式（支持扫码登录，再执行用例）']],c.browserMode||'headless')+lpWorkers(c.workers)+lpSelect('trigger','触发方式',[['manual','手动'],['daily','每日构建（外部调度）'],['ci','CI 构建完成后']],c.trigger||'manual')+`<label>每日执行时间（每日构建时必填）<input type="time" name="schedule" value="${esc(c.schedule||'09:00')}"></label><p class="subtitle">系统提供计划执行接口和 CLI；每日触发需由 Windows 任务计划或现有 CI 调用，不会暗中安装调度服务。</p>`,'查看变更',f=>{const raw=Object.fromEntries(f),s=lpList('suites').find(x=>x.id===raw.suiteId);Object.assign(raw,{suiteRevision:s.revision,enabled:true,...(old?{id:old.id,expectedRevision:old.revision}:{})});lpVersionReview('plan',raw,old);return false});const suiteField=$('#modalForm [name="suiteId"]'),envField=$('#modalForm [name="environment"]');
 function environments(selected){
  const suite=lpContent(lpList('suites').find(s=>s.id===suiteField.value));
  const choices=(lpEnvs?.environments||[]).filter(e=>e.product===suite.product);
  envField.replaceChildren(new Option('请选择执行环境',''),...choices.map(e=>new Option(e.id+' · '+e.product,e.id)));
  envField.value=selected||suite.environment||'';
 }
 environments(c.environment);suiteField.onchange=()=>environments('');
}
function lpStartDialog(suiteId,planId,parentRunId){const parent=parentRunId?lpRun:null,p=planId?lpList('plans').find(x=>x.id===planId):null,pc=p?lpContent(p):null,s=lpList('suites').find(x=>x.id===(suiteId||pc?.suiteId||parent?.snapshot.suiteId));if(!s)return toast('套件不存在');const revision=parent?.snapshot.suite.revision||pc?.suiteRevision||s.revision;const content=s.versions.find(v=>v.revision===revision).content;
 modal(parent?'重跑失败与未完成项':'执行前确认',`<h3>${esc(content.name)} · v${revision}</h3><p>${esc(content.product)} · ${esc(content.layer)} · ${parent?'原运行失败、错误、中断及未执行项':content.cases.length+' 条用例'}</p>`+lpSelect('environment','执行环境',[['','请选择执行环境'],...(lpEnvs?.environments||[]).filter(e=>e.product===content.product).map(e=>[e.id,e.id+' · '+e.product])],pc?.environment||parent?.environment||content.environment)+lpSelect('browserMode','浏览器模式',[['headless','无头模式（后台执行，不显示窗口）'],['headed','有头模式（支持扫码登录，再执行用例）']],pc?.browserMode||parent?.snapshot?.browserMode||'headless')+lpWorkers(pc?.workers||parent?.snapshot?.workers||1)+`<p id="runTimeoutHint" class="subtitle"></p><div class="account-run-panel"><label>登录账号<select name="loginAccount" id="runLoginAccount"></select></label><p id="runAccountHint" class="subtitle" role="status"></p></div>`+`<p>将按固定的资产版本运行所选环境的测试，并保存每条用例的结果。</p><p class="subtitle">环境以 UI 工程配置为准；有头模式支持扫码，登录失败时停止整轮；版本变化和准入不满足时明确阻塞。本次结果不等同于发布批准。</p>`,'开始真实执行',f=>{if(f.get('loginAccount')){toast('账号登录仅为 Demo：将由 UI 自动化系统登录，当前未提交执行');return false}const fields=Object.fromEntries(f);delete fields.loginAccount;const raw={suiteId:s.id,suiteRevision:revision,...fields,...(parent?{parentRunId:parent.id}:{}),...(p?{planId:p.id,expectedPlanRevision:p.revision}:{})};if(p&&(Number(raw.workers||1)!==Number(pc.workers||1)||raw.environment!==pc.environment||raw.browserMode!==(pc.browserMode||'headless'))){toast('计划环境、并发数和浏览器模式固定，请先编辑计划或从套件发起临时执行');return false}lpWrite('start',raw).then(r=>{if(r){lpSelectedRun=r.id;lpTab='runs';lpRun=r;render();lpLoad()}});return false});const envSelect=$('#modalForm [name="environment"]');const sync=()=>{const rows=accountDemoRows.filter(a=>a.environments.includes(envSelect.value));$('#runLoginAccount').innerHTML='<option value="">扫码 / 已有登录态（真实执行）</option>'+rows.map(a=>`<option value="${esc(a.id)}">${esc(a.name)} · ${a.kind==='personal'?'个人账号':'公共账号'}${a.isDefault?' · 默认':''}（演示）</option>`).join('');$('#runLoginAccount').value=rows.find(a=>a.isDefault)?.id||'';accountRunHint()};envSelect.onchange=sync;$('#runLoginAccount').onchange=accountRunHint;sync();
 const count=parent?parent.results.filter(r=>['failed','error','auth','blocked','interrupted','not_run','unknown'].includes(r.status)).length:content.cases.length;
 const updateTimeout=()=>{
  const policy=lpData?.runTimeoutPolicy;
  if(!policy){$('#runTimeoutHint').textContent='当前后台整轮执行时限为 60 分钟；大套件请先更新并重启后台。';return}
  if(policy.mode==='unlimited'){$('#runTimeoutHint').textContent='本次 '+count+' 条用例，整轮不设总时限。可手动停止；单步操作超时仍有效。';return}
  const workers=Math.max(1,Math.min(Number($('#modalForm [name="workers"]')?.value||1),count));
  const seconds=Math.min(policy.maximumSeconds,Math.max(policy.minimumSeconds,policy.setupSeconds+Math.ceil(count/workers)*policy.caseSeconds));
  $('#runTimeoutHint').textContent='本次 '+count+' 条用例，整轮执行时限 '+Math.floor(seconds/60)+' 分钟（暂停时间另计）。时限按用例数和并行数计算，不代表预计耗时。';
 };
 const workersField=$('#modalForm [name="workers"]');if(workersField)workersField.onchange=updateTimeout;updateTimeout();
}
function lpSuitePage(){let rows=lpList('suites').filter(x=>{const c=lpContent(x);return (lpType==='全部'||c.layer===lpType)&&(!lpQuery||(c.name+' '+c.product).toLowerCase().includes(lpQuery.toLowerCase()))});lpPage=Math.min(lpPage,Math.max(0,Math.ceil(rows.length/lpSize)-1));return `<section class="card ex-work"><div class="ex-heading"><h2>测试套件</h2>${btn('新建测试套件','lpSuiteNew','primary small')}</div><div class="ex-toolbar">${['全部',...Object.keys(axTypes)].map(x=>btn(x==='全部'?'全部类型':axTypes[x],'lpType:'+x,lpType===x?'primary small':'small')).join('')}<input id="lpQuery" aria-label="搜索套件" placeholder="套件名称 / 产品 · 回车" value="${esc(lpQuery)}"></div><div class="ex-scroll"><table><thead><tr><th>套件 / 版本</th><th>产品 / 类型</th><th>范围 / 默认环境</th><th>用例数</th><th>最近结果</th><th>操作</th></tr></thead><tbody>${rows.slice(lpPage*lpSize,(lpPage+1)*lpSize).map(s=>{const c=lpContent(s),r=lpList('runs').filter(r=>r.suiteId===s.id).at(-1);return `<tr><td>${esc(c.name)}<small>${esc(s.id)} · v${s.revision}</small></td><td>${esc(c.product)}<small>${esc(axTypes[c.layer])}</small></td><td>${esc(({smoke:'冒烟',daily:'日构建',full:'全量',custom:'自选'})[c.tier]||c.tier)}<small>${esc(c.environment||'执行时选择')}</small></td><td>${c.cases.length}</td><td>${r?badge(lpStatus[r.status]):'未执行'}</td><td>${btn('执行','lpStart:'+s.id,'small')}${btn('编辑','lpSuiteEdit:'+s.id,'link small')}${btn('版本','lpVersions:suites:'+s.id,'link small')}</td></tr>`}).join('')||'<tr><td colspan="6" class="empty">暂无正式套件，请先发布正式用例，再创建套件。</td></tr>'}</tbody></table></div>${exPager(rows.length,lpPage,'lpPage',lpSize)}</section>`}
function lpPlansPage(){return `<section class="card ex-work"><div class="ex-heading"><h2>执行计划</h2>${btn('新建计划','lpPlanNew','primary small')}</div><p class="ex-note">计划固定套件版本、环境和触发方式，构建标识执行时自动生成或由 CI 传入。日构建及 CI 由外部调度调用执行接口。</p><div class="ex-scroll"><table><thead><tr><th>计划 / 修订</th><th>套件版本</th><th>环境 / 构建</th><th>触发</th><th>状态</th><th>操作</th></tr></thead><tbody>${lpList('plans').map(p=>{const c=lpContent(p);return `<tr><td>${esc(c.name)}<small>v${p.revision}</small></td><td>${esc(lpList('suites').find(x=>x.id===c.suiteId)?.versions.find(v=>v.revision===c.suiteRevision)?.content.name||c.suiteId)} · v${c.suiteRevision}</td><td>${esc(c.environment)}<small>执行时自动传入</small></td><td>${esc(({manual:'手动',daily:'每日 '+c.schedule,ci:'CI 触发'})[c.trigger])}<small>${c.trigger==='manual'?'':'待外部调度调用'}</small></td><td>${c.enabled?'启用':'停用'}</td><td>${c.enabled?btn('执行','lpPlanStart:'+p.id,'small'):''}${btn('编辑','lpPlanEdit:'+p.id,'link small')}${btn(c.enabled?'停用':'启用','lpPlanToggle:'+p.id,'link small')}${btn('CI 命令','lpCI:'+p.id,'link small')}</td></tr>`}).join('')||'<tr><td colspan="6" class="empty">暂无执行计划</td></tr>'}</tbody></table></div></section>`}
// Preserve native disclosure state across live polling and explicit refreshes.
const lpOpenDetails=new Set();
function lpDetailAttrs(runId,section){const key=JSON.stringify([runId,section]);return `data-lp-detail="${esc(key)}"${lpOpenDetails.has(key)?' open':''}`}
function lpRememberDetails(){document.querySelectorAll('details[data-lp-detail]').forEach(el=>{const key=el.dataset.lpDetail;if(el.open)lpOpenDetails.add(key);else lpOpenDetails.delete(key)})}
function lpFailureSummary(c){
 if(c.status==='pending')return {title:'等待执行',cause:'尚未开始此用例。',action:'',stage:''};
 if(c.status==='running')return {title:'执行中',cause:'正在执行或收尾，完成后自动更新结果。',action:'',stage:''};
 const raw=String(c.message||'');
 // Match exception output, not Python source excerpts embedded in a traceback.
 const errors=raw.split('\n').filter(s=>/^E\s+/.test(s)).map(s=>s.replace(/^E\s+/,''));
 const evidence=errors.length?errors.join('\n'):raw;
 const last=errors.filter(s=>/(?:Error|Exception|FAILED|HARD FAIL)[:\s]/.test(s)).at(-1)||errors.at(-1)||raw.split('\n').filter(Boolean).at(-1)||'';
 const failed=(c.phases||[]).filter(p=>p.outcome==='failed');
 let stage=({setup:'准备阶段',call:'执行阶段',teardown:'收尾阶段'})[failed[0]?.phase]||'执行检查';
 let title='执行异常，需检查详细日志',cause=last.slice(0,280)||'当前记录未提供具体原因。',action='查看原始异常和截图，确认失败位置。';
 if(c.status==='passed')return {title:'通过',cause:'准备、执行、收尾阶段均通过。',action:'',stage:''};
 if(/HARD FAIL:.*未删除成功|CLEANUP ALERT|INV-cleanup/.test(evidence)){
  title='测试文档清理未通过';stage='清理检查';
  cause=/Network.getResponseBody|Response body is not available/.test(evidence)?'清理时页面已跳转，脚本无法读取接口响应，未能确认测试文档是否删除。':'测试结束后的清理检查失败，尚未确认测试数据已清除。';
  action='先核对测试文档是否残留；检查删除响应读取与页面跳转的先后顺序。此错误不等同于业务操作失败。';
 }else if(/Network.getResponseBody|Response body is not available/.test(evidence)){
  title='接口响应读取失败';cause='页面跳转后，脚本读取的响应正文已不可用。';action='检查脚本是否在页面跳转前读取响应正文，不能据此判定产品接口返回失败。';
 }else if(/the database web_log_db has not been created yet/.test(evidence)){
  title='页面日志组件初始化失败';cause='编辑器调用日志写入时，应用内部数据库连接尚未就绪。';action='保留失败证据，检查产品日志组件的异步初始化；有头模式也可能发生，不应忽略此异常。';
 }else if(/INV-pageerror/.test(evidence)){
  title='页面 JavaScript 报错';cause=last.replace(/^.*?INV-pageerror:\s*/,'').slice(0,280);action='核对页面控制台和发生时机，确认是产品异常还是测试环境初始化问题。';
 }else if(c.status==='auth'||/停在登录|缺少登录态|storage_state.*无效/.test(evidence)){
  title='登录状态不可用';cause='未能进入已登录的业务页面。';action='使用有头模式重新扫码，并确认环境正确。';
 }else if(/TargetClosedError|Target page, context or browser has been closed/.test(evidence)){
  title='页面或浏览器提前关闭';cause='脚本继续操作时，目标页面或浏览器已关闭。';action='检查手动关闭、浏览器崩溃和脚本关闭时机。';
 }else if(/TimeoutError|Timeout \d+ms exceeded|timed out/i.test(evidence)){
  title='等待页面或操作超时';cause=last.slice(0,280);action='查看失败截图及等待目标，核对页面加载、元素定位和等待条件。';
 }else if(c.status==='interrupted'||c.status==='cancelled'){
  title='用例执行中断';cause=raw.slice(0,280)||'已开始执行，但未取得完整阶段结果。';action='查看整轮停止原因，处理后重新执行。';
 }else if(c.status==='not_run'){
  title=(c.phases||[]).length?'执行记录不完整':'尚未执行';cause=raw.slice(0,280)||'本轮没有该用例的执行记录。';action='查看整轮中断或阻塞原因；此项不能视为通过。';
 }else if(c.status==='skipped'){
  title='用例被跳过';action='核对跳过条件与当前环境是否符合执行要求。';
 }else if(c.status==='blocked'){
  title='执行前置检查未通过';action='按提示补齐环境、脚本或登录前置条件后重试。';
 }else if(/AssertionError|assert /.test(evidence)){
  title='检查结果不符合预期';cause=last.replace(/^.*?AssertionError:\s*/,'').slice(0,280);action='对照断言、实际结果和截图确认差异，暂不能仅凭堆栈定位产品根因。';
 }
 if(failed.length>1)action+=' 另有'+(failed.length-1)+'个阶段失败，请展开查看。';
 return {title,cause,action,stage};
}
function lpFailureCell(r,c){
 const s=lpFailureSummary(c);
 const phases=(c.phases||[]).filter(p=>p.outcome==='failed'&&p.message).map(p=>'【'+({setup:'准备',call:'执行',teardown:'收尾'}[p.phase]||p.phase)+'阶段】\n'+p.message).join('\n\n');
 return `<div class="run-failure-summary"><b>${esc(s.title)}</b>${s.stage?`<span class="run-failure-stage">${esc(s.stage)}</span>`:''}<p>${esc(s.cause)}</p>${s.action?`<p class="subtitle">建议：${esc(s.action)}</p>`:''}${c.status!=='passed'?`<details ${lpDetailAttrs(r.id,'case:'+(c.assetId||c.nodeid||c.title))}><summary>技术详情 · 原始异常</summary><pre class="spec-preview">${esc(phases||c.message||'无原始异常记录')}</pre></details>`:''}</div>`;
}
function lpFailureScreenshot(r,c){
 if(c.status==='passed')return '<span class="subtitle">—</span>';
 const images=(c.screenshots||[]).filter(name=>(r.artifacts||[]).includes(name)&&name.endsWith('/failure.png'));
 if(!images.length)return `<span class="subtitle">${esc(c.screenshotIssue||(['pending','not_run','skipped'].includes(c.status)?'未采集截图':['preparing','running','pausing','paused','cancelling'].includes(r.status)?'截图归档中，结束后刷新':'本轮未采集到截图（页面可能已关闭），可查看技术详情'))}</span>`;
 return images.map(name=>{const url=lpScreenshotUrl(r,name);return `<button type="button" class="run-failure-image" data-action="lpScreenshot:${encodeURIComponent(name)}" title="点击放大；截图采集于失败后的收尾阶段"><img data-failure-image src="${esc(url)}" alt="${esc(c.title)} · 失败截图" loading="lazy"><span>点击放大</span></button>`}).join('');
}
function lpOpenScreenshot(path){
 if(!lpRun?.artifacts?.includes(path)||!path.endsWith('/failure.png'))return;
 document.querySelector('#lpImagePreview')?.close();
 const viewer=document.createElement('dialog');viewer.id='lpImagePreview';viewer.className='run-image-viewer';viewer.setAttribute('aria-labelledby','lpImagePreviewTitle');
 viewer.innerHTML=`<div class="run-image-toolbar"><strong id="lpImagePreviewTitle">失败截图预览</strong><div><button type="button" data-zoom="fit">适应窗口</button><button type="button" data-zoom="actual">100%</button><button type="button" data-zoom="out" aria-label="缩小截图">−</button><output aria-live="polite">加载中</output><button type="button" data-zoom="in" aria-label="放大截图">＋</button><button type="button" data-zoom="close" aria-label="关闭截图预览">关闭</button></div></div><p class="run-image-note">点击图片切换原始尺寸；放大后可滚动查看。截图采集于失败后的收尾阶段。</p><div class="run-image-stage"><img alt="失败截图大图"><p class="run-image-error" hidden>截图加载失败，请关闭后重试。</p></div>`;
 const img=viewer.querySelector('img'),stage=viewer.querySelector('.run-image-stage'),output=viewer.querySelector('output');let scale=1,fitted=true;
 const fit=()=>Math.min(1,Math.max(1,stage.clientWidth-24)/img.naturalWidth,Math.max(1,stage.clientHeight-24)/img.naturalHeight);
 const apply=value=>{if(!img.naturalWidth)return;scale=Math.max(.05,Math.min(4,value));img.style.width=(img.naturalWidth*scale)+'px';img.style.height=(img.naturalHeight*scale)+'px';output.textContent=Math.round(scale*100)+'%';img.style.cursor=scale<1?'zoom-in':'zoom-out'};
 viewer.addEventListener('click',e=>{const action=e.target.closest('[data-zoom]')?.dataset.zoom;if(action==='close'){viewer.close();return}if(!img.naturalWidth)return;if(action==='fit'){fitted=true;apply(fit());stage.scrollTo(0,0)}else if(action){fitted=false;apply(action==='actual'?1:action==='in'?scale*1.25:scale/1.25)}});
 img.addEventListener('click',()=>{fitted=!fitted;apply(fitted?fit():1);stage.scrollTo(0,0)});
 img.addEventListener('load',()=>apply(fitted?fit():scale));img.addEventListener('error',()=>{img.hidden=true;viewer.querySelector('.run-image-error').hidden=false;output.textContent='加载失败'});
 const resize=()=>{if(fitted&&img.naturalWidth)apply(fit())};window.addEventListener('resize',resize);
 viewer.addEventListener('close',()=>{window.removeEventListener('resize',resize);viewer.remove()},{once:true});
 document.body.append(viewer);viewer.showModal();img.src=lpScreenshotUrl(lpRun,path);viewer.querySelector('[data-zoom="close"]').focus();
}
function lpDuration(seconds){if(typeof seconds!=='number'||!Number.isFinite(seconds))return '—';seconds=Math.max(0,seconds);if(seconds<60)return seconds.toFixed(1)+' 秒';const n=Math.floor(seconds);return (n>=3600?Math.floor(n/3600)+' 小时 ':'')+Math.floor(n%3600/60)+' 分 '+n%60+' 秒'}
function lpCaseDuration(c){const seconds=c.status==='running'&&c.startedAt?Math.max(0,(Date.now()-Date.parse(c.startedAt))/1000):c.durationSeconds;return `<span title="${c.durationEstimated?'历史记录：已记录阶段耗时合计':'包含准备、执行、收尾阶段'}">${esc(lpDuration(seconds))}${c.durationEstimated?'（阶段合计）':''}</span>${c.startedAt?`<small>开始 ${esc(exTime(c.startedAt))}</small>`:''}`}
function lpRunDuration(r){return r.createdAt&&(r.finishedAt||['preparing','running','pausing','paused','cancelling'].includes(r.status))?lpDuration(((r.finishedAt?Date.parse(r.finishedAt):Date.now())-Date.parse(r.createdAt))/1000):'—'}
function lpRunActions(r,detail=false){
 if(!lpData?.runControls)return ['preparing','running','cancelling'].includes(r.status)?btn('停止','lpCancel:'+r.id,'small'):(detail?btn('重跑失败与未完成项','lpRetry:'+r.id,'small'):'');
 if(r.deleteRequested)return '<span class="subtitle">停止并删除中…</span>';
 const active=['preparing','running','pausing','paused','cancelling'].includes(r.status);
 let actions='';
 if(['preparing','running'].includes(r.status))actions+=btn('暂停','lpPause:'+r.id,'small');
 if(['pausing','paused'].includes(r.status))actions+=btn(r.status==='pausing'?'撤销暂停':'继续','lpResume:'+r.id,'small');
 if(active&&r.status!=='cancelling')actions+=btn('停止','lpCancel:'+r.id,'small');
 if(!active&&detail)actions+=btn('重跑失败与未完成项','lpRetry:'+r.id,'small');
 return '<span class="run-controls">'+actions+btn('删除','lpDeleteRun:'+r.id,'link small')+'</span>';
}
function lpRunDetail(){const r=lpRun;if(!r)return '';return `<section class="card pad"><div class="row"><h2>${esc(r.name)} · ${esc(lpStatus[r.status])}</h2>${lpRunActions(r,true)}</div><p>${esc(r.environment)} · ${esc(r.snapshot?.environmentConfig?.api_base_url || r.snapshot?.environmentConfig?.base_url || '')} · ${r.snapshot?.browserMode==='headed'?'有头模式':'无头模式'} · ${Math.min(r.snapshot?.workers||1,r.total)>1?Math.min(r.snapshot.workers,r.total)+' 路并行':'串行'} · ${r.buildSource==='generated'?'自动执行标识':'构建标识'} ${esc(r.build)} · ${esc(r.snapshot?.contract||'ci_fresh_context')}</p><p role="status">${esc(r.message)}</p><p class="subtitle">整轮耗时 ${esc(lpRunDuration(r))}（含登录及前置检查）${['preparing','running','pausing','paused','cancelling'].includes(r.status)?' · 每 2 秒自动刷新用例状态和耗时':' · 已结束'}</p>${['preparing','running','pausing','paused','cancelling'].includes(r.status)?`<a href="/api/automation/runs/${r.id}/artifacts/console.log" target="_blank">查看当前控制台日志</a>`:''}<div class="ex-counts">${Object.entries(r.counts||{}).map(([k,v])=>`<span>${esc(lpStatus[k])} <b>${v}</b></span>`).join('')}</div><div class="ex-scroll" data-run-results="${esc(r.id)}"><table><thead><tr><th>用例</th><th>结果</th><th>执行耗时</th><th>原因</th><th>失败截图</th></tr></thead><tbody>${r.results.map(c=>`<tr><td>${esc(c.title)}</td><td>${badge(lpStatus[c.status]||c.status)}</td><td class="run-duration">${lpCaseDuration(c)}</td><td>${lpFailureCell(r,c)}</td><td>${lpFailureScreenshot(r,c)}</td></tr>`).join('')}</tbody></table></div><details ${lpDetailAttrs(r.id,"events")}><summary>执行事件与证据</summary>${(r.events||[]).map(e=>`<p>${exTime(e.at)} · ${esc(e.message)}</p>`).join('')}<div class="actions">${(r.artifacts||[]).map(name=>`<a href="/api/automation/runs/${r.id}/artifacts/${name.split('/').map(encodeURIComponent).join('/')}" download>${esc(name)}</a>`).join('')}</div></details><div class="actions">${btn('查看 / 导出质量报告','lpReport:'+r.id,'small')}${btn('刷新进展','lpRun:'+r.id,'small')}</div></section>`}
function lpGroupStatuses(group){
 return group==='passed'?['passed']:['failed','error','auth'];
}
function lpGroupItems(cases){
 return cases.map(c=>`<li>${esc(c.title||c.assetId)}${['error','auth'].includes(c.status)?' · '+esc(lpStatus[c.status]):''}</li>`).join('');
}
async function lpShowGroup(id,group){
 try{
  const detail=await workspaceRequest('/api/automation/runs/'+encodeURIComponent(id));
  const cases=detail.results.filter(c=>lpGroupStatuses(group).includes(c.status));
  modal(detail.name+' · '+(group==='passed'?'通过':'失败')+'用例（'+cases.length+'）',
   '<ul>'+lpGroupItems(cases)+'</ul>','关闭',()=>{});
 }catch(e){toast('读取用例明细失败：'+e.message)}
}
function lpRunCaseGroup(run, group) {
 const passed = group === 'passed';
 const label = passed ? '通过' : '失败';
 const statuses=lpGroupStatuses(group);
 if(!Array.isArray(run.results)){
  if(!run.counts)return '<span title="暂无统计">—</span>';
  const count=statuses.reduce((sum,status)=>sum+(run.counts[status]||0),0);
  if(count)return `<button class="link small" data-action="lpGroup:${esc(run.id)}:${group}" aria-label="查看${count}条${label}用例">${count}</button>`;
 }
 const cases = (run.results || []).filter(c => statuses.includes(c.status));
 if (!cases.length) return `<span class="run-case-zero" aria-label="${label} 0 条">0</span>`;
 return `<details class="run-case-group ${group}" ${lpDetailAttrs(run.id, 'cases-'+group)}>
   <summary aria-label="查看${cases.length}条${label}用例">${cases.length}</summary>
   <ul>${lpGroupItems(cases)}</ul>
 </details>`;
}
function lpRunsPage(){return `<section class="card ex-work"><div class="ex-heading"><h2>运行记录</h2>${!lpData?.runControls?'<span class="subtitle">后台更新后可暂停、继续及删除运行（请在本轮结束后重启后台）</span>':''}${btn('刷新','lpRefresh','small')}</div><div class="ex-scroll"><table><thead><tr><th>套件</th><th>产品 / 构建</th><th>环境</th><th>结果</th><th>执行数</th><th>通过用例</th><th title="含断言失败、脚本或环境错误、登录异常">失败用例</th><th>整轮耗时</th><th>开始时间</th><th></th></tr></thead><tbody>${lpList('runs').slice().reverse().map(r=>`<tr><td>${esc(r.name)}</td><td>${esc(r.product)}<small>${esc(r.build)}</small></td><td>${esc(r.environment)}</td><td>${badge(lpStatus[r.status])}</td><td>${r.executed}/${r.total}</td><td>${lpRunCaseGroup(r,'passed')}</td><td>${lpRunCaseGroup(r,'failed')}</td><td>${esc(lpRunDuration(r))}</td><td>${exTime(r.createdAt)}</td><td>${btn('查看','lpRun:'+r.id,'small')}${lpRunActions(r)}</td></tr>`).join('')||'<tr><td colspan="10" class="empty">暂无真实运行记录</td></tr>'}</tbody></table></div></section>`+lpRunDetail()}
let lpLoginPending=false;
function lpSupportsLogin(e){
 return Boolean(e&&Object.hasOwn(e,'authOperation'));
}
function lpPlaceholder(e){
 try{
  const url=new URL(e.url);
  return !['https:','http:'].includes(url.protocol)||url.hostname.endsWith('.example.com');
 }catch{return true}
}
async function lpLoginAction(environment,action){
 if(lpLoginPending)return;
 const current=lpEnvs?.environments?.find(e=>e.id===environment);
 if(!current)return;
 if(action==='login'&&lpPlaceholder(current))return;
 lpLoginPending=true;
 try{
  if(lpSupportsLogin(current)){
   try{
    await workspaceRequest('/api/automation/login-state',{environment,action},30000);
   }catch(e){
    if(e.status!==404||e.path!=='/api/automation/login-state')throw e;
    delete current.authOperation;
    if(action==='login')return toast('请再次点击重新扫码，在浏览器打开登录页');
    if(action!=='check')throw Error('当前后台仅支持读取本机登录态。请关闭原后台窗口并重新启动工作台。');
   }
  }else if(action!=='check')return;
  if(action==='clear')closeModal();
  const snapshot=await workspaceRequest('/api/automation/environments',undefined,30000);
  const row=snapshot.environments.find(e=>e.id===environment);
  if(!row)throw Error(snapshot.error||'当前环境已移除，请刷新环境列表');
  if(!lpSupportsLogin(current)){
   delete row.authOperation;
   toast(environment+' · '+(row.loginState?.message||'后台未返回本机登录态'));
  }
  lpEnvs=snapshot;
 }catch(e){toast(e.message)}
 finally{lpLoginPending=false;if(page==='automation'&&lpTab==='environments')render()}
}
function lpLoginPanel(e){
 const state=e.loginState,job=e.authOperation||{},managed=lpSupportsLogin(e),placeholder=lpPlaceholder(e);
 const busy=lpLoginPending||lpEnvs?.environments.some(row=>row.authOperation?.status==='running');
 const actions=managed?[['check','检测登录状态'],['login','重新扫码'],['clear','清除登录态']]:[['check','刷新本机登录状态'],['login','重新扫码']];
 const buttons=actions.map(([action,label])=>{
  const disabled=busy||(action==='clear'&&!state?.saved)||(placeholder&&(action==='login'||(managed&&action==='check')));
  if(action==='login'&&!managed&&!disabled){
   return `<a class="small env-scan-link" href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  }
  return `<button type="button" class="small" data-action="lpLogin:${esc(e.id)}:${action}" ${disabled?'disabled':''}>${label}</button>`;
 }).join('');
 return `<section class="environment-login"><b>本机登录状态</b><p>${esc(state?.message||'后台未提供登录态信息')}</p>
  ${state?.saved?`<p class="subtitle">身份：${esc(state.identity||'未知')} · 最近验证 ${state.verifiedAt?esc(exTime(state.verifiedAt)):'暂无记录'}</p>`:''}
  ${job.message?`<p role="status">${esc(job.message)}${job.status==='failed'?'（未成功）':''}</p>`:''}
  <div class="actions">${buttons}</div>
  ${!managed?'<p class="subtitle">扫码将在浏览器新标签页打开。要将登录态保存给自动化执行，请重启工作台后台后扫码。</p>':''}
  ${placeholder?'<p class="subtitle">占位地址，请先在环境配置中填写实际入口。</p>':''}</section>`;
}
automationPage=function(){return title('自动化执行','套件定义范围，执行计划安排环境与触发，每次运行保留独立版本和证据。',btn('刷新','lpRefresh','small'))+`<p class="notice info">UI 和 API 均可通过本地 pytest 执行。真实运行会操作目标环境。套件、计划、结果保存到本地后台。</p>${lpError?`<p class="notice">${esc(lpError)}</p>`:''}<div class="tabs automation-tabs" aria-label="自动化执行视图" role="group">${[['suites','测试套件'],['plans','执行计划'],['runs','运行记录'],['environments','执行环境'],['accounts','登录账号'],['legacy','旧演示配置']].map(([key,name])=>`<button type="button" class="small" data-action="lpTab:${key}" aria-pressed="${lpTab===key}">${name}</button>`).join('')}</div>`+({suites:lpSuitePage,plans:lpPlansPage,runs:lpRunsPage,accounts:accountPage,environments:()=>`<section class="card pad"><h3>健康管理测试环境</h3>${(lpEnvs?.environments||[]).map(e=>`<p>${esc(e.id)} · ${esc(e.baseUrl)}</p>`).join('')}${lpEnvs?.error?`<p>${esc(lpEnvs.error)}</p>`:''}${btn('配置测试环境','editProductEnv','small')}</section>`,legacy:()=>`<details class="card pad"><summary>旧浏览器演示配置（只读）</summary><pre class="spec-preview">${esc(JSON.stringify({plans:autoState.plans,runs:autoState.runs},null,2))}</pre></details>`}[lpTab]||lpSuitePage)()};

let laProduct='',laLayer='',laSubproduct='',laQuery='',laPage=0,laSize=20;
const laTypes=[['','全部类型'],['UI','UI 自动化'],['API','接口自动化'],['性能','性能自动化'],['安全','安全自动化']];
function laProductRows(){return lpList('assets').filter(a=>!laProduct||lpContent(a).product===laProduct)}
function laRows(){const q=laQuery.toLowerCase().trim();return laProductRows().filter(a=>{const c=lpContent(a);return (!laLayer||c.layer===laLayer)&&(!laSubproduct||c.subproduct===laSubproduct)&&(!q||[a.id,c.spec?.id,c.title,c.feature,c.subproduct].join(' ').toLowerCase().includes(q))})}
function lpAssetPage(){const all=lpList('assets'),products=[...new Set([...abProducts,...all.map(a=>lpContent(a).product)])],scope=laProductRows(),rows=laRows(),subs=[...new Set(scope.filter(a=>!laLayer||lpContent(a).layer===laLayer).map(a=>lpContent(a).subproduct).filter(Boolean))].sort();laPage=Math.min(laPage,Math.max(0,Math.ceil(rows.length/laSize)-1));return `<div class="la-layout"><nav class="card pad la-products" aria-label="正式用例所属产品"><h3>产品</h3>${[['','全部产品'],...products.map(p=>[p,p])].map(([id,name])=>`<button data-action="laProduct:${encodeURIComponent(id)}" class="${laProduct===id?'active':''}" aria-pressed="${laProduct===id}"><span>${esc(name)}</span><small>${id?all.filter(a=>lpContent(a).product===id).length:all.length}</small></button>`).join('')}<p class="subtitle">数量为已纳入的正式用例</p></nav><section class="card ex-work la-main"><div class="ex-heading"><div><h2>${esc(laProduct||'正式用例库')}</h2><p>按产品和自动化类型查看，保留用例版本与脚本关联。</p></div><div class="actions">${btn('刷新','lpRefresh','small')}${btn('导出用例与套件','lpExportAssets','small')}${btn('导入用例与套件','lpImportAssets','small')}${btn('纳入用例','lpImport','primary small')}</div></div><div class="la-types" aria-label="正式用例自动化类型">${laTypes.map(([id,name])=>`<button data-action="laLayer:${id}" class="${laLayer===id?'active':''}" aria-pressed="${laLayer===id}">${name} <small>${id?scope.filter(a=>lpContent(a).layer===id).length:scope.length}</small></button>`).join('')}</div><div class="la-filters"><label>查找用例<input id="laQuery" placeholder="名称、编号或特性 · 回车搜索" value="${esc(laQuery)}"></label><label>子产品<select id="laSubproduct"><option value="">全部子产品</option>${subs.map(sub=>`<option value="${esc(sub)}" ${sub===laSubproduct?'selected':''}>${esc(typeof abSubproductLabel==='function'?abSubproductLabel(sub):sub)}</option>`).join('')}</select></label>${btn('清空筛选','laReset','link small')}</div><p class="ex-note">匹配 ${rows.length} 条 · 脚本就绪为静态检查结果，不代表运行通过。</p><div class="ex-scroll la-scroll"><table><thead><tr><th>用例 / 版本</th><th>产品 / 特性</th><th>类型</th><th>脚本关联</th><th>操作</th></tr></thead><tbody>${rows.slice(laPage*laSize,(laPage+1)*laSize).map(a=>{const c=lpContent(a);return `<tr><td><strong>${esc(c.title)}</strong><small>${esc(c.spec?.id||a.id)} · v${a.revision}</small></td><td>${esc(c.product)}<small>${esc(c.feature||c.subproduct)}</small></td><td>${esc(({UI:'UI',API:'接口',性能:'性能',安全:'安全'})[c.layer]||c.layer)}</td><td>${c.binding?'已关联脚本':'未关联脚本'}<small>${c.binding?esc(c.binding.admission):'待实现或关联'}</small></td><td>${btn('查看版本','lpVersions:assets:'+a.id,'small')}${['UI','API'].includes(c.layer)?btn('设计并生成脚本','generateScript:'+a.id,'small')+btn('关联脚本','lpBind:'+a.id,'link small'):''}</td></tr>`}).join('')||`<tr><td colspan="5" class="empty">${laQuery||laSubproduct?'没有符合筛选条件的用例，可清空筛选。':'当前产品与类型暂无正式用例；其他类型的 UI 用例不会计入本分类。'}</td></tr>`}</tbody></table></div><div class="la-pager"><label>每页 <select id="laSize">${[20,50].map(n=>`<option ${n===laSize?'selected':''}>${n}</option>`).join('')}</select> 条</label><span>${laPage+1} / ${Math.max(1,Math.ceil(rows.length/laSize))} 页</span><button data-action="laPage:prev" ${laPage===0?'disabled':''}>上一页</button><button data-action="laPage:next" ${(laPage+1)*laSize>=rows.length?'disabled':''}>下一页</button></div></section></div>`}
const lpAssetsOld=assets;
assets=function(){const template=document.createElement('template');template.innerHTML=lpAssetsOld();const nav=template.content.querySelector('.ab-tabs');nav?.insertAdjacentHTML('beforeend',`<button role="tab" data-action="lpAssets" aria-selected="${abTab==='published'}" class="${abTab==='published'?'active':''}">正式用例库</button>`);if(abTab==='published'){nav?.querySelectorAll('button').forEach(b=>{b.classList.toggle('active',b.dataset.action==='lpAssets');b.setAttribute('aria-selected',String(b.dataset.action==='lpAssets'))});const body=template.content.querySelector('[role="tabpanel"]');body.setAttribute('aria-label','正式用例库');body.innerHTML=lpAssetPage()}return template.innerHTML};
async function lpChooseScript(assetId){if(!abInventory)abInventory=await workspaceRequest('/api/assets');const asset=lpList('assets').find(x=>x.id===assetId),product=asset?lpContent(asset).product:'';return modal(asset?'查找要关联的脚本':'查找已有脚本资产',lpInput('query','关键词（名称、特性或编号）')+'<p>仅从最近扫描索引中选择，最多展示 80 条候选；需要更新时先刷新测试资产。</p>','查找',f=>{const query=f.get('query').trim().toLowerCase(),rows=(abInventory?.cases||[]).filter(c=>(!asset||c.layer===lpContent(asset).layer)&&(!product||c.product===product)&&(c.title+' '+c.id+' '+c.feature).toLowerCase().includes(query)).slice(0,80);modal('选择脚本资产',lpSelect('inventoryId','匹配结果',rows.map(c=>[c.assetId,c.product+' / '+c.title+' · '+c.admission])),'核对关联',g=>{const id=g.get('inventoryId'),row=rows.find(x=>x.assetId===id);if(!row)return false;if(asset)lpVersionReview('bind',{id:asset.id,expectedRevision:asset.revision,scriptAssetId:id},asset,{title:lpContent(asset).title,script:row});else{const old=lpList('assets').find(a=>lpContent(a).source?.inventoryId===id);lpVersionReview('import-ui',{assetId:id,...(old?{expectedRevision:old.revision}:{})},old,row)}return false});return false})}
function lpPublish(){const t=task(),d=caseState(t).draft;if(!caseAccepted(t))return toast('请先确认用例集');return modal('发布设计用例',lpSelect('caseId','本次用例',d.cases.map(c=>[c.id,c.id+' '+c.title]))+lpSelect('target','发布方式',[['','新增正式用例'],...lpList('assets').map(a=>[a.id,'更新：'+lpContent(a).title+' · v'+a.revision])])+lpSelect('product','产品',abProducts.map(x=>[x,x]),t.product)+lpInput('subproduct','子产品',t.feature||'')+lpInput('feature','特性',t.feature||''),'对比并发布',f=>{const fields=Object.fromEntries(f),old=lpList('assets').find(a=>a.id===fields.target),candidate=d.cases.find(c=>c.id===fields.caseId);const raw={taskId:t.id,...fields,...(old?{id:old.id,expectedRevision:old.revision}:{})};lpVersionReview('publish',raw,old,{...candidate,product:fields.product,subproduct:fields.subproduct,feature:fields.feature});return false})}

async function lpModelLoad(){try{const t=task();t.designModel=await workspaceRequest('/api/automation/model/'+t.id);save();render()}catch(e){toast(e.message)}}
function lpModelPanel(){const t=task(),m=t.designModel;return `<section class="card pad"><div class="row"><div><h2>场景与测试点</h2><p class="subtitle">根据已确认方案逐需求建立场景，再细化测试点。确认后用于用例生成及覆盖校验。</p></div>${btn(m?'刷新方案基线':'载入方案场景','lpModelLoad','small')}</div>${m?`<p>${m.confirmed?'已确认':'待审阅'} · ${m.scenarios.length} 个场景 · ${m.scenarios.reduce((n,s)=>n+s.points.length,0)} 个测试点</p><div class="da-review-list">${m.scenarios.map((s,i)=>`<article class="da-point"><div class="row"><h3>${esc(s.id)} · ${esc(s.title)}</h3>${btn('编辑场景','lpScene:'+i,'small')}</div><p>需求 ${esc(s.requirementIds.join('、'))}</p>${s.points.map((p,j)=>`<p>${esc(p.id)} · ${esc(p.title)} ${btn('编辑','lpPoint:'+i+':'+j,'link small')}</p>`).join('')}${btn('新增测试点','lpPoint:'+i+':new','small')}</article>`).join('')}</div><div class="actions">${btn('新增场景','lpScene:new','small')}${btn('保存草稿','lpModelSave:draft','small')}${btn('确认场景与测试点','lpModelSave:confirm','primary small')}</div>`:'<p>先载入方案中的需求覆盖安排，再核对场景和测试点。</p>'}</section>`}
const lpCasesOld=cases;
cases=function(){return (journey==='design'&&planConfirmed(task())?lpModelPanel():'')+lpCasesOld()+(journey==='design'&&caseAccepted(task())?`<section class="card pad"><h2>交付正式资产</h2><p>选择新增或更新已有用例，核对差异后发布。更新设计版本会清除旧脚本关联，需重新核对并关联。</p>${btn('发布到正式用例库','lpPublish','primary')}</section>`:'')};
const lpCaseGenerate=caseGenerate;
caseGenerate=async function(){if(!task().designModel?.confirmed)return toast('请先载入并确认场景与测试点');return lpCaseGenerate()};
function lpReportText(r){return `# ${r.name} · 本轮质量报告\n\n产品：${r.product}\n构建：${r.build}\n环境：${r.environment}\n套件版本：${r.snapshot.suite.revision}\n执行契约：${r.snapshot.contract}\n运行：${r.id}\n结果：${lpStatus[r.status]}\n选中 ${r.total} / 已执行 ${r.executed}\n\n${Object.entries(r.counts).map(([k,v])=>lpStatus[k]+'：'+v).join('\n')}\n\n## 遗留问题与未测范围\n${r.results.filter(x=>x.status!=='passed').map(x=>{const s=lpFailureSummary(x);return x.title+'：'+lpStatus[x.status]+' · 耗时 '+lpDuration(x.durationSeconds)+' · '+s.title+'\n'+s.cause+'\n建议：'+s.action+'\n\n原始异常：\n'+x.message}).join('\n\n')||'本轮范围内无未通过项；不代表范围外无风险。'}\n\n${r.report?.releaseDecision||'运行尚未完成，不能得出最终结论。'}`}
const lpReportsOld=reports;
reports=function(){return `<section class="card pad"><h2>自动化质量报告</h2><p>每份报告固定产品、构建、环境、套件版本及真实运行证据；资产数量不代表产品质量。</p>${lpList('runs').filter(r=>r.finishedAt).slice().reverse().map(r=>`<div class="list-item row"><div><b>${esc(r.name)}</b><p>${esc(r.product)} · ${esc(r.build)} · ${esc(r.environment)} · ${esc(lpStatus[r.status])}</p></div>${btn('查看报告','lpReport:'+r.id,'small')}</div>`).join('')||'<p>暂无真实自动化报告。</p>'}</section>`+lpReportsOld()};

const lpActOld=act;
act=function(action){const [name,arg,sub]=action.split(':');
 if(name==='editProductEnv')return editProductEnvironment();
 if(name==='generateScript')return openScriptDesign(arg);
 if(action==='scenario:automation'||name==='autoTask'){page='assets';abTab='published';render();toast('选择正式 API 或 UI 用例，点击「设计并生成脚本」');return}if(name==='laProduct'){laProduct=decodeURIComponent(arg);laSubproduct='';laPage=0;render();return}if(name==='laLayer'){laLayer=arg;laSubproduct='';laPage=0;render();return}if(name==='laPage'){laPage=Math.max(0,laPage+(arg==='next'?1:-1));render();return}if(name==='laReset'){laQuery='';laSubproduct='';laPage=0;render();return}if(name==='lpTab'){lpTab=arg;render();return}if(name==='lpRefresh'){lpEnvs=null;return lpLoad()}
 if(name==='lpType'){lpType=arg;lpPage=0;render();return}if(name==='lpPage'){lpPage=Math.max(0,lpPage+(arg==='next'?1:-1));render();return}
 if(name==='lpAssets'){page='assets';abTab='published';render();return}
 if(name==='lpSuiteNew')return lpSuiteDialog();if(name==='lpSuiteEdit')return lpSuiteDialog(arg);
 if(name==='lpPlanNew')return lpPlanDialog();if(name==='lpPlanEdit')return lpPlanDialog(arg);
 if(name==='lpStart')return lpStartDialog(arg);if(name==='lpPlanStart')return lpStartDialog(null,arg);
 if(name==='lpRetry')return lpStartDialog(null,null,arg);
 if(name==='lpPlanToggle'){const p=lpList('plans').find(x=>x.id===arg);return lpWrite('plan',{...lpContent(p),id:p.id,expectedRevision:p.revision,enabled:!lpContent(p).enabled})}
 if(name==='lpCI')return modal('CI / 任务计划执行入口',`<p>在已启动工作台的同一电脑调用。任务计划可设置每天时间，CI 自动读取 BUILD_ID、BUILD_NUMBER、CI_PIPELINE_ID 或 GITHUB_RUN_ID；未提供时生成执行标识，不代表实际产品版本。</p><pre class="spec-preview">python -m workbench.run_plan --plan ${esc(arg)} --wait</pre><p>成功仅代表本轮所选用例通过；执行记录和证据保存在工作台。</p>`,'关闭',()=>{});
 if(name==='lpGroup')return lpShowGroup(arg,sub);
 if(name==='lpRun')return workspaceRequest('/api/automation/runs/'+arg).then(lpPrepareScreenshots).then(r=>{lpSelectedRun=arg;lpRun=r;lpTab='runs';render()}).catch(e=>toast(e.message));
 if(name==='lpScreenshot')return lpOpenScreenshot(decodeURIComponent(arg));
 if(name==='lpLogin'){if(sub==='clear')return modal('清除本机登录态','<p>后续执行需要重新扫码。不会退出服务端账号，也不会修改正在执行的浏览器会话。</p>','清除',()=>{lpLoginAction(arg,sub);return false});return lpLoginAction(arg,sub)}
 if(name==='lpPause')return lpWrite('control',{id:arg,action:'pause'});
 if(name==='lpResume')return lpWrite('control',{id:arg,action:'resume'});
 if(name==='lpCancel')return modal('停止本次运行', '<p>停止后保留已完成的用例结果及证据，未完成用例标记为中断或未执行。</p>', '停止运行',()=>{lpWrite('cancel',{id:arg});return false});
 if(name==='lpDeleteRun'){
  const r=lpList('runs').find(r=>r.id===arg);if(!r)return;
  const active=['preparing','running','pausing','paused','cancelling'].includes(r.status);
  return modal(active?'停止并删除运行':'删除运行记录',`<p><b>${esc(r.name)}</b></p><p>${active?'将先停止执行，再删除':'将删除'}本次运行记录、报告及截图等证据，无法恢复。测试套件、正式用例和登录配置保留。</p>`,active?'停止并删除':'确认删除',()=>{lpWrite('delete-run',{id:arg});return false});
 }
 if(name==='lpReport')return workspaceRequest('/api/automation/runs/'+arg).then(r=>{lpRun=r;modal('本轮质量报告',`<pre class="spec-preview">${esc(lpReportText(r))}</pre>${btn('导出 Markdown','lpExport','small')}`,'关闭',()=>{})}).catch(e=>toast(e.message));
 if(name==='lpExport')return download(lpRun.id+'-report.md',lpReportText(lpRun),'text/markdown');
 if(name==='lpVersions'){const x=lpList(arg).find(x=>x.id===sub);return modal('版本记录',x.versions.slice().reverse().map(v=>`<details><summary>v${v.revision} · ${exTime(v.at)}</summary><pre class="spec-preview">${esc(JSON.stringify(v.content,null,2))}</pre></details>`).join(''),'关闭',()=>{})}
 if(name==='lpExportAssets')return lpExportAssets();if(name==='lpImportAssets')return lpImportAssets();if(name==='lpImport')return liOpen();if(name==='lpBind')return lpChooseScript(arg);if(name==='lpPublish')return lpPublish();
 if(name==='lpModelLoad')return lpModelLoad();
 if(name==='lpModelSave'){const t=task(),m=t.designModel;return lpWrite('model',{...m,expectedRevision:m.revision,confirmed:arg==='confirm'}).then(r=>{if(r){t.designModel=r;save();render()}})}
 if(name==='lpScene'){const m=task().designModel,old=arg==='new'?null:m.scenarios[Number(arg)];return modal('编辑业务场景',lpInput('title','场景名称',old?.title||'')+lpInput('requirements','需求 ID（逗号分隔）',old?.requirementIds.join(',')||''),'保存',f=>{const row=old||{id:'S'+crypto.randomUUID().slice(0,8),points:[{id:'P1',title:'请细化测试点',method:'请填写验证方法'}]};row.title=f.get('title');row.requirementIds=f.get('requirements').split(/[,，]/).map(x=>x.trim()).filter(Boolean);if(!old)m.scenarios.push(row);m.confirmed=false;save();render()})}
 if(name==='lpPoint'){const m=task().designModel,s=m.scenarios[Number(arg)],old=sub==='new'?null:s.points[Number(sub)];return modal('编辑测试点',lpInput('title','测试点',old?.title||'')+lpInput('method','验证方法 / 因子与边界',old?.method||''),'保存',f=>{const row=old||{id:'P'+crypto.randomUUID().slice(0,8)};Object.assign(row,Object.fromEntries(f));if(!old)s.points.push(row);m.confirmed=false;save();render()})}
 return lpActOld(action)
};
const lpRenderOld=render;
render=function(){
 const previous=$('[data-run-results]');
 const top=previous?.scrollTop,left=previous?.scrollLeft;
 lpRememberDetails();
 lpRenderOld();
 const current=$('[data-run-results]');
 if(current&&previous&&current.dataset.runResults===previous.dataset.runResults){
  current.scrollTop=top;
  current.scrollLeft=left;
 }
 if(['automation','assets','reports'].includes(page)&&!lpData&&!lpBusy&&!lpError)setTimeout(lpLoad,0);if(page==='task'&&(tab==='cases'||journey==='automation')&&!lpData&&!lpBusy&&!lpError)setTimeout(lpLoad,0);if($('#lpQuery'))$('#lpQuery').onchange=e=>{lpQuery=e.target.value;lpPage=0;render()};if($('#laQuery'))$('#laQuery').onchange=e=>{laQuery=e.target.value;laPage=0;render()};if($('#laSubproduct'))$('#laSubproduct').onchange=e=>{laSubproduct=e.target.value;laPage=0;render()};if($('#laSize'))$('#laSize').onchange=e=>{laSize=Number(e.target.value);laPage=0;render()};const header=$('header .demo');if(header)header.textContent='本地测试工作台 · UI 真实执行需运行前检查'};
setInterval(()=>{if(!lpBusy&&(lpData?.runs.some(r=>['preparing','running','pausing','paused','cancelling'].includes(r.status))||lpEnvs?.environments?.some(e=>e.authOperation?.status==='running'))){if(lpEnvs?.environments?.some(e=>e.authOperation?.status==='running'))lpEnvs=null;lpLoad(Boolean(lpEnvs))}},2000);

// Admission is separate from linking an existing formal case to a UI script.
let liProduct='',liSubproduct=null,liLayer='UI',liQuery='',liPage=0,liSelected=new Set(),liCandidates=[],liLoading=false;
function liBuildCandidates(){const formal=lpList('assets').map(lpContent),inventoryIds=new Set(formal.flatMap(c=>[c.source?.inventoryId,c.binding?.inventoryId].filter(Boolean))),designIds=new Set(formal.filter(c=>c.source?.taskId&&c.source?.caseId).map(c=>c.source.taskId+'|'+c.source.caseId));const rows=[];
 for(const c of abInventory?.cases||[]){if(inventoryIds.has(c.assetId))continue;rows.push({key:'ui|'+c.assetId,kind:'inventory',layer:c.layer||'UI',product:c.product,subproduct:c.feature.split('/')[0],feature:c.feature,title:c.title,id:c.id,inventoryId:c.assetId,ready:c.admission==='静态可执行',state:c.admission,reason:c.reason||'',spec:c})}
 for(const t of data.tasks||[]){if(taskLC(t).location==='trash'||!caseAccepted(t))continue;for(const c of caseState(t).draft?.cases||[]){if(!['UI','API','性能','安全'].includes(c.layer)||designIds.has(t.id+'|'+c.id))continue;rows.push({key:'design|'+t.id+'|'+c.id,kind:'design',layer:c.layer,product:t.product||'',subproduct:t.subproduct||'',feature:t.feature||'',title:c.title,id:c.id,taskId:t.id,ready:true,state:'设计已确认',reason:'来自测试任务：'+t.name+'；纳入后可继续关联脚本',spec:c})}}
 return rows;
}
async function liOpen(){if(liLoading)return;liLoading=true;try{await flushWorkspace();const [state,inventory]=await Promise.all([lpReadIndex('summary'),workspaceRequest('/api/assets')]);lpData=state;abInventory=inventory;liCandidates=liBuildCandidates();liProduct=laProduct;liLayer=laLayer||'UI';liSubproduct=laSubproduct||null;liQuery='';liPage=0;liSelected.clear();liDialog()}catch(e){toast(e.message)}finally{liLoading=false}}
function liProductRows(){
 return liCandidates.filter(c=>c.layer===liLayer&&(!liProduct||c.product===liProduct));
}
function liRows(scope){
 const query=liQuery.trim().toLowerCase();
 return scope.filter(c=>(liSubproduct===null||c.subproduct===liSubproduct)&&
  (!query||[c.title,c.id,c.feature].join(' ').toLowerCase().includes(query)));
}
function liProducts(){
 return [...new Set([...abProducts,...liCandidates.map(c=>c.product),laProduct].filter(Boolean))];
}
function liDialog(){
 const scope=liProductRows();
 const subproducts=[...new Set(scope.map(c=>c.subproduct))].sort();
 const subOptions=subproducts.map(sub=>`<option value="sub:${esc(sub)}" ${sub===liSubproduct?'selected':''}>${esc(abSubproductLabel(sub)||'未分类')}</option>`);
 if(liSubproduct!==null&&!subproducts.includes(liSubproduct))liSubproduct=null;
 const rows=liRows(scope);liPage=Math.min(liPage,Math.max(0,Math.ceil(rows.length/20)-1));const visible=rows.slice(liPage*20,(liPage+1)*20);modal('纳入用例',`<p>只展示尚未纳入正式库的用例；已纳入或已关联的来源自动排除。</p><div class="form-grid"><label>产品<select id="liProduct"><option value="">全部产品</option>${liProducts().map(p=>`<option ${p===liProduct?'selected':''}>${esc(p)}</option>`).join('')}</select></label><label>子产品<select id="liSubproduct"><option value="">全部子产品</option>${subOptions.join('')}</select></label><label>自动化类型<select id="liLayer">${laTypes.filter(([id])=>id).map(([id,name])=>`<option value="${id}" ${id===liLayer?'selected':''}>${name}</option>`).join('')}</select></label></div><label>搜索未纳入用例<input id="liQuery" placeholder="名称、编号或特性 · 回车搜索" value="${esc(liQuery)}"></label><p class="subtitle">${rows.length} 条未纳入 · ${rows.filter(c=>c.ready).length} 条可纳入。扫描来源须脚本就绪；设计来源须用例集已确认。</p><label class="inline-check"><input type="checkbox" class="check" id="liAll">全选筛选结果（含所有页）</label><p id="liCount" aria-live="polite"></p><div class="li-candidates">${visible.map(c=>`<label class="li-candidate"><input type="checkbox" name="candidate" value="${esc(c.key)}" ${liSelected.has(c.key)?'checked':''} ${c.ready?'':'disabled'}><span><strong>${esc(c.title)}</strong><small>${esc(c.product||'未指定产品')} · ${esc(c.feature||'未指定特性')} · ${esc(c.kind==='inventory'?'扫描资产':'已确认设计')}</small><small>${esc(c.state)} · ${esc(c.reason)}</small></span></label>`).join('')||`<div class="empty">当前范围没有未纳入的${esc(laTypes.find(([id])=>id===liLayer)?.[1]||'')}用例。${['UI','API'].includes(liLayer)?'已纳入的用例不会重复出现。':'当前可从已确认测试设计纳入；此类型脚本扫描来源尚未接入。'}</div>`}</div><div class="la-pager"><button type="button" id="liPrev" ${liPage===0?'disabled':''}>上一页</button><span>${liPage+1} / ${Math.max(1,Math.ceil(rows.length/20))}</span><button type="button" id="liNext" ${(liPage+1)*20>=rows.length?'disabled':''}>下一页</button></div><p class="subtitle">未就绪项请先在来源修复并刷新资产；这里不会将 UI 用例改标为接口、性能或安全。</p>`,'核对并纳入',()=>{const selected=rows.filter(c=>c.ready&&liSelected.has(c.key));
  if(selected.length===1)liReview(selected[0]);
  if(selected.length>1)liBatchReview(selected);
  return false;
 });
 const eligible=rows.filter(c=>c.ready);
 const all=$('#liAll');
 function sync(){
  const count=liSelected.size;
  all.disabled=!eligible.length;
  all.checked=count>0&&count===eligible.length;
  all.indeterminate=count>0&&!all.checked;
  $('#liCount').textContent='已选 '+count+' 条';
  $('#modalSubmit').disabled=!count;
 }
 all.onchange=()=>{
  liSelected=new Set(all.checked?eligible.map(c=>c.key):[]);
  liDialog();
 };
 function refilter(){liPage=0;liSelected.clear();liDialog()}
 $('#liProduct').onchange=e=>{liProduct=e.target.value;liSubproduct=null;refilter()};
 $('#liSubproduct').onchange=e=>{liSubproduct=e.target.value?e.target.value.slice(4):null;refilter()};
 $('#liLayer').onchange=e=>{liLayer=e.target.value;liSubproduct=null;refilter()};
 $('#liQuery').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();liQuery=e.target.value;refilter()}};
 $('#liPrev').onclick=()=>{liPage--;liDialog()};
 $('#liNext').onclick=()=>{liPage++;liDialog()};
 document.querySelectorAll('[name="candidate"]').forEach(el=>el.onchange=()=>{
  if(el.checked)liSelected.add(el.value);else liSelected.delete(el.value);
  sync();
 });
 sync();
}
function liBatchReview(selected){
 const groups=new Map();
 const totals=new Map();
 for(const c of selected){
  const product=c.product||'未指定产品';
  totals.set(product,(totals.get(product)||0)+1);
  if(c.kind==='design'&&!groups.has(c.taskId))groups.set(c.taskId,{c,index:groups.size});
 }
 const fields=Array.from(groups.values(),({c,index})=>
  '<fieldset><legend>'+esc(c.reason)+'</legend>'+
  lpSelect('product'+index,'产品',abProducts.map(p=>[p,p]),c.product)+
  lpInput('subproduct'+index,'子产品',c.subproduct)+lpInput('feature'+index,'特性',c.feature)+'</fieldset>').join('');
 const overview=Array.from(totals,([p,n])=>esc(p)+' · '+n+' 条').join('，');
 modal('确认纳入正式用例库','<p>已选 '+selected.length+' 条 · '+overview+'</p>'+fields+
  '<details><summary>查看所选用例</summary><ul class="li-candidates">'+selected.map(c=>'<li>'+esc(c.id)+' · '+esc(c.title)+'</li>').join('')+'</ul></details><p id="liBatchStatus" role="status"></p>',
  '确认纳入',f=>{
   if(liLoading)return false;
   const items=selected.map(c=>{
    if(c.kind==='inventory')return {assetId:c.inventoryId};
    const i=groups.get(c.taskId).index;
    return {taskId:c.taskId,caseId:c.id,product:f.get('product'+i),subproduct:f.get('subproduct'+i),feature:f.get('feature'+i)};
   });
   liBatchSubmit(items);
   return false;
  });
}
function liLegacyReview(items){
 modal('确认逐条纳入',`<p>当前后台会逐条保存所选的 ${items.length} 条用例。遇到失败时停止，已保存的用例会保留。</p><p id="liLegacyStatus" role="status"></p>`,
  '开始逐条纳入',()=>{if(!liLoading)liLegacySubmit(items);return false});
}
async function liLegacySubmit(items){
 if(liLoading)return;
 liLoading=true;
 const status=$('#liLegacyStatus'),submit=$('#modalSubmit');
 submit.disabled=true;
 let saved=0,skipped=0;
 const report=()=>`共 ${items.length} 条，已保存 ${saved} 条，已有 ${skipped} 条`;
 async function write(){
  lpData=await workspaceRequest('/api/automation');
  const available=new Set(liBuildCandidates().filter(c=>c.ready).map(c=>c.key));
  for(const item of items){
   if(!status.isConnected||$('#overlay').classList.contains('hidden'))break;
   const inventory=Object.hasOwn(item,'assetId');
   const key=inventory?'ui|'+item.assetId:'design|'+item.taskId+'|'+item.caseId;
   if(!available.has(key)){
    const exists=lpList('assets').some(a=>{
     const c=lpContent(a);
     return inventory?(c.source?.inventoryId===item.assetId||c.binding?.inventoryId===item.assetId):
      (c.source?.taskId===item.taskId&&c.source?.caseId===item.caseId);
    });
    if(!exists)throw Error('用例已不满足纳入条件');
    skipped++;
   }else{
    await workspaceRequest('/api/automation/'+(inventory?'import-ui':'publish'),item,60000);
    saved++;
   }
   status.textContent=report();
  }
 }
 try{
  status.textContent='正在读取正式用例库…';
  await navigator.locks.request('workbench-case-intake',write);
  if(status.isConnected)closeModal();
  toast(report());
 }catch(e){
  const message=report()+'。逐条纳入已停止：'+e.message+'。请重新打开纳入列表核对剩余用例。';
  status.textContent=message;
  toast(message);
 }finally{
  liLoading=false;
  await lpLoad();
 }
}
async function liBatchSubmit(items){
 liLoading=true;
 const submit=$('#modalSubmit'),status=$('#liBatchStatus');
 submit.disabled=true;
 status.textContent='正在校验并纳入 '+items.length+' 条用例…';
 try{
  await flushWorkspace();
  const result=await workspaceRequest('/api/automation/intake',{items},300000);
  if(status.isConnected)closeModal();
  await lpLoad();
  toast('已纳入 '+result.count+' 条正式用例');
 }catch(e){
  if(e.status===404&&e.path==='/api/automation/intake'){
   if(status.isConnected&&!$('#overlay').classList.contains('hidden'))liLegacyReview(items);
  }else status.textContent=e.message;
 }finally{liLoading=false;if(status.isConnected)submit.disabled=false}
}
function liReview(c){if(c.kind==='inventory')return modal('确认纳入正式用例库',`<p>${esc(c.product)} · ${esc(c.layer)} 自动化 · ${esc(c.feature)}</p><pre class="spec-preview">${esc(JSON.stringify(c.spec,null,2))}</pre><p>新建正式版本并固定规格与脚本关联；不会启动执行。</p>`,'确认纳入',()=>{liSubmit(c,{assetId:c.inventoryId});return false});
 return modal('确认纳入正式用例库',`<h3>${esc(c.title)}</h3><p>类型：${esc(c.layer)} · 已确认设计</p>`+lpSelect('product','产品',abProducts.map(p=>[p,p]),c.product||liProduct)+lpInput('subproduct','子产品',c.subproduct)+lpInput('feature','特性',c.feature)+`<pre class="spec-preview">${esc(JSON.stringify(c.spec,null,2))}</pre><p>创建正式用例版本，保留设计来源；未关联脚本不代表可执行。</p>`,'确认纳入',f=>{liSubmit(c,{taskId:c.taskId,caseId:c.id,...Object.fromEntries(f)});return false});
}
async function liSubmit(c,raw){if(liLoading)return;liLoading=true;try{lpData=await workspaceRequest('/api/automation');const remaining=liBuildCandidates();if(!remaining.some(x=>x.key===c.key&&x.ready))throw Error('该用例已纳入或不再满足条件，请重新打开纳入列表');const result=await lpWrite(c.kind==='inventory'?'import-ui':'publish',raw);if(result)toast('已纳入正式用例库')}catch(e){toast(e.message)}finally{liLoading=false}}

// Account configuration prototype: metadata lives in this page only; passwords are never retained.
const accountDemoRows=[];
function accountRunHint(){const selected=$('#runLoginAccount').value;$('#runAccountHint').textContent=selected?'演示：工作台提供账号凭据，登录、验证码及登录态由 UI 自动化系统处理。当前不会发起真实执行。':'先以无头浏览器验证本机加密登录态；有效时自动复用，有头模式失效时等待扫码并保存，无头模式失效时明确阻塞。';$('#modalSubmit').textContent=selected?'预览账号执行':'开始真实执行'}
function accountList(){return `<div class="account-demo-list">${accountDemoRows.map(a=>`<article><div><b>${esc(a.name)}</b> ${badge(a.kind==='personal'?'个人账号':'公共账号')}<p class="subtitle">${esc(a.username)} · ${a.hasPassword?'已填写演示密码（未保存）':'未填写密码'}</p><p class="subtitle">适用环境：${esc(a.environments.join('、')||'暂未关联')}</p></div><div class="actions"><button type="button" class="link small" data-action="accountEdit:${esc(a.id)}">编辑</button><button type="button" class="link small" data-action="accountRemove:${esc(a.id)}">移除</button></div></article>`).join('')||'<div class="empty">暂无账号，添加后可关联多个环境。</div>'}</div>`}
function accountPage(){return `<section class="card pad"><div class="row"><div><h2>统一账号管理</h2><p class="subtitle">个人与公共账号只配置一次，各环境勾选使用，登录由 UI 自动化系统处理。</p></div>${btn('添加账号','accountAdd','primary small')}</div><p class="notice info">Demo：配置仅在当前页面保留，刷新清空；请勿输入真实密码，密码不会保存或发送。</p>${accountList()}</section>`}
function accountManage(){modal('统一账号管理',accountPage(),'完成',()=>{})}
function accountEdit(id){const old=accountDemoRows.find(a=>a.id===id);modal(old?'编辑登录账号':'添加登录账号',`<p class="notice info">仅演示配置流程，请使用测试占位值，密码不会保存或发送。</p>`+lpInput('name','账号名称',old?.name||'')+lpSelect('kind','账号类型',[['personal','个人账号'],['shared','公共账号']],old?.kind||'personal')+lpInput('username','登录账号',old?.username||'')+`<label>密码（演示，不保存）<input type="password" name="password" autocomplete="new-password" maxlength="300" placeholder="填写演示密码"></label><h3>适用环境（可多选）</h3><div class="account-environment-options">${(lpEnvs?.environments||[]).map(e=>`<label class="inline-check"><input class="check" type="checkbox" name="environments" value="${esc(e.id)}" ${old?.environments.includes(e.id)?'checked':''}>${esc(e.id)} · ${esc(e.product)}</label>`).join('')}</div><p class="subtitle">也可暂不选择，之后在执行环境中勾选此账号。</p>`,'保存演示配置',f=>{const row={id:old?.id||'demo-account-'+Date.now(),environments:f.getAll('environments'),name:f.get('name').trim(),username:f.get('username').trim(),kind:f.get('kind'),hasPassword:Boolean(f.get('password'))||Boolean(old?.hasPassword)};if(!row.name||!row.username)return false;if(old)Object.assign(old,row);else accountDemoRows.push(row);$('#modalForm [name="password"]').value='';if(page==='automation')render();toast('演示账号已保存');});}
function accountBind(environment){modal('选择适用账号 · '+environment,`<p class="subtitle">从统一账号库勾选此环境可使用的账号。取消勾选不会删除账号，也不影响其他环境。</p><div class="account-demo-list">${accountDemoRows.map(a=>`<label class="inline-check"><input type="checkbox" class="check" name="accounts" value="${esc(a.id)}" ${a.environments.includes(environment)?'checked':''}><span>${esc(a.name)} · ${a.kind==='personal'?'个人':'公共'}<small> · ${esc(a.username)}</small></span></label>`).join('')||'<div class="empty">暂无账号，请先到“登录账号”页签添加。</div>'}</div>`,'保存关联',f=>{const ids=f.getAll('accounts');for(const a of accountDemoRows){a.environments=a.environments.filter(e=>e!==environment);if(ids.includes(a.id))a.environments.push(environment)}if(page==='automation')render();toast('环境账号关联已更新');})}
const accountDemoAct=act;
act=function(action){const [name,id]=action.split(':');if(name==='accountManage')return accountManage();if(name==='accountAdd')return accountEdit();if(name==='accountEdit')return accountEdit(id);if(name==='accountBind')return accountBind(id);if(name==='accountRemove'){const i=accountDemoRows.findIndex(a=>a.id===id);if(i>=0){accountDemoRows.splice(i,1);if(page==='automation')render()}return}return accountDemoAct(action)};
function openScriptDesign(id, draft) {
  const asset = lpList('assets').find(item => item.id === id);
  if (!asset) return toast('请刷新后选择正式用例');
  const content = lpContent(asset);
  const api = content.layer === 'API';
  const design = draft || content.scriptDesign || {};
  const area = (key, label, value) => `<label>${label}<textarea name="${key}" rows="4">${esc(value)}</textarea></label>`;
  const json = value => JSON.stringify(value, null, 2);
  const fields = api
    ? lpSelect('method','HTTP 方法',['GET','POST','PUT','PATCH','DELETE'].map(x=>[x,x]),design.method||'GET')
      + lpInput('status','预期 HTTP 状态码',String(design.status||200))
      + area('body','请求 JSON（无请求体可留空）',design.body == null ? '' : json(design.body))
      + area('expected','预期响应字段（JSON 对象）',json(design.expected||{}))
    : area('steps','按顺序操作（JSON 数组）',json(design.steps||[]))
      + '<small>例如 [{"action":"fill","testId":"name","value":"合成记录"},{"action":"click","testId":"save"}]</small>'
      + area('testId','断言元素的 test ID（留空则检查页面标题）',design.testId||'')
      + area('status','预期主文档状态码（留空为 2xx）',design.status ?? '')
      + lpInput('text','预期文本或页面标题',design.text||'');
  modal('设计 ' + content.layer + ' 自动化脚本',
    `<h3>${esc(content.title)} · v${asset.revision}</h3><details><summary>查看用例步骤与预期</summary><pre>${esc(json(content.spec))}</pre></details>`
    + lpInput('path',api?'接口相对路径':'页面相对路径',design.path||'/') + fields,
    '生成代码预览', form => {
      let input;
      try {
        input = api ? {method:form.get('method'),path:form.get('path'),status:Number(form.get('status')),
          body:JSON.parse(form.get('body')||'null'),expected:JSON.parse(form.get('expected')||'{}')}
          : {path:form.get('path'),status:form.get('status').trim() ? Number(form.get('status')) : null,steps:JSON.parse(form.get('steps')||'[]'),testId:form.get('testId').trim(),text:form.get('text')};
      } catch { toast('请检查表单中的 JSON 格式'); return false; }
      if (!api && input.status !== null && (!Number.isInteger(input.status) || input.status<100 || input.status>599)) {toast('状态码须为 100 到 599 的整数');return false;}
      const request = {id,expectedRevision:asset.revision,design:input};
      workspaceRequest('/api/automation/generate',request).then(preview => {
        modal('审阅 pytest 脚本',
          `<p>${esc(content.title)} · ${esc(content.layer)}</p><pre class="spec-preview">${esc(preview.code)}</pre><button type="button" id="editScriptDesign">返回修改</button>`,
          '发布并绑定到用例', () => {
            const button = document.querySelector('#modalSubmit');
            button.disabled = true;
            workspaceRequest('/api/automation/generate',{...request,publish:true,digest:preview.digest}).then(saved => {
              closeModal(); lpLoad(); toast('脚本已绑定到 v'+saved.revision+'，可在自动化执行中新建或更新套件');
            }).catch(e=>{button.disabled=false;toast(e.message)});
            return false;
          });
        document.querySelector('#editScriptDesign').onclick=()=>openScriptDesign(id,input);
      }).catch(e=>toast(e.message));
      return false;
    });
}

function editProductEnvironment() {
  workspaceRequest('/api/automation/environment-config',{}).then(current=>{
    const labels = {environment:'环境名称',api_base_url:'API 基础地址',health_path:'健康检查路径',
                    base_url:'UI 基础地址',expected_title:'首页冒烟预期标题'};
    const fields = Object.entries(labels).map(([key,label])=>
      `<label>${label}<input name="${key}" value="${esc(current[key])}"></label>`).join('');
    modal('配置测试环境','<p>填写 API 或 UI 对应的一组字段。</p>'+fields,'保存环境',form=>{
      workspaceRequest('/api/automation/environment-config',{save:true,fields:Object.fromEntries(form)})
        .then(()=>{closeModal();lpEnvs=null;lpLoad();toast('测试环境已保存')}).catch(e=>toast(e.message));
      return false;
    });
  }).catch(e=>toast(e.message));
}

function taskScriptPanel(t) {
  const assets = lpList('assets').filter(a => {
    const c = lpContent(a);
    return c.source?.taskId === t.id && ['API','UI'].includes(c.layer);
  });
  const rows = assets.map(a => {
    const c = lpContent(a);
    return `<div class="list-item row"><span>${esc(c.title)} · ${esc(c.layer)} · v${a.revision}</span>${btn('设计并生成脚本','generateScript:'+a.id,'small')}</div>`;
  }).join('');
  const next = caseAccepted(t) ? btn('发布设计用例','lpPublish','small') : btn('进入测试设计','direct:design:'+t.id,'small');
  return `<section class="card pad"><h2>当前任务的自动化用例</h2>${rows || '<p>确认并发布本任务的 API 或 UI 用例后，即可设计脚本。</p>'}<div class="actions">${next}${btn('打开正式用例库','autoTask:'+t.id,'small')}</div></section>`;
}
