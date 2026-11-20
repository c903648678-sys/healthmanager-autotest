"""Invoke a persisted execution plan from Windows Task Scheduler or a CI step."""
import argparse
import os
import json
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--plan',required=True);parser.add_argument('--build',default=os.environ.get('BUILD_ID') or os.environ.get('BUILD_NUMBER') or os.environ.get('CI_PIPELINE_ID') or os.environ.get('GITHUB_RUN_ID') or '')
    parser.add_argument('--port',type=int,default=8878);parser.add_argument('--wait',action='store_true')
    parser.add_argument('--timeout',type=int,default=3900)
    args=parser.parse_args();base=f'http://127.0.0.1:{args.port}'
    def call(path,data=None):
        request=Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
        with urlopen(request,timeout=30) as response:return json.load(response)
    try:
        run=call('/api/automation/start',{'planId':args.plan,'build':args.build});print(run['id'],flush=True)
        if not args.wait:return 0
        until=time.monotonic()+args.timeout
        while run['status'] in ('preparing','running','cancelling') and time.monotonic()<until:
            time.sleep(2);run=call('/api/automation/runs/'+run['id'])
        print(json.dumps({'id':run['id'],'status':run['status'],'counts':run['counts'],'message':run['message']},ensure_ascii=False))
        return 0 if run['status']=='passed' else 1 if run['status']=='failed' else 2
    except HTTPError as exc:print(exc.read().decode('utf-8',errors='replace'));return 2
    except (URLError,OSError,ValueError) as exc:print(str(exc));return 2

if __name__=='__main__':raise SystemExit(main())
