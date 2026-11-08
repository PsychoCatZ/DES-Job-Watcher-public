import tempfile
from pathlib import Path
import unittest

import httpx

from des_job_watcher.history import History
from des_job_watcher.hh_api import HHClient, HHError


class HistoryTests(unittest.TestCase):
    def test_versions_persist_and_original_is_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.sqlite3'
            original = {'id': '123', 'name': 'Поддержка', 'description': '<p>Чат</p>'}
            with History(path) as history:
                self.assertEqual(history.save_detail(original), 'new')
                self.assertEqual(history.save_detail({**original, 'counters': {'views': 2}}), 'unchanged')
                self.assertEqual(history.save_detail({**original, 'description': '<p>Переписка</p>'}), 'changed')
            with History(path) as history:
                self.assertTrue(history.has_detail('123'))
                self.assertFalse(history.has_detail('999'))
                rows = history.db.execute('SELECT raw_json FROM versions ORDER BY id').fetchall()
                self.assertEqual(len(rows), 2)
                self.assertIn('<p>Чат</p>', rows[0][0])

    def test_detail_id_and_body_validation(self):
        with HHClient('Watcher', 'test-token', transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={'id': '123', 'description': '<p>Чат</p>'})
        )) as client:
            self.assertEqual(client.detail('123')['id'], '123')
            with self.assertRaises(HHError):
                client.detail('456')
            with self.assertRaises(ValueError):
                client.detail('../token')
