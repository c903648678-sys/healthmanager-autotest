"""Process isolation for the existing UI pytest engine. No shell commands from UI input."""
import json
import os
from pathlib import Path
import subprocess
import time
import threading
from datetime import datetime, timezone
from .contracts import ROOT

MAX_UI_WORKERS = 10
RUN_TIMEOUT_POLICY = {'mode': 'unlimited'}
CASE_WATCHDOG_SECONDS = 600


class ExecutionWatchdog:
    """Parent-process guard: browser/event-loop hangs cannot disable this timer."""
    def __init__(self, limit=CASE_WATCHDOG_SECONDS):
        self.limit=limit
        self.started={}
        self.signature=None
        self.last_change=0

    def check(self, folder, active_seconds):
        try:
            rows=json.loads((Path(folder)/'live.json').read_text(encoding='utf-8'))['results']
            if not isinstance(rows,list):return None
        except (OSError,ValueError,KeyError):
            rows=[]
        signature=tuple((r.get('nodeid'),r.get('status'),r.get('phase'),r.get('finishedAt')) for r in rows)
        if signature!=self.signature:
            self.signature=signature;self.last_change=active_seconds
        running={r['nodeid']:r for r in rows if r.get('status')=='running' and r.get('nodeid')}
        self.started={node:self.started.get(node,active_seconds) for node in running}
        for node,started in self.started.items():
            if active_seconds-started>=self.limit:
                return {'nodeid':node,'message':f'用例超过 {self.limit // 60} 分钟未完成，已停止本轮执行：{running[node].get("title",node)}'}
        if active_seconds-self.last_change>=self.limit:
            return {'message':f'执行器连续 {self.limit // 60} 分钟没有阶段进展，已停止本轮执行'}
        return None


def run_timeout_seconds(case_count, workers):
    """New runs have no batch deadline; UI operation timeouts remain independent."""
    return None


def execution_workers(value, mode):
    if type(value) not in (int, str) or str(value) not in {str(i) for i in range(1, MAX_UI_WORKERS + 1)}:
        raise ValueError(f'并发数须为 1 到 {MAX_UI_WORKERS} 的整数')
    count = int(value)
    if count > 1 and mode != 'headless':
        raise ValueError('并行执行仅支持无头模式')
    return count


def pause_acknowledged(folder, token, workers=1):
    names = ['control-status.json'] if workers == 1 else [f'control-gw{i}.json' for i in range(workers)]
    try:
        states = [json.loads((folder/name).read_text(encoding='utf-8')) for name in names]
        paused = [s.get('state')=='paused' and s.get('requestId')==token for s in states]
        return any(paused) and all(ok or s.get('state')=='finished' for ok,s in zip(paused,states))
    except (ValueError,OSError):
        return False

def reconcile(snapshot, result, missing='not_run'):
    """Return exactly one result per selected asset, in snapshot order."""
    expected={case['assetId']:case for case in snapshot['cases']}
    by_id={}
    invalid=False
    statuses={'passed','failed','error','auth','blocked','skipped','interrupted','not_run','unknown'}
    raw_rows=result.get('results')
    if not isinstance(raw_rows,list):
        raw_rows=[]
        invalid=True
    for row in raw_rows:
        identity=row.get('assetId') if isinstance(row,dict) else None
        if not isinstance(identity,str) or identity not in expected:
            invalid=True
            continue
        if identity in by_id or not isinstance(row.get('status'),str) or row['status'] not in statuses:
            invalid=True
            by_id[identity]={'assetId':identity,'title':expected[identity]['content']['title'],
                             'status':'unknown','message':'结果重复或状态无效'}
        else:
            by_id[identity]={**row,'title':expected[identity]['content']['title']}
    status=result.get('status')
    message=result.get('message','')
    if status=='passed' and (result.get('exitCode')!=0 or not expected or by_id.keys()!=expected.keys()
                              or any(row['status']!='passed' for row in by_id.values())):
        invalid=True
    if invalid or not isinstance(status,str) or status not in {'passed','failed','blocked','cancelled','interrupted','incomplete'}:
        status='incomplete'
        message='结果与执行快照或退出状态不一致，请核对本轮证据'
    rows=[by_id.get(identity,{'assetId':identity,'title':case['content']['title'],'status':missing,
                              'message':message or '没有本轮结果'}) for identity,case in expected.items()]
    return {**result,'status':status,'message':message,'results':rows}


def ui_python(root):
    return Path(root)/'ui'/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')


class UIExecutor:
    def __init__(self,root=ROOT):
        self.root=Path(root);self.ui=self.root/'ui'
        self.python=ui_python(self.root)
        self.bridge=Path(__file__).with_name('ui_run_bridge.py')
        self.auth_operations={};self.auth_lock=threading.Lock()

    def environments(self):
        if not self.python.is_file():return {'environments':[],'error':'UI 虚拟环境不存在，请先安装 UI 工程依赖'}
        result=subprocess.run([str(self.python),'-B',str(self.bridge),'probe'],cwd=self.ui,capture_output=True,encoding='utf-8',errors='replace',timeout=25,
             env={**os.environ,'PYTHONIOENCODING':'utf-8'},creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        if result.returncode:return {'environments':[],'error':'UI 环境读取失败：'+result.stderr[-1000:]}
        data=json.loads(result.stdout)
        with self.auth_lock:
            for row in data['environments']:row['authOperation']=dict(self.auth_operations.get(row['id'],{}))
        return data

    def login_action(self,raw):
        name,action=raw.get('environment'),raw.get('action')
        if action not in ('login','check','clear'):raise ValueError('登录操作无效')
        if name not in [e['id'] for e in self.environments()['environments']]:raise ValueError('未知执行环境')
        with self.auth_lock:
            if any(j['status']=='running' for j in self.auth_operations.values()):raise ValueError('已有登录操作正在进行')
            job={'status':'running','action':action,'message':'正在处理登录状态；扫码最多等待 180 秒'}
            self.auth_operations[name]=job
        def worker():
            try:
                process=subprocess.Popen([str(self.python),'-B','-u',str(self.bridge),'auth',name,action],cwd=self.ui,
                    stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',errors='replace',
                    env={**os.environ,'PYTHONIOENCODING':'utf-8'},creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                def timeout():
                    if process.poll() is None:
                        if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                        else:process.terminate()
                timer=threading.Timer(300,timeout);timer.start()
                try:
                    for line in process.stdout:
                        with self.auth_lock:job['message']=line.strip()[:300]
                    code=process.wait()
                finally:timer.cancel();process.stdout.close()
                with self.auth_lock:job['status']='complete' if code==0 else 'failed'
            except Exception:
                with self.auth_lock:job.update(status='failed',message='登录操作未完成，请检查 UI 执行器后重试')
        threading.Thread(target=worker,daemon=True).start()
        return dict(job)

    def execute(self,snapshot,folder,event,progress):
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        if snapshot['suite']['content']['layer']!='UI':return {'status':'blocked','message':'此类型尚未接入真实执行器','results':[]}
        if not self.python.is_file():return {'status':'blocked','message':'缺少 UI 虚拟环境','results':[]}
        request=folder/'request.json';request.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
        log=folder/'console.log'
        timeout_seconds=snapshot.get('timeoutSeconds',run_timeout_seconds(len(snapshot['cases']),snapshot.get('workers',1)))
        progress("本轮不设总时限；单条用例超过 10 分钟未完成或连续 10 分钟无阶段进展，将自动停止本轮（暂停时间不计）" if timeout_seconds is None else f"本轮执行时限 {timeout_seconds // 60} 分钟（暂停时间另计）")
        with log.open('w',encoding='utf-8') as output:
            process=subprocess.Popen([str(self.python),'-B','-u',str(self.bridge),'run',str(request.resolve())],cwd=self.ui,stdout=output,stderr=subprocess.STDOUT,
                env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1'},creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            started=time.monotonic();last='';stopped=False;paused_seconds=0;tick=started
            watchdog=ExecutionWatchdog();watchdog_stop=None
            while process.poll() is None:
                cancelled=event.wait(.5)
                current=time.monotonic()
                try:
                    command=json.loads((folder/'control.json').read_text(encoding='utf-8'))
                    if command.get('action')=='pause' and pause_acknowledged(folder,command.get('requestId'),min(snapshot.get('workers',1),len(snapshot['cases']))):
                        paused_seconds+=current-tick
                except (OSError,ValueError):pass
                tick=current
                watchdog_stop=watchdog.check(folder,current-started-paused_seconds)
                if cancelled or watchdog_stop or (timeout_seconds is not None and current-started-paused_seconds>timeout_seconds):
                    stopped=True
                    if watchdog_stop and not cancelled:
                        (folder/'watchdog.json').write_text(json.dumps(watchdog_stop,ensure_ascii=False),encoding='utf-8')
                        progress(watchdog_stop['message'])
                    if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                    else:process.terminate()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
                    break
                state=folder/'progress.json'
                try:
                    message=json.loads(state.read_text(encoding='utf-8'))['message']
                    if message!=last:progress(message);last=message
                except (OSError,ValueError,KeyError):pass
        result=self.read_evidence(folder, process.returncode, stopped, event.is_set(), timeout_seconds)
        if watchdog_stop and not event.is_set():
            result.update(status='interrupted',message=watchdog_stop['message'])
            for row in result.get('results',[]):
                if row.get('nodeid')==watchdog_stop.get('nodeid') and row.get('status')=='interrupted':
                    row.update(status='error',message=watchdog_stop['message'])
        return reconcile(snapshot,result)

    @staticmethod
    def read_evidence(folder, exit_code, stopped=False, cancelled=False, timeout_seconds=3600):
        try:
            result=json.loads((folder/'result.json').read_text(encoding='utf-8'))
            if not isinstance(result,dict) or not isinstance(result.get('results'),list) or not result.get('status'):
                result=None
        except (OSError,ValueError):
            result=None
        # The bridge can also emit a blocked fallback after pytest has started.
        has_partial_result = (result and result.get('status') == 'blocked'
                              and not result['results'] and (folder/'phases.json').exists())
        if stopped or result is None or has_partial_result:
            try:
                phases=json.loads((folder/'phases.json').read_text(encoding='utf-8'))
                identities=json.loads((folder/'node-map.json').read_text(encoding='utf-8'))
            except (OSError,ValueError):
                phases={};identities={}
            try:live={r['nodeid']:r for r in json.loads((folder/'live.json').read_text(encoding='utf-8'))['results']}
            except (OSError,ValueError,KeyError,TypeError):live={}
            if not isinstance(phases,dict):phases={}
            if not isinstance(identities,dict):identities={}
            rows=[]
            for node in set(phases)|{n for n,r in live.items() if r.get('startedAt')}:
                parts=phases.get(node,[])
                if not isinstance(identities.get(node),dict) or not isinstance(parts,list) or not all(isinstance(p,dict) for p in parts):continue
                row={**identities[node],'nodeid':node,'phases':parts,'status':'interrupted','message':'运行已停止，保留已收到阶段；本项不计通过'}
                if len(parts)==3 and all(p.get('outcome')=='passed' for p in parts):row.update(status='passed',message='此用例在停止前已完整通过')
                else:
                    bad=next((p for p in parts if p.get('outcome')=='failed'),None)
                    if bad:row.update(status='failed' if bad['phase']=='call' and 'AssertionError' in bad.get('message','') else 'error',message=bad.get('message',''))
                    elif any(p.get('phase')=='teardown' for p in parts) and any(p.get('outcome')=='skipped' for p in parts):row.update(status='skipped',message='此用例在停止前已跳过')
                timing=live.get(node,{})
                row.update({k:timing.get(k) for k in ('startedAt','finishedAt','durationSeconds')})
                if row.get('startedAt') and not row.get('finishedAt'):
                    row['finishedAt']=datetime.now(timezone.utc).isoformat()
                    row['durationSeconds']=max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(row['startedAt'])).total_seconds())
                rows.append(row)
            message=(result or {}).get('message') or '执行器未生成有效的最终结果，请查看阶段证据和控制台日志'
            if stopped:
                message='执行已取消' if cancelled else (f'运行超过 {timeout_seconds // 60} 分钟，已停止' if timeout_seconds is not None else '执行保护已停止本轮运行')
            result={'status':'cancelled' if stopped and cancelled else 'interrupted',
                    'message':message,'results':rows}
        # UI phase records carry node IDs. Cross-check their association even
        # when result.json was written before the parent process restarted.
        rows=result['results']
        if any(isinstance(row,dict) and row.get('nodeid') for row in rows):
            try:
                node_map=json.loads((folder/'node-map.json').read_text(encoding='utf-8'))
            except (OSError,ValueError):
                node_map={}
            for row in rows:
                if not isinstance(row,dict) or not row.get('nodeid'):
                    continue
                identity=node_map.get(row['nodeid']) if isinstance(node_map,dict) and isinstance(row['nodeid'],str) else None
                if not isinstance(identity,dict) or identity.get('assetId')!=row.get('assetId'):
                    row.update(status='unknown',message='节点与本轮用例映射不一致')
                    result.update(status='incomplete',message='本轮执行证据映射不一致')
        for row in rows:
            if not isinstance(row,dict) or row.get('status')!='passed':
                continue
            phases=row.get('phases',[])
            if not (row.get('nodeid') and isinstance(phases,list) and len(phases)==3
                    and all(isinstance(p,dict) and p.get('outcome')=='passed' and not p.get('xfail') for p in phases)
                    and sorted(str(p.get('phase')) for p in phases)==['call','setup','teardown']):
                row.update(status='unknown',message='缺少完整通过的节点阶段证据')
                result.update(status='incomplete',message='本轮阶段证据不完整')
        if result['status']=='passed':
            if exit_code is None:
                result.update(status='incomplete',message='已恢复阶段结果，无法确认子进程最终退出码')
            elif result.get('exitCode',exit_code)!=exit_code:
                result.update(status='incomplete',message='桥接退出码与子进程实际退出码不一致')
        result['exitCode']=exit_code
        result['artifacts']=[p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file() and p.name!='request.json' and p.suffix in ('.log','.png','.zip','.xml','.json')]
        return result
