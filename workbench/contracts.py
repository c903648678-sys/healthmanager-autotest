"""Provider-neutral input/output contract and evidence checks."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


STR = {"type": "string"}
REF = obj({"sourceId": STR, "quote": STR})
REFS = {"type": "array", "items": REF}
SCHEMA = obj({
    "summary": STR,
    "requirements": {"type": "array", "items": obj({"id": STR, "title": STR, "understanding": STR, "acceptance": STR, "citations": REFS})},
    "questions": {"type": "array", "items": obj({"id": STR, "title": STR, "reason": STR, "impact": STR, "blocking": {"type": "boolean"}, "suggestion": STR, "citations": REFS})},
    "risks": {"type": "array", "items": obj({"title": STR, "impact": STR, "testDirection": STR, "citations": REFS})},
    "warnings": {"type": "array", "items": STR},
})

PLAN_FIELDS = ("title", "objective", "scope", "outOfScope", "strategy", "environmentAndData", "entryCriteria", "exitCriteria", "risksAndDependencies")
PLAN_SCHEMA = obj({**{key: STR for key in PLAN_FIELDS},
    "coverage": {"type": "array", "items": obj({"requirementId": STR, "disposition": {"type": "string", "enum": ["included", "deferred", "excluded"]}, "approach": STR, "reason": STR})},
    "openItems": {"type": "array", "items": obj({"questionId": STR, "handling": STR})},
})


CASE_SCHEMA = obj({"title": STR, "cases": {"type": "array", "items": obj({
    "id": STR, "group": STR, "title": STR,
    "requirementIds": {"type": "array", "items": STR},
    "layer": {"type": "string", "enum": ["UI", "API", "端侧", "手工"]},
    "priority": {"type": "string", "enum": ["P0", "P1", "P2"]},
    "preconditions": STR, "testData": STR,
    "steps": {"type": "array", "items": obj({"action": STR, "expected": STR})},
    "cleanup": STR, "dependencies": STR,
})}, "openItems": {"type": "array", "items": obj({"questionId": STR, "handling": STR})}})


def result_schema(kind="requirements", design_model=False):
    from .design_assist import SCHEMAS
    if kind in SCHEMAS:
        return SCHEMAS[kind]
    if kind=='test-cases' and design_model:
        from copy import deepcopy
        schema=deepcopy(CASE_SCHEMA);case=schema['properties']['cases']['items']
        case['properties'].update(scenarioId=STR,testPointIds={'type':'array','items':STR})
        case['required']+=['scenarioId','testPointIds']
        return schema
    return {"test-plan": PLAN_SCHEMA, "test-cases": CASE_SCHEMA}.get(kind, SCHEMA)


def validate_cases(result, payload):
    validate_shape(result, result_schema('test-cases',bool(payload.get('designModel'))))
    if not result['title'].strip() or not result['cases']:
        raise ValueError('用例集名称和用例不能为空')
    included = {r['requirementId'] for r in payload['plan']['coverage'] if r['disposition'] == 'included'}
    covered, ids = set(), set()
    for c in result['cases']:
        if payload.get('designModel'):
            scene=next((s for s in payload['designModel']['scenarios'] if s['id']==c['scenarioId']),None)
            if not scene or not c['testPointIds'] or not set(c['testPointIds'])<={p['id'] for p in scene['points']} or not set(c['requirementIds'])<=set(scene['requirementIds']):
                raise ValueError('用例的场景、测试点或需求关联无效')
        if any(not c[k].strip() for k in ('id', 'group', 'title', 'preconditions', 'testData', 'cleanup', 'dependencies')):
            raise ValueError('用例字段不能为空；不适用的字段请注明无')
        if c['id'] in ids:
            raise ValueError('用例ID重复')
        ids.add(c['id'])
        refs = set(c['requirementIds'])
        if not refs or len(refs) != len(c['requirementIds']) or not refs <= included:
            raise ValueError('用例只能关联方案已纳入的需求，且不得重复引用')
        covered |= refs
        if not c['steps'] or any(not s['action'].strip() or not s['expected'].strip() for s in c['steps']):
            raise ValueError('每条用例必须包含操作及逐步预期')
    if payload.get('designModel'):
        expected={(s['id'],p['id']) for s in payload['designModel']['scenarios'] for p in s['points']}
        actual={(c['scenarioId'],p) for c in result['cases'] for p in c['testPointIds']}
        if actual!=expected:raise ValueError('用例遗漏已确认测试点')
    if covered != included:
        raise ValueError('方案纳入的需求存在用例覆盖遗漏')
    items = result['openItems']
    if len(items) != len({i['questionId'] for i in items}) or {i['questionId'] for i in items} != {i['questionId'] for i in payload['plan']['openItems']} or any(not i['handling'].strip() for i in items):
        raise ValueError('必须保留方案中的未决问题及处理安排')
    return result


def validate_plan(result, payload):
    validate_shape(result, PLAN_SCHEMA)
    if any(not result[key].strip() for key in PLAN_FIELDS):
        raise ValueError("方案章节不能为空；无相关内容请明确说明原因")
    requirements = {r['id'] for r in payload['analysis']['requirements']}
    rows = result['coverage']
    if len(rows) != len(requirements) or {r['requirementId'] for r in rows} != requirements:
        raise ValueError("每个需求点必须有且仅有一条覆盖安排")
    for row in rows:
        if not row['approach'].strip() or not row['reason'].strip():
            raise ValueError("覆盖安排需填写验证方向和纳入/排除/暂缓原因")
    deferred = {a['questionId'] for a in payload['confirmedReview']['answers'] if a['status'] == 'deferred'}
    answered = {a['questionId'] for a in payload['confirmedReview']['answers'] if a['status'] == 'answered'}
    unresolved = {q['id'] for q in payload['analysis']['questions']} - answered
    items = result['openItems']
    if len(items) != len({i['questionId'] for i in items}) or {i['questionId'] for i in items} != unresolved | deferred or any(not i['handling'].strip() for i in items):
        raise ValueError("未决疑问必须逐项保留处理安排，不得遗漏或编造问题ID")
    return result


def validate_shape(value, schema=SCHEMA, path="result"):
    """Validate the complete subset of JSON Schema used by this contract."""
    kind = schema["type"]
    expected = {"object": dict, "array": list, "string": str, "boolean": bool}[kind]
    if type(value) is not expected:
        raise ValueError(f"{path} 类型错误")
    if kind == "object":
        if set(value) != set(schema["properties"]):
            raise ValueError(f"{path} 字段缺失或存在额外字段")
        for key, child in schema["properties"].items():
            validate_shape(value[key], child, f"{path}.{key}")
    elif kind == "array":
        if len(value) > 200:
            raise ValueError(f"{path} 条目超过200条")
        for child in value:
            validate_shape(child, schema["items"], path + "[]")
    elif kind == "string" and len(value) > 20000:
        raise ValueError(f"{path} 内容过长")
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(f"{path} 值不在允许范围内")


def validate_result(result, payload):
    from .design_assist import KINDS, validate
    if payload.get('kind') in KINDS:
        return validate(result, payload)
    if payload.get('kind') == 'test-cases':
        return validate_cases(result, payload)
    if payload.get('kind') == 'test-plan':
        return validate_plan(result, payload)
    validate_shape(result)
    sources = {s["id"]: s["text"] for s in payload["sources"]}
    current_ids = set(sources)
    sources.update({s['id']: s['text'] for s in payload.get('references', [])})
    if not result["summary"].strip() or not (result["requirements"] or result["questions"]):
        raise ValueError("分析为空：需返回需求点或澄清问题")
    if payload.get('designContext') and {r['id'] for r in result['requirements']}!={p['id'] for p in payload['designContext']['understanding']['points']}:
        raise ValueError('需求分析必须保留理解卡的全部需求点 ID')
    for group in ("requirements", "questions", "risks"):
        ids = set()
        for item in result[group]:
            if not item["title"].strip():
                raise ValueError("条目标题为空")
            if group != "risks":
                key = item["id"]
                if not key or key in ids:
                    raise ValueError("需求或问题 ID 为空/重复")
                ids.add(key)
            if group == "requirements" and not item["citations"]:
                raise ValueError("需求点缺少原文引用")
            if group == 'requirements' and not any(ref['sourceId'] in current_ids for ref in item['citations']):
                raise ValueError('需求点必须引用当前规格，不能只凭历史资产生成需求')
            if group == 'risks' and item['title'].startswith(('【历史冲突】', '【影响分析】', '【复用建议】')):
                historical_ids = {r['id'] for r in payload.get('references', [])}
                if not any(ref['sourceId'] in historical_ids for ref in item['citations']):
                    raise ValueError('历史审视结论缺少历史资产原文引用')
            for ref in item["citations"]:
                if not ref["quote"].strip() or ref["quote"] not in sources.get(ref["sourceId"], ""):
                    raise ValueError("引用不存在或原文不匹配；候选未进入审阅")
    return result


def validate_input(raw):
    if not isinstance(raw, dict):
        raise ValueError("请求必须为对象")
    provider = raw.get("provider", "codex")
    if provider not in ("codex", "claude"):
        raise ValueError("不支持此模型供应商")
    sources = raw.get("sources")
    if not isinstance(sources, list) or not 1 <= len(sources) <= 10:
        raise ValueError("请选择1至10份规格")
    cleaned, ids = [], set()
    for s in sources:
        if not isinstance(s, dict) or any(not isinstance(s.get(k), str) for k in ("id", "name", "text")):
            raise ValueError("资料字段错误")
        if not s["id"] or s["id"] in ids or not s["text"].strip():
            raise ValueError("资料ID重复或内容为空")
        if len(s["text"].encode()) > 200 * 1024:
            raise ValueError("单份资料超过200KB")
        ids.add(s["id"])
        cleaned.append({k: s[k] for k in ("id", "name", "text")})
    if sum(len(s["text"].encode()) for s in cleaned) > 1024 * 1024:
        raise ValueError("资料总计超过1MB")
    task_id = raw.get("taskId", "")
    instructions = raw.get("instructions", "")
    model = raw.get("model", "")
    if not all(isinstance(v, str) for v in (task_id, instructions, model)) or len(instructions) > 10000 or len(task_id) > 150 or len(model) > 150:
        raise ValueError("任务或模型字段错误")
    if not task_id:
        raise ValueError("缺少任务ID")
    answers = raw.get("answers", [])
    if not isinstance(answers, list) or len(answers) > 200:
        raise ValueError("人工结论格式错误")
    for a in answers:
        if not isinstance(a, dict) or set(a) != {"questionId", "question", "status", "answer", "basis"} or any(not isinstance(v, str) or len(v) > 10000 for v in a.values()):
            raise ValueError("人工结论字段错误")
        if a["status"] not in ("answered", "deferred"):
            raise ValueError("人工结论状态错误")
    references = raw.get('references', [])
    reference_limit = 24 if raw.get('kind')=='asset-retrieval' else 8
    if not isinstance(references, list) or len(references)>reference_limit:
        raise ValueError(f'最多 {reference_limit} 份历史参考资产')
    for ref in references:
        if not isinstance(ref, dict) or any(not isinstance(ref.get(k), str) for k in ('id','name','text','hash')) or not ref['id'].startswith('history:') or len(ref['text'])>18000:
            raise ValueError('历史参考资产格式错误')
        if ref['id'] in ids:
            raise ValueError('参考资产 ID 重复')
        ids.add(ref['id'])
    return {"taskId": task_id, "provider": provider, "model": model, "sources": cleaned, "instructions": instructions, "answers": answers, 'references':references}


def expert_context(kind="requirements"):
    from .design_assist import PROMPTS
    from .template_assets import GUIDANCE
    if kind in PROMPTS:
        content = PROMPTS[kind] + '\n' + GUIDANCE
        return content, {'id':kind,'name':'测序资产驱动测试设计专家','version':'1.1.0','digest':digest(content),'references':[]}
    folder = ROOT / "experts" / ({"test-plan": "test-planner", "test-cases": "test-case-designer"}.get(kind, "requirements-analyst"))
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    parts = [(folder / manifest["prompt"]).read_text(encoding="utf-8")]
    for ref in manifest["references"]:
        source = (ROOT / ref["path"]).resolve()
        if not source.is_relative_to(ROOT):
            raise ValueError("专家引用越界")
        text = source.read_text(encoding="utf-8")
        # Fail closed on upstream heading drift, never silently omit rules.
        start = text.index(ref["start"])
        end = text.index(ref["end"], start)
        parts.append(f"\n参考方法（{ref['path']}）：\n" + text[start:end])
    content = "\n".join(parts) + '\n' + GUIDANCE
    return content, {"id": manifest["id"], "name": manifest["name"], "version": manifest["version"], "digest": digest(content), "references": manifest["references"]}
