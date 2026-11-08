import tempfile
import unittest
from pathlib import Path

from des_job_watcher.telegram_delivery import load_binding, save_binding, receipt_path, next_card


class DeliveryTests(unittest.TestCase):
    def test_binding_roundtrip_and_other_bot_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'binding.json'
            self.assertIsNone(load_binding(path, '123'))
            save_binding(path, '123', 42)
            self.assertEqual(load_binding(path, '123'), 42)
            with self.assertRaises(ValueError):
                load_binding(path, '999')
            with self.assertRaises(FileExistsError):
                save_binding(path, '123', 43)

    def test_old_receipt_key_and_pending_attempt_both_block_duplicates(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            first = {'vacancy_id': '10', 'profile_id': 'support', 'group': 'consider'}
            second = {**first, 'vacancy_id': '11'}
            path = receipt_path(directory, '123', 42, first)
            self.assertEqual(path.stem, hashlib.sha256(b'123:42:10:support').hexdigest())
            path.write_text('{"status":"reserved_delivery_unknown"}', encoding='utf-8')
            self.assertEqual(next_card([first, second], directory, '123', 42), second)
            receipt_path(directory, '123', 42, second).write_text('{"status":"sent"}', encoding='utf-8')
            self.assertIsNone(next_card([first, second], directory, '123', 42))

    def test_no_automatic_professional_review_delivery(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(next_card([{'group': 'professional_review'}], Path(temp), '123', 42))
