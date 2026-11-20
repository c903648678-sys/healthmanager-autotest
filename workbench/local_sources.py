"""References to user-selected files on the workbench host."""
import json
import os
from pathlib import Path
import subprocess
from itertools import islice
import sys
from threading import Lock
from uuid import uuid4

from .contracts import ROOT

FORMATS = {'.docx', '.xlsx', '.pptx', '.doc', '.xls', '.ppt', '.pdf', '.md', '.markdown', '.txt'}
MAX_TEXT = 200 * 1024
MAX_FILE = 30 * 1024 * 1024


def pick_paths(mode):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    try:
        if mode == 'folder':
            folder = filedialog.askdirectory(parent=root, title='选择规格文件夹', mustexist=True)
            return [folder] if folder else []
        return list(filedialog.askopenfilenames(parent=root, title='选择规格文件',
                       filetypes=[('支持的文档', ' '.join('*'+ext for ext in sorted(FORMATS)))]))
    finally:
        root.destroy()


class LocalSources:
    def __init__(self, folder):
        self.path = Path(folder) / 'source-links.json'
        self.links = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
        self.lock = Lock()
        self.picker = Lock()

    def pick(self, mode):
        if mode not in ('files', 'folder'):
            raise ValueError('请选择文件或文件夹')
        if not self.picker.acquire(blocking=False):
            raise ValueError('已有文件选择窗口打开')
        try:
            result = subprocess.run(
                [sys.executable, '-X', 'utf8', '-m', 'workbench.local_sources', '--pick', mode],
                cwd=ROOT, capture_output=True, encoding='utf-8', timeout=240,
            )
            if result.returncode:
                raise ValueError('无法打开本机文件选择窗口，请在工作台所在的桌面运行服务')
            paths = [Path(path) for path in json.loads(result.stdout)]
            if mode == 'folder' and paths:
                folder = paths[0].resolve()
                paths = list(islice((p for p in folder.rglob('*') if p.suffix.lower() in FORMATS
                                     and p.is_file() and p.resolve().is_relative_to(folder)), 501))
            if len(paths) > 500:
                raise ValueError('所选内容包含超过 500 份文档，请选择更小的文件夹')
            return self.register(sorted(paths))
        finally:
            self.picker.release()

    def register(self, paths):
        with self.lock:
            links = dict(self.links)
            existing = {(item['path'], item['mtime'], item['size']): ref for ref, item in links.items()}
            added = []
            for path in dict.fromkeys(path.resolve() for path in paths):
                if path.name.startswith('~$') or path.suffix.lower() not in FORMATS or not path.is_file():
                    continue
                info = path.stat()
                key = (str(path), info.st_mtime_ns, info.st_size)
                ref = existing.get(key) or uuid4().hex
                links[ref] = dict(path=str(path), mtime=info.st_mtime_ns, size=info.st_size)
                added.append(dict(localRef=ref, path=str(path), name=path.name, size=info.st_size))
            if added:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix('.tmp')
                temporary.write_text(json.dumps(links, ensure_ascii=False), encoding='utf-8')
                temporary.replace(self.path)
                self.links = links
            return added

    def read(self, ref):
        with self.lock:
            link = self.links.get(ref) if isinstance(ref, str) else None
        if not link:
            raise ValueError('本机引用不存在，请重新选择文件')
        path = Path(link['path'])
        def verify():
            try:
                info = path.stat()
            except OSError as exc:
                raise ValueError(f'{path.name} 不可访问，请重新选择文件') from exc
            if (info.st_mtime_ns, info.st_size) != (link['mtime'], link['size']):
                raise ValueError(f'{path.name} 已变化，请移除旧引用并重新选择')
        verify()
        if link['size'] > MAX_FILE:
            raise ValueError(f'{path.name} 超过 30 MB，请拆分后再引用')
        if path.suffix.lower() in ('.md', '.markdown', '.txt'):
            text = path.read_text(encoding='utf-8-sig')
        else:
            interpreter = ROOT/'api/.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
            if not interpreter.exists():
                raise ValueError('请先运行 python scripts/bootstrap.py --project api 安装文档读取依赖')
            result = subprocess.run([str(interpreter), '-X', 'utf8', '-m', 'workbench.source_extract', str(path)],
                                    cwd=ROOT, capture_output=True, encoding='utf-8', timeout=45)
            if result.returncode:
                raise ValueError(f'{path.name}：{result.stdout.strip() or "无法提取文档文本"}')
            text = result.stdout
        verify()
        if not text.strip() or '\0' in text:
            raise ValueError(f'{path.name} 没有可读取的文本。扫描版 PDF 请先进行 OCR')
        if len(text.encode('utf-8')) > MAX_TEXT:
            raise ValueError(f'{path.name} 提取文本超过 200 KB，请拆分后再引用')
        return {'name':path.name, 'text':text}

    def materialize(self, sources):
        if not isinstance(sources, list) or len(sources)>10:
            raise ValueError('每个任务最多引用 10 份资料')
        resolved = []
        for source in sources:
            if not isinstance(source, dict):
                raise ValueError('资料引用格式无效')
            if 'localRef' in source:
                resolved.append({'id':source.get('id'), **self.read(source['localRef'])})
            else:
                resolved.append({key:source.get(key) for key in ('id','name','text')})
        return resolved


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--pick':
        print(json.dumps(pick_paths(sys.argv[2]), ensure_ascii=False))
