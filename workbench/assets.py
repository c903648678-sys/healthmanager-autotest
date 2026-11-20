"""On-demand read-only inventory; failures never replace a successful snapshot."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from .contracts import ROOT
from .asset_history import advance, public_history
from .ui_execution import ui_python


class Assets:
    def __init__(self, folder=None):
        self.lock = threading.Lock()
        self.history = None
        self.cache_path = Path(folder or ROOT / '.local/workbench') / 'ui-assets-cache.json'
        self.value = {'scannedAt': None, 'cases': [], 'sources': [], 'errors': [], 'apiConnected': False}
        try:
            stored = json.loads(self.cache_path.read_text(encoding='utf-8'))
            if isinstance(stored.get('snapshot', {}).get('cases'), list):
                self.value = stored['snapshot']
                self.history = stored.get('history')
        except (OSError, ValueError, AttributeError):
            pass

    def get(self):
        # Snapshots are replaced atomically, never mutated during a refresh.
        return self.value

    def refresh(self):
        with self.lock:
            interpreter = ui_python(ROOT)
            result = subprocess.run(
                [str(interpreter) if interpreter.is_file() else sys.executable, '-B', str(Path(__file__).with_name('ui_inventory.py')), str(self.cache_path)],
                cwd=ROOT, capture_output=True, encoding='utf-8', errors='replace', timeout=90,
                env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'},
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
            if result.returncode:
                raise ValueError('UI 用例扫描失败，请检查 UI 工程依赖和目录：' + result.stderr[-1200:])
            value = json.loads(result.stdout)
            cache = value.pop('_cache')
            history = advance(self.history, self.value, value)
            value['weekly'] = public_history(history)
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.cache_path.with_suffix('.tmp')
            temporary.write_text(json.dumps({'snapshot': value, 'cache': cache, 'history': history}, ensure_ascii=False), encoding='utf-8')
            temporary.replace(self.cache_path)
            self.value = value
            self.history = history
            return self.value
