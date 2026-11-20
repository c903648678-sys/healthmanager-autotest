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
    for spec_path in sorted((root/'testcases').rglob('case_spec.json')):
        spec=json.loads(spec_path.read_text(encoding='utf-8'))
        script=spec_path.parent/'test_main.py'
        relative=spec_path.parent.relative_to(root).as_posix()
        ready=script.is_file() and spec.get('status')=='ready'
        rows.append({'assetId':'ui/'+relative,'id':spec_path.parent.name,
            'title':spec['case_name'],'product':'健康管理','feature':spec.get('feature','基础冒烟'),
            'layer':'UI','specPath':'ui/'+relative+'/case_spec.json',
            'scriptPath':'ui/'+relative+'/test_main.py','suiteTier':'smoke',
            'admission':'静态可执行' if ready else '待完善','reason':'环境在执行前检查',
            'shared':False,**{k:spec.get(k,'') for k in ('steps','expected','preconditions','priority')}})
    return {'scannedAt':datetime.now(timezone.utc).isoformat(),'cases':rows,
        'sources':[{'product':'健康管理','path':'ui/testcases','status':'connected'}],
        'errors':[],'apiConnected':False,'_cache':{}}


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
