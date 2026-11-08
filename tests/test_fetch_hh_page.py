"""Проверки границы с внешним HTML. Реальных запросов к HH нет."""

import html
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from examples import fetch_hh_page as example


class FetchPageTests(unittest.TestCase):
    def test_profiles_select_queries_without_salary_or_schedule_filters(self):
        plan = example.load_search_plan()
        original = example.SEARCH_PARAMS.copy()
        for profile_id, profile in plan['profiles'].items():
            for entry in profile['queries']:
                query, params = example.select_query(plan, profile_id, entry['id'])
                self.assertEqual(params['text'], entry['text'])
                self.assertEqual(query['id'], entry['id'])
                self.assertEqual(set(params),
                                 {'text', 'area', 'work_format', 'order_by', 'page'})
        self.assertEqual(example.SEARCH_PARAMS, original)
        with self.assertRaises(ValueError):
            example.select_query(plan, 'support', 'claude')

    def test_search_validation_uses_selected_query(self):
        plan = example.load_search_plan()
        _, params = example.select_query(plan, 'developer', 'claude')
        criteria = {'area': [113], 'work_format': ['REMOTE'], 'page': 0,
                    'order_by': 'publication_time', 'text': 'Claude'}
        state = {'vacancySearchResult': {'criteria': criteria, 'vacancies': [],
                                        'totalResults': 0}}
        self.assertEqual(example.extract_search(state, params)['items'], [])
        with self.assertRaises(ValueError):
            example.extract_search(state)

    def test_state_decodes_html_entities_once(self):
        state = {"name": 'Кот & текст "без звонков"'}
        markup = html.escape(json.dumps(state, ensure_ascii=False))
        page = f'<template id="HH-Lux-InitialState">{markup}</template>'
        self.assertEqual(example.extract_state(page), state)

    def test_missing_or_invalid_state_is_not_empty_search(self):
        for page in ('<html>Другая страница</html>',
                     '<template id="HH-Lux-InitialState">[]</template>',
                     '<template id="HH-Lux-InitialState">not json</template>'):
            with self.subTest(page=page), self.assertRaises(ValueError):
                example.extract_state(page)

    def test_description_preserves_negation_and_word_boundaries(self):
        markup = ('<p>Без <strong>обязательных</strong> звонков.</p>'
                  '<ul><li>Чаты &amp; тикеты</li><li>Обучение текстом</li></ul>'
                  '<script>скрытый код</script>')
        self.assertEqual(example.description_to_text(markup),
                         'Без обязательных звонков.\nЧаты & тикеты\nОбучение текстом')

    def test_access_errors_stop_after_one_request(self):
        for status in (403, 429, 503, 302):
            calls = []
            def handler(request):
                calls.append(request)
                return httpx.Response(status, headers={'location': '/captcha'})
            with self.subTest(status=status), httpx.Client(
                transport=httpx.MockTransport(handler)
            ) as client:
                with self.assertRaises((ValueError, httpx.HTTPStatusError)):
                    example.fetch_state(client, example.SEARCH_URL)
                self.assertEqual(len(calls), 1)

    def test_wrong_filters_rejected_and_empty_search_accepted(self):
        criteria = {'area': [113], 'work_format': ['REMOTE'], 'page': 0,
                    'order_by': 'publication_time', 'text': 'чат поддержка'}
        state = {'vacancySearchResult': {'criteria': criteria, 'vacancies': [],
                                        'totalResults': 0}}
        self.assertEqual(example.extract_search(state)['items'], [])
        criteria['area'] = [1]
        with self.assertRaises(ValueError):
            example.extract_search(state)

    def test_detail_must_match_requested_id(self):
        state = {'vacancyView': {'vacancyFull': {'vacancy': {
            'vacancyId': 42, 'description': '<p>Без звонков</p>',
            'status': {'archived': False}, 'workFormats': ['REMOTE']}}}}
        self.assertEqual(example.extract_detail(state, '42')['description_text'],
                         'Без звонков')
        with self.assertRaises(ValueError):
            example.extract_detail(state, '43')

    def test_snapshots_roundtrip_without_overwriting(self):
        temp_root = example.ROOT / 'tmp'
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as folder:
            with patch.object(example, 'ROOT', Path(folder)):
                snapshot = {'description_text': 'Только текст, без звонков'}
                first = example.save_snapshot(snapshot)
                second = example.save_snapshot({'other': True})
                self.assertNotEqual(first, second)
                self.assertEqual(json.loads(first.read_text(encoding='utf-8')), snapshot)
                self.assertFalse(list(first.parent.glob('*.tmp')))


if __name__ == '__main__':
    unittest.main()
