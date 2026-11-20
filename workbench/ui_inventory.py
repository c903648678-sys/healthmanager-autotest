"""Read-only UI adapter, run in a subprocess to isolate UI dependencies."""
import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time


def script_has_skip(content):
    tree=ast.parse(content.decode('utf-8-sig'))
    return any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr in {'skip','skipif'} for node in ast.walk(tree))


def scan(root, cache=None):
    root=Path(root).resolve()
    rows=[]
    errors = []
    sources = []
    for project, directory in [('ui', root), ('api', root.parent / 'api')]:
        tree = directory / 'testcases'
        sources.append({'product':'健康管理','path':project+'/testcases','status':'connected' if tree.is_dir() else 'missing'})
        for spec_path in sorted(tree.rglob('case_spec.json')):
            prefix = project + '/' + spec_path.parent.relative_to(directory).as_posix()
            row = {'assetId':prefix,'id':spec_path.parent.name,'title':spec_path.parent.name,
                   'product':'健康管理','feature':'基础冒烟','layer':project.upper(),
                   'specPath':prefix+'/case_spec.json','scriptPath':prefix+'/test_main.py',
                   'suiteTier':'smoke','admission':'待完善','reason':'','shared':False}
            try:
                spec = json.loads(spec_path.read_text(encoding='utf-8-sig'))
                if not isinstance(spec, dict) or not isinstance(spec.get('case_name'), str) or not spec['case_name'].strip():
                    raise ValueError('缺少有效的 case_name')
                row.update(title=spec['case_name'])
                for key in ('feature','steps','expected','preconditions','priority'):
                    if key in spec:
                        if not isinstance(spec[key], str): raise ValueError(key+' 应为文本')
                        row[key] = spec[key]
                nodes = ast.parse(spec_path.with_name('test_main.py').read_bytes()).body
                candidates = list(nodes)
                for node in nodes:
                    if isinstance(node, ast.ClassDef) and node.name.startswith('Test'):
                        candidates.extend(node.body)
                if not any(isinstance(fn, ast.FunctionDef) and fn.name.startswith('test') for fn in candidates):
                    raise ValueError('未发现测试函数或方法')
                if spec.get('status') == 'ready':
                    row.update(admission='静态可执行', reason='运行时由 pytest 收集')
            except (OSError, ValueError, SyntaxError) as exc:
                row['reason'] = str(exc)
                errors.append({'path':row['specPath'],'error':str(exc)})
            rows.append(row)
    return {'scannedAt':datetime.now(timezone.utc).isoformat(),'cases':rows,
            'sources':sources,'errors':errors,'apiConnected':sources[1]['status']=='connected','_cache':{}}


if __name__ == '__main__':
    # Older running workbenches invoke this entry point with their own Python.
    # Resolve the UI environment before loading any UI dependencies.
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from workbench.ui_execution import ui_python
    interpreter = ui_python(root)
    if interpreter.is_file() and Path(sys.prefix).resolve() != (root / 'ui/.venv').resolve():
        import subprocess
        raise SystemExit(subprocess.call([str(interpreter), '-B', __file__, *sys.argv[1:]]))
    sys.stdout.reconfigure(encoding='utf-8')
    cache = None
    if len(sys.argv) > 1:
        try:
            cache = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')).get('cache')
        except (OSError, ValueError, AttributeError, TypeError):
            pass
    print(json.dumps(scan(Path(__file__).resolve().parents[1] / 'ui', cache), ensure_ascii=False))
