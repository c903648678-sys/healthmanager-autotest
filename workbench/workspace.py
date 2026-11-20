"""Versioned, file-backed task workspace. Shares the job lock for lifecycle gates."""
from copy import deepcopy
import json
from pathlib import Path
import re
import shutil
from hashlib import sha256

from .jobs import now, TERMINAL


class Conflict(ValueError):
    pass


class Workspace:
    def __init__(self, path, jobs):
        self.path, self.jobs, self.lock = Path(path), jobs, jobs.lock
        self.disk_hash = sha256(self.path.read_bytes()).hexdigest() if self.path.exists() else None
        self.value = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {'revision': 0, 'data': None}

        self._finish_purge()

    def _finish_purge(self):
        pending=self.value.get('pendingPurge')
        if not pending:
            return
        root=self.jobs.folder.resolve()
        task_id=pending['taskId']
        if task_id not in self.value.get('deletedTaskIds',[]):
            raise Conflict('删除记录不一致，请核对工作区')
        trash = root / '.purged-jobs'
        if trash.resolve() != trash:
            raise Conflict('任务清理目录无效')
        targets = []
        for key in pending['jobIds']:
            path = root / key
            if not re.fullmatch(r'[A-Za-z0-9_-]+', key) or path.resolve() != path or path.parent != root:
                raise Conflict('任务历史目录不合法，已停止清理')
            if path.exists():
                job = json.loads((path / 'job.json').read_text(encoding='utf-8'))
                if job.get('id') != key or job.get('taskId') != task_id:
                    raise Conflict('任务历史归属不一致，已停止清理')
            targets.append((key, path))
        for key, path in targets:
            retired = trash / key
            if retired.resolve() != retired:
                raise Conflict('任务清理路径无效')
            if path.exists():
                trash.mkdir(exist_ok=True)
                path.rename(retired)
            self.jobs.jobs.pop(key, None)
            self.jobs.cancel_events.pop(key, None)
            if retired.exists():
                shutil.rmtree(retired)
        self._commit(self.value['data'])

    def _reload_external(self):
        raw = self.path.read_bytes() if self.path.exists() else None
        digest = sha256(raw).hexdigest() if raw is not None else None
        if digest == self.disk_hash:
            return False
        if raw is None:
            raise Conflict('工作区文件已在外部移除，请恢复文件后重新加载，避免覆盖。')
        value = json.loads(raw.decode('utf-8'))
        if not isinstance(value, dict) or not isinstance(value.get('revision'), int) or 'data' not in value:
            raise Conflict('外部工作区文件格式不合法，请恢复备份。')
        self.value, self.disk_hash = value, digest
        return True

    def get(self):
        with self.lock:
            self._reload_external()
            return deepcopy(self.value)

    def _commit(self, data, purge=None):
        value = {'revision': self.value['revision'] + 1, 'data': data, 'deletedTaskIds': self.value.get('deletedTaskIds', [])}
        if purge:
            value['pendingPurge']=purge
            value['deletedTaskIds']=[*value['deletedTaskIds'],purge['taskId']]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_suffix('.previous.json'))
        temp.replace(self.path)
        self.value = value
        self.disk_hash = sha256(self.path.read_bytes()).hexdigest()
        return self.get()

    def _revision(self, raw):
        if self._reload_external():
            raise Conflict('工作区已被其他页面或外部程序更新，请重新加载后台版本后再操作。')
        self._finish_purge()
        if not isinstance(raw, dict) or raw.get('revision') != self.value['revision']:
            raise Conflict('工作区已被其他页面更新。请先导出当前草稿，再重新加载后台版本；不会覆盖其他页面的数据。')

    @staticmethod
    def normalize(task):
        if not isinstance(task, dict) or not isinstance(task.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,150}', task['id']):
            raise ValueError('任务ID不合法')
        for field, limit in (('name', 80), ('version', 100), ('requirementNo', 100)):
            if not isinstance(task.get(field, ''), str) or len(task.get(field, '')) > limit:
                raise ValueError('任务名称、版本或需求单号不合法')
        if not task.get('name', '').strip():
            raise ValueError('任务名称不能为空')
        for field in ('cases', 'attempts', 'runs', 'issues'):
            if not isinstance(task.get(field), list):
                raise ValueError('任务资产或记录格式不合法')
        if 'lifecycle' not in task:
            task['lifecycle'] = {'status': 'completed' if task.get('stage') == '已完成' else 'active',
                                 'location': 'work', 'createdAt': now(), 'updatedAt': now(), 'history': []}
        return task

    def save(self, raw):
        with self.lock:
            self._revision(raw)
            data = deepcopy(raw.get('data'))
            if not isinstance(data, dict) or not isinstance(data.get('tasks'), list) or len(data['tasks']) > 1000:
                raise ValueError('工作区任务格式不合法（最多1000个任务）')
            previous = {t['id']: t for t in (self.value['data'] or {}).get('tasks', [])}
            ids = set()
            for task in data['tasks']:
                self.normalize(task)
                if task['id'] in self.value.get('deletedTaskIds', []):
                    raise Conflict('此任务已彻底删除，请重新加载后台版本，不能恢复旧任务数据。')
                if task['id'] in ids:
                    raise ValueError('任务ID重复')
                ids.add(task['id'])
                old = previous.get(task['id'])
                if old:
                    if old['lifecycle'] != task['lifecycle']:
                        raise ValueError('请通过任务管理入口修改生命周期')
                    if old['lifecycle']['status'] != 'active' or old['lifecycle']['location'] != 'work':
                        # Navigation and stale browser callbacks must not modify closed records.
                        task.clear()
                        task.update(deepcopy(old))
                else:
                    # Never accept lifecycle metadata supplied by a new/imported record.
                    task.pop('lifecycle', None)
                    self.normalize(task)
            if not set(previous) <= ids:
                raise ValueError('不能直接移除任务，请移入回收站')
            return self._commit(data)

    def assert_editable(self, task_id):
        if self.value['data'] is None:
            return  # Legacy installations can migrate their browser workspace first.
        task = next((t for t in self.value['data']['tasks'] if t['id'] == task_id), None)
        if task is None:
            raise ValueError('请先将任务保存到本地后台')
        if task['lifecycle']['status'] != 'active' or task['lifecycle']['location'] != 'work':
            raise ValueError('任务当前只读，请恢复或重新打开后操作')

    def transition(self, task_id, action, raw):
        with self.lock:
            self._revision(raw)
            data = deepcopy(self.value['data'])
            if data is None:
                raise ValueError('工作区尚未初始化')
            task = next((t for t in data['tasks'] if t['id'] == task_id), None)
            if task is None:
                raise KeyError(task_id)
            lc = task['lifecycle']
            status, location = lc['status'], lc['location']
            reason = raw.get('reason', '')
            if not isinstance(reason, str) or len(reason) > 5000:
                raise ValueError('原因或结论格式错误')
            if any(j['taskId'] == task_id and j['status'] not in TERMINAL for j in self.jobs.jobs.values()):
                raise ValueError('此任务仍有模型作业运行，请先取消并等待停止')
            if action == 'purge':
                if location != 'trash':
                    raise ValueError('只有回收站中的任务可以彻底删除')
                if raw.get('confirmName') != task['name']:
                    raise ValueError('请输入完整任务名称确认彻底删除')
                job_ids = [key for key, job in self.jobs.jobs.items() if job['taskId'] == task_id]
                root = self.jobs.folder.resolve()
                paths = [(root / key).resolve() for key in job_ids]
                if any(path.parent != root or path == root for path in paths):
                    raise ValueError('任务历史目录不合法，已停止删除')
                data['tasks'] = [item for item in data['tasks'] if item['id'] != task_id]
                self._commit(data, purge={'taskId':task_id,'jobIds':job_ids})
                self._finish_purge()
                return self.get()
            before = {'status': status, 'location': location}
            if action == 'edit':
                self.assert_editable(task_id)
                details = {}
                for field, limit in (('name',80),('requirementNo',100),('description',5000)):
                    value = raw.get(field, '')
                    if not isinstance(value,str) or len(value) > limit or (field == 'name' and not value.strip()):
                        raise ValueError('任务信息不合法')
                    details[field] = {'before':task.get(field,''), 'after':value.strip()}
                    task[field] = value.strip()
                before['fields'] = details
            elif action == 'restore' and location == 'trash':
                lc['location'] = lc.pop('previousLocation', 'work')
            elif action == 'delete' and location != 'trash':
                lc['previousLocation'] = location
                lc['location'] = 'trash'
            elif action == 'archive' and location == 'work' and status in ('completed','cancelled'):
                lc['location'] = 'archive'
            elif action == 'unarchive' and location == 'archive':
                lc['location'] = 'work'
            elif location == 'work' and action == 'pause' and status == 'active':
                lc['status'] = 'paused'
            elif location == 'work' and action in ('resume','reopen') and status in ('paused','completed','cancelled'):
                lc['status'] = 'active'
            elif location == 'work' and action == 'cancel' and status in ('active','paused'):
                if not reason.strip():
                    raise ValueError('请填写取消原因')
                lc['status'] = 'cancelled'
            elif location == 'work' and action == 'complete' and status == 'active':
                if not reason.strip():
                    raise ValueError('请填写交付结论、未完成事项与遗留风险')
                if raw.get('designOnly'):
                    case_job = self.jobs.jobs.get((task.get('caseDesigner', {}).get('job') or {}).get('id'), {})
                    if case_job.get('taskId') != task_id or case_job.get('kind') != 'test-cases' or not (case_job.get('review') or {}).get('accepted') or not self.jobs._basis_current(case_job):
                        raise ValueError('完成设计前，请先确认当前基线的整套用例')
                    if task['caseDesigner'].get('draft') != case_job['review']['draft']:
                        raise ValueError('用例仍有未确认修改')
                    plan_job = self.jobs.jobs[case_job['planJobId']]
                    analysis_job = self.jobs.jobs[plan_job['analysisJobId']]
                    planner, analyst = task.get('planner', {}), task.get('ai', {})
                    if (planner.get('draft') != plan_job['review']['draft']
                            or analyst.get('answers', []) != analysis_job['review']['answers']
                            or (planner.get('job') or {}).get('id') != plan_job['id']
                            or (analyst.get('job') or {}).get('id') != analysis_job['id']):
                        raise ValueError('任务的需求或方案存在未确认修改')
                    original = json.loads((self.jobs.folder / analysis_job['id'] / 'input.json').read_text(encoding='utf-8'))
                    sources = [{k:s.get(k) for k in ('id','name','text')} for s in task.get('sources', [])]
                    if any('localRef' in source for source in task.get('sources', [])):
                        sources = self.resolve_sources(task['sources'])
                    if sources != original['sources'] or analyst.get('instructions','') != original['instructions']:
                        raise ValueError('规格或分析范围已变化，请先重新确认设计')
                    selected = analyst.get('historyRefs', [])
                    if {(r['id'],r['hash']) for r in selected} != {(r['id'],r['hash']) for r in original.get('references', [])}:
                        raise ValueError('历史参考资产选择已变化，请重新确认设计')
                    context=original.get('designContext')
                    if context and (analyst.get('assist',{}).get('cardDraft')!=context['understanding'] or analyst.get('assist',{}).get('mappingDraft')!=context['mapping']):
                        raise ValueError('需求理解卡或资产对照草稿已变化，请重新确认设计')
                    for candidate in (planner, task['caseDesigner']):
                        if candidate.get('instructions','') != candidate.get('generationInstructions',''):
                            raise ValueError('生成约束已变化，请重新确认设计')
                lc['status'] = 'completed'
                lc['completion'] = {'designOnly':raw.get('designOnly') is True, 'conclusion':reason.strip(),
                                    'caseCount':len(task['cases']), 'confirmedCount':sum(bool(c.get('confirmed')) for c in task['cases']),
                                    'attemptCount':len(task['attempts']), 'openIssueCount':sum(i.get('status') != '已关闭' for i in task['issues'])}
            else:
                raise ValueError('当前状态不支持此操作')
            lc['updatedAt'] = now()
            if lc['status'] == 'completed':
                task['stage'] = '已完成'
            elif lc['status'] == 'active':
                task['stage'] = '执行中' if task.get('activeStep') == 'execution' else '设计中'
            lc['history'].append({'action':action, 'time':lc['updatedAt'], 'reason':reason.strip(), 'before':before,
                                  'after':{'status':lc['status'],'location':lc['location']}})
            return self._commit(data)
