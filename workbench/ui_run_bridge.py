"""Invoked only in ui/.venv. Probe never launches a browser; run uses fixed suite identities."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1];UI=ROOT/'ui'
sys.path.insert(0,str(UI))

def write(path,value):
    # Readers on Windows may briefly deny replacing an open destination.
    # Never truncate the live file or reuse a previous writer's temp name.
    path=Path(path)
    temp=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as handle:
            temp=Path(handle.name)
            json.dump(value,handle,ensure_ascii=False,indent=2)
        for attempt in range(6):
            try:
                temp.replace(path)
                return
            except PermissionError:
                if attempt==5:raise
                time.sleep(.01 * (2 ** attempt))
    finally:
        if temp is not None:
            try:temp.unlink(missing_ok=True)
            except OSError:pass

def wait_for_resume(folder,worker=None):
    """Pause only between cases; keep the engine/browser alive."""
    acknowledged=None
    while True:
        try:command=json.loads((folder/'control.json').read_text(encoding='utf-8'))
        except FileNotFoundError:return
        except (OSError,ValueError):
            time.sleep(.2);continue
        if command.get('action')!='pause':return
        if acknowledged!=command.get('requestId'):
            write(folder/(f'control-{worker}.json' if worker else 'control-status.json'),{'requestId':command['requestId'],'state':'paused'})
            acknowledged=command['requestId']
        time.sleep(.2)

def environments():
    from config.settings import list_environments
    from config.urls import resolve_env
    from config.auth_state import auth_state_path
    from core.executor.login_vault import status
    return {'environments':[{'id':name,'url':resolve_env(name).entry_url,'origin':resolve_env(name).origin,
         'product':'DocZip' if 'doczip' in name.lower() else 'Welink云文档','authAvailable':auth_state_path(name).is_file(),
         'loginState':status(name,resolve_env(name).origin),'contract':'ci_fresh_context'} for name in list_environments()]}

def fingerprints(paths):
    return {str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths)) if p.is_file()}

def execute(request):
    import pytest
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from workbench.ui_inventory import script_has_skip
    from core.executor.runner import discover_cases
    snapshot=json.loads(request.read_text(encoding='utf-8'));out=request.parent
    telemetry_errors={}
    def telemetry(name,value):
        try:write(out/name,value)
        except OSError:
            telemetry_errors[name]=telemetry_errors.get(name,0)+1
            if telemetry_errors[name]==1:
                print('[进度警告] '+name+' 暂时无法更新；用例继续执行，最终结果单独保存',flush=True)
    def progress(msg):
        telemetry('progress.json',{'message':msg})
        print(msg,flush=True)
    def block(msg):write(out/'result.json',{'status':'blocked','message':msg,'results':[]});return 2
    progress('检查 UI 环境、登录态文件和脚本版本')
    env=next((e for e in environments()['environments'] if e['id']==snapshot['environment']),None)
    if not env:return block('UI 工程中不存在此环境')
    from urllib.parse import urlsplit
    if (urlsplit(env['url']).hostname or '').endswith('example.com'):return block('此环境是占位地址，不能执行')
    if env['product']!=snapshot['suite']['content']['product']:return block('环境与产品不匹配')
    product='doc_zip' if env['product']=='DocZip' else 'cloud_docs'
    discovered={str(c.directory.relative_to(ROOT)).replace('\\','/'):c for c in discover_cases(product=product)}
    targets=[];mapping={};source_paths=[]
    for asset in snapshot['cases']:
        content=asset['content'];binding=content.get('binding')
        if not binding:return block('用例尚未关联 UI 脚本：'+content['title'])
        if binding.get('admission')!='静态可执行':return block('绑定版本未通过扫描准入，请重新核对：'+content['title'])
        case=discovered.get(binding['inventoryId'])
        if case is None:return block('用例已不满足 UI 工程发现/准入规则：'+content['title'])
        for relative,expected in binding['files'].items():
            path=(ROOT/relative).resolve()
            if not path.is_relative_to((UI/'testcases').resolve()) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:return block('脚本或规格已变化，请更新正式资产版本：'+content['title'])
            if path.suffix=='.py' and script_has_skip(path.read_bytes()):return block('当前脚本含 skip/skipif，未通过扫描准入：'+content['title'])
            source_paths.append(path)
        target=f'suites/test_{product}.py::test_suite_case[{case.param_id}]'
        if target in mapping:return block('套件重复引用同一 UI 执行身份，请去重')
        targets.append(target);mapping[target]=asset
        source_paths.extend(case.directory.parent.glob('*.py'))
    source_paths.extend((UI/'core').rglob('*.py'));source_paths.extend((UI/'config').glob('*.py'));source_paths.extend((UI/'config').glob('*.yaml'));source_paths.append(UI/'conftest.py')
    before=fingerprints(source_paths);write(out/'source-fingerprints.json',before);write(out/'environment.json',env)
    write(out/'node-map.json',{node:{'assetId':a['assetId'],'title':a['content']['title']} for node,a in mapping.items()})
    reports={};batch=[None];started=set();configs=[];timings={}
    def live():
        rows=[]
        for node,asset in mapping.items():
            parts=reports.get(node,[]);clock=timings.get(node,{})
            bad=next((p for p in parts if p['outcome']=='failed'),None)
            done=any(p['phase']=='teardown' for p in parts)
            status='pending' if node not in started else 'running'
            if done:
                status='failed' if bad and bad['phase']=='call' and 'AssertionError' in bad['message'] else 'error' if bad else 'skipped' if any(p['outcome']=='skipped' or p['xfail'] for p in parts) else 'passed' if len(parts)==3 and all(p['outcome']=='passed' for p in parts) else 'interrupted'
            rows.append({'assetId':asset['assetId'],'nodeid':node,'title':asset['content']['title'],'status':status,
                         'screenshotIssue':'本轮无头执行已关闭截图' if mode=='headless' else '',
                         'message':bad['message'][-6000:] if bad else '等待执行' if status=='pending' else '正在执行 / 收尾' if status=='running' else '',
                         'startedAt':clock.get('startedAt'),'finishedAt':clock.get('finishedAt'),
                         'durationSeconds':clock.get('durationSeconds'),'phase':parts[-1]['phase'] if parts else None})
        telemetry('live.json',{'results':rows,'updatedAt':datetime.now(timezone.utc).isoformat()})
    mode=snapshot.get('browserMode','headless')
    if mode not in ('headless','headed'):return block('浏览器模式无效')
    print('浏览器模式：'+('无头（不显示窗口）' if mode=='headless' else '有头（显示窗口）'),flush=True)
    from workbench.ui_execution import execution_workers
    workers=min(execution_workers(snapshot.get('workers',1),mode), len(targets))
    parallel=workers>1
    options=[]
    if parallel:
        from importlib.util import find_spec
        if find_spec('xdist') is None:return block('缺少并行执行组件；请在 UI 虚拟环境安装 pytest-xdist==3.8.0，或选择串行执行')
        options=['-n',str(workers),'--dist=load','--max-worker-restart=0','--no-run-board','-p','workbench.parallel_worker']
    from core.executor.workbench_auth import login_for_batch
    try:
        auth=login_for_batch(env['id'],mode,progress)
    except ValueError as exc:
        return block(str(exc))
    class Evidence:
        @pytest.hookimpl(tryfirst=True)
        def pytest_runtest_protocol(self,item,nextitem):
            wait_for_resume(out)

        @pytest.hookimpl(optionalhook=True)
        def pytest_configure_node(self,node):
            node.workerinput['workbench']={'auth':auth,'out':str(out.resolve()),'targets':targets}

        @pytest.hookimpl(optionalhook=True)
        def pytest_testnodedown(self,node,error):
            write(out/('control-'+node.gateway.id+'.json'),{'state':'finished'})

        session=None
        def pytest_runtest_logstart(self,nodeid,location):
            if nodeid in mapping:
                started.add(nodeid);timings[nodeid]={'startedAt':datetime.now(timezone.utc).isoformat(),'tick':time.monotonic()};live()
        @pytest.hookimpl(trylast=True)
        def pytest_configure(self,config):
            # Explicit run selection wins over inherited --headed/addopts.
            config.option.headed = mode == 'headed'
            config._workbench_capture_screenshots = mode != 'headless'
            config._workbench_storage_state = auth
            configs.append(config)
        @pytest.hookimpl(trylast=True)
        def pytest_sessionfinish(self,session,exitstatus):
            ctx=getattr(session.config,'_run_board_ctx',None)
            if ctx and ctx.get('batch_dir'):batch[0]=Path(ctx['batch_dir'])
        @pytest.hookimpl(trylast=True)
        def pytest_collection_finish(self,session):
            self.session=session
            if parallel:
                progress(f'{workers} 路无头浏览器开始独立上下文执行');live();return
            actual=[item.nodeid for item in session.items]
            if len(actual)!=len(targets) or set(actual)!=set(targets):raise pytest.UsageError('实际收集身份与本轮套件快照不同，禁止执行')
            ctx=getattr(session.config,'_run_board_ctx',None)
            if ctx and ctx.get('batch_dir'):batch[0]=Path(ctx['batch_dir'])
            progress('已收集 '+str(len(actual))+' 条用例，开始独立上下文执行')
            live()
        def pytest_runtest_logreport(self,report):
            if report.nodeid not in mapping:return
            reports.setdefault(report.nodeid,[]).append({'phase':report.when,'outcome':report.outcome,'message':str(report.longrepr) if report.longrepr else '', 'duration':report.duration,'xfail':bool(getattr(report,'wasxfail',False))})
            if report.when=='teardown' and report.nodeid in timings:
                timings[report.nodeid].update(finishedAt=datetime.now(timezone.utc).isoformat(),durationSeconds=max(0,time.monotonic()-timings[report.nodeid]['tick']))
            live()
            progress(mapping[report.nodeid]['content']['title']+' · '+report.when+' · '+report.outcome)
            telemetry('phases.json',reports)
            if report.failed and any(marker in str(report.longrepr).lower() for marker in ('停在登录','storage_state 无效','login.welink.huaweicloud.com','缺少登录态')):
                if self.session:self.session.shouldstop='登录态失效，停止后续用例；请重新发起有头扫码执行'
    # Fixed argv; no user-supplied executable, pytest options, URL or arbitrary script path.
    code=int(pytest.main([*options,*targets,'--env',env['id'],'--execution-contract=ci_fresh_context','--no-cdp','--import-mode=importlib','--asyncio-mode=auto','--maxfail=0','-v','-s'],plugins=[Evidence()]))
    telemetry('phases.json',reports)
    stop_reason='pytest 执行器内部异常，整轮提前中断，请查看控制台日志' if code==3 else '执行提前停止，请查看控制台日志或执行事件'
    changed=before!=fingerprints(source_paths)
    if not parallel and code==0 and not changed and configs:
        refreshed=getattr(configs[0],'_workbench_final_storage_state',None)
        if refreshed:
            from core.executor.workbench_auth import refresh_saved_login
            refresh_saved_login(env['id'],refreshed,progress)
    rows=[]
    for node,asset in mapping.items():
        phases=reports.get(node,[]);bad=next((p for p in phases if p['outcome']=='failed'),None)
        message=bad['message'] if bad else ''
        if bad:
            status='auth' if any(x in message.lower() for x in ('storage_state 无效','停在登录','缺少登录态','login.welink.huaweicloud.com')) else 'failed' if bad['phase']=='call' and 'AssertionError' in message else 'error'
        elif any(p['outcome']=='skipped' or p['xfail'] for p in phases):status='skipped';message=next((p['message'] for p in phases if p['outcome']=='skipped'),'预期失败/XPASS，不计通过')
        elif len(phases)==3 and {p['phase'] for p in phases}=={'setup','call','teardown'} and all(p['outcome']=='passed' for p in phases):status='passed'
        elif phases or node in started:
            status='interrupted';message=stop_reason+'；此用例已开始，但未取得完整 setup/call/teardown 结果'
        else:status='not_run';message=stop_reason+'；尚未开始此用例'
        clock=timings.get(node,{})
        rows.append({'assetId':asset['assetId'],'title':asset['content']['title'],'status':status,'nodeid':node,'message':message[-6000:],'phases':phases,
                     'screenshotIssue':'本轮无头执行已关闭截图' if mode=='headless' else '',
                     'startedAt':clock.get('startedAt'),'finishedAt':clock.get('finishedAt'),
                     'durationSeconds':clock.get('durationSeconds',max(0,time.monotonic()-clock['tick']) if clock else None)})
    if batch[0] and batch[0].resolve().is_relative_to((UI/'run_results').resolve()):
        for path in batch[0].rglob('*'):
            if path.is_file() and path.resolve().is_relative_to(batch[0].resolve()) and path.suffix in ('.png','.zip','.json','.xml'):
                dest=out/'evidence'/path.relative_to(batch[0]);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
    all_pass=all(r['status']=='passed' for r in rows)
    status='passed' if all_pass and code==0 and not changed else 'incomplete' if code==3 else 'failed' if any(r['status']=='failed' for r in rows) else 'incomplete'
    message='本轮所选用例全部通过（非发布批准）' if status=='passed' else '源码在执行期间变化，结果不可作为可信基线' if changed else stop_reason if code==3 else '本轮存在失败、错误、跳过或未执行项'
    if telemetry_errors:message+='；部分实时进度写入失败，最终结果已按本轮阶段记录汇总'
    # Unlike progress, final results are mandatory. Persistent write failures
    # must propagate, never silently publish a successful batch.
    write(out/'result.json',{'status':status,'results':rows,'message':message,'exitCode':code,'telemetryWarnings':telemetry_errors})
    return code

if __name__=='__main__':
    if sys.argv[1]=='probe':print(json.dumps(environments(),ensure_ascii=False))
    elif sys.argv[1]=='auth':
        sys.path.insert(0,str(ROOT))
        from workbench.lease import WorkspaceLease
        from core.executor.workbench_auth import login_for_batch
        from core.executor.login_vault import clear
        lease=None
        try:
            name,action=sys.argv[2:4]
            if name not in [e['id'] for e in environments()['environments']]:raise ValueError('未知环境')
            lease=WorkspaceLease(ROOT/'.local/workbench/ui-engine-lease')
            if action=='clear':
                clear(name);print('已清除本机登录态（不代表服务端退出登录）',flush=True)
            elif action in ('login','check'):
                login_for_batch(name,'headed' if action=='login' else 'headless',lambda msg: print(msg.replace('可在工作台停止运行','可关闭扫码窗口取消'),flush=True),force=action=='login')
                print('登录验证成功，已加密保存',flush=True)
            else:raise ValueError('未知登录操作')
        except Exception:
            print('操作未完成：请检查环境连接、扫码状态，或等待正在执行的任务结束后重试',flush=True)
            raise SystemExit(2)
        finally:
            if lease:lease.close()
    else:
        path=Path(sys.argv[2]).resolve()
        # Child owns the OS lease: even if the workbench exits, a second run
        # cannot overlap an orphaned pytest/browser process.
        sys.path.insert(0,str(ROOT))
        from workbench.lease import WorkspaceLease
        lease=None
        try:
            lease=WorkspaceLease(ROOT/'.local/workbench/ui-engine-lease')
            if (path.parent/'recovered.flag').exists():
                raise SystemExit(2)
            raise SystemExit(execute(path))
        except Exception as exc:
            write(path.parent/'result.json',{'status':'blocked','message':str(exc),'results':[]});raise
        finally:
            if lease:lease.close()
