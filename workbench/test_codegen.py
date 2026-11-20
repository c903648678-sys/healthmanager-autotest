import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from .contracts import ROOT
from .server import make_server


class ScriptDesignFlow(unittest.TestCase):
    def test_preview_publish_execute_and_report(self):
        class Product(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                body = b'{"ready":true}' if self.path == '/health' else b'<title>Test</title><button data-testid="go" onclick="this.textContent=\'Done\'">Start</button>'
                self.send_header('Content-Type','application/json' if self.path=='/health' else 'text/html')
                self.send_header('Content-Length',str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        with TemporaryDirectory() as tmp, ThreadingHTTPServer(('127.0.0.1',0),Product) as product:
            root = Path(tmp)
            wb = make_server(0,root/'storage')
            wb.automation.executor.root = root
            wb.automation.executor.ui = root/'ui'
            workers = [Thread(target=s.serve_forever,daemon=True) for s in (product,wb)]
            for thread in workers: thread.start()
            url = f'http://127.0.0.1:{wb.server_port}'
            product_url = f'http://127.0.0.1:{product.server_port}'

            def request(route, data=None):
                req = Request(url+'/api/automation/'+route,
                              data=json.dumps(data).encode() if data is not None else None,
                              headers={'Content-Type':'application/json'})
                with urlopen(req) as response:
                    return json.load(response)

            try:
                request('environment-config',{'save':True,'fields':{'environment':'fixture','api_base_url':product_url,
                        'health_path':'/health','base_url':product_url,'expected_title':'Test'}})
                for layer,design in [('API',dict(path='/health',method='GET',status=200,expected={'ready':True})),
                                     ('UI',dict(path='/',steps=[{'action':'click','testId':'go'}],testId='go',text='Done'))]:
                    content = {'title':layer+' fixture','product':'健康管理','subproduct':'测试','feature':'基础',
                               'spec':{'steps':'测试','expected':'通过'},'layer':layer,'source':{},'binding':None}
                    asset = wb.automation._version('assets',{},content,'asset')
                    payload = {'id':asset['id'],'expectedRevision':1,'design':design}
                    preview = request('generate',payload)
                    self.assertFalse((root/layer.lower()/'testcases').exists())
                    with self.assertRaises(HTTPError) as conflict:
                        request('generate',{**payload,'publish':True,'digest':'stale'})
                    self.assertEqual(conflict.exception.code,409)
                    published = request('generate',{**payload,'publish':True,'digest':preview['digest']})
                    self.assertEqual(published['revision'],2)
                    suite = request('suite',{'layer':layer,'name':layer,'cases':[{'assetId':asset['id'],'revision':2}]})
                    run = request('start',{'suiteId':suite['id'],'suiteRevision':1,'environment':'fixture'})
                    for _ in range(300):
                        run = request('runs/'+run['id'])
                        if run.get('finishedAt'): break
                        time.sleep(.1)
                    self.assertEqual(run['status'],'passed',run.get('message'))
                    self.assertEqual(run['report']['counts'],{'passed':1})
            finally:
                for server in (wb,product): server.shutdown()
                wb.store.shutdown()
                wb.server_close()
                for thread in workers: thread.join()
