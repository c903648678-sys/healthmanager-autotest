"""Local versioned assets, suites, schedules and immutable run snapshots."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import threading
import uuid

from .contracts import ROOT, digest
from .workspace import Conflict
from .ui_inventory import script_has_skip
from .ui_execution import MAX_UI_WORKERS, UIExecutor, execution_workers, reconcile, pause_acknowledged
from .lease import WorkspaceLease
from .asset_transfer import export_package, prepare_import
from .ui_execution import RUN_TIMEOUT_POLICY, run_timeout_seconds

TYPES = ('UI', 'API', '性能', '安全')
PRODUCTS = ('健康管理',)
TERMINAL = ('passed', 'failed', 'blocked', 'cancelled', 'interrupted', 'incomplete')

def now(): return datetime.now(timezone.utc).isoformat()
def uid(prefix): return prefix+'-'+uuid.uuid4().hex[:16]
def required(raw,key,limit=300):
    if not isinstance(raw,dict):raise ValueError('记录格式无效')
    value=raw.get(key)
    if not isinstance(value,str) or not value.strip() or len(value)>limit: raise ValueError('请填写有效的 '+key)
    return value.strip()

class Automation:
    def __init__(self,folder,workspace,inventory,executor=None):
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True)
        self.path=self.folder/'state.json';self.lock=threading.RLock()
        self.workspace,self.inventory=workspace,inventory
        if executor is None:
            executor=UIExecutor()
        self.executor=executor;self.events={}
        initial=self.path.read_bytes() if self.path.exists() else None
        self.disk_digest=hashlib.sha256(initial).digest() if initial is not None else None
        self.state=json.loads(initial) if initial is not None else {'revision':0,'assets':[],'suites':[],'plans':[],'runs':[],'models':{}}
        self.pending_recovery={run['id'] for run in self.state['runs']
                               if run['status'] not in TERMINAL or
                               (run['status']=='interrupted' and not run.get('report') and run.get('snapshot'))}
        self._recover_runs()
        self._save()

    def _recover_runs(self):
        if not self.pending_recovery:
            return
        lease=None
        if isinstance(self.executor,UIExecutor):
            try:
                lease=WorkspaceLease(self.executor.root/'.local/workbench/ui-engine-lease')
            except OSError:
                for identity in self.pending_recovery:
                    self.find('runs',identity).update(status='running',message='等待原执行器释放运行锁后恢复证据')
                return  # The bridge is still running. The next poll will try again.
        try:
            for identity in list(self.pending_recovery):
                run=self.find('runs',identity)
                snapshot=run.get('snapshot')
                directory=self.folder/'runs'/identity
                if snapshot and directory.resolve().parent==(self.folder/'runs').resolve():
                    directory.mkdir(parents=True,exist_ok=True)
                    # A child waiting to start must see this under the same engine lease.
                    (directory/'recovered.flag').touch()
                    result={'status':'interrupted','message':'后台重启，本轮执行情况未知','results':[]}
                    try:
                        request=json.loads((directory/'request.json').read_text(encoding='utf-8'))
                        if request==snapshot and request.get('runId',identity)==identity:
                            result=UIExecutor.read_evidence(directory,None)
                    except (OSError,ValueError):
                        pass
                    self._finish_run(run,result,missing='unknown')
                else:
                    run.update(status='interrupted',finishedAt=now(),message='后台重启，无法确认执行情况')
                self._save()
                self.pending_recovery.remove(identity)
        finally:
            if lease:
                lease.close()

    def _check_disk(self):
        try:
            current=hashlib.sha256(self.path.read_bytes()).digest()
        except FileNotFoundError:
            current=None
        if current!=self.disk_digest:
            raise Conflict('自动化状态文件已在外部修改或移除。请核对文件后重启工作台。')

    def _save(self, candidate=None):
        self._check_disk()
        committed=dict(self.state if candidate is None else candidate, revision=self.state['revision']+1)
        content=json.dumps(committed,ensure_ascii=False,indent=2).encode('utf-8')
        temp=self.path.with_suffix('.tmp')
        temp.write_bytes(content)
        temp.replace(self.path)
        self.state=committed
        self.disk_digest=hashlib.sha256(content).digest()

    def run_summaries(self):
        with self.lock:
            self._recover_runs()
            fields=('id','name','product','environment','build','createdAt','finishedAt','status',
                    'executed','total','workers','counts','message','suiteId','suiteRevision','parentRunId','planId','planRevision')
            summaries=[]
            for stored in self.state['runs']:
                run=dict(stored)
                self._live_results(run)
                summaries.append({key:deepcopy(run[key]) for key in fields if key in run})
            return summaries

    def get(self, summary=False):
        with self.lock:
            data={key:deepcopy(value) for key,value in self.state.items() if key!='runs'}
            data['runControls']=True
            data['parallelUI']=False
            data['maxUIWorkers']=1
            data['runTimeoutPolicy']=dict(RUN_TIMEOUT_POLICY)
            if summary:
                data['runs']=self.run_summaries()
            else:
                data['runs']=[]
                for stored in self.state['runs']:
                    run=dict(stored)
                    self._live_results(run)
                    data['runs'].append({k:deepcopy(v) for k,v in run.items() if k not in ('events','snapshot')})
            return data

    def _live_results(self,run):
        if run.get('status') not in ('preparing','running','pausing','paused','cancelling'):return
        if run['status']=='pausing':
            workers=min(run.get('workers',1),run['total'])
            if pause_acknowledged(self.folder/'runs'/run['id'],run.get('controlId'),workers):
                run.update(status='paused',message='已暂停，保留浏览器会话；点击继续执行下一条用例')
        cases=run.get('snapshot',{}).get('cases',[])
        try:
            data=json.loads((self.folder/'runs'/run['id']/'live.json').read_text(encoding='utf-8'))
            updates={r['assetId']:r for r in data['results']}
            self._live_cache={run['id']:data}
            run['liveUpdatedAt']=data.get('updatedAt')
        except (OSError,ValueError,KeyError,TypeError):
            data=getattr(self,'_live_cache',{}).get(run['id'],{})
            updates={r['assetId']:r for r in data.get('results',[])}
            run['liveUpdatedAt']=data.get('updatedAt')
        rows=[]
        for case in cases:
            row=deepcopy(updates.get(case['assetId'],{'assetId':case['assetId'],'status':'pending','message':'等待执行'}))
            row['title']=case['content']['title']
            if row['status']=='running' and row.get('startedAt'):
                try:row['durationSeconds']=max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(row['startedAt'])).total_seconds())
                except (ValueError,TypeError):pass
            rows.append(row)
        run['results']=rows
        run['executed']=sum(r['status'] in ('passed','failed','error','auth','interrupted') for r in rows)
        run['counts']=dict(Counter(r['status'] for r in rows))

    def find(self,kind,identity):
        found=next((v for v in self.state[kind] if v['id']==identity),None)
        if found is None: raise ValueError('记录不存在：'+kind)
        return found

    def version(self,kind,identity,revision):
        item=self.find(kind,identity)
        value=next((v for v in item['versions'] if v['revision']==revision),None)
        if value is None: raise ValueError('版本不存在')
        return deepcopy(value)

    def _version(self,kind,raw,content,prefix):
        self._check_disk()
        old=self.find(kind,raw['id']) if raw.get('id') else None
        if old and raw.get('expectedRevision')!=old['revision']: raise Conflict('资产已更新，请刷新后对比差异')
        if old and digest(old['versions'][-1]['content'])==digest(content): return deepcopy(old)
        item=old or {'id':uid(prefix),'revision':0,'versions':[]}
        item['revision']+=1
        item['versions'].append({'revision':item['revision'],'at':now(),'content':deepcopy(content),'digest':digest(content)})
        if not old:self.state[kind].append(item)
        self._save();return deepcopy(item)

    def _binding(self,asset_id,product):
        row=next((r for r in self.inventory.get()['cases'] if r['assetId']==asset_id),None)
        return self._row_binding(row,product)

    def _row_binding(self,row,product):
        if not row or row['product']!=product: raise ValueError('脚本未扫描或产品不匹配')
        if row.get('admission')!='静态可执行':raise ValueError('脚本未通过扫描准入：'+row.get('reason','请刷新资产'))
        files={}
        for key in ('specPath','scriptPath'):
            path=(ROOT/row[key]).resolve() if row.get(key) else None
            if path is None or not path.is_relative_to((ROOT/'ui/testcases').resolve()) or not path.is_file():raise ValueError('规格或脚本路径无效')
            content=path.read_bytes()
            if key=='scriptPath':
                try:
                    skips=script_has_skip(content)
                except (SyntaxError,UnicodeError) as exc:
                    raise ValueError('脚本无法解析，请修复后重新扫描') from exc
                if skips:
                    raise ValueError('当前脚本含 skip/skipif，未通过扫描准入')
            files[row[key]]=hashlib.sha256(content).hexdigest()
        spec=json.loads((ROOT/row['specPath']).read_text(encoding='utf-8-sig'))
        if row.get('shared'):
            shared=(ROOT/row['scriptPath']).parent/'case_spec.json'
            if not shared.resolve().is_relative_to((ROOT/'ui/testcases').resolve()):raise ValueError('公共规格路径无效')
            business=json.loads(shared.read_text(encoding='utf-8-sig'))
            files[shared.relative_to(ROOT).as_posix()]=hashlib.sha256(shared.read_bytes()).hexdigest()
        else:business=spec
        if any(row.get(k,'')!=business.get(k,'') for k in ('steps','expected','preconditions')) or row['title']!=(business.get('case_name') or spec.get('case_name') or (ROOT/row['specPath']).parent.name):
            raise ValueError('规格已变化，请先刷新测试资产，再核对关联')
        return {'inventoryId':row['assetId'],'files':files,'admission':row['admission'],'reason':row.get('reason','')}

    def publish(self,raw):
        with self.workspace.lock,self.lock:
            return self._version('assets',raw,self._design_content(raw),'asset')

    def _design_content(self,raw):
        task_id=required(raw,'taskId');case_id=required(raw,'caseId')
        task=next((t for t in (self.workspace.get().get('data') or {}).get('tasks',[]) if t['id']==task_id),None)
        if not task or task.get('lifecycle',{}).get('location')=='trash':raise ValueError('任务不可用')
        job_id=task.get('caseDesigner',{}).get('job',{}).get('id')
        job=self.workspace.jobs.get(job_id) if job_id else None
        if not job or not job.get('review',{}).get('accepted') or job.get('basisCurrent') is False:raise ValueError('请先确认当前用例集')
        if task.get('caseDesigner',{}).get('draft')!=job['review']['draft']:raise ValueError('用例有未确认修改')
        case=next((c for c in job['review']['draft']['cases'] if c['id']==case_id),None)
        if not case:raise ValueError('用例不存在')
        product=required(raw,'product');subproduct=required(raw,'subproduct');feature=required(raw,'feature')
        if product not in PRODUCTS:raise ValueError('不支持的产品')
        content={'title':case['title'],'product':product,'subproduct':subproduct,'feature':feature,'layer':case['layer'],
                 'spec':deepcopy(case),'source':{'taskId':task_id,'jobId':job_id,'caseId':case_id,'requirementNo':task.get('requirementNo',''),'reviewDigest':job['reviewDigest']},'binding':None}
        if raw.get('scriptAssetId'):content['binding']=self._binding(raw['scriptAssetId'],product)
        if content['binding'] and content['layer']!='UI':raise ValueError('当前脚本适配器仅支持 UI')
        return content

    def import_ui(self,raw):
        with self.lock:
            row=next((c for c in self.inventory.get()['cases'] if c['assetId']==raw.get('assetId')),None)
            if not row:raise ValueError('请先刷新 UI 资产目录')
            binding=self._binding(row['assetId'],row['product'])
            existing=next((a for a in self.state['assets'] if a['versions'][-1]['content'].get('source',{}).get('inventoryId')==row['assetId']),None)
            if existing:
                if raw.get('expectedRevision')!=existing['revision']:raise Conflict('已存在正式资产，请先查看当前版本后更新')
                raw={**raw,'id':existing['id']}
            return self._version('assets',raw,self._inventory_content(row,binding),'asset')

    @staticmethod
    def _inventory_content(row,binding):
        return {'title':row['title'],'product':row['product'],'subproduct':row['feature'].split('/')[0], 'feature':row['feature'],'layer':'UI',
                 'spec':{k:row.get(k,'') for k in ('id','title','priority','preconditions','steps','expected')},'binding':binding,
                 'source':{'inventoryId':row['assetId'],'kind':'existing-ui-script'}}


    def intake(self,raw):
        items=raw.get('items')
        if not isinstance(items,list) or not 1 <= len(items) <= 10000:
            raise ValueError('请选择 1～10000 条用例')
        with self.workspace.lock,self.lock:
            existing=[a['versions'][-1]['content'] for a in self.state['assets']]
            inventory_ids={ref.get('inventoryId') for c in existing for ref in (c['source'],c.get('binding') or {})}
            designs={(c['source'].get('taskId'),c['source'].get('caseId')) for c in existing}
            inventory=None
            additions=[]
            for item in items:
                if not isinstance(item,dict):
                    raise ValueError('用例来源无效')
                if 'assetId' in item:
                    identity=required(item,'assetId')
                    if identity in inventory_ids:
                        raise Conflict('扫描用例已纳入，请重新筛选')
                    if inventory is None:
                        inventory={r['assetId']:r for r in self.inventory.get()['cases']}
                    row=inventory.get(identity)
                    if not row:
                        raise ValueError('请先刷新 UI 资产目录')
                    content=self._inventory_content(row,self._row_binding(row,row['product']))
                    inventory_ids.add(identity)
                else:
                    identity=(required(item,'taskId'),required(item,'caseId'))
                    if identity in designs:
                        raise Conflict('设计用例已纳入，请重新筛选')
                    content=self._design_content({k:item.get(k) for k in ('taskId','caseId','product','subproduct','feature')})
                    designs.add(identity)
                version={'revision':1,'at':now(),'content':content,'digest':digest(content)}
                additions.append({'id':uid('asset'),'revision':1,'versions':[version]})
            self._save(dict(self.state,assets=self.state['assets']+additions))
            return {'count':len(additions)}

    def export_assets(self, raw):
        with self.lock:
            self._check_disk()
            return export_package(self.state)

    def import_assets(self, raw):
        with self.lock:
            self._check_disk()
            candidate, report = prepare_import(self, raw.get('package'))
            if raw.get('commit') is not True:
                return report
            if raw.get('expectedRevision') != self.state['revision'] or raw.get('packageDigest') != report['packageDigest']:
                raise Conflict('本机资产或导入文件已变化，请重新预览')
            if report['conflicts']:
                raise Conflict('导入存在冲突，请核对预览结果')
            if report['added'] or report['updated']:
                self._save(candidate)
            return report

    def bind(self,raw):
        with self.lock:
            item=self.find('assets',required(raw,'id'));content=deepcopy(item['versions'][-1]['content'])
            if content['layer']!='UI':raise ValueError('当前仅支持绑定 UI 脚本')
            content['binding']=self._binding(required(raw,'scriptAssetId'),content['product'])
            return self._version('assets',raw,content,'asset')

    def suite(self,raw):
        with self.lock:
            layer=required(raw,'layer');refs=raw.get('cases')
            if layer not in TYPES or not isinstance(refs,list) or not 1<=len(refs)<=10000:raise ValueError('请选择类型及 1～10000 条正式用例')
            seen=set();products=set()
            for ref in refs:
                if not isinstance(ref,dict) or ref.get('assetId') in seen:raise ValueError('用例重复或引用无效')
                case=self.version('assets',ref.get('assetId'),ref.get('revision'))['content']
                if case['layer']!=layer:raise ValueError('套件不能混用不同自动化类型')
                seen.add(ref['assetId']);products.add(case['product'])
            if len(products)!=1:raise ValueError('同一套件仅包含同一产品的用例')
            tier=raw.get('tier','smoke')
            if tier not in ('smoke','daily','full','custom'):raise ValueError('范围无效')
            environment=raw.get('environment','')
            if not isinstance(environment,str):raise ValueError('执行环境格式错误')
            if environment:
                self._validate_environment(environment,next(iter(products)))
            return self._version('suites',raw,{'name':required(raw,'name'),'layer':layer,'product':next(iter(products)), 'tier':tier,'environment':environment,'cases':deepcopy(refs)},'suite')

    def _validate_environment(self,environment,product):
        configured=next((e for e in self.executor.environments()['environments'] if e['id']==environment),None)
        if not configured:raise ValueError('所选执行环境已不存在，请刷新环境配置')
        if configured.get('product') and configured['product']!=product:raise ValueError('执行环境与套件产品不匹配')

    def plan(self,raw):
        with self.lock:
            suite=self.version('suites',raw.get('suiteId'),raw.get('suiteRevision'))
            trigger=raw.get('trigger','manual')
            if trigger not in ('manual','daily','ci'):raise ValueError('触发方式无效')
            env=required(raw,'environment');build=raw.get('build','')
            self._validate_environment(env,suite['content']['product'])
            schedule=raw.get('schedule','')
            if trigger=='daily':
                import re
                if not isinstance(schedule,str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',schedule):raise ValueError('日构建时间请填写 HH:MM')
            mode=raw.get('browserMode','headless')
            if mode not in ('headless','headed'):raise ValueError('浏览器模式无效')
            return self._version('plans',raw,{'name':required(raw,'name'),'suiteId':raw['suiteId'],'suiteRevision':suite['revision'],
                'environment':env,'browserMode':mode,'workers':execution_workers(raw.get('workers',1),mode),'build':build,'trigger':trigger,'schedule':schedule,'enabled':bool(raw.get('enabled',True))},'plan')

    def start(self,raw):
        with self.lock:
            self._recover_runs()
            if self.pending_recovery:raise Conflict('旧执行器仍占用运行锁，请等待恢复完成')
            if any(r['status'] not in TERMINAL for r in self.state['runs']):raise Conflict('已有 UI 执行进行中，请等待完成或取消')
            plan=None
            if raw.get('planId'):
                plan=self.find('plans',raw['planId']);pc=deepcopy(plan['versions'][-1]['content'])
                if ('expectedPlanRevision' in raw or 'suiteId' in raw) and raw.get('expectedPlanRevision')!=plan['revision']:
                    raise Conflict('执行计划已更新，请刷新并重新确认执行范围')
                if not pc['enabled']:raise ValueError('执行计划已停用')
                suite_id,suite_rev,env,build=pc['suiteId'],pc['suiteRevision'],pc['environment'],raw.get('build','')
            else:
                suite_id,suite_rev=raw.get('suiteId'),raw.get('suiteRevision');env=required(raw,'environment');build=raw.get('build','')
            if not isinstance(build,str) or len(build)>300:raise ValueError('构建标识无效')
            build_source='provided' if build.strip() else 'generated'
            build=build.strip() or 'AUTO-'+uuid.uuid4().hex[:16]
            suite=self.version('suites',suite_id,suite_rev)
            cases=[{'assetId':ref['assetId'],**self.version('assets',ref['assetId'],ref['revision'])} for ref in suite['content']['cases']]
            parent=None
            if raw.get('parentRunId'):
                parent=self.find('runs',raw['parentRunId'])
                if parent['status'] not in TERMINAL:raise ValueError('原运行尚未结束')
                if parent['snapshot']['suiteId']!=suite_id or parent['snapshot']['suite']['revision']!=suite_rev:raise ValueError('重跑必须使用原套件版本')
                failed={r['assetId'] for r in parent['results'] if r['status'] in ('failed','error','auth','blocked','interrupted','not_run','unknown')}
                cases=[c for c in parent['snapshot']['cases'] if c['assetId'] in failed]
                if not cases:raise ValueError('没有可重跑的失败或未完成项')
            mode=pc.get('browserMode','headless') if plan else raw.get('browserMode',parent['snapshot'].get('browserMode','headless') if parent else 'headless')
            if mode not in ('headless','headed'):raise ValueError('浏览器模式无效')
            workers=execution_workers(pc.get('workers',1) if plan else raw.get('workers',1),mode)
            run={'id':uid('run'),'workers':workers,'createdAt':now(),'finishedAt':None,'status':'preparing','message':'执行前检查',
                 'suiteId':suite_id,'suiteRevision':suite_rev,
                 'planId':plan['id'] if plan else None,'planRevision':plan['revision'] if plan else None,'parentRunId':parent['id'] if parent else None,
                 'snapshot':{'suiteId':suite_id,'suite':suite,'plan':deepcopy(plan['versions'][-1]) if plan else None,'cases':deepcopy(cases),'environment':env,'build':build,'contract':'ci_fresh_context','browserMode':mode,'workers':workers,'buildSource':build_source},
                 'name':suite['content']['name'],'product':suite['content']['product'],'environment':env,'build':build,'buildSource':build_source,
                 'results':[],'events':[],'total':len(cases),'executed':0,'counts':{},'report':None}
            run['snapshot']['runId']=run['id']
            run['snapshot']['timeoutSeconds']=run_timeout_seconds(len(cases),workers)
            self._save({**self.state,'runs':[*self.state['runs'],run]})
            self.events[run['id']]=threading.Event()
            try:
                threading.Thread(target=self._run,args=(run['id'],),daemon=True).start()
            except RuntimeError as exc:
                self.events.pop(run['id'])
                run.update(status='interrupted',message='执行线程未启动',finishedAt=now())
                self._save()
                raise ValueError('执行线程未启动，请重试') from exc
            return deepcopy(run)

    def _run(self,run_id):
        event=self.events[run_id]
        with self.lock:snapshot=deepcopy(self.find('runs',run_id)['snapshot'])
        def progress(message):
            with self.lock:
                run=self.find('runs',run_id);run['message']=str(message)[:1000];run['events'].append({'at':now(),'message':run['message']})
                if any(marker in message for marker in ('开始独立上下文执行',' · setup · ',' · call · ',' · teardown · ')) and not event.is_set() and run['status'] not in ('pausing','paused'):run['status']='running'
                try:
                    self._save()
                except Conflict as exc:
                    run['message']=str(exc)
        try:
            progress('核对固定用例、脚本版本和环境，准备独立浏览器上下文')
            result=self.executor.execute(snapshot,self.folder/'runs'/run_id,event,progress)
        except Exception as exc:
            result={'status':'blocked','message':'执行适配器异常：'+str(exc),'results':[]}
        with self.lock:
            run=self.find('runs',run_id)
            self._finish_run(run,result)
            try:
                self._save()
            except Conflict as exc:
                run['message'] += '；本轮状态未写入磁盘：'+str(exc)

            if run.get('deleteRequested'):
                try:self._delete_run(run)
                except OSError as exc:
                    run['message']='执行已停止，但清理证据失败，请重试删除：'+str(exc);self._save()

    @staticmethod
    def _finish_run(run,result,missing='not_run'):
        snapshot=run['snapshot']
        result=reconcile(snapshot,result,missing)
        rows=result['results']
        run.update(status=result['status'],message=result.get('message',''),results=rows,finishedAt=now(),exitCode=result.get('exitCode'))
        run['executed']=sum(r['status'] in ('passed','failed','error','auth','interrupted') for r in rows)
        run['counts']=dict(Counter(r['status'] for r in rows))
        run['artifacts']=result.get('artifacts',[])
        run['report']={'scope':snapshot['suite']['content'],'environment':snapshot['environment'],'build':snapshot['build'],
            'counts':deepcopy(run['counts']),'unexecuted':[r['assetId'] for r in rows if r['status'] in ('not_run','skipped')],
            'risks':[r.get('message','') for r in rows if r['status'] not in ('passed',)],'releaseDecision':'未作发布批准；当前报告仅代表本轮所选范围'}

    def run(self,run_id):
        with self.lock:
            self._recover_runs()
            run=deepcopy(self.find('runs',run_id))
        self._live_results(run)
        # The UI engine suffix hashes the full nodeid, so similarly named cases
        # cannot borrow each other's screenshots. Enrich old runs read-only.
        for row in run.get('results',[]):
            if row.get('durationSeconds') is None and row.get('phases'):
                durations=[p.get('duration') for p in row['phases']]
                if all(isinstance(d,(int,float)) for d in durations):
                    row['durationSeconds']=sum(durations);row['durationEstimated']=True
            node=row.get('nodeid')
            if not node:continue
            suffix='--'+hashlib.sha256(node.encode('utf-8')).hexdigest()[:16]
            images=[]
            for name in run.get('artifacts',[]):
                path=Path(name)
                if path.name=='failure.png' and path.parent.name.endswith(suffix):
                    try:self.artifact(run_id,name)
                    except ValueError:continue
                    images.append(name)
            row['screenshots']=images
        return run

    def cancel(self,raw):
        with self.lock:
            run=self.find('runs',required(raw,'id'))
            if run['id'] in self.pending_recovery:raise Conflict('旧执行器仍在退出，请等待恢复完成')
            if run['status'] not in TERMINAL:
                self.events[run['id']].set();run['status']='cancelling';run['message']='正在停止执行';self._save()
            return deepcopy(run)

    def control(self,raw):
        if getattr(self.executor,"supports_pause",True) is False:
            raise ValueError("健康管理执行器暂不支持暂停，请使用取消后重跑")
        from .ui_run_bridge import write
        with self.lock:
            run=self.find('runs',required(raw,'id'));action=required(raw,'action')
            if action not in ('pause','resume'):raise ValueError('不支持的运行操作')
            if run['status'] in TERMINAL or run['status']=='cancelling':raise Conflict('运行已结束或正在停止，请刷新')
            if action=='pause' and run['status'] in ('pausing','paused'):return deepcopy(run)
            if action=='resume' and run['status'] not in ('pausing','paused'):raise Conflict('当前运行未暂停')
            folder=self.folder/'runs'/run['id'];folder.mkdir(parents=True,exist_ok=True)
            token=uid('control')
            write(folder/'control.json',{'requestId':token,'action':action})
            run.update(controlId=token,status='pausing' if action=='pause' else 'running',
                       message='等待当前用例完成后暂停；登录及前置检查不会中途挂起' if action=='pause' else '继续执行')
            run['events'].append({'at':now(),'message':run['message']});self._save()
            return deepcopy(run)

    def _delete_run(self,run):
        root=(self.folder/'runs').resolve();target=(root/run['id']).resolve()
        if target==root or target.parent!=root:raise ValueError('运行证据目录无效')
        if target.exists():shutil.rmtree(target)
        self.state['runs'].remove(run);self.events.pop(run['id'],None)
        if hasattr(self,'_live_cache'):self._live_cache.pop(run['id'],None)
        self._save()

    def delete_run(self,raw):
        with self.lock:
            run=self.find('runs',required(raw,'id'))
            if run['status'] not in TERMINAL:
                run['deleteRequested']=True
                self.cancel(raw)
                run['message']='正在停止并删除本次运行记录和证据';self._save()
                return {'id':run['id'],'pending':True}
            self._delete_run(run)
            return {'id':run['id'],'deleted':True}

    def artifact(self,run_id,name):
        self.find('runs',run_id)
        root=(self.folder/'runs'/run_id).resolve();path=(root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.suffix not in ('.log','.json','.png','.zip','.xml'):raise ValueError('证据不存在')
        return path

    def model(self,task_id):
        with self.workspace.lock,self.lock:
            task=next((t for t in (self.workspace.get().get('data') or {}).get('tasks',[]) if t['id']==task_id),None)
            if not task:raise ValueError('任务不存在')
            job_id=task.get('planner',{}).get('job',{}).get('id')
            job=self.workspace.jobs.get(job_id) if job_id else None
            if not job or not job.get('review',{}).get('accepted') or job.get('basisCurrent') is False:raise ValueError('请先确认测试方案')
            if task.get('planner',{}).get('draft')!=job['review']['draft']:raise ValueError('方案存在未确认修改，请先确认方案')
            basis=job['reviewDigest'];stored=self.state['models'].get(task_id)
            if stored and stored['basis']==basis:return deepcopy(stored)
            rows=job['review']['draft']['coverage']
            return {'taskId':task_id,'planJobId':job_id,'basis':basis,'confirmed':False,'revision':stored['revision'] if stored else 0,
                'scenarios':[{'id':'S'+str(i+1),'title':r['requirementId']+' · 需求场景','requirementIds':[r['requirementId']],
                'points':[{'id':'P'+str(i+1),'title':r['approach'],'method':'根据方案细化验证条件与可观察结果'}]} for i,r in enumerate(rows) if r['disposition']=='included']}

    def save_model(self,raw):
        with self.workspace.lock,self.lock:
            current=self.model(required(raw,'taskId'))
            if raw.get('basis')!=current['basis'] or raw.get('expectedRevision')!=current['revision']:raise Conflict('方案或场景已更新，请刷新')
            allowed={r for s in current['scenarios'] for r in s['requirementIds']}
            scenes=raw.get('scenarios');seen=set();covered=set()
            if not isinstance(scenes,list) or not 1<=len(scenes)<=200:raise ValueError('请提供 1～200 个场景')
            clean=[]
            for s in scenes:
                identity=required(s,'id');title=required(s,'title',2000);refs=s.get('requirementIds',[])
                if identity in seen or not isinstance(refs,list) or not refs or not all(isinstance(r,str) for r in refs) or not set(refs)<=allowed:raise ValueError('场景 ID 重复或需求关联无效')
                seen.add(identity);covered.update(refs);points=s.get('points');pids=set()
                if not isinstance(points,list) or not 1<=len(points)<=100:raise ValueError('每个场景需要测试点')
                out=[]
                for point in points:
                    pid=required(point,'id')
                    if pid in pids:raise ValueError('场景内测试点 ID 重复')
                    pids.add(pid);out.append({'id':pid,'title':required(point,'title',5000),'method':required(point,'method',5000)})
                clean.append({'id':identity,'title':title,'requirementIds':refs,'points':out})
            if covered!=allowed:raise ValueError('场景遗漏方案已纳入的需求')
            current.update(scenarios=clean,confirmed=bool(raw.get('confirmed')),revision=current['revision']+1)
            self._check_disk()
            self.state['models'][raw['taskId']]=current;self._save();return deepcopy(current)

    def generation_model(self,task_id):
        model=self.model(task_id)
        if not model['confirmed']:raise ValueError('请先审阅并确认场景与测试点')
        return model
