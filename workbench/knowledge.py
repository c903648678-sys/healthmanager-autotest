"""Local knowledge catalog: originals stay in place; reviewed hashes and snapshots persist."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock
from datetime import datetime, timezone


class Knowledge:
    def __init__(self, folder, roots):
        self.folder = Path(folder)
        self.roots = {name: Path(path).resolve() for name, path in roots.items()}
        self.lock = RLock()
        self.path = self.folder / 'catalog.json'
        self.value = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {'documents': [], 'refreshedAt': None}
        self.organization_path = self.folder / 'organization.json'
        self.organization = json.loads(self.organization_path.read_text(encoding='utf-8')) if self.organization_path.exists() else {'revision':0,'meta':{},'local':[]}

    def organization_get(self):
        with self.lock:return deepcopy(self.organization)

    def organization_save(self, raw):
        from .workspace import Conflict
        with self.lock:
            if raw.get('revision') != self.organization['revision']:raise Conflict('产品知识已在其他页面更新，请刷新后重试')
            meta,local=raw.get('meta'),raw.get('local')
            if not isinstance(meta,dict) or not isinstance(local,list) or len(meta)>2000 or len(local)>500:raise ValueError('资料信息格式或数量无效')
            for identity,fields in meta.items():
                if not isinstance(identity,str) or not isinstance(fields,dict) or any(not isinstance(v,str) or len(v)>500 for v in fields.values()):raise ValueError('资料信息字段无效')
            total=0;seen=set();clean=[]
            previous={d['id']:d for d in self.organization['local']}
            for doc in local:
                if not isinstance(doc,dict) or not isinstance(doc.get('id'),str) or not doc['id'].startswith('local-') or doc['id'] in seen:raise ValueError('导入资料标识无效')
                seen.add(doc['id'])
                text=doc.get('text');name=doc.get('name')
                if not isinstance(text,str) or not text.strip() or '\x00' in text or not isinstance(name,str) or len(name)>250 or Path(name).suffix.lower() not in {'.md','.markdown','.txt'}:raise ValueError('仅支持有效 Markdown / TXT 资料')
                size=len(text.encode('utf-8'));total+=size
                if size>200*1024 or total>1024*1024:raise ValueError('导入资料每份最多 200 KB，合计最多 1 MB')
                old=previous.get(doc['id'])
                if old:
                    if old['text']!=text or old['name']!=name:raise ValueError('不能覆盖已归档资料正文，请导入新资料')
                    clean.append(deepcopy(old))
                else:clean.append({'id':doc['id'],'name':name,'path':name,'text':text,'hash':sha256(text.encode('utf-8')).hexdigest(),'feature':'未分类','local':True,'revision':1,'history':[],'size':size,'sizeLabel':f'{size/1024:.1f} KB','status':'待确认','change':'新增','missing':False})
            if not set(previous)<=seen:raise ValueError('请保留已归档资料；可通过审阅标记失效')
            self.organization={'revision':self.organization['revision']+1,'meta':deepcopy(meta),'local':clean}
            self._save_organization()
            return self.organization_get()

    def _save_organization(self):
        self.folder.mkdir(parents=True,exist_ok=True)
        temp=self.organization_path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.organization,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(self.organization_path)

    def _save(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.value, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(self.path)

    def get(self):
        with self.lock:
            docs=deepcopy(self.value['documents']+self.organization['local'])
            for doc in docs:
                meta=self.organization['meta'].get(doc['id'],{})
                doc['metadata']=deepcopy(meta)
            return {**deepcopy(self.value), 'documents':docs,'roots': {k: str(v) for k, v in self.roots.items()}}

    def refresh(self):
        with self.lock:
            old = {d['path']: d for d in self.value['documents']}
            found, errors, total = [], [], 0
            for label, root in self.roots.items():
                if not root.is_dir():
                    errors.append(f'{label}: 目录不存在')
                    continue
                for path in sorted(root.rglob('*')):
                    if path.suffix.lower() not in {'.md', '.markdown', '.txt'} or not path.is_file():
                        continue
                    key = label + '/' + path.relative_to(root).as_posix()
                    try:
                        # Symlinks/junctions may never expose files outside an admitted root.
                        if not path.resolve().is_relative_to(root):
                            raise ValueError('链接指向目录外，已跳过')
                        if path.stat().st_size > 200 * 1024:
                            raise ValueError('超过 200 KB，已跳过')
                        raw = path.read_bytes()
                        total += len(raw)
                        if len(found) >= 500 or total > 10 * 1024 * 1024:
                            raise ValueError('扫描额度已满（500 份 / 10 MB）')
                        text = raw.decode('utf-8-sig')
                        if not text.strip() or '\x00' in text:
                            raise ValueError('不是有效 UTF-8 文本')
                        digest = sha256(raw).hexdigest()
                        previous = old.get(key)
                        # Preserve identity for an unambiguous move with unchanged content.
                        if previous is None:
                            matches = [d for d in old.values() if d['hash'] == digest and not self._exists(d['path'])]
                            if len(matches) == 1:
                                previous = matches[0]
                        changed = previous is None or previous['hash'] != digest
                        doc = deepcopy(previous) if previous else {'id': 'doc-' + sha256(key.encode()).hexdigest()[:20], 'revision': 0, 'history': []}
                        if changed:
                            if previous:
                                doc['history'].append({k: previous.get(k) for k in ('revision', 'hash', 'text', 'status', 'reviewNote')})
                            doc['revision'] += 1
                            doc['status'] = '待确认'
                            doc['reviewNote'] = ''
                        doc.update(name=path.name, path=key, feature=label + '/' + path.relative_to(root).parent.as_posix(), hash=digest,
                                   text=text, size=len(raw), sizeLabel=f'{len(raw)/1024:.1f} KB', missing=False,
                                   change='新增' if previous is None else '已更新' if changed else '未变化')
                        found.append(doc)
                    except (OSError, UnicodeError, ValueError) as exc:
                        errors.append(f'{key}: {exc}')
            seen = {d['id'] for d in found}
            for previous in old.values():
                if previous['id'] not in seen:
                    doc = deepcopy(previous)
                    doc.update(missing=True, change='不可读取')
                    found.append(doc)
            self.value = {'documents': found, 'errors': errors, 'refreshedAt': datetime.now(timezone.utc).isoformat()}
            self._save()
            return self.get()

    def _exists(self, key):
        label, relative = key.split('/', 1)
        return label in self.roots and (self.roots[label] / relative).is_file()

    def review(self, raw):
        with self.lock:
            doc = next((d for d in self.value['documents']+self.organization['local'] if d['id'] == raw.get('id')), None)
            if doc is None:
                raise KeyError('资料不存在')
            if doc['hash'] != raw.get('hash') or doc.get('missing'):
                raise ValueError('资料版本已变化或不可读取，请刷新后确认')
            if raw.get('status') not in {'待确认', '已确认', '已失效'}:
                raise ValueError('不支持的知识状态')
            note = str(raw.get('note', '')).strip()
            if not note or len(note) > 2000:
                raise ValueError('请填写确认依据（1 至 2000 字）')
            doc.update(status=raw['status'], reviewNote=note, reviewedAt=datetime.now(timezone.utc).isoformat())
            if doc.get('local'):
                self.organization['revision']+=1;self._save_organization()
            else:self._save()
            return self.get()
