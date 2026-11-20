"""Bounded local backup with checksums; archives contain data, never executable restore hooks."""
from hashlib import sha256
import io
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile, ZIP_DEFLATED


def backup(folder):
    root=Path(folder).resolve()
    output=io.BytesIO();manifest={'format':'healthmanager-workbench-backup','version':1,'files':{}}
    total=0
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob('*')):
            if not path.is_file() or not path.resolve().is_relative_to(root):
                continue
            key=path.relative_to(root).as_posix()
            if key not in {'workspace.json','workspace.previous.json','ui-assets-cache.json'} and key.split('/')[0] not in {'jobs','knowledge','execution','automation'}:
                continue
            if key.startswith('knowledge/suggestions/'):
                continue
            if path.name.startswith('.') or path.suffix=='.tmp':
                continue
            content=path.read_bytes();total+=len(content)
            if total>100*1024*1024 or len(manifest['files'])>=10000:
                raise ValueError('备份超过 100 MB 或 10000 文件，请先人工归档证据')
            manifest['files'][key]={'sha256':sha256(content).hexdigest(),'size':len(content)}
            archive.writestr(key,content)
        archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    return output.getvalue()


def verify_backup(content):
    if len(content)>110*1024*1024:
        raise ValueError('备份文件过大')
    with ZipFile(io.BytesIO(content)) as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)) or len(names)>10001:
            raise ValueError('备份存在重复成员或文件过多')
        for info in archive.infolist():
            path=PurePosixPath(info.filename)
            if path.is_absolute() or '..' in path.parts or '\\' in info.filename or ':' in info.filename or info.file_size>100*1024*1024:
                raise ValueError('备份成员路径或大小不合法')
        if sum(i.file_size for i in archive.infolist())>101*1024*1024:
            raise ValueError('备份展开后过大')
        manifest=json.loads(archive.read('manifest.json'))
        if manifest.get('format')!='healthmanager-workbench-backup' or manifest.get('version')!=1:
            raise ValueError('备份格式不受支持')
        if set(names)!=set(manifest['files'])|{'manifest.json'}:
            raise ValueError('备份清单不完整')
        for key,expected in manifest['files'].items():
            raw=archive.read(key)
            if len(raw)!=expected['size'] or sha256(raw).hexdigest()!=expected['sha256']:
                raise ValueError('备份校验失败：'+key)
        return manifest
