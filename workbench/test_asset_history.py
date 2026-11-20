import unittest
import tempfile
from pathlib import Path
from .backup import backup, verify_backup
from .asset_history import advance, public_history, week_key


def snap(at, *ids, status='connected'):
    return {'scannedAt': at, 'sources': [{'product': 'DocZip', 'status': status}],
            'cases': [{'assetId': key, 'id': key, 'title': key, 'product': 'DocZip',
                       'feature': 'ai_table/column', 'suiteTier': 'smoke', 'admission': '静态可执行'} for key in ids]}


class HistoryTests(unittest.TestCase):
    def test_history_included_in_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'ui-assets-cache.json').write_text('{"history":{}}', encoding='utf-8')
            self.assertIn('ui-assets-cache.json', verify_backup(backup(folder))['files'])

    def test_baseline_week_boundary_repeat_restore_and_missing_source(self):
        first = snap('2026-11-08T15:59:00+00:00', 'a')
        state = advance(None, {}, first)
        self.assertEqual(week_key(first['scannedAt']), '2026-11-02')
        self.assertEqual(public_history(state)['weeks'][0]['added'], [])
        second = snap('2026-11-08T16:01:00+00:00', 'a', 'b')
        state = advance(state, first, second)
        self.assertEqual(week_key(second['scannedAt']), '2026-11-09')
        state = advance(state, second, second)
        self.assertEqual(len(state['weeks']['2026-11-09']['added']), 1)
        third = snap('2026-11-09T00:00:00+00:00', 'a')
        state = advance(state, second, third)
        self.assertEqual(len(state['weeks']['2026-11-09']['removed']), 1)
        state = advance(state, third, second)
        self.assertEqual(len(state['weeks']['2026-11-09']['restored']), 1)
        self.assertEqual(len(state['weeks']['2026-11-09']['added']), 1)
        missing = snap('2026-11-10T00:00:00+00:00', status='missing')
        state = advance(state, second, missing)
        self.assertEqual(len(state['weeks']['2026-11-09']['removed']), 1)
        self.assertEqual(len(public_history(state)['weeks']), 2)


if __name__ == '__main__':
    unittest.main()
