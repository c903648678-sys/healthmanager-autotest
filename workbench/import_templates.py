"""Archive the supplied XMind files without modifying their originals."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ARCHIVE = Path(__file__).resolve().parents[1] / 'assets' / 'design-templates' / 'huawei-cloud' / 'v1'
NAMES = {
    'E2E场景测试设计模板': ('e2e', '跨角色、入口和业务流程的端到端场景；默认基础模板'),
    '接口测试设计模板': ('api', '接口参数、功能、性能、可靠性、安全及兼容性'),
    '集成测试设计模板': ('integration', '跨特性交互、数据、配置、组网与上线准入'),
    '性能测试设计模板': ('performance', '环境、负载模型、性能方法与场景指标'),
    '可靠性测试设计': ('reliability', '故障模式、典型对象、检测、降级及恢复'),
    '安全隐私测试设计模板': ('security', '通用安全、数据生命周期、隐私、白盒及 Fuzz'),
    'App测试策略模板': ('app', '移动端功能、界面、兼容、稳定性与资源消耗'),
    '车联网云服务应用设计模版': ('vehicle-cloud', '车联网云服务行业专项，仅相关需求适用'),
    '车载设备应用设计模版': ('vehicle-device', '车载设备行业专项，仅相关需求适用'),
}

def archive(source, destination=ARCHIVE):
    source, destination = Path(source), Path(destination)
    entries = []
    for path in sorted(source.glob('*.xmind')):
        template_id, scope = NAMES[path.stem]
        raw = path.read_bytes()
        with zipfile.ZipFile(path) as package:
            sheets = json.loads(package.read('content.json'))
        lines, count = [], 0
        def walk(node, depth=0):
            nonlocal count
            count += 1
            title = node.get('title', '').replace('\r', '').replace('\n', '\n' + '  ' * (depth+1))
            lines.append('  ' * depth + '- ' + title)
            note = node.get('notes', {}).get('plain', {}).get('content', '')
            if note:
                lines.append('  ' * (depth+1) + '备注：' + note)
            for children in node.get('children', {}).values():
                for child in children:
                    walk(child, depth+1)
        for sheet in sheets:
            walk(sheet['rootTopic'])
        text = '# ' + path.stem + '\n\n' + '\n'.join(lines) + '\n'
        target = destination / template_id
        target.mkdir(parents=True, exist_ok=True)
        original = target / path.name
        if original.exists() and original.read_bytes() != raw:
            raise ValueError('已归档版本不可覆盖，请创建新版本目录：' + str(original))
        shutil.copyfile(path, original)
        (target / 'outline.md').write_text(text, encoding='utf-8')
        entries.append({'id':template_id, 'name':path.stem, 'scope':scope, 'version':'1.0.0',
                        'filename':path.name, 'sha256':hashlib.sha256(raw).hexdigest(),
                        'outlineSha256':hashlib.sha256(text.encode()).hexdigest(),
                        'nodeCount':count, 'sheetCount':len(sheets)})
    manifest = {'schemaVersion':1, 'collection':'华为云测试设计模板（用户提供）',
                'source':str(source.resolve()), 'provenance':'用户提供，未另行核验官方发布版本',
                'templates':entries}
    (destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest

if __name__ == '__main__':
    import sys
    result = archive(sys.argv[1])
    print(f"Archived {len(result['templates'])} templates, {sum(t['nodeCount'] for t in result['templates'])} topics")
