"""Health product adapter for the migrated versioned execution workbench."""
import hashlib
import json
import os
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from .ui_execution import UIExecutor
from .contracts import ROOT
from scripts.run import validate

class HealthExecutor(UIExecutor):
    supports_pause = False

    def login_action(self,raw):
        raise ValueError("产品登录机制尚未提供，暂未接入登录态管理")

    def environments(self):
        path=self.root/'config.local.json'
        if not path.exists():
            return {'environments':[], 'error':'尚未配置健康管理测试环境，请填写 config.local.json'}
        config=json.loads(path.read_text(encoding='utf-8'))
        try: validate('ui')
        except ValueError as exc: return {'environments':[], 'error':str(exc)}
        return {'environments':[{'id':config.get('environment','test'),'name':'健康管理测试环境','product':'健康管理','baseUrl':config['base_url']}]}

    def execute(self,snapshot,folder,event,progress):
        validate('ui')
        if snapshot['environment'] not in [e['id'] for e in self.environments()['environments']]:
            raise ValueError('执行环境不存在')
        if snapshot.get('workers',1)!=1:
            raise ValueError('健康管理执行器当前支持串行执行，请将并发数设为 1')
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        (folder/'request.json').write_text(json.dumps(snapshot,ensure_ascii=False),encoding='utf-8')
        rows=[]
        for index,case in enumerate(snapshot['cases']):
            if event.is_set():break
            binding=case['content'].get('binding')
            if not binding:raise ValueError('用例尚未绑定测试脚本')
            scripts=[]
            for name,digest in binding['files'].items():
                path=(self.root/name).resolve()
                if not path.is_relative_to((self.root/'ui/testcases').resolve()) or not path.is_file():
                    raise ValueError('脚本路径无效')
                if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('脚本版本已变化，请重新扫描并绑定')
                if path.suffix=='.py':scripts.append(path)
            if len(scripts)!=1:raise ValueError('每条资产须对应一个测试脚本')
            report=folder/f'case-{index}.xml'
            progress('开始独立上下文执行：'+case['content']['title'])
            # Output bodies are intentionally not persisted; JUnit is used only to classify results.
            with open(os.devnull,'w') as log:
                process=subprocess.Popen([str(self.python),'-m','pytest',str(scripts[0]),'-q',f'--junitxml={report}'],cwd=self.ui,stdout=log,stderr=log,
                    env={**os.environ,'HM_HEADED':'1' if snapshot.get('browserMode')=='headed' else '0'},
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                deadline=time.monotonic()+600
                while process.poll() is None:
                    if event.wait(0.2) or time.monotonic()>deadline:
                        if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
                        else:process.kill()
                        process.wait();break
            status='failed'
            if event.is_set():status='interrupted'
            elif process.returncode==0 and report.exists():
                cases=ET.parse(report).getroot().findall('.//testcase')
                status='passed' if cases and all(not any(c.find(tag) is not None for tag in ('failure','error','skipped')) for c in cases) else 'incomplete'
            rows.append({'assetId':case['assetId'],'title':case['content']['title'],'status':status,'message':'pytest 退出码：'+str(process.returncode)})
            if report.exists():report.unlink()
        status='cancelled' if event.is_set() else 'passed' if len(rows)==len(snapshot['cases']) and all(r['status']=='passed' for r in rows) else 'failed'
        result={'status':status,'results':rows,'exitCode':0 if status=='passed' else 1,'message':'健康管理 pytest 执行完成'}
        (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
        return result
