"""Run versioned health test assets and checkpoint sanitized results."""
import shutil
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET

from scripts.run import validate, validate_config
from .source_digest import matches_digest
from .ui_execution import UIExecutor
from .contracts import ROOT


def checkpoint(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def classify(report, code):
    try:
        cases = ET.parse(report).findall('.//testcase')
    except (ET.ParseError, OSError):
        cases = []
    for tag, status, phase in [('error', 'error', 'fixture / collection'),
                               ('failure', 'failed', 'call'), ('skipped', 'skipped', 'skip')]:
        for case in cases:
            element = case.find(tag)
            if element is not None:
                if tag == 'skipped' and code != 0:
                    return 'error', 'pytest', 'pytest 退出异常'
                # Keep exception classes only; tracebacks and parameter values may contain health data.
                details = element.text or ''
                for name in ('AssertionError', 'TimeoutError', 'ReadTimeout', 'ReadError',
                             'ConnectionError', 'TypeError', 'ValueError', 'RuntimeError', 'KeyError'):
                    if name in details:
                        return status, phase, name
                return status, phase, {'error':'pytest error','failure':'测试断言或调用失败','skipped':'pytest skip'}[tag]
    if not cases or code:
        return 'error', 'pytest', '缺少有效测试结果或退出异常'
    return 'passed', 'call', '测试通过'


class HealthExecutor(UIExecutor):
    supports_pause = False
    timeout = 600

    @staticmethod
    def read_evidence(folder, exit_code):
        path = folder/'result.json'
        if path.exists():
            result = json.loads(path.read_text(encoding='utf-8'))
            if result.get('format') == 'health-v1' and isinstance(result.get('results'), list):
                return result
        return UIExecutor.read_evidence(folder, exit_code)

    def __init__(self, root=ROOT):
        super().__init__(root)
        self.api_python = self.root/'api'/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')

    def login_action(self, raw):
        raise ValueError('产品登录机制尚未配置')

    def environments(self):
        for project in ('ui', 'api'):
            try:
                config = validate(project, self.root)
                return {'environments':[{'id':config.get('environment','test'),
                        'name':'健康管理测试环境','product':'健康管理',
                        'baseUrl':config.get('base_url') or config.get('api_base_url')}]}
            except (ValueError, OSError):
                continue
        return {'environments':[], 'error':'请配置 UI 或 API 测试环境'}

    def freeze_environment(self, name, cases):
        try:
            current = json.loads((self.root/'config.local.json').read_text(encoding='utf-8'))
        except FileNotFoundError as exc:
            raise ValueError('请先配置测试环境') from exc
        if not isinstance(current, dict) or current.get('environment', 'test') != name:
            raise ValueError('执行环境已变化，请重新选择')
        fields = {'environment': name}
        for layer in {case['content'].get('layer', 'UI').lower() for case in cases}:
            if layer not in ('api', 'ui'):
                raise ValueError('不支持的执行类型')
            validate_config(layer, current)
            keys = ('api_base_url', 'health_path') if layer == 'api' else ('base_url', 'expected_title')
            fields.update({key: current[key] for key in keys})
        return fields

    def script(self, case, root=None):
        root = root or self.root
        content = case['content']
        project = content.get('layer', 'UI').lower()
        if project not in ('api','ui'):
            raise ValueError('不支持的执行类型')
        binding = content.get('binding') or {}
        scripts = []
        for name, digest in binding.get('files', {}).items():
            path = (root / name).resolve()
            if not path.is_relative_to((root/project/'testcases').resolve()) or not path.is_file():
                raise ValueError('规格或脚本路径无效')
            if not matches_digest(path.read_bytes(), digest):
                raise ValueError('脚本版本已变化，请重新扫描并绑定')
            if path.suffix == '.py':
                scripts.append(path)
        if len(scripts) != 1:
            raise ValueError('每条资产须绑定一个测试脚本')
        return project, scripts[0]

    def run_script(self, project, script, mode, event, root=None):
        python = self.python if project == 'ui' else self.api_python
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp)/'report.xml'
            process = subprocess.Popen([str(python), '-m','pytest',str(script),f'--junitxml={report}'],
                cwd=(root or self.root)/project, env={**os.environ,'HM_HEADED':str(int(mode=='headed'))},
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic()+self.timeout
            while process.poll() is None:
                if event.wait(.15) or time.monotonic() >= deadline:
                    if os.name == 'nt':
                        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
                    else:
                        process.kill()
                    process.wait()
                    if event.is_set():
                        return 'interrupted','execution','用户取消'
                    return 'error','timeout','执行超时'
            return classify(report, process.returncode)

    def execute(self, snapshot, folder, event, progress):
        if snapshot.get('workers',1) != 1:
            raise ValueError('执行器仅支持串行执行')
        if 'environmentConfig' not in snapshot:
            snapshot = {**snapshot, 'environmentConfig': self.freeze_environment(snapshot['environment'], snapshot['cases'])}
        with tempfile.TemporaryDirectory(prefix='health-run-') as tmp:
            return self.execute_frozen(snapshot, folder, event, progress, Path(tmp))

    def execute_frozen(self, snapshot, folder, event, progress, isolated_root):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        checkpoint(folder/'request.json', snapshot)
        rows = []
        def save(status, message):
            result = {'format':'health-v1','status':status,'results':rows,'exitCode':0 if status=='passed' else 1,'message':message}
            checkpoint(folder/'result.json', result)
            return result


        def blocked(case, exc):
            rows.append({'assetId':case['assetId'],'status':'blocked','phase':'preflight','message':str(exc)})
            return save('blocked','用例执行前检查失败')

        for case in snapshot['cases']:
            try:
                self.script(case)
            except (ValueError, OSError) as exc:
                return blocked(case, exc)
        # Preserve the relative config path used by previously published scripts.
        checkpoint(isolated_root/'config.local.json', snapshot['environmentConfig'])
        for project in {case['content'].get('layer', 'UI').lower() for case in snapshot['cases']}:
            shutil.copytree(self.root/project, isolated_root/project,
                            ignore=shutil.ignore_patterns('.venv', '__pycache__', '.pytest_cache', '.auth', 'outputs'))
        for case in snapshot['cases']:
            if event.is_set():
                return save('cancelled','用户取消')
            try:
                self.script(case)
                project, script = self.script(case, isolated_root)
            except (ValueError, OSError) as exc:
                return blocked(case, exc)
            progress('开始独立上下文执行：'+case['content']['title'])
            start = time.monotonic()
            try:
                status, phase, message = self.run_script(project, script, snapshot.get('browserMode'), event, isolated_root)
            except OSError:
                status, phase, message = 'error','launch','执行进程或报告不可用'
            rows.append({'assetId':case['assetId'],'status':status,'phase':phase,'message':message,
                         'durationSeconds':round(time.monotonic()-start,3)})
            save('interrupted','已保存完成项')
        statuses = {row['status'] for row in rows}
        if event.is_set():
            return save('cancelled','用户取消')
        if statuses == {'passed'}:
            return save('passed','全部通过')
        if statuses & {'error','failed'}:
            return save('failed','存在失败或执行错误')
        return save('incomplete','存在未执行或跳过项')
