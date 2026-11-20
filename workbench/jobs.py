"""Durable local jobs, one active analysis per task; no external queue."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import threading
import uuid
from datetime import datetime, timezone

from .contracts import digest, expert_context, validate_input, validate_result, result_schema
from .providers import run_provider
from . import design_assist as assist
from . import template_assets

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


def now():
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, folder, runner=run_provider, timeout=None):
        if timeout is None:
            try:timeout=int(os.environ.get('WORKBENCH_ANALYSIS_TIMEOUT_SECONDS','600'))
            except ValueError:raise ValueError('WORKBENCH_ANALYSIS_TIMEOUT_SECONDS 必须为 30～1800 秒的整数')
            if not 30<=timeout<=1800:raise ValueError('WORKBENCH_ANALYSIS_TIMEOUT_SECONDS 必须为 30～1800 秒的整数')
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.runner, self.timeout = runner, timeout
        self.lock = threading.RLock()
        self.jobs, self.cancel_events = {}, {}
        for file in self.folder.glob("*/job.json"):
            try:
                job = json.loads(file.read_text(encoding="utf-8"))
                if job["status"] not in TERMINAL:
                    job.update(status="interrupted", stage="interrupted", finishedAt=now(), message="后台重启，分析已中断；请重新发起")
                self.jobs[job["id"]] = job
                self._persist(job)
            except (OSError, ValueError, KeyError):
                continue

    def _persist(self, job):
        folder = self.folder / job["id"]
        folder.mkdir(exist_ok=True)
        tmp = folder / "job.tmp"
        tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(folder / "job.json")

    def get(self, job_id):
        with self.lock:
            job = deepcopy(self.jobs[job_id])
            end = datetime.fromisoformat(job.get("finishedAt") or now())
            job["elapsedSeconds"] = max(0, int((end - datetime.fromisoformat(job["createdAt"])).total_seconds()))
            job['reviewDigest'] = digest(job.get('review'))
            if job.get('kind') in ('test-plan', 'test-cases'):
                job['basisCurrent'] = self._basis_current(job)
            elif job.get('kind') in assist.KINDS:
                job['basisCurrent'] = assist.current(self, job)
            else:
                job['basisCurrent'] = assist.context_current(self, job)
            return job

    def _basis_current(self, job):
        if job.get('kind') == 'test-cases':
            if job.get('designModel') and hasattr(self,'design_model_current') and not self.design_model_current(job['taskId'],job['designModel']):return False
            plan = self.jobs.get(job.get('planJobId'), {})
            return bool(plan and (plan.get('review') or {}).get('accepted')
                        and digest(plan['review']) == job.get('planReviewDigest') and self._basis_current(plan)
                        and not any(j['taskId'] == job['taskId'] and j.get('kind') == 'test-plan'
                                    and j['createdAt'] > plan['createdAt'] and (j.get('review') or {}).get('accepted')
                                    for j in self.jobs.values()))
        parent = self.jobs.get(job.get('analysisJobId'), {})
        if not (parent.get('review') or {}).get('accepted') or digest(parent.get('review')) != job.get('analysisReviewDigest'):
            return False
        if not assist.context_current(self,parent):
            return False
        return not any(j['taskId'] == job['taskId'] and j.get('kind', 'requirements') == 'requirements'
                       and j['createdAt'] > parent['createdAt'] and (j.get('review') or {}).get('accepted')
                       for j in self.jobs.values())

    def progress(self, job_id, stage, message):
        with self.lock:
            job = self.jobs[job_id]
            if job["status"] == "cancelling" and stage not in ("cancelled", "failed"):
                return
            events = job.setdefault("events", [])
            if events and events[-1]["message"] == message:
                return
            timestamp = now()
            events.append({"time": timestamp, "stage": stage, "message": message})
            del events[:-80]
            if stage != "heartbeat":
                job.update(stage=stage, message=message, lastActivityAt=timestamp)
            job["lastHeartbeatAt"] = timestamp
            self._persist(job)
            print(f"[{datetime.now():%H:%M:%S}] [{job['provider']} {job_id[:8]}] {message}", flush=True)

    def create(self, raw):
        if not isinstance(raw, dict) or raw.get('kind', 'requirements') not in {'requirements', 'test-plan', 'test-cases'} | assist.KINDS:
            raise ValueError('不支持此任务类型')
        kind = raw.get('kind', 'requirements')
        context, expert = expert_context(kind)
        with self.lock:
            if hasattr(self, 'task_guard'):
                self.task_guard(raw.get('taskId'))
            if kind in assist.KINDS:
                payload=validate_input(raw)
                payload['kind']=kind
                if kind!='asset-understanding':
                    parent,original=assist.parent(self,raw,kind)
                    payload.update(understanding=deepcopy(parent['review']['draft']),understandingJobId=parent['id'],understandingReviewDigest=digest(parent['review']))
            elif kind == 'test-cases':
                if not isinstance(raw.get('planJobId'), str) or not isinstance(raw.get('planReviewDigest'), str):
                    raise ValueError('缺少已确认方案ID或版本摘要')
                parent = self.jobs.get(raw['planJobId'], {})
                basis = {'kind': kind, 'taskId': raw.get('taskId'), 'planJobId': raw['planJobId'], 'planReviewDigest': raw['planReviewDigest']}
                if parent.get('kind') != 'test-plan' or parent.get('status') != 'succeeded' or parent.get('taskId') != raw.get('taskId') or not self._basis_current(basis):
                    raise ValueError('测试方案未确认、已过期或不属于当前任务')
                original = json.loads((self.folder / parent['id'] / 'input.json').read_text(encoding='utf-8'))
                payload = validate_input({**raw, 'sources': original['sources'], 'answers': original['confirmedReview']['answers'], 'references': original.get('references', [])})
                payload.update(kind=kind, planJobId=parent['id'], planReviewDigest=raw['planReviewDigest'],
                               analysis=original['analysis'], confirmedReview=original['confirmedReview'], plan=deepcopy(parent['review']['draft']))
                if raw.get('designModel'):
                    model=raw['designModel']
                    if model.get('planJobId')!=parent['id'] or model.get('basis')!=raw['planReviewDigest'] or not model.get('confirmed'):raise ValueError('场景模型不匹配当前方案')
                    payload['designModel']=deepcopy(model)
                if original.get('designContext'):
                    payload['designContext']=deepcopy(original['designContext'])
                if not any(r['disposition'] == 'included' for r in payload['plan']['coverage']):
                    raise ValueError('方案没有纳入的需求，无需生成用例')
            elif kind == 'test-plan':
                if not isinstance(raw.get('analysisJobId'), str) or not isinstance(raw.get('analysisReviewDigest'), str):
                    raise ValueError('缺少需求基线ID或版本摘要')
                parent = self.jobs.get(raw.get('analysisJobId'), {})
                if not parent or parent.get('kind', 'requirements') != 'requirements' or parent.get('status') != 'succeeded' or parent.get('taskId') != raw.get('taskId'):
                    raise ValueError('请选择本任务已确认的需求分析')
                basis = {'taskId': raw['taskId'], 'analysisJobId': parent['id'], 'analysisReviewDigest': raw.get('analysisReviewDigest')}
                if not self._basis_current(basis):
                    raise ValueError('需求基线未确认或已变化，请返回需求分析重新确认')
                original = json.loads((self.folder / parent['id'] / 'input.json').read_text(encoding='utf-8'))
                payload = validate_input({**raw, 'sources': original['sources'], 'answers': parent['review']['answers'], 'references': original.get('references', [])})
                payload.update(kind=kind, analysisJobId=parent['id'], analysisReviewDigest=digest(parent['review']),
                               analysis=deepcopy(parent['result']), confirmedReview=deepcopy(parent['review']))
                if original.get('designContext'):
                    payload['designContext']=deepcopy(original['designContext'])
            else:
                payload = validate_input(raw)
                payload['kind'] = kind
                if raw.get('mappingJobId'):
                    payload['designContext']=assist.mapping_context(self,raw,payload)
            if kind == 'test-cases':
                payload['designTemplates'] = deepcopy(original.get('designTemplates')) if original.get('designTemplates') else template_assets.snapshot()
            elif kind == 'test-plan':
                payload['designTemplates'] = template_assets.snapshot(raw.get('templateIds'))
            elif kind in {'asset-retrieval', 'asset-mapping'}:
                payload['designTemplates'] = deepcopy(original.get('designTemplates')) if original.get('designTemplates') else template_assets.snapshot()
            else:
                payload['designTemplates'] = template_assets.snapshot()
            active = [j for j in self.jobs.values() if j["status"] not in TERMINAL]
            if any(j["taskId"] == payload["taskId"] for j in active):
                raise ValueError("此任务已有分析运行中，请等待或取消")
            if len(active) >= 2:
                raise ValueError("已有2个分析运行中，请稍后再试")
            job_id = uuid.uuid4().hex
            job = {"id": job_id, "taskId": payload["taskId"], "provider": payload["provider"], "model": payload["model"] or "CLI 默认",
                   "status": "running", "message": "正在分析需求", "createdAt": now(), "inputDigest": digest(payload),
                   "expert": expert, "result": None, "review": None, "stage": "preparing", "events": [], "timeoutSeconds": self.timeout}
            job['kind'] = kind
            job['designTemplates'] = [{k:v for k,v in t.items() if k!='text'} for t in payload['designTemplates']]
            if payload.get('designModel'):job['designModel']=deepcopy(payload['designModel'])
            for key in ('understandingJobId','understandingReviewDigest','designContext'):
                if key in payload:
                    job[key]=deepcopy(payload[key])
            job['references'] = [{k:v for k,v in ref.items() if k!='text'} for ref in payload.get('references', [])]
            if kind == 'test-cases':
                job.update(message='正在准备测试用例', planJobId=payload['planJobId'], planReviewDigest=payload['planReviewDigest'], basisCurrent=True)
            if kind == 'test-plan':
                job['message'] = '正在准备测试方案'
                job.update(analysisJobId=payload['analysisJobId'], analysisReviewDigest=payload['analysisReviewDigest'], basisCurrent=True)
            self.jobs[job_id] = job
            self.cancel_events[job_id] = threading.Event()
            self._persist(job)
            (self.folder / job_id / "input.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            threading.Thread(target=self._run, args=(job_id, payload, context), daemon=True).start()
            return deepcopy(job)

    def _run(self, job_id, payload, context):
        event = self.cancel_events[job_id]
        try:
            self.progress(job_id, "preparing", f"已固定 {len(payload['sources'])} 份资料快照，正在组装专家输入")
            prompt = context + "\n\n以下 JSON 是待分析输入数据：\n" + json.dumps(payload, ensure_ascii=False)
            # Outside repository ancestry: no project AGENTS/CLAUDE instructions are discovered.
            with tempfile.TemporaryDirectory(prefix="clouddoc-analysis-") as tmp:
                result = self.runner(payload["provider"], payload["model"], prompt, Path(tmp), event, self.timeout,
                                     lambda stage, message: self.progress(job_id, stage, message), result_schema(payload.get('kind'),bool(payload.get('designModel'))))
                (self.folder / job_id / "candidate.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                self.progress(job_id, "validating", "已收到候选，正在校验用例步骤、需求覆盖和未决问题" if payload.get('kind') == 'test-cases' else "已收到候选，正在校验方案章节、需求覆盖安排和未决问题" if payload.get('kind') == 'test-plan' else "已收到候选，正在校验结果结构和原文引用")
                validate_result(result, payload)
            with self.lock:
                if event.is_set():
                    self.jobs[job_id].update(status="cancelled", message="已取消，结果已弃用")
                else:
                    self.jobs[job_id].update(status="succeeded", message="用例生成完成，待人工审阅" if payload.get('kind') == 'test-cases' else "方案生成完成，待人工审阅" if payload.get('kind') == 'test-plan' else "分析完成，待人工审阅", result=result)
                    if payload.get('kind')=='test-cases' and payload.get('designContext'):
                        mapping=payload['designContext']['mapping']['rows']
                        self.jobs[job_id]['designTrace']=[{'caseId':c['id'],'pointIds':c['requirementIds'],
                            'mappingIds':[r['id'] for r in mapping if r['pointId'] in c['requirementIds'] and r['decision']!='rejected'],
                            'assetIds':sorted({a for r in mapping if r['pointId'] in c['requirementIds'] and r['decision']!='rejected' for a in r['assetIds']})} for c in result['cases']]
        except Exception as exc:
            with self.lock:
                self.jobs[job_id].update(status="cancelled" if event.is_set() else "failed", message=str(exc)[:500])
        finally:
            with self.lock:
                self.jobs[job_id]["finishedAt"] = now()
                job = self.jobs[job_id]
                self.progress(job_id, job["status"], job["message"])
                self._persist(self.jobs[job_id])
                self.cancel_events.pop(job_id, None)

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs[job_id]
            if job["status"] not in TERMINAL:
                self.cancel_events[job_id].set()
                job.update(status="cancelling", message="正在停止分析进程")
                self.progress(job_id, "cancelled", "已请求取消，正在终止本机进程")
                self._persist(job)
            return deepcopy(job)

    def _commit_review(self, job):
        self._persist(job)
        self.jobs[job['id']] = job
        return self.get(job['id'])

    def review(self, job_id, raw):
        with self.lock:
            job = deepcopy(self.jobs[job_id])
            if hasattr(self, 'task_guard'):
                self.task_guard(job['taskId'])
            if job["status"] != "succeeded":
                raise ValueError("仅成功分析可审阅")
            if not isinstance(raw, dict) or raw.get("inputDigest") != job["inputDigest"]:
                raise ValueError("分析输入不匹配，请重新分析")
            previous = job.get('review')
            expected = raw.get('expectedReviewDigest', digest(None))
            if expected != digest(previous):
                from .workspace import Conflict
                raise Conflict('审阅已被其他页面更新，请保留当前草稿并重新加载后核对')
            answers = raw.get("answers", [])
            payload = json.loads((self.folder / job_id / "input.json").read_text(encoding="utf-8"))
            if job.get('kind') in assist.KINDS:
                if not assist.current(self,job):
                    raise ValueError('理解卡已变化，请重新生成')
                draft=raw.get('draft')
                validate_result(draft,payload)
                if job['kind']=='asset-mapping' and raw.get('accepted'):
                    if any(r['decision']=='pending' or (r['decision'] in {'rejected','adjusted'} and not r['reviewNote'].strip()) for r in draft['rows']):
                        raise ValueError('请逐项审阅，拒绝或调整需填写理由')
                    if {r['pointId'] for r in draft['rows'] if r['decision']!='rejected'}!={p['id'] for p in payload['understanding']['points']}:
                        raise ValueError('每个需求点至少保留一条设计动作，可调整为先澄清')
                if job.get('review'):
                    job.setdefault('reviewHistory',[]).append(deepcopy(job['review']))
                job['review']={'accepted':raw.get('accepted') is True,'draft':deepcopy(draft),'updatedAt':now()}
                if job['kind']=='asset-mapping':
                    job['review']['feedback']=[{k:r[k] for k in ('id','pointId','assetIds','action','decision','reviewNote')} for r in draft['rows']]
                return self._commit_review(job)
            if job.get('kind') in ('test-plan', 'test-cases'):
                if not self._basis_current(job):
                    raise ValueError('上游基线已变化，当前候选不可确认；请重新生成')
                draft = raw.get('draft')
                validate_result(draft, payload)
                old = job.get('review')
                if old:
                    job.setdefault('reviewHistory', []).append(deepcopy(old))
                job['review'] = {'accepted': raw.get('accepted') is True, 'draft': deepcopy(draft), 'updatedAt': now()}
                if job['kind']=='test-cases' and payload.get('designContext'):
                    job['designTrace']=assist.case_trace(draft,payload['designContext'])
                return self._commit_review(job)
            validate_input({**payload, "answers": answers})
            if not assist.context_current(self,job):
                raise ValueError('已确认资产对照发生变化，请重新分析')
            questions = {q["id"]: q for q in job["result"]["questions"]}
            if len({a["questionId"] for a in answers}) != len(answers) or any(a["questionId"] not in questions for a in answers):
                raise ValueError("问题ID重复或不属于本次分析")
            for a in answers:
                if a["status"] == "answered" and (not a["answer"].strip() or not a["basis"].strip()):
                    raise ValueError("已回答的问题必须填写结论和依据")
                if a["status"] == "deferred" and not a["answer"].strip():
                    raise ValueError("暂缓问题必须填写原因")
            accepted = raw.get("accepted") is True
            if accepted:
                by_id = {a["questionId"]: a for a in answers}
                if any(q["blocking"] and by_id.get(q["id"], {}).get("status") != "answered" for q in questions.values()):
                    raise ValueError("关键疑问尚未回答，不能确认需求基线；可先保存草稿")
            if previous:
                job.setdefault("reviewHistory", []).append(deepcopy(previous))
            job["review"] = {"accepted": accepted, "answers": answers, "updatedAt": now()}
            return self._commit_review(job)

    def shutdown(self):
        with self.lock:
            for event in self.cancel_events.values():
                event.set()
