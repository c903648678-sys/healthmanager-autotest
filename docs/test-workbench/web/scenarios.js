// Scenario navigation shares the existing task and asset records; no data reset.
const journeys = {
  design: {name:'测试设计',icon:'✎',desc:'从新需求开始，形成测试方案与用例。',steps:['requirements','plan','cases'],output:'已审阅用例与待确认问题',hint:'只做设计也可以结束，不必立即执行。'},
  manual: {name:'手工执行',icon:'☑',desc:'已有用例，直接操作并记录测试结果。',steps:['execution','summary'],output:'手工结果、证据与执行汇总',hint:'选择用例，录入实际结果；失败或阻塞时记录问题。'},
  automation: {name:'实现自动化',icon:'⌘',desc:'将已确认用例转为可验证的候选脚本。',steps:['execution'],output:'生成并绑定本任务的测试脚本',hint:'选择已发布用例，设计并审阅脚本。'},
  regression: {name:'自动化回归',icon:'▷',desc:'选择已有自动化，运行本机或 CI 回归。',steps:['execution','summary'],output:'模拟运行记录与汇总',hint:'只运行已确认、已验证的示例；在自动化执行页面运行已确认套件。'},
  issues: {name:'处理问题',icon:'⚑',desc:'确认原因、记录处理，再安排回归。',steps:['issues','execution','summary'],output:'问题处理与回归记录',hint:'可以保留未解决问题，不强制关闭，也不改写历史结果。'},
  change: {name:'需求变更',icon:'↻',desc:'查看变更影响，复核相关用例与实现。',steps:['changes','cases','execution','summary'],output:'变更记录、待复核资产与回归结果',hint:'明确选择受影响用例。接受变更后，相关用例必须重新确认。'},
  summary: {name:'测试总结',icon:'▤',desc:'汇总执行情况，说明未测范围与风险。',steps:['summary'],output:'测试总结与导出报告',hint:'无需重走设计和执行流程；总结不代表发布批准。'}
};
let journey='design';
tabs.changes='需求变更';
const stepName = key => key==='execution' ? ({manual:'记录手工结果',automation:'实现与验证',regression:'执行回归',issues:'回归验证',change:'变更后验证'}[journey]||'执行') : tabs[key];

function home(){
  const all=data.tasks.flatMap(t=>t.cases);
  return title('今天，你要完成什么测试工作？','选择一个场景开始，已有任务和历史记录随时可以继续。')+
    `<div class="scenario-grid">${['design','manual'].map(k=>`<button class="scenario-card featured" data-action="scenario:${k}"><span class="scenario-icon">${journeys[k].icon}</span><h2>${journeys[k].name}</h2><p>${journeys[k].desc}</p><span class="scenario-cta">开始 →</span></button>`).join('')}</div>`+
    `<div class="secondary-scenes">${['automation','issues','change','summary'].map(k=>`<button class="scene-mini" data-action="scenario:${k}"><span>${journeys[k].icon}</span><div><b>${journeys[k].name}</b><small>${journeys[k].desc}</small></div><span>→</span></button>`).join('')}</div>`+
    stats([['进行中的任务',data.tasks.filter(t=>t.stage!=='已完成').length,'个'],['用例待审阅',all.filter(c=>!c.confirmed).length,'条'],['待处理问题',data.tasks.flatMap(t=>t.issues).filter(i=>i.status!=='已关闭').length,'项'],['需求变更',data.tasks.flatMap(t=>t.changes||[]).length,'条记录']])+
    `<div class="grid"><div class="card"><div class="card-head"><h2>继续最近的工作</h2><span class="subtitle">刷新保留已保存数据</span></div>${data.tasks.map(t=>`<div class="task-row"><div class="row"><div><h3>${esc(t.name)}</h3><div class="tags">${badge(t.stage)}${badge(journeys[t.activeJourney]?.name||'测试设计')}<span class="badge">${esc(t.version)}</span></div></div>${btn('继续任务 →','open:'+t.id,'small')}</div><p class="meta">${t.requirementNo?'需求 '+esc(t.requirementNo)+' · ':''}${t.cases.length} 条用例 · ${t.attempts.length} 次手工记录 · ${t.runs.length} 次自动化模拟</p><div class="actions">${btn('手工执行','direct:manual:'+t.id,'link small')}${btn('处理问题','direct:issues:'+t.id,'link small')}${btn('查看总结','direct:summary:'+t.id,'link small')}</div></div>`).join('')}</div><div class="card pad"><h2>建议这样体验</h2><div class="todo"><span class="number">1</span><div><h3>先选一个场景</h3><p class="subtitle">不需要走完整套测试流程。</p></div></div><div class="todo"><span class="number">2</span><div><h3>选择任务或用例范围</h3><p class="subtitle">新需求可以新建任务，已有资产可以直接用。</p></div></div><div class="todo"><span class="number">3</span><div><h3>完成当前工作</h3><p class="subtitle">保存后可返回首页，也可切换到下一场景。</p></div></div><div class="source">示例产品：多维表 / 字段管理。<br>需求分析与测试方案可调用本机模型；测试用例也支持真实生成与思维导图审阅；自动化执行仍为示例。</div></div></div>`;
}

function enterJourney(key,id,part){
  journey=journeys[key]?key:'design';taskId=id;page='task';
  const t=task();tab=journeys[journey].steps.includes(part)?part:journeys[journey].steps[0];
  t.activeJourney=journey;t.activeStep=tab;selected.clear();save();render();
}
function openTask(id,part){
  const t=data.tasks.find(t=>t.id===id);
  const key=part==='summary'?'summary':part==='issues'?'issues':t.activeJourney||'design';
  enterJourney(key,id,part||t.activeStep);
}
function chooseJourney(key){
  if(key==='design')return modal('测试设计：从哪里开始？',`<label>开始方式<select name="start"><option value="new">新建需求测试任务</option>${data.tasks.map(t=>`<option value="${esc(t.id)}">继续：${esc(t.name)}</option>`).join('')}</select></label><p class="subtitle">填写任务名称、需求单号与版本，再选择规格资料进行需求分析。</p>`,'继续',f=>{const id=f.get('start');if(id==='new'){closeModal();newTask(false);return false}enterJourney(key,id)});
  modal(journeys[key].name+'：选择测试任务',`<p class="subtitle">${journeys[key].desc}</p><label style="margin-top:18px">测试任务<select name="task">${data.tasks.map(t=>`<option value="${esc(t.id)}">${esc(t.name)} · ${t.cases.length} 条用例</option>`).join('')}</select></label><div class="source">${journeys[key].hint}</div>`,'进入场景',f=>enterJourney(key,f.get('task')));
}

function taskPage(){
  const t=task(),j=journeys[journey];
  if(!j.steps.includes(tab))tab=j.steps[0];
  const idx=j.steps.indexOf(tab);
  return `<button class="link small" data-nav="home">← 返回工作台</button>`+
    title(esc(t.name),`目标版本 ${esc(t.version||'待填写')}${t.requirementNo?' · 需求 '+esc(t.requirementNo):''}`)+
    (journey==='design'?'':`<nav class="task-sections" aria-label="任务内工作">${['design','automation','issues','change','summary'].map(key=>
      `<button type="button" aria-current="${journey===key?'page':'false'}" data-action="direct:${key}:${esc(t.id)}">${esc(journeys[key].name)}</button>`
    ).join('')}</nav>`)+
    `<div class="journey-banner"><div><b>本次目标：${j.output}</b><p class="subtitle">${j.hint}</p></div>${badge(t.stage)}</div>`+
    `<div class="journey-steps" role="tablist">${j.steps.map((s,i)=>`<button role="tab" aria-selected="${tab===s}" data-tab="${s}" class="${s===tab?'active':''}"><span>${i+1}</span>${stepName(s)}</button>`).join('')}</div>`+
    (journey==='automation'?taskScriptPanel(t):({sources,requirements,plan,cases,execution,issues,summary,changes}[tab])())+
    `<div class="journey-footer"><span class="subtitle">步骤 ${idx+1} / ${j.steps.length} · 可保存后稍后继续</span><div class="actions">${idx?btn('← 上一步','step:'+j.steps[idx-1],''):''}${idx<j.steps.length-1?btn('下一步：'+stepName(j.steps[idx+1]),'step:'+j.steps[idx+1],'primary'):btn('保存并返回工作台','finishScene','primary')}</div></div>`;
}

function execution(){
  const t=task(),manual=['manual','issues','change'].includes(journey),build=journey==='automation',auto=!manual&&!build;
  return `<div class="card pad"><div class="row"><div><h3>本次执行条件</h3><p class="subtitle">环境：${esc(t.environment||'basetest')} · 产品版本：${esc(t.version)}</p></div>${btn('修改执行条件','executionConfig','small')}</div></div>`+
    `<div class="notice ${manual?'info':''}">${manual?'按实际操作录入结果。失败、阻塞或跳过时请填写原因。':build?'候选脚本与验证均为示例；未完成验证的候选不能进入回归。':'仅运行勾选的已确认、已验证示例，不执行真实测试；结果不计入手工通过数。'}</div>`+
    `<div class="row section-title"><div><h2>${stepName('execution')}</h2><p class="subtitle">${manual?'查看步骤与预期，再记录结果。':'先勾选要处理的用例。'}</p></div><div class="actions">${build?btn('生成候选脚本','scripts','small')+btn('验证候选（模拟）','validate','primary small'):auto?btn(busy?'模拟运行中…':'开始回归（模拟）','run','primary small'):''}</div></div>`+
    `<div class="card table-wrap"><table><thead><tr>${!manual?'<th>选择</th>':''}<th>用例</th><th>设计状态</th><th>${manual?'本版本手工结果':'自动化实现'}</th><th>操作</th></tr></thead><tbody>${t.cases.map(c=>`<tr>${!manual?`<td><input type="checkbox" class="check" data-check="${c.id}" aria-label="选择 ${c.id}" ${selected.has(c.id)?'checked':''} ${!c.confirmed?'disabled':''}></td>`:''}<td class="case-title">${esc(c.title)}<small>${c.id}</small></td><td>${badge(c.confirmed?'已确认':c.reviewNeeded?'待复核':'待确认')}</td><td>${badge(manual?(latest(t,c.id)?.result||'未执行'):c.script)}</td><td>${manual?`<button class="small" data-action="manual:${c.id}" ${!c.confirmed?'disabled':''}>录入结果</button>`:btn('查看用例','edit:'+c.id,'small')}</td></tr>`).join('')||'<tr><td colspan="5" class="empty">还没有用例，请先进入“测试设计”。</td></tr>'}</tbody></table></div>`+
    `<div class="actions">${manual?btn('处理本次问题 →','direct:issues:'+t.id,'link'):build?btn('进入自动化执行 →','direct:regression:'+t.id,'link'):btn('需要新增自动化？','direct:automation:'+t.id,'link')}${btn('设计 / 复核用例','direct:design:'+t.id,'link')}</div>`+
    (auto?`<div class="card" style="margin-top:20px"><div class="card-head"><h2>回归记录</h2><span class="subtitle">${t.runs.length} 次模拟</span></div><div class="pad">${busy?'<p role="status">模拟执行中…</p>':''}${t.runs.map(r=>`<div class="list-item"><div class="row"><b>${esc(r.mode)} · ${esc(r.env)}</b>${badge('模拟完成')}</div><p class="subtitle">${esc(r.time)} · ${esc(r.version||'版本未记录（旧示例）')} · ${r.count} 条示例通过</p></div>`).join('')||'<p class="subtitle">暂无回归记录。</p>'}</div></div>`:'');
}

function changes(){
  const t=task();return `<div class="notice info">这里由你填写变更并选择影响范围，示例资料更新到用例复核的流程，不自动猜测真实需求。</div><div class="card"><div class="card-head"><h2>需求变化与影响</h2>${btn('记录需求变更','newChange','primary small')}</div>${(t.changes||[]).map(c=>`<div class="task-row"><div class="row"><h3>${esc(c.title)}</h3>${badge('已记录')}</div><p class="subtitle">${esc(c.fromVersion)} → ${esc(c.toVersion)} · ${esc(c.time)}</p><div class="change-diff"><div><small>原规则</small><p>${esc(c.before)}</p></div><div><small>新规则</small><p>${esc(c.after)}</p></div></div><p class="subtitle">影响用例：${c.caseIds.map(esc).join('、')} · 依据：${esc(c.basis)}</p></div>`).join('')||'<div class="empty">还没有变更。点击“记录需求变更”开始。</div>'}</div><div class="card pad"><h3>当前待复核用例</h3><div class="tags">${t.cases.filter(c=>c.reviewNeeded).map(c=>badge(c.id+' '+c.title)).join('')||'<span class="subtitle">暂无待复核项。</span>'}</div><p class="subtitle" style="margin-top:12px">接受变更不会改写历史记录。下一步审阅用例，补齐预期，再安排验证。</p></div>`;
}

function saveVisible(){
  if(page!=='task')return;
  if($('#planText'))task().plan=$('#planText').value;
  if($('#summaryNotes'))task().notes=$('#summaryNotes').value;
  task().activeStep=tab;save();
}
// Save editable page text before in-app navigation; modal edits still require Save.
document.addEventListener('click',e=>{if(e.target.closest('[data-nav],[data-tab],[data-action]')&&$('#overlay').classList.contains('hidden'))saveVisible()},true);
const oldRender=render;
render=function(){if(page==='task'){const t=task();t.activeStep=tab;save()}oldRender()};

function act(action){
  const [name,id,tid]=action.split(':'),t=task();
  if(name==='scenario')return chooseJourney(id);
  if(name==='direct')return enterJourney(id,tid);
  if(name==='switchScene')return modal('切换当前任务的场景',`<label>我要做什么<select name="scene">${Object.entries(journeys).filter(([k])=>!['regression','manual'].includes(k)).map(([k,j])=>`<option value="${k}" ${k===journey?'selected':''}>${j.name}</option>`).join('')}</select></label><p class="subtitle">沿用当前任务与资产，不创建重复任务。</p>`,'切换',f=>enterJourney(f.get('scene'),t.id));
  if(name==='step'){saveVisible();tab=id;render();return}
  if(name==='finishScene'){saveVisible();page='home';render();toast('当前工作已保存，可随时继续');return}
  if(name==='executionConfig')return modal('本次执行条件',`<label>产品版本<input name="version" required value="${esc(t.version)}"></label><label>测试环境<select name="environment">${['basetest','m3welink'].map(v=>`<option ${t.environment===v?'selected':''}>${v}</option>`).join('')}</select></label><p class="subtitle">历史尝试保留当时版本。更换版本不会继承其他版本的手工通过结果。</p>`,'保存条件',f=>{t.version=f.get('version').trim();if(!t.version)return false;t.environment=f.get('environment');save();render()});
  if(name==='newChange')return modal('记录需求变更',`<div class="form-grid"><label>变更标题<input name="title" required placeholder="例如：只读用户字段权限调整"></label><label>新产品版本<input name="version" required placeholder="例如：V2.8.1"></label></div><label>原规则<textarea name="before" required></textarea></label><label>新规则<textarea name="after" required></textarea></label><label>变更依据<input name="basis" required placeholder="方案版本、章节或确认记录"></label><h3>受影响用例（请人工核对）</h3>${t.cases.map(c=>`<label class="inline-check"><input class="check" type="checkbox" name="affected" value="${c.id}">${c.id} · ${esc(c.title)}</label>`).join('')}`,'记录并标记待复核',f=>{
    const ids=f.getAll('affected');if(!ids.length){toast('请至少选择一条受影响用例');return false}
    const entry={id:'CHG-'+Date.now(),title:f.get('title'),fromVersion:t.version,toVersion:f.get('version'),before:f.get('before'),after:f.get('after'),basis:f.get('basis'),caseIds:ids,time:new Date().toLocaleString('zh-CN')};
    (t.changes||=[]).push(entry);t.version=entry.toVersion;t.stage='设计中';
    t.cases.filter(c=>ids.includes(c.id)).forEach(c=>{c.confirmed=false;c.reviewNeeded=true;if(c.script!=='未实现')c.script='需重新验证'});save();render();toast('已标记受影响用例，请继续复核')
  });
  if(name==='run'&&(!t.version?.trim())){toast('请先填写执行版本');return}
  if(name==='new'){journey='design';return newTask(false)}
  return baseAct(action);
}
render();
