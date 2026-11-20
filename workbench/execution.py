"""Append-only manual execution batches and immutable report revisions."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import base64
import json
import re
from pathlib import Path
import uuid


def stamp():
    return datetime.now(timezone.utc).isoformat()


def required(raw, key, limit=2000):
    if not isinstance(raw, dict):
        raise ValueError("Record must be an object")
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{key} 必填，且不得超过 {limit} 字')
    return value.strip()


class Execution:
    def __init__(self, folder, workspace):
        self.folder, self.workspace = Path(folder), workspace
        self.lock = workspace.lock
        self.path = self.folder / 'execution.json'
        self.value = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {'batches': [], 'reports': [], 'issues': []}

    def _save(self, value=None):
        self.folder.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.value if value is None else value, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(self.path)

    def get(self, task_id):
        with self.lock:
            return {key: deepcopy([v for v in values if v['taskId'] == task_id]) for key, values in self.value.items()}

    def task(self, task_id):
        self.workspace.assert_editable(task_id)
        tasks = (self.workspace.get()['data'] or {}).get('tasks', [])
        return next(t for t in tasks if t['id'] == task_id)

    def create(self, raw):
        with self.lock:
            task = self.task(required(raw, 'taskId', 150))
            ids = raw.get('caseIds')
            if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)):
                raise ValueError('请至少选择一条不重复的用例')
            cases = [c for c in task['cases'] if c['id'] in ids]
            if len(cases) != len(ids) or any(not c.get('confirmed') or c.get('reviewNeeded') for c in cases):
                raise ValueError('只能执行已确认且无需复核的用例')
            if any(not c.get('steps') or not c.get('expected') for c in cases):
                raise ValueError('用例必须有步骤与预期结果')
            batch = {'id': 'batch-' + uuid.uuid4().hex, 'taskId': task['id'], 'name': required(raw, 'name', 100),
                     'environment': required(raw, 'environment', 200), 'productVersion': required(raw, 'productVersion', 100),
                     'createdAt': stamp(), 'status': 'open', 'cases': deepcopy(cases), 'sources': deepcopy(task.get('sources', [])),
                     'attempts': [], 'taskName': task['name'], 'requirementNo': task.get('requirementNo', '')}
            self.value['batches'].append(batch)
            self._save()
            return deepcopy(batch)

    def _batch(self, raw):
        batch = next((b for b in self.value['batches'] if b['id'] == raw.get('batchId')), None)
        if batch is None:
            raise ValueError('批次不存在')
        self.task(batch['taskId'])
        return batch

    def record(self, raw):
        with self.lock:
            batch = self._batch(raw)
            request_id = required(raw, 'requestId', 100)
            prior = next((a for a in batch['attempts'] if a['requestId'] == request_id), None)
            if prior:
                return deepcopy(prior)
            if batch['status'] != 'open':
                raise ValueError('批次已结束；请新建批次执行')
            case = next((c for c in batch['cases'] if c['id'] == raw.get('caseId')), None)
            if case is None:
                raise ValueError('用例不属于此批次')
            result = raw.get('result')
            if result not in {'通过', '失败', '阻塞', '跳过'}:
                raise ValueError('不支持的执行结果')
            actual = str(raw.get('actual', '')).strip()
            if len(actual) > 10000 or (result != '通过' and not actual):
                raise ValueError('失败、阻塞、跳过必须填写原因（不超过 10000 字）')
            attempt = {'id': 'attempt-' + uuid.uuid4().hex, 'requestId': request_id, 'caseId': case['id'], 'result': result,
                       'actual': actual, 'at': stamp(), 'evidence': []}
            files = raw.get('files', [])
            if not isinstance(files, list) or len(files) > 3:
                raise ValueError('每次最多 3 份证据')
            pending = []
            for file in files:
                name = required(file, 'name', 200)
                if Path(name).suffix.lower() not in {'.png', '.jpg', '.jpeg', '.txt', '.log', '.json'}:
                    raise ValueError('证据仅支持 PNG、JPG、TXT、LOG、JSON')
                try:
                    content = base64.b64decode(file['base64'], validate=True)
                except (KeyError, ValueError, TypeError) as exc:
                    raise ValueError('证据编码不合法') from exc
                if not content or len(content) > 2 * 1024 * 1024:
                    raise ValueError('每份证据必须非空，且不超过 2 MB')
                file_id = uuid.uuid4().hex
                attempt['evidence'].append({'id': file_id, 'name': name, 'sha256': sha256(content).hexdigest(), 'size': len(content)})
                pending.append((file_id, content))
            evidence_dir = self.folder / 'evidence'
            evidence_dir.mkdir(parents=True, exist_ok=True)
            candidate = deepcopy(self.value)
            batch = next(b for b in candidate['batches'] if b['id'] == batch['id'])
            batch['attempts'].append(attempt)
            if result in {'失败', '阻塞'}:
                issue = next((i for i in candidate['issues'] if i['batchId'] == batch['id'] and i['caseId'] == case['id'] and i['status'] != '已关闭'), None)
                if issue is None:
                    issue = {'id': 'issue-' + uuid.uuid4().hex, 'taskId': batch['taskId'], 'batchId': batch['id'], 'caseId': case['id'],
                             'title': case['title'], 'status': '待处理', 'type': '待分类', 'attemptIds': [], 'history': []}
                    candidate['issues'].append(issue)
                issue['attemptIds'].append(attempt['id'])
            try:
                for file_id, content in pending:
                    (evidence_dir / file_id).write_bytes(content)
                self._save(candidate)
            except OSError:
                for file_id, _ in pending:
                    (evidence_dir / file_id).unlink(missing_ok=True)
                raise
            self.value = candidate
            return deepcopy(attempt)

    def close_batch(self, raw):
        with self.lock:
            batch = self._batch(raw)
            if batch['status'] != 'closed':
                batch.update(status='closed', closedAt=stamp(), conclusion=required(raw, 'conclusion', 4000))
                self._save()
            return deepcopy(batch)

    def review_issue(self, raw):
        with self.lock:
            issue = next((i for i in self.value['issues'] if i['id'] == raw.get('issueId')), None)
            if issue is None:
                raise ValueError('问题不存在')
            self.task(issue['taskId'])
            kind = raw.get('type')
            status = raw.get('status')
            if kind not in {'待分类', '产品缺陷', '环境问题', '用例问题', '数据问题', '需求疑问'} or status not in {'待处理', '处理中', '待回归', '已关闭'}:
                raise ValueError('问题分类或状态无效')
            note = required(raw, 'note', 4000)
            regression = str(raw.get('regressionAttemptId', '')).strip()
            exception = str(raw.get('nonFixReason', '')).strip()
            if status == '已关闭':
                batch = next(b for b in self.value['batches'] if b['id'] == issue['batchId'])
                attempts = batch['attempts']
                last_failure = max(n for n, a in enumerate(attempts) if a['id'] in issue['attemptIds'])
                original = next(c for c in batch['cases'] if c['id'] == issue['caseId'])
                valid = False
                for candidate in self.value['batches']:
                    same_case = next((c for c in candidate['cases'] if c['id'] == issue['caseId']), None)
                    if candidate['taskId'] != issue['taskId'] or not same_case or any(same_case.get(k) != original.get(k) for k in ('steps', 'expected')):
                        continue
                    if candidate is batch:
                        later = attempts[last_failure + 1:]
                    else:
                        later = (a for a in candidate['attempts'] if a['at'] > attempts[last_failure]['at'])
                    valid = any(a['id'] == regression and a['caseId'] == issue['caseId'] and a['result'] == '通过' for a in later)
                    if valid:
                        break
                if not valid and not exception:
                    raise ValueError('关闭需关联同一任务、相同步骤与预期、失败之后的通过尝试，或填写明确的不修复原因')
            issue.update(type=kind, status=status)
            issue['history'].append({'at': stamp(), 'status': status, 'type': kind, 'note': note, 'regressionAttemptId': regression, 'nonFixReason': exception})
            self._save()
            return deepcopy(issue)

    def freeze(self, raw):
        with self.lock:
            batch = self._batch(raw)
            if batch['status'] != 'closed':
                raise ValueError('请先结束批次，再冻结报告')
            latest = {a['caseId']: a for a in batch['attempts']}
            counts = {key: 0 for key in ['通过', '失败', '阻塞', '跳过', '未执行']}
            for case in batch['cases']:
                counts[latest.get(case['id'], {}).get('result', '未执行')] += 1
            retried = sum(1 for c in batch['cases'] if latest.get(c['id'], {}).get('result') == '通过' and any(a['caseId'] == c['id'] and a['result'] == '失败' for a in batch['attempts']))
            reports = [r for r in self.value['reports'] if r['batchId'] == batch['id']]
            report = {'id': 'report-' + uuid.uuid4().hex, 'taskId': batch['taskId'], 'batchId': batch['id'], 'revision': len(reports)+1,
                      'frozenAt': stamp(), 'batch': deepcopy(batch), 'counts': counts, 'caseCount': len(batch['cases']),
                      'executionItemCount': len(batch['cases']), 'attemptCount': len(batch['attempts']), 'retryPassedCount': retried,
                      'coverage': None, 'notes': required(raw, 'notes', 4000),
                      'issues': deepcopy([i for i in self.value['issues'] if i['batchId'] == batch['id']])}
            self.value['reports'].append(report)
            self._save()
            return deepcopy(report)

    def evidence(self, file_id):
        with self.lock:
            for batch in self.value['batches']:
                for attempt in batch['attempts']:
                    for item in attempt['evidence']:
                        if item['id'] == file_id:
                            content = (self.folder / 'evidence' / file_id).read_bytes()
                            if sha256(content).hexdigest() != item['sha256']:
                                raise ValueError('证据哈希不一致')
                            return content
            raise ValueError('证据不存在')


    def propose_feedback(self, raw):
        with self.lock:
            report = next((r for r in self.value['reports'] if r['id'] == raw.get('reportId')), None)
            if report is None:
                raise ValueError('请选择真实存在的冻结报告作为回馈依据')
            self.task(report['taskId'])
            proposal = {'id': 'feedback-' + uuid.uuid4().hex, 'taskId': report['taskId'], 'reportId': report['id'],
                        'title': required(raw, 'title', 200), 'content': required(raw, 'content', 10000),
                        'basis': required(raw, 'basis', 4000), 'status': '待审阅', 'createdAt': stamp()}
            self.value.setdefault('feedback', []).append(proposal)
            self._save()
            return deepcopy(proposal)

    def review_feedback(self, raw, knowledge):
        with self.lock:
            proposal = next((p for p in self.value.get('feedback', []) if p['id'] == raw.get('id')), None)
            if proposal is None or proposal['status'] != '待审阅':
                raise ValueError('回馈不存在或已经审阅')
            self.task(proposal['taskId'])
            decision = raw.get('decision')
            if decision not in {'已采纳', '已拒绝'}:
                raise ValueError('不支持的审阅结论')
            note = required(raw, 'note', 2000 if decision=='已采纳' else 4000)
            candidate=deepcopy(self.value)
            entry=next(p for p in candidate['feedback'] if p['id']==proposal['id'])
            entry.update(status=decision,reviewNote=note,reviewedAt=stamp())
            if decision=='已采纳':
                entry['pendingKnowledge']=True
            self._save(candidate)
            self.value=candidate
            self.resume_feedback(knowledge)
            return deepcopy(entry)

    def resume_feedback(self, knowledge):
        with self.lock, knowledge.lock:
            for proposal in self.value.get('feedback',[]):
                if not proposal.get('pendingKnowledge'):
                    continue
                if proposal.get('status')!='已采纳' or not re.fullmatch(r'feedback-[0-9a-f]{32}',proposal['id']):
                    raise ValueError('回馈恢复记录无效')
                notes=knowledge.roots['workbench-notes']
                notes.mkdir(parents=True,exist_ok=True)
                note=proposal['reviewNote']
                text = '# ' + proposal['title'] + '\n\n' + proposal['content'] + '\n\n## 依据与适用范围\n' + proposal['basis'] + '\n\n冻结报告：' + proposal['reportId'] + '\n\n审阅说明：' + note + '\n'
                path=notes/(proposal['id']+'.md')
                if not path.resolve().is_relative_to(notes.resolve()):
                    raise ValueError('回馈文件路径无效')
                temp=path.with_suffix('.tmp')
                temp.write_text(text,encoding='utf-8')
                temp.replace(path)
                catalog=knowledge.refresh()
                doc=next(d for d in catalog['documents'] if d['path']=='workbench-notes/'+path.name)
                knowledge.review({'id':doc['id'],'hash':doc['hash'],'status':'已确认','note':note})
                del proposal['pendingKnowledge']
                try:
                    self._save()
                except OSError:
                    proposal['pendingKnowledge']=True
                    raise
