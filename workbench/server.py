"""python -m workbench.server --port 8878 (loopback only)."""
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
from urllib.parse import urlsplit

from .contracts import ROOT
from .jobs import JobStore
from .providers import executable
from .workspace import Workspace, Conflict
from .local_sources import LocalSources
from .knowledge import Knowledge
from .execution import Execution
from .case_import import parse_csv
from .lease import WorkspaceLease
from .backup import backup
from .assets import Assets
from .history_search import HistorySearch
from . import design_assist as assist
from . import template_assets
from .codegen import generate, environment_form
from .automation import Automation
from .health_execution import HealthExecutor
import subprocess


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        # Keep the operator console readable; job events carry the useful progress.
        if args and str(args[0]).startswith(("GET /api/jobs/", "GET /api/health")):
            return
        super().log_message(format, *args)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "docs/test-workbench/web"), **kwargs)

    def _local(self):
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if self.headers.get("Host") not in allowed:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in {"http://" + host for host in allowed}

    def reply(self, status, value):
        content = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if not self._local():
            return self.reply(403, {"error": "仅允许本机同源访问"})
        route = urlsplit(self.path).path
        if route in ('/api/automation','/api/automation/summary'):
            return self.reply(200, self.server.automation.get(summary=route.endswith('/summary')))
        if route == '/api/automation/runs':
            return self.reply(200,self.server.automation.run_summaries())
        if route == '/api/automation/environments':
            try:return self.reply(200,self.server.automation.executor.environments())
            except (OSError,ValueError,subprocess.TimeoutExpired) as exc:return self.reply(503,{'error':str(exc)})
        if route.startswith('/api/automation/model/'):
            try:return self.reply(200,self.server.automation.model(route.split('/')[-1]))
            except ValueError as exc:return self.reply(400,{'error':str(exc)})
        if route.startswith('/api/automation/runs/'):
            parts=route.split('/')
            try:
                if len(parts)==5:return self.reply(200,self.server.automation.run(parts[4]))
                if len(parts)>6 and parts[5]=='artifacts':
                    path=self.server.automation.artifact(parts[4],'/'.join(parts[6:]));raw=path.read_bytes()
                    self.send_response(200);self.send_header('Content-Type','image/png' if path.suffix=='.png' else 'application/octet-stream');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Disposition',('inline' if path.suffix=='.png' else 'attachment')+'; filename="'+path.name.encode('ascii','replace').decode().replace('"','')+'"');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
            except (ValueError,OSError):return self.reply(404,{'error':'运行或证据不存在'})
        if route == '/api/design-templates':
            return self.reply(200, template_assets.catalog())
        if route == '/api/knowledge/organization':
            return self.reply(200,self.server.knowledge.organization_get())
        if route.startswith('/api/knowledge/suggestions/'):
            try:return self.reply(200,self.server.knowledge_suggestions.get(route.split('/')[-1]))
            except ValueError as exc:return self.reply(404,{'error':str(exc)})
        if route.startswith('/api/design-templates/'):
            parts = route.split('/')
            try:
                if len(parts) == 5 and parts[4] == 'original':
                    path = template_assets.original(parts[3])
                    raw = path.read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/octet-stream')
                    self.send_header('Content-Disposition', 'attachment; filename="'+parts[3]+'.xmind"')
                    self.send_header('Content-Length', str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                if len(parts) == 4:
                    return self.reply(200, template_assets.snapshot([parts[3]])[0])
            except (ValueError, OSError):
                return self.reply(404, {'error':'模板不存在或归档校验失败'})
            return self.reply(404, {'error':'模板地址不存在'})
        if route == '/api/assets':
            return self.reply(200, self.server.assets.get())
        if route == '/api/backup':
            try:
                with self.server.store.lock, self.server.knowledge.lock, self.server.automation.lock:
                    if any(j.get('status') in {'running', 'cancelling'} for j in self.server.store.jobs.values()):
                        return self.reply(409, {'error': '生成任务进行中，请结束后备份'})
                    if any(j['status']=='running' for j in self.server.knowledge_suggestions.jobs.values()):
                        return self.reply(409,{'error':'目录建议正在生成，请结束后备份'})
                    if any(r['status'] in {'preparing','running','pausing','paused','cancelling'} for r in self.server.automation.state['runs']):return self.reply(409,{'error':'执行进行中，请结束后备份'})
                    content = backup(self.server.workspace.path.parent)
                self.send_response(200)
                self.send_header('Content-Type', 'application/zip')
                self.send_header('Content-Disposition', 'attachment; filename=workbench-backup.zip')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            except (OSError, ValueError) as exc:
                return self.reply(400, {'error': str(exc)})
        if route == '/api/diagnostics':
            return self.reply(200, {'service':'healthmanager-workbench', 'dataFolder':str(self.server.workspace.path.parent), 'providers':{p:bool(executable(p)) for p in ('codex','claude')}, 'knowledgeDocuments':len(self.server.knowledge.get()['documents']), 'batchCount':len(self.server.execution.value['batches']), 'reportCount':len(self.server.execution.value['reports']), 'automation':'ui-pytest', 'storage':'local-files', 'version':'20261107-local-3'})
        if route == '/api/execution':
            with self.server.store.lock:
                return self.reply(200, {'reports':[{k:r[k] for k in ('id','taskId','batchId','revision','frozenAt','attemptCount','counts')} | {'name':r['batch']['name']} for r in self.server.execution.value['reports']], 'issues':[{k:i[k] for k in ('id','taskId','status')} for i in self.server.execution.value['issues']], 'batches':[{k:b[k] for k in ('id','taskId','name','status')} | {'attemptCount':len(b['attempts'])} for b in self.server.execution.value['batches']]})
        if route.startswith('/api/execution/'):
            return self.reply(200, self.server.execution.get(route.split('/')[-1]))
        if route.startswith('/api/evidence/'):
            try:
                content = self.server.execution.evidence(route.split('/')[-1])
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Disposition', 'attachment')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            except (OSError, ValueError):
                return self.reply(404, {'error': 'Evidence unavailable'})
        if route == '/api/knowledge':
            return self.reply(200, self.server.knowledge.get())
        if route == '/api/workspace':
            try:
                return self.reply(200, self.server.workspace.get())
            except (OSError, ValueError) as exc:
                return self.reply(409, {'error': str(exc)})
        if route == "/api/health":
            return self.reply(200, {"service": "healthmanager-workbench", "providers": [{"id": p, "installed": bool(executable(p))} for p in ("codex", "claude")]})
        if route.startswith("/api/jobs/"):
            try:
                return self.reply(200, self.server.store.get(route.split("/")[-1]))
            except KeyError:
                return self.reply(404, {"error": "分析记录不存在"})
        # No directory listing or arbitrary repo files, even for encoded traversal paths.
        if route not in {"/", "/index.html", "/app.js", "/scenarios.js", "/sources.js", "/analysis.js", "/planner.js", "/case-designer.js", "/tasks.js", "/ux.js", "/knowledge.js", "/execution.js", "/assets.js", "/history.js", "/design-assist.js", "/templates.js", "/execution-ux.js", "/automation-live.js", "/ux.css", "/mindmap.css", "/scenarios.css"}:
            return self.reply(404, {"error": "接口不存在，请确认后台版本" if route.startswith("/api/") else "页面不存在"})
        return super().do_GET()

    def do_POST(self):
        if not self._local():
            return self.reply(403, {"error": "仅允许本机同源访问"})
        if self.headers.get_content_type() != "application/json":
            return self.reply(415, {"error": "必须使用 application/json"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            limit = 32 if urlsplit(self.path).path in ('/api/workspace', '/api/automation/import-assets') else 9 if urlsplit(self.path).path == '/api/execution/record' else 2
            if not 0 < length <= limit * 1024 * 1024:
                raise ValueError(f"请求大小不合法（最多{limit}MB）")
            raw = json.loads(self.rfile.read(length))
            if not isinstance(raw, dict):
                raise ValueError("JSON request must be an object")
            route = urlsplit(self.path).path.split("/")
            if len(route)==4 and route[:3]==['','api','automation']:
                methods={'generate':lambda value:generate(self.server.automation,value,self.server.automation.executor.root),
                         'environment-config':lambda value:environment_form(self.server.automation.executor.root,value),'intake':self.server.automation.intake,'publish':self.server.automation.publish,'import-ui':self.server.automation.import_ui,'bind':self.server.automation.bind,
                         'export-assets':self.server.automation.export_assets,'import-assets':self.server.automation.import_assets,
                         'suite':self.server.automation.suite,'plan':self.server.automation.plan,'start':self.server.automation.start,
                         'cancel':self.server.automation.cancel,'control':self.server.automation.control,'delete-run':self.server.automation.delete_run,'model':self.server.automation.save_model,
                         'login-state':self.server.automation.executor.login_action}
                if route[3] in methods:return self.reply(200,methods[route[3]](raw))
            if route == ['', 'api', 'history', 'search']:
                return self.reply(200, self.server.history_search.search(raw))
            if route == ['', 'api', 'assets', 'refresh']:
                return self.reply(200, self.server.assets.refresh())
            if route == ['', 'api', 'cases', 'parse-csv']:
                return self.reply(200, parse_csv(raw))
            if len(route) == 4 and route[:3] == ['', 'api', 'execution']:
                methods = {'create': self.server.execution.create, 'record': self.server.execution.record, 'close': self.server.execution.close_batch, 'issue': self.server.execution.review_issue, 'freeze': self.server.execution.freeze, 'feedback':self.server.execution.propose_feedback, 'feedback-review':lambda value: self.server.execution.review_feedback(value, self.server.knowledge)}
                if route[3] in methods:
                    return self.reply(200, methods[route[3]](raw))
            if route == ['', 'api', 'knowledge', 'refresh']:
                return self.reply(200, self.server.knowledge.refresh())
            if route == ['', 'api', 'knowledge', 'organization']:
                return self.reply(200,self.server.knowledge.organization_save(raw))
            if route == ['', 'api', 'knowledge', 'suggest']:
                return self.reply(202,self.server.knowledge_suggestions.create(raw))
            if route == ['', 'api', 'knowledge', 'suggest-cancel']:
                return self.reply(200,self.server.knowledge_suggestions.cancel(raw.get('id')))
            if route == ['', 'api', 'knowledge', 'review']:
                return self.reply(200, self.server.knowledge.review(raw))
            if route == ['', 'api', 'workspace']:
                return self.reply(200, self.server.workspace.save(raw))
            if len(route) == 5 and route[:3] == ['', 'api', 'tasks']:
                return self.reply(200, self.server.workspace.transition(route[3], route[4], raw))
            if route == ['', 'api', 'source-links', 'pick']:
                return self.reply(200, {'documents': self.server.local_sources.pick(raw.get('mode'))})
            if route == ['', 'api', 'source-links', 'preview']:
                return self.reply(200, self.server.local_sources.read(raw.get('localRef')))
            if route == ["", "api", "jobs"]:
                if isinstance(raw.get('sources'), list) and any(isinstance(item, dict) and 'localRef' in item for item in raw['sources']):
                    raw['sources'] = self.server.local_sources.materialize(raw['sources'])
                raw.pop('designModel',None)
                if raw.get('kind')=='test-cases' and raw.get('useDesignModel'):
                    raw['designModel']=self.server.automation.generation_model(raw.get('taskId'))
                raw.pop('references', None)
                if raw.get('kind')=='asset-retrieval':
                    parent,_ = assist.parent(self.server.store,raw,'asset-retrieval')
                    card=parent['review']['draft']
                    candidates=self.server.history_search.search({'taskId':raw['taskId'],
                        'product':card['product'] if card['product'] in {'Welink云文档','DocZip','AI健康','AIGC'} else '',
                        'feature':card['subproduct'], 'query':' '.join(card['keywords']+card['objects']+card['operations'])})
                    if not candidates['items']:
                        raise ValueError('未召回相关历史资产，请调整理解卡关键词或补充本地资料')
                    raw['references']=[{k:v for k,v in r.items() if k not in {'score','reason'}} for r in candidates['items'][:24]]
                elif raw.get('kind', 'requirements') in {'requirements','asset-mapping'}:
                    raw['references'] = self.server.history_search.resolve(raw)
                return self.reply(202, self.server.store.create(raw))
            if len(route) == 5 and route[:3] == ["", "api", "jobs"]:
                if route[4] == "cancel":
                    return self.reply(200, self.server.store.cancel(route[3]))
                if route[4] == "review":
                    return self.reply(200, self.server.store.review(route[3], raw))
            return self.reply(404, {"error": "接口不存在"})
        except Conflict as exc:
            return self.reply(409, {'error': str(exc)})
        except (OSError, subprocess.TimeoutExpired) as exc:
            return self.reply(503, {'error': '本地操作未完成：' + str(exc)})
        except (ValueError, UnicodeError) as exc:
            return self.reply(400, {"error": str(exc)})
        except KeyError:
            return self.reply(404, {"error": "分析记录不存在"})


class WorkbenchServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_close(self):
        if hasattr(self,'knowledge_suggestions'):
            for event in self.knowledge_suggestions.events.values():event.set()
        if hasattr(self, 'automation'):
            for event in self.automation.events.values():event.set()
        if hasattr(self, 'lease'):
            self.lease.close()
        super().server_close()

    def server_bind(self):
        if os.name == 'nt':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(port=8878, folder=None, runner=None):
    server = WorkbenchServer(("127.0.0.1", port), Handler)
    try:
        server.lease = WorkspaceLease(Path(folder) if folder else ROOT / '.local/workbench')
    except OSError:
        server.server_close()
        raise
    options = {"runner": runner} if runner else {}
    server.store = JobStore(folder or ROOT / ".local/workbench/jobs", **options)
    server.workspace = Workspace((server.store.folder / 'workspace.json') if folder else ROOT / '.local/workbench/workspace.json', server.store)
    server.local_sources = LocalSources(server.workspace.path.parent)
    server.workspace.resolve_sources = server.local_sources.materialize
    (server.workspace.path.parent / 'knowledge/notes').mkdir(parents=True, exist_ok=True)
    server.knowledge = Knowledge(server.workspace.path.parent / 'knowledge', {
        'product': ROOT / 'knowledge/product',
        'testing': ROOT / 'knowledge/testing',
        'workbench-notes': server.workspace.path.parent / 'knowledge/notes',
    })
    from .knowledge_suggestions import KnowledgeSuggestions
    server.knowledge_suggestions = KnowledgeSuggestions(server.knowledge)
    server.execution = Execution(server.workspace.path.parent / 'execution', server.workspace)
    server.execution.resume_feedback(server.knowledge)
    server.assets = Assets(server.workspace.path.parent)
    server.automation = Automation(server.workspace.path.parent / 'automation',server.workspace,server.assets,executor=HealthExecutor())
    server.store.design_model_current = lambda task_id,model: server.automation.state['models'].get(task_id)==model
    server.history_search = HistorySearch(server.knowledge, server.assets, server.workspace, server.store, server.execution)
    server.history_search.automation = server.automation
    server.store.task_guard = server.workspace.assert_editable
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8878)
    parser.add_argument("--open", action="store_true", help="启动后打开浏览器")
    args = parser.parse_args()
    try:
        server = make_server(args.port)
    except OSError:
        from urllib.request import urlopen
        try:
            with urlopen(f'http://127.0.0.1:{args.port}/api/health', timeout=3) as response:
                if json.load(response).get('service') != 'healthmanager-workbench':
                    raise ValueError('端口被其他服务占用')
            print('工作台已在运行，请在页面查看进展；控制台日志位于原启动窗口。', flush=True)
            if args.open:
                import webbrowser
                webbrowser.open(f'http://127.0.0.1:{args.port}/')
            return
        except Exception:
            raise SystemExit(f'端口 {args.port} 不可用，请关闭占用程序或更换 --port')
    print(f"工作台：http://127.0.0.1:{server.server_port}/", flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{server.server_port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.store.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
