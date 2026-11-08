from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from des_job_watcher.analysis_cache import analysis_scope, import_attempts
from des_job_watcher.history import History


class AnalysisCacheTests(unittest.TestCase):
    def payload(self):
        return {'vacancy': {'id': '123', 'name': 'Разметчик', 'description': 'Разметка данных'},
                'profile': {'profile_id': 'ai_data', 'version': 1}}

    def test_scope_does_not_rebill_for_config_but_distinguishes_text_and_profile(self):
        payload = self.payload()
        scope = analysis_scope(payload)
        changed = deepcopy(payload)
        changed['profile']['version'] = 2
        changed['vacancy']['salary_information_only'] = 100
        self.assertEqual(scope, analysis_scope(changed))
        changed['vacancy']['description'] += ' и проверка качества'
        self.assertNotEqual(scope, analysis_scope(changed))
        changed = deepcopy(payload)
        changed['profile']['profile_id'] = 'support'
        self.assertNotEqual(scope, analysis_scope(changed))

    def test_reservation_survives_reopen_and_cannot_be_taken_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.sqlite3'
            with History(path) as first, History(path) as second:
                self.assertTrue(first.reserve_attempt('scope', 'request', 'result.json'))
                self.assertFalse(second.reserve_attempt('scope', 'request', 'other.json'))
            with History(path) as history:
                self.assertEqual(history.attempt_status('scope'), 'in_flight')
                history.finish_attempt('scope', 'analysis_failed')
                self.assertFalse(history.reserve_attempt('scope', 'request', 'retry.json'))

    def test_import_ignores_unpaid_plan_and_preserves_failed_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root / 'batches' / 'run'
            batch.mkdir(parents=True)
            (batch / '001_input.json').write_text(json.dumps(self.payload()), encoding='utf-8')
            with History(root / 'history.sqlite3') as history:
                self.assertEqual(import_attempts(history, root / 'batches'), 0)
                (batch / '001_result.json').write_text(json.dumps({'status': 'analysis_failed'}), encoding='utf-8')
                self.assertEqual(import_attempts(history, root / 'batches'), 1)
                self.assertEqual(import_attempts(history, root / 'batches'), 0)
                self.assertEqual(history.attempt_status(analysis_scope(self.payload())), 'analysis_failed')
