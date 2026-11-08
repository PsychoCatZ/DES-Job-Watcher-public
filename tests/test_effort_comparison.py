from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from des_job_watcher.openai_adapter import prepare_body, analyze_once
from des_job_watcher.effort_comparison import prepare_comparison, load_jobs, run_comparison, reuse_completed
from des_job_watcher.assessment import validate_and_decide
from des_job_watcher.history import History
from des_job_watcher.prompting import ROOT
import httpx


class EffortComparisonTests(unittest.TestCase):
    def payload(self):
        payload = json.loads((ROOT / 'examples/fixtures/analysis_input.json').read_text(encoding='utf-8'))
        payload['rules'] = json.loads((ROOT / 'config/matching_rules.json').read_text(encoding='utf-8'))
        return payload

    def test_only_effort_changes_and_default_stays_medium(self):
        payload = self.payload()
        medium, meta_m = prepare_body(payload)
        high, meta_h = prepare_body(payload, effort='high')
        self.assertEqual(medium['reasoning']['effort'], 'medium')
        altered = deepcopy(medium)
        altered['reasoning']['effort'] = 'high'
        self.assertEqual(altered, high)
        self.assertNotEqual(meta_m['api_body_sha256'], meta_h['api_body_sha256'])
        self.assertEqual(meta_m['request_sha256'], meta_h['request_sha256'])

    def test_high_reaches_actual_http_body_and_record(self):
        bodies = []
        def respond(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(403, json={})
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            result = analyze_once(self.payload(), 'test-key', client, effort='high')
        self.assertEqual(result['reasoning_effort'], 'high')
        self.assertEqual(bodies[0]['reasoning']['effort'], 'high')

    def test_frozen_pack_detects_input_change(self):
        with tempfile.TemporaryDirectory() as directory:
            pack = Path(directory) / 'pack'
            prepare_comparison([{'id': 'test', 'payload': self.payload(), 'checks_for_human': ['Check meaning']}], pack)
            self.assertEqual(len(load_jobs(pack)), 2)
            path = pack / '01_high.input.json'
            payload = json.loads(path.read_text(encoding='utf-8'))
            payload['vacancy']['description'] += ' Changed text.'
            path.write_text(json.dumps(payload), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_jobs(pack)

    def test_failed_call_stops_and_cannot_be_repeated(self):
        with tempfile.TemporaryDirectory() as directory:
            pack = Path(directory) / 'pack'
            prepare_comparison([{'id': 'test', 'payload': self.payload(), 'checks_for_human': []}], pack)
            jobs = load_jobs(pack)
            called = []
            def analyze(payload, effort):
                called.append(effort)
                return {'status': 'analysis_failed', 'error': 'test'}
            with History(Path(directory) / 'history.sqlite3') as history:
                self.assertFalse(run_comparison(pack, jobs, history, analyze))
                with self.assertRaises(ValueError):
                    run_comparison(pack, jobs, history, analyze)
                self.assertEqual(called, ['medium'])
                def complete(payload, effort):
                    called.append(effort)
                    return {'status': 'completed', 'request': jobs[1]['request']}
                self.assertTrue(run_comparison(pack, jobs, history, complete, skip_saved_failures=True))
                self.assertEqual(called, ['medium', 'high'])
                failed = json.loads((pack / '01_medium.result.json').read_text(encoding='utf-8'))
                self.assertEqual(failed['status'], 'analysis_failed')

    def test_reuse_requires_exact_api_body_and_keeps_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack = root / 'pack'
            payload = self.payload()
            prepare_comparison([{'id': 'test', 'payload': payload, 'checks_for_human': []}], pack)
            jobs = load_jobs(pack)
            analysis = json.loads((ROOT / 'examples/fixtures/analysis_response.json').read_text(encoding='utf-8'))
            record = {'status': 'completed', 'request': jobs[0]['request'],
                      'assessment': validate_and_decide(analysis, payload)}
            source = root / 'source.json'
            original = json.dumps(record)
            source.write_text(original, encoding='utf-8')
            self.assertTrue(reuse_completed(jobs[0], source, pack))
            self.assertFalse(reuse_completed(jobs[1], source, pack))
            self.assertEqual(source.read_text(encoding='utf-8'), original)
