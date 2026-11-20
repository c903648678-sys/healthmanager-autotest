"""Local deterministic retrieval; historical evidence never becomes a new requirement."""
import json
import re
from .contracts import digest


def terms(text):
    tokens = re.findall(r'[a-z0-9_]{2,}|[\u4e00-\u9fff]+', text.lower())
    result = []
    for word in tokens:
        result.extend([word] if word.isascii() else [word[i:i+2] for i in range(len(word)-1)])
    for group in (('字段','列','column'),('新增','创建','新建','添加'),('重命名','改名','名称'),('权限','授权','只读','编辑者'),('删除','移除'),('导入','import'),('导出','export')):
        if any(word in text.lower() for word in group):
            result.extend(group)
    return list(dict.fromkeys(result))[:160]


class HistorySearch:
    def __init__(self, knowledge, assets, workspace, store, execution=None):
        self.knowledge, self.assets, self.workspace, self.store = knowledge, assets, workspace, store
        self.execution=execution

    def catalog(self, task_id):
        rows = []
        def add(key, name, text, kind, path='', product='', feature='', status='', revision=''):
            if not text.strip():
                return
            entry = dict(id='history:'+key, name=name, text=text[:18000], kind=kind, path=path,
                         product=product, feature=feature, status=status, revision=str(revision), excerpt=len(text)>18000)
            entry['hash'] = digest(entry)
            rows.append(entry)
        for doc in self.knowledge.get()['documents']:
            if not doc.get('missing'):
                meta=doc.get('metadata',{})
                feature='/'.join(filter(None,[meta.get('subproduct'),meta.get('feature')])) or doc.get('feature','')
                add('doc/'+doc['id'], meta.get('title') or doc['name'], doc['text'], '知识规格', doc['path'],
                    meta.get('product') or doc.get('product', ''), feature, doc.get('status', '待确认'), doc.get('revision', ''))
        for case in self.assets.get().get('cases', []):
            text = '\n'.join(f'{name}：{case.get(key, "")}' for key, name in
                             [('id','用例编号'),('title','名称'),('preconditions','前置条件'),('steps','步骤'),('expected','预期'),('admission','脚本状态'),('reason','状态说明')])
            add(case['assetId'], case['title'], text, 'UI 用例', case['specPath'], case['product'],
                case['feature'], case['admission'], digest(text)[:12])
        tasks = {t['id']: t for t in (self.workspace.get().get('data') or {}).get('tasks', [])}
        for task in tasks.values():
            if task['id']==task_id or task.get('lifecycle',{}).get('location')=='trash':
                continue
            for case in task.get('cases',[]):
                if not case.get('confirmed') or case.get('reviewNeeded') or case.get('retired') or case.get('status')=='已失效':
                    continue
                add('design-case/'+task['id']+'/'+case['id'],case['title'],json.dumps(case,ensure_ascii=False),'设计用例',
                    '任务/'+task['id']+'/'+case['id'],case.get('product') or task.get('product',''),case.get('feature') or task.get('feature',''),
                    '人工已确认设计（不代表已实现或执行）',digest(case)[:12])
        with self.store.lock:
            jobs = list(self.store.jobs.values())
        for job in jobs:
            task = tasks.get(job.get('taskId'))
            if not task or task['id'] == task_id or task.get('lifecycle', {}).get('location') == 'trash':
                continue
            review = job.get('review') or {}
            if not review.get('accepted'):
                continue
            if job.get('kind')=='asset-mapping':
                parent=next((j for j in jobs if j['id']==job.get('understandingJobId')), {})
                card=(parent.get('review') or {}).get('draft',{})
                add('feedback/'+job['id'],task['name']+' · 资产审阅反馈',json.dumps(review.get('feedback',[]),ensure_ascii=False),
                    '审阅反馈','任务/'+task['id'],card.get('product',''),card.get('subproduct',''),'人工审阅（仅适用于原需求上下文）',review.get('updatedAt',''))
            if job.get('kind') != 'test-plan' or job.get('status') != 'succeeded':
                continue
            add('plan/'+job['id'], task['name']+' · 已确认测试方案', json.dumps(review['draft'], ensure_ascii=False),
                '历史测试方案', '任务/'+task['id'], task.get('product', ''), task.get('feature', ''),
                '历史已确认（需核对适用版本）', review.get('updatedAt', ''))
        if self.execution:
            with self.execution.lock:
                from copy import deepcopy
                execution=deepcopy(self.execution.value)
            batches={b['id']:b for b in execution['batches']}
            for issue in execution['issues']:
                task=tasks.get(issue['taskId'])
                if not task or task.get('lifecycle',{}).get('location')=='trash':
                    continue
                batch=batches.get(issue['batchId'],{})
                attempts=[{k:a.get(k) for k in ('id','caseId','result','at','actual','note')} for a in batch.get('attempts',[]) if a['id'] in issue.get('attemptIds',[])]
                add('issue/'+issue['id'],issue['title'],json.dumps({'issue':issue,'attempts':attempts,'environment':batch.get('environment'),'productVersion':batch.get('productVersion')},ensure_ascii=False),
                    '历史缺陷/问题','问题/'+issue['id'],task.get('product',''),task.get('feature',''),issue['type']+' / '+issue['status'],digest(issue)[:12])
            for report in execution['reports']:
                task=tasks.get(report['taskId'])
                if not task or task.get('lifecycle',{}).get('location')=='trash':
                    continue
                batch=report['batch']
                evidence={'environment':batch['environment'],'productVersion':batch['productVersion'],'cases':batch['cases'],
                          'attempts':[{k:a.get(k) for k in ('id','caseId','result','at','actual','note')} for a in batch['attempts']],
                          'counts':report['counts'],'notes':report['notes'],'frozenAt':report['frozenAt']}
                add('execution/'+report['id'],batch['name']+' · 执行报告',json.dumps(evidence,ensure_ascii=False),'执行证据',
                    '报告/'+report['id'],task.get('product',''),task.get('feature',''),'已冻结（特定环境/版本）',report['revision'])
        if getattr(self,'automation',None):
            state=self.automation.get()
            for asset in state['assets']:
                case=asset['versions'][-1]['content']
                add('formal/'+asset['id'],case['title'],json.dumps(case,ensure_ascii=False),'正式用例','正式用例/'+asset['id'],case['product'],case['feature'],'正式资产（需核对适用版本）',asset['revision'])
            for run in state['runs']:
                if not run.get('finishedAt') or not run.get('executed'):continue
                evidence={k:run.get(k) for k in ('id','name','product','environment','build','counts','results','report','finishedAt')}
                add('auto-run/'+run['id'],run['name']+' · 自动化执行',json.dumps(evidence,ensure_ascii=False),'执行证据','自动化运行/'+run['id'],run['product'],'','本轮独立上下文记录（非发布批准）',run['id'])
        return rows

    def search(self, raw):
        if not isinstance(raw, dict):
            raise ValueError('检索参数错误')
        product, feature, query = (raw.get(k, '') for k in ('product','feature','query'))
        if any(not isinstance(v, str) for v in (product,feature,query)) or len(query)>16000 or len(feature)>200 or len(product)>100:
            raise ValueError('检索范围过长或格式错误')
        if raw.get('refresh') or not self.knowledge.get().get('refreshedAt'):
            self.knowledge.refresh()
        keywords = terms(feature+' '+query)
        found = []
        for entry in self.catalog(raw.get('taskId')):
            if product and entry['product'] and product != entry['product']:
                continue
            title = (entry['name']+' '+entry['path']+' '+entry['feature']).lower()
            body = entry['text'].lower()
            hits = [word for word in keywords if word in title or word in body]
            score = sum(4 if word in title else 1 for word in hits)
            if feature and feature.lower() in title:
                score += 20
            if not score:
                continue
            if product and entry['product'] == product:
                score += 10
            found.append({**entry, 'score': score, 'reason': '匹配关键词：'+ '、'.join(hits[:6])+
                          ('；产品归属待核实' if not entry['product'] else '；'+entry['product'])})
        found.sort(key=lambda row: (-row['score'], row['id']))
        # Diversity prevents thousands of script matches from hiding specifications.
        chosen = []
        budgets={'知识规格':4,'历史测试方案':3,'UI 用例':3,'设计用例':3,'历史缺陷/问题':3,'执行证据':3,'审阅反馈':2,'正式用例':3}
        for kind, limit in budgets.items():
            chosen.extend([r for r in found if r['kind']==kind][:limit])
        chosen.sort(key=lambda row: (-row['score'], row['id']))
        return {'items': chosen, 'total':len(found), 'method':'本地关键词匹配（非语义检索）',
                'knowledgeAt':self.knowledge.get().get('refreshedAt'), 'assetsAt':self.assets.get().get('scannedAt')}

    def resolve(self, raw):
        selected = raw.get('historyRefs', [])
        if not isinstance(selected, list) or len(selected)>8:
            raise ValueError('最多选择 8 份历史参考资产')
        if not selected:
            return []
        self.knowledge.refresh()
        catalog = {r['id']: r for r in self.catalog(raw.get('taskId'))}
        result, seen = [], set()
        for ref in selected:
            if not isinstance(ref, dict) or not isinstance(ref.get('id'), str):
                raise ValueError('历史资产选择格式错误')
            entry = catalog.get(ref['id'])
            if not entry or entry['hash'] != ref.get('hash'):
                raise ValueError('历史资产已变化或不可用，请重新检索并选择')
            if entry['id'] in seen:
                raise ValueError('历史资产重复')
            seen.add(entry['id'])
            result.append(entry)
        return result
