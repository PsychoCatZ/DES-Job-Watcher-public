import unittest

from examples.analyze_saved import make_api_snapshot


class ApiSnapshotTests(unittest.TestCase):
    def test_html_text_and_remote_field_are_preserved_for_analysis(self):
        snapshot = make_api_snapshot({'id': '123', 'name': 'Чат',
            'description': '<p>Переписка &amp; инструкции</p><ul><li>Без звонков</li></ul>',
            'work_format': [{'id': 'REMOTE'}], 'archived': False,
            'employer': {'name': 'Учебная компания'}})
        self.assertEqual(snapshot['detail']['description_text'], 'Переписка & инструкции\nБез звонков')
        self.assertEqual(snapshot['detail']['work_formats'], ['REMOTE'])
        self.assertEqual(snapshot['search']['items'][0]['employer'], {'name': 'Учебная компания'})
