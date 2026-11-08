"""Граница HH API и дедупликация, только MockTransport."""

import json
import unittest

import httpx

from des_job_watcher.hh_api import HHClient, HHError, collect_candidates
from examples.fetch_hh_page import load_search_plan


class HHApiTests(unittest.TestCase):
    def test_token_is_form_encoded_then_used_only_as_header(self):
        seen = []

        def respond(request):
            seen.append(request)
            if request.url.path == '/token':
                self.assertEqual(request.method, 'POST')
                self.assertIn(b'grant_type=client_credentials', request.content)
                self.assertIn(b'client_secret=test-secret', request.content)
                return httpx.Response(200, json={'access_token': 'test-token'})
            self.assertEqual(request.headers['Authorization'], 'Bearer test-token')
            self.assertEqual(request.url.params['work_format'], 'REMOTE')
            self.assertEqual(request.url.params['area'], '113')
            self.assertNotIn('salary', request.url.params)
            self.assertNotIn('schedule', request.url.params)
            return httpx.Response(200, json={'items': [], 'found': 0})

        with HHClient('Watcher/0.1 (test@example.com)', transport=httpx.MockTransport(respond)) as client:
            self.assertIsNone(client.issue_token('test-id', 'test-secret'))
            client.search('поддержка')
        self.assertEqual(len(seen), 2)

    def test_errors_do_not_leak_response_or_retry(self):
        calls = []

        def respond(request):
            calls.append(request)
            return httpx.Response(403, text='test-secret test-token')

        with HHClient('Watcher', 'test-token', transport=httpx.MockTransport(respond)) as client:
            with self.assertRaises(HHError) as caught:
                client.search('поддержка')
        self.assertEqual(len(calls), 1)
        self.assertNotIn('test-secret', str(caught.exception))
        self.assertNotIn('test-token', str(caught.exception))

    def test_dedup_keeps_both_profile_sources_and_primary_defaults(self):
        plan = load_search_plan()
        self.assertEqual(plan['default_profiles'], ['support', 'ai_data'])

        def respond(request):
            return httpx.Response(200, json={'items': [{'id': '123', 'name': 'Учебная вакансия'}]})

        pauses = []
        with HHClient('Watcher', 'test-token', transport=httpx.MockTransport(respond)) as client:
            result = collect_candidates(client, plan, plan['default_profiles'], pause=pauses.append)
        expected = [(profile, query['id']) for profile in plan['default_profiles']
                    for query in plan['profiles'][profile]['queries']]
        self.assertEqual([(item['profile'], item['query']) for item in result['searches']], expected)
        self.assertEqual(len(pauses), len(expected) - 1)
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual({s['profile'] for s in result['candidates'][0]['sources']}, {'support', 'ai_data'})
        self.assertNotIn('test-token', json.dumps(result))

    def test_malformed_items_are_not_empty_success(self):
        with HHClient('Watcher', 'test-token', transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={'items': None})
        )) as client:
            with self.assertRaises(HHError):
                client.search('разметка')
