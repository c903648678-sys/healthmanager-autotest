import json
import tempfile
import unittest
from pathlib import Path
from .ui_inventory import scan

class InventoryTests(unittest.TestCase):
    def test_health_asset_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'testcases/home';folder.mkdir(parents=True)
            spec=folder/'case_spec.json'
            spec.write_text(json.dumps({'case_name':'Synthetic home','status':'ready'}))
            self.assertEqual(scan(root)['cases'][0]['admission'],'待完善')
            (folder/'test_main.py').write_text('def test_home(): pass')
            self.assertEqual(scan(root)['cases'][0]['admission'],'静态可执行')
            self.assertEqual(scan(root)['cases'][0]['product'],'健康管理')
            spec.unlink()
            self.assertEqual(scan(root)['cases'],[])

    def test_bad_specs_and_empty_scripts_leave_valid_assets_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'ui'
            for name, spec, code in [('bad','{',''),('empty','{"case_name":"empty","status":"ready"}','x=1'),
                                     ('valid','{"case_name":"ok","status":"ready"}','def test_ok(): pass')]:
                folder = root/'testcases'/name
                folder.mkdir(parents=True)
                (folder/'case_spec.json').write_text(spec)
                (folder/'test_main.py').write_text(code)
            result = scan(root)
            self.assertEqual(len(result['errors']),2)
            self.assertEqual([row['id'] for row in result['cases'] if row['admission']=='静态可执行'],['valid'])
