"""Compile reviewed, structured case designs into ordinary pytest files."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from .source_digest import source_digest
from .workspace import Conflict


def field(data, name, limit=500):
    value = data.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'请填写有效的 {name}')
    return value


def compile_case(layer, design):
    path = field(design, 'path')
    if not path.startswith('/') or path.startswith('//') or '\\' in path or any(ord(c)<32 for c in path) or urlsplit(path).netloc:
        raise ValueError('路径须以单个 / 开头')
    lines = ['import json','import os','from pathlib import Path','']
    config = "json.loads((Path(__file__).resolve().parents[4] / 'config.local.json').read_text(encoding='utf-8'))"
    if layer == 'API':
        method = design.get('method', 'GET')
        status = design.get('status')
        if method not in ('GET','POST','PUT','PATCH','DELETE') or type(status) != int or not 100 <= status <= 599:
            raise ValueError('请检查 HTTP 方法和预期状态码')
        body = design.get('body')
        expected = design.get('expected')
        if not isinstance(expected, dict):
            raise ValueError('预期 JSON 字段须为对象，可填 {}')
        lines += ['import httpx','','','def test_generated():',f'    config = {config}',
                  "    token = os.getenv('HM_API_TOKEN')",
                  "    headers = {'Authorization': 'Bearer ' + token} if token else {}",
                  "    with httpx.Client(base_url=config['api_base_url'], headers=headers, timeout=20) as client:",
                  f'        response = client.request({method!r}, {path!r}, json={body!r})',
                  f'    assert response.status_code == {status}']
        if expected:
            lines += ['    data = response.json()',f'    for key, value in {expected!r}.items():',
                      '        assert same_json(data[key], value)', '', '',
                      'def same_json(actual, expected):',
                      '    if isinstance(actual, bool) or isinstance(expected, bool):',
                      '        return actual is expected',
                      '    if isinstance(expected, dict):',
                      '        return isinstance(actual, dict) and actual.keys() == expected.keys() and all(',
                      '            same_json(actual[key], value) for key, value in expected.items())',
                      '    if isinstance(expected, list):',
                      '        return isinstance(actual, list) and len(actual) == len(expected) and all(',
                      '            same_json(left, right) for left, right in zip(actual, expected))',
                      '    return actual == expected']
    elif layer == 'UI':
        status = design.get('status')
        if status is not None and (type(status) != int or not 100 <= status <= 599):
            raise ValueError('预期 HTTP 状态码须为 100 到 599 的整数')
        steps = design.get('steps', [])
        if not isinstance(steps,list) or len(steps)>30:
            raise ValueError('最多支持 30 个页面步骤')
        lines += ['from playwright.sync_api import expect, sync_playwright','','','def test_generated():',f'    config = {config}',
                  '    with sync_playwright() as p:',"        browser = p.chromium.launch(headless=os.getenv('HM_HEADED') != '1')",
                  '        try:',"            page = browser.new_page(base_url=config['base_url'])",f'            response = page.goto({path!r})',
                  '            assert response is not None',
                  '            assert response.ok' if status is None else f'            assert response.status == {status}']
        for step in steps:
            if not isinstance(step,dict): raise ValueError('页面步骤须为对象')
            locator = f'page.get_by_test_id({field(step,"testId")!r})'
            if step.get('action') == 'click':
                lines.append(f'            {locator}.click()')
            elif step.get('action') == 'fill' and isinstance(step.get('value'),str):
                lines.append(f'            {locator}.fill({step["value"]!r})')
            else:
                raise ValueError('支持 click 或 fill 操作')
        expected = field(design,'text')
        target = design.get('testId')
        if target:
            lines.append(f'            expect(page.get_by_test_id({field(design,"testId")!r})).to_have_text({expected!r})')
        else:
            lines.append(f'            expect(page).to_have_title({expected!r})')
        lines += ['        finally:', '            browser.close()']
    else:
        raise ValueError('选择 API 或 UI 用例')
    code = '\n'.join(lines)+'\n'
    compile(code,'test_main.py','exec')
    return code


def generate(auto, raw, root):
    with auto.lock:
        item = auto.find('assets',field(raw,'id'))
        revision = raw.get('expectedRevision')
        if item['revision'] != revision:
            raise Conflict('用例已更新，请重新生成预览')
        content = deepcopy(item['versions'][-1]['content'])
        design = raw.get('design')
        if not isinstance(design,dict): raise ValueError('缺少脚本设计')
        code = compile_case(content['layer'],design)
        spec = {'case_name':content['title'],'status':'ready','feature':content['feature'],
                'sourceAsset':item['id'],'sourceRevision':revision,'design':design}
        for key in ('steps','expected','preconditions','priority'):
            value = content['spec'].get(key,'')
            spec[key] = value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)
        metadata = json.dumps(spec,ensure_ascii=False,indent=2,sort_keys=True)+'\n'
        key = hashlib.sha256((metadata+'\0'+code).encode()).hexdigest()
        if raw.get('publish') is not True:
            return {'code':code,'digest':key}
        if raw.get('digest') != key: raise Conflict('预览已变化，请重新审阅')
        parent = Path(root)/content['layer'].lower()/'testcases'/'_generated'
        parent.mkdir(parents=True,exist_ok=True)
        target = parent/key
        files = {'test_main.py':code.encode(),'case_spec.json':metadata.encode()}
        if not target.exists():
            with TemporaryDirectory(dir=parent) as temp:
                stage = Path(temp)/'case'
                stage.mkdir()
                for name, data in files.items(): (stage/name).write_bytes(data)
                stage.rename(target)
        if any(source_digest((target/name).read_bytes())!=source_digest(data) for name,data in files.items()):
            raise Conflict('生成目录已有不同内容')
        prefix = target.relative_to(root).as_posix()
        content['binding'] = {'inventoryId':prefix,'layer':content['layer'],'admission':'静态可执行',
                              'files':{prefix+'/'+name:source_digest(data) for name,data in files.items()}}
        content['scriptDesign'] = design
        return auto._version('assets',raw,content,'asset')

def environment_form(root, raw):
    """Read/write only public test environment fields, preserving local extensions."""
    from scripts.run import validate
    path = Path(root)/'config.local.json'
    current = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    keys = ('environment','api_base_url','health_path','base_url','expected_title')
    if not isinstance(current,dict):
        raise ValueError('本地环境配置格式错误')
    if raw.get('save') is not True:
        return {key:current.get(key,'test' if key=='environment' else '') for key in keys}
    fields = raw.get('fields')
    if not isinstance(fields,dict) or set(fields)!=set(keys) or not all(isinstance(v,str) for v in fields.values()):
        raise ValueError('环境字段无效')
    config = {**current,**{k:v.strip() for k,v in fields.items()}}
    projects = [p for p,k in [('api','api_base_url'),('ui','base_url')] if config[k]]
    if not projects or not config['environment']:
        raise ValueError('请填写环境名和至少一个服务地址')
    with TemporaryDirectory(dir=root) as tmp:
        candidate = Path(tmp)/path.name
        candidate.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
        for project in projects:
            validate(project,Path(tmp))
        candidate.replace(path)
    return {'saved':True}
