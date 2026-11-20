"""Offline maintenance: python -m workbench.maintenance verify-backup FILE.zip."""
import argparse
import json
from pathlib import Path
from zipfile import ZipFile
from .backup import verify_backup


def restore_to(archive_path, destination):
    content=Path(archive_path).read_bytes()
    manifest=verify_backup(content)
    destination=Path(destination).resolve()
    if destination.exists():
        raise ValueError('恢复目标必须是不存在的新目录；不会覆盖现有工作区')
    destination.mkdir(parents=True)
    try:
        with ZipFile(archive_path) as archive:
            for name in manifest['files']:
                target=(destination/name).resolve()
                if not target.is_relative_to(destination):
                    raise ValueError('恢复路径越界')
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(archive.read(name))
    except Exception:
        # Keep partial files for diagnosis. Never recursively delete operator-specified paths.
        raise
    return {'destination':str(destination),'files':len(manifest['files']),'status':'restored-to-new-folder'}


def main():
    parser=argparse.ArgumentParser(description='工作台备份校验与隔离恢复（不覆盖当前数据）')
    sub=parser.add_subparsers(dest='action',required=True)
    check=sub.add_parser('verify-backup');check.add_argument('archive')
    restore=sub.add_parser('restore-to');restore.add_argument('archive');restore.add_argument('destination')
    args=parser.parse_args()
    try:
        result=verify_backup(Path(args.archive).read_bytes()) if args.action=='verify-backup' else restore_to(args.archive,args.destination)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (OSError,ValueError,KeyError) as exc:
        parser.exit(1,str(exc)+'\n')

if __name__=='__main__':
    main()
