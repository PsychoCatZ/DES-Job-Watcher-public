import copy
import json
import unittest
from unittest.mock import patch

import httpx

from des_job_watcher import openai_adapter as adapter
from des_job_watcher.prompting import ROOT


class OpenAIAdapterTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads((ROOT / 'examples/fixtures/analysis_input.json').read_text(encoding='utf-8'))
        self.payload['rules'] = json.loads((ROOT / 'config/matching_rules.json').read_text(encoding='utf-8'))
        self.analysis = json.loads((ROOT / 'examples/fixtures/analysis_response.json').read_text(encoding='utf-8'))
        self.envelope = {
            'id': 'resp_test', 'model': 'gpt-6-luna', 'status': 'completed',
            'output': [{'type': 'reasoning', 'summary': []},
                       {'type': 'message', 'role': 'assistant', 'status': 'completed',
                        'content': [{'type': 'output_text', 'text': json.dumps(self.analysis)}]}],
            'usage': {'input_tokens': 100, 'output_tokens': 200},
        }

    def call_with_response(self, status, body, *, mode='production'):
        calls = []
        def handler(request):
            calls.append(request)
            self.assertEqual(request.url, adapter.ENDPOINT)
            return httpx.Response(status, json=body, headers={'x-request-id': 'req_test'})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            result = adapter.analyze_once(self.payload, 'test-key-do-not-log', client, mode=mode)
        self.assertEqual(len(calls), 1)
        self.assertNotIn('test-key-do-not-log', json.dumps(result))
        return result, json.loads(calls[0].content)

    def test_one_completed_call_passes_existing_validator(self):
        result, body = self.call_with_response(200, self.envelope)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['assessment']['decision'], 'suitable')
        self.assertEqual(result['usage']['output_tokens'], 200)
        self.assertFalse(body['store'])
        self.assertEqual(body['model'], 'gpt-6-luna')
        self.assertEqual(body['reasoning']['effort'], 'medium')
        self.assertEqual(body['max_output_tokens'], 8192)
        self.assertTrue(body['text']['format']['strict'])
        self.assertNotIn('tools', body)

    def test_synthetic_context_reaches_adapter_body_without_changing_model(self):
        self.payload['profile']['profile_kind'] = 'synthetic'
        body, metadata = adapter.prepare_body(self.payload, mode='synthetic')
        self.assertEqual(body['model'], 'gpt-6-luna')
        self.assertEqual(body['reasoning']['effort'], 'medium')
        self.assertEqual(metadata['analysis_mode'], 'synthetic')
        self.assertIn('условного кандидата', body['input'][0]['content'])
        with self.assertRaises(ValueError):
            adapter.prepare_body(self.payload)

    def test_synthetic_context_is_preserved_in_saved_mock_api_result(self):
        self.payload['profile']['profile_kind'] = 'synthetic'
        result, body = self.call_with_response(200, self.envelope, mode='synthetic')
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['request']['analysis_mode'], 'synthetic')
        self.assertIn('ДОВЕРЕННЫЙ РЕЖИМ: СИНТЕТИЧЕСКИЙ СЦЕНАРИЙ', body['input'][0]['content'])

    def test_terminal_quote_recovery_keeps_original_model_output(self):
        self.payload['vacancy']['description'] += ' Грамотная письменная речь;'
        self.analysis['requirements'][0]['quote'] = 'Грамотная письменная речь.'
        original_text = json.dumps(self.analysis)
        self.envelope['output'][1]['content'][0]['text'] = original_text
        result, _ = self.call_with_response(200, self.envelope)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['output_text'], original_text)
        self.assertEqual(result['assessment']['analysis']['requirements'][0]['quote'], 'Грамотная письменная речь;')
        self.assertEqual(len(result['validation_recovery']['changes']), 1)

    def test_terminal_quote_recovery_does_not_hide_other_validation_errors(self):
        self.payload['vacancy']['description'] += ' Грамотная письменная речь;'
        self.analysis['requirements'][0]['quote'] = 'Грамотная письменная речь.'
        self.analysis['requirements'][0]['profile_evidence_ids'] = ['foreign_id']
        self.envelope['output'][1]['content'][0]['text'] = json.dumps(self.analysis)
        result, _ = self.call_with_response(200, self.envelope)
        self.assertEqual(result['status'], 'analysis_failed')
        self.assertNotIn('assessment', result)

    def test_http_errors_are_saved_without_body_and_without_retries(self):
        for status in (400, 401, 403, 429, 500, 302):
            with self.subTest(status=status):
                result, _ = self.call_with_response(status, {'error': 'test-key-do-not-log'})
                self.assertEqual(result['status'], 'analysis_failed')
                self.assertEqual(result['http_status'], status)
                self.assertNotIn('assessment', result)

    def test_incomplete_response_does_not_get_a_decision(self):
        self.envelope['status'] = 'incomplete'
        self.envelope['incomplete_details'] = {'reason': 'max_output_tokens'}
        result, _ = self.call_with_response(200, self.envelope)
        self.assertEqual(result['status'], 'analysis_failed')
        self.assertNotIn('assessment', result)
        self.assertEqual(result['incomplete_details']['reason'], 'max_output_tokens')

    def test_refusal_and_wrong_profile_fail_analysis(self):
        self.envelope['output'][1]['content'] = [{'type': 'refusal', 'refusal': 'No'}]
        result, _ = self.call_with_response(200, self.envelope)
        self.assertEqual(result['status'], 'analysis_failed')
        self.analysis['profile_id'] = 'developer'
        self.envelope['output'][1]['content'] = [{'type': 'output_text', 'text': json.dumps(self.analysis)}]
        result, _ = self.call_with_response(200, self.envelope)
        self.assertEqual(result['status'], 'analysis_failed')

    def test_timeout_is_not_retried(self):
        calls = []
        def handler(request):
            calls.append(request)
            raise httpx.ReadTimeout('test-key-do-not-log', request=request)
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            result = adapter.analyze_once(self.payload, 'test-key-do-not-log', client)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['status'], 'analysis_failed')
        self.assertNotIn('test-key-do-not-log', json.dumps(result))

    def test_missing_key_never_opens_client(self):
        with patch.object(httpx, 'Client') as client:
            with self.assertRaises(ValueError):
                adapter.analyze_once(self.payload, '')
            client.assert_not_called()

    def test_api_schema_adaptation_keeps_local_contract_unchanged(self):
        original = {'const': 1, 'items': {'uniqueItems': True}}
        saved = copy.deepcopy(original)
        self.assertEqual(adapter.api_schema(original), {'enum': [1], 'items': {}})
        self.assertEqual(original, saved)

    def test_output_limit_changes_full_api_fingerprint(self):
        _, first = adapter.prepare_body(self.payload)
        with patch.object(adapter, 'MAX_OUTPUT_TOKENS', 4096):
            _, second = adapter.prepare_body(self.payload)
        self.assertNotEqual(first['api_body_sha256'], second['api_body_sha256'])


if __name__ == '__main__':
    unittest.main()
