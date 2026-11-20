// Structured asset-guided design; confirmed snapshots remain owned by durable jobs.
let daPollTimer;
const daNames={card:'需求理解卡',rank:'AI 语义筛选',mapping:'资产对照表'};
const daKinds={card:'asset-understanding',rank:'asset-retrieval',mapping:'asset-mapping'};
const daActions={reuse:'直接复用',modify:'修改已有',new:'新增用例',clarify:'先澄清',regression:'影响回归'};
function daState(t){const a=aiState(t);return a.assist||(a.assist={})}
function daEnabled(t){return aiState(t).assetGuided??!aiState(t).job}
function daSources(t){return JSON.stringify({sources:(t.sources||[]).map(s=>[s.id,s.name,s.text]),instructions:aiState(t).instructions||''})}
function daCardCurrent(t){const s=daState(t);return s.card?.review?.accepted&&s.card.basisCurrent!==false&&s.cardKey===daSources(t)&&JSON.stringify(s.cardDraft)===JSON.stringify(s.card.review.draft)}
function daMappingKey(t){return JSON.stringify([daSources(t),daState(t).card?.reviewDigest,(aiState(t).historyRefs||[]).map(r=>[r.id,r.hash])])}
function daMappingCurrent(t){const s=daState(t);return daCardCurrent(t)&&s.mapping?.review?.accepted&&s.mapping.basisCurrent!==false&&s.mappingKey===daMappingKey(t)&&JSON.stringify(s.mappingDraft)===JSON.stringify(s.mapping.review.draft)}
function daReadyForSearch(t){return !daEnabled(t)||daCardCurrent(t)}
const daOriginalRunning=aiRunning;
aiRunning=function(t){return daOriginalRunning(t)||!!daState(t).submitting||['card','rank','mapping'].some(k=>['running','cancelling'].includes(daState(t)[k]?.status))};
const daOriginalStale=aiStale;
aiStale=function(t){return daOriginalStale(t)||aiState(t).job?.basisCurrent===false||(daEnabled(t)&&aiState(t).job&&!daMappingCurrent(t))};
function daField(label,name,value){return `<label>${label}<textarea name="${name}" required>${esc(value||'')}</textarea></label>`}
const daViews=new Map(),daSettings=new Map();
function daStep(t){const desired=daViews.get(t.id)??(!daEnabled(t)||daMappingCurrent(t)?4:daCardCurrent(t)?2:1);return daEnabled(t)?Math.min(desired,daCardCurrent(t)?daMappingCurrent(t)?4:3:1):desired}
function daControl(label,action,disabled=false,primary=false){return `<button data-action="${action}" class="${primary?'primary':''}" ${disabled?'disabled':''}>${label}</button>`}
function daJob(s,k){const j=s[k];if(!j)return '';return `<details class="da-job" ${['running','cancelling','failed','interrupted'].includes(j.status)?'open':''}><summary>${daNames[k]} · ${({running:'生成中',cancelling:'取消中',failed:'失败，请重试',interrupted:'已中断',cancelled:'已取消',succeeded:'已生成'})[j.status]||'等待中'}</summary>${aiProgressPanel(j,'daRefresh:'+k)}${['running','cancelling'].includes(j.status)?btn('取消生成','daCancel:'+k,'small'):''}</details>`}
function daPanel(t){const s=daState(t),step=daStep(t),locked=aiRunning(t)||!taskEditable(t),card=s.cardDraft,map=s.mappingDraft;
 const names=['理解需求','选择参考','审阅对照','处理疑问'];
 const hints=['核对 AI 提取的需求点，确认它理解正确。','选择适用的历史资产；没有合适资产也可以继续。','逐条判断复用建议，明确本次需要补充什么。','分析需求与风险，回答关键疑问后进入测试方案。'];
 const nav=`<nav class="da-steps" aria-label="需求审视步骤">${names.map((n,i)=>{const k=i+1,disabled=daEnabled(t)&&(k>1&&!daCardCurrent(t)||k===4&&!daMappingCurrent(t));return `<button data-action="daStep:${k}" ${disabled?'disabled':''} ${step===k?'aria-current="step"':''}><span>${k}</span><b>${n}</b><small>${k===1&&daCardCurrent(t)||k===3&&daMappingCurrent(t)?'已确认':k===step?'当前步骤':disabled?'待前序确认':'可查看'}</small></button>`}).join('')}</nav>`;
 let body='';
 if(step===1)body=`${card?`<div class="da-card-meta"><b>${esc(card.product)} / ${esc(card.subproduct)}</b>${btn('编辑基本信息','daEditCard','small')}<span>对象：${esc(card.objects.join('、'))} · 操作：${esc(card.operations.join('、'))}</span></div><div class="da-review-list">${card.points.map((p,i)=>`<article class="da-point"><div class="row"><h3>${esc(p.id)} · ${esc(p.title)}</h3>${locked?'':btn('修改','daPoint:'+i,'small')}</div><p><b>规则</b>${esc(p.rule)}</p><p><b>变化</b>${esc(p.change)}</p><p><b>影响</b>${esc(p.impact)}</p><details><summary>查看原文依据</summary>${(p.citations||[]).map(c=>`<p>${esc(c.quote)}</p>`).join('')}</details></article>`).join('')}</div><p class="da-note">待明确：${esc(card.questions.join('；')||'暂无，请核对是否遗漏')}</p>`:'<div class="da-empty"><h3>先让 AI 读懂这次需求</h3><p>根据已确认的规格提取规则、变化点和影响范围，供你核对。</p><p>请先在上方检查资料和分析范围，再开始生成。</p></div>'}${daJob(s,'card')}<div class="da-foot"><span>${daCardCurrent(t)?'理解卡已确认，可继续选择参考。':card?'核对需求点后确认；有误可逐条修改。':'生成后由你确认，不会自动进入下一步。'}</span>${daControl(card?'重新生成':'生成需求理解卡','daStart:card',locked||!confirmedSources(t),!card)}${card?daControl(daCardCurrent(t)?'下一步：选择参考':'确认并选择参考',daCardCurrent(t)?'daStep:2':'daConfirm:card',locked,true):''}</div>`;
 if(step===2)body=`<div class="da-reference-slot"></div><details class="da-semantic"><summary>候选较多？使用 AI 辅助筛选（可选）</summary><p class="da-note">根据已确认需求判断候选相关性，需额外调用模型。请核对版本和适用范围。</p><div class="actions">${daControl('AI 筛选候选','daStart:rank',locked||!daCardCurrent(t))}${daControl('采用相关候选（最多 8 份）','daUseRank',locked||!s.rank?.result||s.rankKey!==s.card?.reviewDigest)}</div>${s.rank?.result?`<div class="da-review-list">${s.rank.result.items.map(r=>`<p><b>${esc(({direct:'直接相关',related:'间接相关',not_relevant:'不相关'})[r.relation])}</b> · ${esc(s.rank.references?.find(x=>x.id===r.assetId)?.name||r.assetId)}<br>${esc(r.reason)}</p>`).join('')}</div>`:''}${daJob(s,'rank')}</details><div class="da-foot"><span>已选 ${(aiState(t).historyRefs||[]).length} / 8 份；未选择时将依据当前规格设计。</span>${btn('上一步','daStep:1')}${daControl('下一步：审阅对照','daStep:3',locked,true)}</div>`;
 if(step===3){const pending=map?.rows.filter(r=>r.decision==='pending').length||0;body=`${map?`<p class="da-note">共 ${map.rows.length} 项 · 待审阅 ${pending} 项。逐条接受建议，或进入“调整 / 不采用”说明原因。</p><div class="da-review-list">${map.rows.map((r,i)=>`<article class="da-point"><div class="row"><h3>${esc(r.pointId)} · ${esc(card?.points.find(p=>p.id===r.pointId)?.title||r.pointId)}</h3><span class="da-tag">${daActions[r.action]} · ${r.area==='regression'?'影响回归':'本次需求'}</span></div><p><b>建议</b>${esc(r.changes)}</p><p><b>理由</b>${esc(r.reason)}</p><details><summary>关联资产 · ${r.assetIds.length} 份</summary>${esc(r.assetIds.map(id=>s.mapping.references?.find(x=>x.id===id)?.name||id).join('、')||'暂无已有资产')}${(r.citations||[]).map(c=>`<p>${esc(c.quote)}</p>`).join('')}</details><div class="da-row-actions"><span>${({pending:'待审阅',accepted:'已接受',rejected:'不采用',adjusted:'已调整'})[r.decision]}${r.reviewNote?' · '+esc(r.reviewNote):''}</span>${r.decision==='pending'?daControl('接受建议','daAcceptRow:'+i,locked):''}${daControl('调整 / 不采用','daRow:'+i,locked)}</div></article>`).join('')}</div>`:'<div class="da-empty"><h3>明确已有覆盖与新增工作</h3><p>AI 将为每个需求点给出复用、修改、新增、澄清或影响回归建议。</p></div>'}${daJob(s,'mapping')}<div class="da-foot"><span>${pending?'还有 '+pending+' 项待审阅':map?'确认后即可开展需求分析与疑问处理。':'已选参考资料将与当前需求一起用于对照。'}</span>${btn('上一步','daStep:2')}${daControl(map?'重新生成对照':'生成资产对照表','daStart:mapping',locked,!map)}${map?daControl(daMappingCurrent(t)?'下一步：处理疑问':'确认并处理疑问',daMappingCurrent(t)?'daStep:4':'daConfirm:mapping',locked||pending>0,true):''}</div>`}
 return `<div class="da-workflow">${nav}<section class="card pad da-panel"><div class="da-section-head"><h2>${names[step-1]}</h2><p class="subtitle">${hints[step-1]}</p></div>${s.error?`<p class="notice" role="alert">${esc(s.error)}</p>`:''}${body}${step===4?'<div class="da-analysis-slot"></div>':''}</section></div>`;
}
async function daStart(stage){const t=task(),a=aiState(t),s=daState(t);if(aiRunning(t)||!taskEditable(t))return;if(!confirmedSources(t))return toast('请先确认当前规格');if(stage!=='card'&&!daCardCurrent(t))return toast('请先确认理解卡');a.assetGuided=true;s.submitting=true;s.error='';save();render();try{await flushWorkspace();const request={kind:daKinds[stage],taskId:t.id,provider:a.provider,model:a.model,sources:t.sources.map(x=>({id:x.id,name:x.name,text:x.text})),instructions:a.instructions||'',historyRefs:(a.historyRefs||[]).map(r=>({id:r.id,hash:r.hash}))};if(stage!=='card')Object.assign(request,{understandingJobId:s.card.id,understandingReviewDigest:s.card.reviewDigest});s[stage]=await workspaceRequest('/api/jobs',request,30000);s[stage+'Key']=stage==='card'?daSources(t):stage==='mapping'?daMappingKey(t):s.card.reviewDigest;delete s[stage+'Draft']}catch(e){s.error=e.message}finally{s.submitting=false;save();render();daSchedule()}}
async function daRefresh(t,stage){const s=daState(t);if(!s[stage])return;try{const job=await workspaceRequest('/api/jobs/'+s[stage].id);
if(reviewChanged(s[stage],job)&&s[stage+'Draft']){
 if(!useUpdatedReview())return;
 s[stage+'Draft']=structuredClone(job.review.draft);
}
s[stage]=job;if(s[stage].status==='succeeded'&&!s[stage+'Draft'])s[stage+'Draft']=JSON.parse(JSON.stringify(s[stage].review?.draft||s[stage].result));save();if(taskId===t.id&&page==='task')render()}catch(e){s.error=e.message}}
function daSchedule(){clearTimeout(daPollTimer);daPollTimer=setTimeout(async()=>{for(const t of data.tasks){const s=t.ai?.assist;if(!s)continue;for(const stage of ['card','rank','mapping'])if(['running','cancelling'].includes(s[stage]?.status))await daRefresh(t,stage)}daSchedule()},2000)}
async function daConfirm(stage){const t=task(),s=daState(t);if(aiRunning(t)||!taskEditable(t))return;const job=s[stage];if(!job||job.status!=='succeeded')return toast('请等待生成成功');if(stage==='card'&&s.cardKey!==daSources(t)||stage==='mapping'&&s.mappingKey!==daMappingKey(t))return toast('输入已变化，请重新生成');try{s[stage]=await workspaceRequest('/api/jobs/'+job.id+'/review',{expectedReviewDigest:job.reviewDigest,inputDigest:job.inputDigest,accepted:true,draft:s[stage+'Draft']});daViews.set(t.id,stage==='card'?2:4);s.error='';save();if(stage==='card'){aiState(t).historyScope={product:s.cardDraft.product,feature:s.cardDraft.subproduct,query:[...s.cardDraft.objects,...s.cardDraft.operations,...s.cardDraft.keywords].join(' ')};hrCache.delete(t.id);save();await hrSearch(t)}render();toast('已确认'+daNames[stage])}catch(e){s.error=e.message;render()}}
const daOldRequirements=requirements;
requirements=function(){
 const t=task(),step=daStep(t),template=document.createElement('template');template.innerHTML=daOldRequirements();
 const nodes=[...template.content.children],source=nodes.shift(),history=nodes.shift(),settings=nodes.shift();
 const actions=settings.querySelector('.actions');actions?.remove();
 const start=actions?.querySelector('[data-action="aiStart"]');if(start)start.textContent=aiRunning(t)?'正在生成…':aiState(t).job?'重新分析需求':'开始分析需求与疑问';
 const panel=document.createElement('template');panel.innerHTML=daPanel(t);
 panel.content.querySelector('.da-reference-slot')?.append(history);
 const slot=panel.content.querySelector('.da-analysis-slot');if(slot){
  if(actions)slot.append(actions);
  const supporting=[];
  for(const node of nodes){const title=node.querySelector('h2')?.textContent||'';
   if(['需求理解 ·','风险与测试方向','历史冲突与影响','已有用例复用建议'].some(x=>title.startsWith(x))){
    const detail=document.createElement('details');detail.className='da-result-detail';
    const summary=document.createElement('summary');summary.textContent=title+' · 展开审阅';detail.append(summary,node);supporting.push(detail);
   }else slot.append(node);
  }
  const finish=slot.querySelector('[data-action="aiAccept"]')?.closest('.card');
  for(const node of supporting){if(finish)slot.insertBefore(node,finish);else slot.append(node)}
 }
 const settingsOpen=daSettings.get(t.id)??!confirmedSources(t);
 return `<details class="card da-setup" id="daSetup" ${settingsOpen?'open':''}><summary><span><b>资料与分析设置</b> · ${t.sources?.length||0} 份规格 · ${esc(aiState(t).provider||'codex')} / ${esc(aiState(t).model||'默认模型')}</span><span>${confirmedSources(t)?'查看 / 调整':'请先确认规格'}</span></summary><div class="da-setup-body">${source.outerHTML}${settings.outerHTML}</div></details>`+panel.innerHTML;
};
const daOldStart=aiStart;
aiStart=async function(){const t=task();if(daEnabled(t)&&!daMappingCurrent(t))return toast('请先确认需求理解卡及资产对照表');return daOldStart()};
const daOldAct=act;
act=function(action){const [name,arg]=action.split(':');const t=page==='task'?task():null,s=t?daState(t):null;
 if(name==='daStep'){daViews.set(t.id,Number(arg));render();document.querySelector('.da-steps')?.scrollIntoView({block:'nearest'});return}
 if(name==='daStart')return daStart(arg);
 if(name==='daRefresh')return daRefresh(t,arg);
 if(name==='daCancel'){const job=s[arg];if(job)return workspaceRequest('/api/jobs/'+job.id+'/cancel',{}).then(j=>{s[arg]=j;save();render()}).catch(e=>toast(e.message));return}
 if(name==='daConfirm')return daConfirm(arg);
 if(name==='daFeedback')return modal('审阅反馈（持久保存）',`<pre class="spec-preview">${esc(JSON.stringify({current:s.mapping?.review?.feedback||[],history:s.mapping?.reviewHistory||[]},null,2))}</pre>`,'关闭',()=>{});
 if(name.startsWith('da')&&(!taskEditable(t)||aiRunning(t)))return toast('当前任务只读或正在生成，请稍后操作');
 if(name==='daAcceptRow'){const r=s.mappingDraft?.rows[Number(arg)];if(r&&r.decision==='pending'){r.decision='accepted';r.reviewNote='';save();render()}return}
 if(name==='daEditCard'){const c=s.cardDraft;return modal('编辑需求理解卡',daField('产品','product',c.product)+daField('子产品','subproduct',c.subproduct)+[['objects','业务对象'],['operations','操作'],['keywords','检索关键词'],['questions','未明确事项']].map(([key,label])=>daField(label+'（每行一项，无则填无）',key,c[key].join('\n'))).join(''),'保存',f=>{for(const key of ['product','subproduct'])c[key]=f.get(key).trim();for(const key of ['objects','operations','keywords','questions'])c[key]=f.get(key).split('\n').map(x=>x.trim()).filter(Boolean);save();render()})}
 if(name==='daPoint'){const p=s.cardDraft.points[Number(arg)];return modal('修改需求点 '+p.id,['title','rule','change','impact'].map((key,i)=>daField(['标题','规则','变化点','影响范围'][i],key,p[key])).join('')+'<p>原文引用保留；如原规格变化，请重新生成理解卡。</p>','保存',f=>{for(const key of ['title','rule','change','impact'])p[key]=f.get(key).trim();save();render()})}
 if(name==='daRow'){const r=s.mappingDraft.rows[Number(arg)];return modal('审阅资产对照 '+r.id,`<label>处理动作<select name="action">${Object.entries(daActions).map(([key,label])=>`<option value="${key}" ${r.action===key?'selected':''}>${label}</option>`).join('')}</select></label><label>验证范围<select name="area"><option value="requirement" ${r.area==='requirement'?'selected':''}>本次需求验证</option><option value="regression" ${r.area==='regression'?'selected':''}>影响回归</option></select></label>${daField('具体设计 / 修改动作','changes',r.changes)}<label>审阅结论<select name="decision"><option value="accepted">接受</option><option value="adjusted" ${r.decision==='adjusted'?'selected':''}>调整后采用</option><option value="rejected" ${r.decision==='rejected'?'selected':''}>不采用</option></select></label><label>审阅理由（调整或不采用必填）<textarea name="reviewNote">${esc(r.reviewNote)}</textarea></label>`,'保存',f=>{const values=Object.fromEntries(f);if((values.action!==r.action||values.area!==r.area||values.changes!==r.changes)&&values.decision==='accepted')values.decision='adjusted';if(['adjusted','rejected'].includes(values.decision)&&!values.reviewNote.trim()){toast('请填写调整或拒绝理由');return false}Object.assign(r,values);save();render()})}
 if(name==='daUseRank'){if(!daCardCurrent(t)||s.rank?.basisCurrent===false||s.rankKey!==s.card?.reviewDigest)return toast('理解卡已变化，请重新筛选');const ids=s.rank.result.items.filter(r=>r.relation!=='not_relevant').slice(0,8).map(r=>r.assetId);aiState(t).historyRefs=s.rank.references.filter(r=>ids.includes(r.id)).map(r=>({id:r.id,hash:r.hash,name:r.name}));save();render();toast('已选择 '+ids.length+' 份参考，请检查后生成对照表');return}
 return daOldAct(action)
};
const daOldRender=render;
render=function(){daOldRender();if(page!=='task')return;const t=task(),s=daState(t);if(tab==='requirements'){const setup=$('#daSetup');if(setup)setup.ontoggle=()=>daSettings.set(t.id,setup.open);const start=$('[data-action="aiStart"]');if(start&&daEnabled(t)&&!daMappingCurrent(t))start.disabled=true;for(const el of document.querySelectorAll('[data-action^="daStart:"],[data-action^="daEdit"],[data-action^="daConfirm:"]'))if(aiRunning(t)||!taskEditable(t))el.disabled=true}if(['plan','cases'].includes(tab)&&s.mapping?.review?.accepted){const content=$('#content');if(content&&!$('#daTrace'))content.insertAdjacentHTML('beforeend',`<details class="card pad" id="daTrace"><summary>资产对照与设计关联（确认快照）</summary><p>需求点 ID 贯穿理解卡、需求分析、方案和用例；下方为设计依据，不代表已复用执行脚本。</p><pre class="spec-preview">${esc(JSON.stringify({mapping:s.mapping.review.draft,caseTrace:t.caseDesigner?.job?.designTrace||[]},null,2))}</pre></details>`)}};
daSchedule();

for(const t of data.tasks)if(t.ai?.assist)t.ai.assist.submitting=false;
// Preserve nested review scrolling and expanded evidence across same-step renders.
const daPositionRender=render;
render=function(){
 const key=page==='task'&&tab==='requirements'?taskId+'|'+daStep(task()):'',old=document.querySelector('.da-workflow');
 const snapshot=key&&old?.dataset.viewKey===key?{x:window.scrollX,y:window.scrollY,lists:[...old.querySelectorAll('.da-review-list')].map(el=>({top:el.scrollTop,left:el.scrollLeft})),details:[...old.querySelectorAll('details')].map(el=>el.open)}:null;
 daPositionRender();const current=document.querySelector('.da-workflow');if(current)current.dataset.viewKey=key;
 if(snapshot&&current){const restore=()=>{if(!current.isConnected||current.dataset.viewKey!==key)return;current.querySelectorAll('details').forEach((el,i)=>{if(i<snapshot.details.length)el.open=snapshot.details[i]});current.querySelectorAll('.da-review-list').forEach((el,i)=>{if(snapshot.lists[i]){el.scrollTop=snapshot.lists[i].top;el.scrollLeft=snapshot.lists[i].left}});window.scrollTo({left:snapshot.x,top:snapshot.y,behavior:'instant'})};restore();requestAnimationFrame(restore)}
};
