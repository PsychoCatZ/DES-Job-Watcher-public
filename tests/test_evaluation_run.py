import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from des_job_watcher.evaluation_run import prepare_cases, run_cases
from des_job_watcher.prompting import ROOT


class EvaluationRunTests(unittest.TestCase):
    def setUp(self):
        self.dataset = {'dataset_version': 2, 'split': 'development'}
        self.job = {'case': {'id': 'first', 'checks': [
            {'path': 'decision', 'allowed': ['clarify']}], 'human_checks': ['Проверить цитаты']},
            'payload': {'vacancy': {'id': 'first'}},
            'request': {'api_body_sha256': 'digest'}}
        self.record = {'status': 'completed', 'request': {'api_body_sha256': 'digest'},
                       'assessment': {'decision': 'clarify', 'delivery': {'action': 'show'}}}
        (ROOT / 'tmp').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp')
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / 'run'

    def two_jobs(self):
        second = copy.deepcopy(self.job)
        second['case']['id'] = 'second'
        return [self.job, second]

    def test_completed_report_and_expectations_do_not_enter_analyze(self):
        def analyze(payload):
            self.assertEqual(payload, self.job['payload'])
            self.assertNotIn('checks', payload)
            return self.record
        summary = run_cases(self.dataset, [self.job], self.output, analyze)
        self.assertEqual(summary['status'], 'completed')
        self.assertTrue(summary['results'][0]['checks'][0]['passed'])
        self.assertTrue((self.output / 'first.result.json').exists())
        self.assertIn('Проверить цитаты', (self.output / 'report.md').read_text(encoding='utf-8'))

    def test_disagreement_is_reported_without_stopping(self):
        self.record['assessment']['decision'] = 'unsuitable'
        summary = run_cases(self.dataset, self.two_jobs(), self.output, lambda _: self.record)
        self.assertEqual(len(summary['results']), 2)
        self.assertFalse(summary['results'][0]['checks'][0]['passed'])
        self.assertIn('Расхождение', (self.output / 'report.md').read_text(encoding='utf-8'))

    def test_failed_call_is_saved_and_stops_without_retry(self):
        calls = []
        def analyze(payload):
            calls.append(payload)
            return {'status': 'analysis_failed', 'error': 'HTTP 429'}
        summary = run_cases(self.dataset, self.two_jobs(), self.output, analyze)
        self.assertEqual(len(calls), 1)
        self.assertEqual(summary['status'], 'stopped_on_error')
        self.assertTrue((self.output / 'first.result.json').exists())
        self.assertFalse((self.output / 'second.result.json').exists())

    def test_interruption_keeps_in_flight_marker(self):
        def analyze(_):
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            run_cases(self.dataset, [self.job], self.output, analyze)
        summary = json.loads((self.output / 'summary.json').read_text(encoding='utf-8'))
        self.assertEqual(summary['status'], 'interrupted')
        self.assertEqual(summary['in_flight'], 'first')

    def test_existing_run_is_not_overwritten(self):
        self.output.mkdir()
        with self.assertRaises(FileExistsError):
            run_cases(self.dataset, [self.job], self.output, lambda _: self.fail('No API'))

    def test_changed_request_is_not_scored(self):
        self.record['request']['api_body_sha256'] = 'other'
        summary = run_cases(self.dataset, self.two_jobs(), self.output, lambda _: self.record)
        self.assertEqual(summary['status'], 'stopped_on_error')
        self.assertNotIn('checks', summary['results'][0])

    def test_unknown_case_rejected(self):
        with patch('des_job_watcher.evaluation_run.load_cases', return_value=(self.dataset, [])):
            with self.assertRaisesRegex(ValueError, 'Неизвестные'):
                prepare_cases('unused', ['missing'])


if __name__ == '__main__':
    unittest.main()
