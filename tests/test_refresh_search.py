from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

from des_job_watcher.dig_control import DigControl, START, STOP, REFRESH, digging_enabled
from des_job_watcher.vacancy_queue import VacancyQueue
from examples.control_telegram import apply_refresh


def update(number, text, owner=42):
    return {'update_id': number, 'message': {'text': text,
            'chat': {'id': owner, 'type': 'private'}, 'from': {'id': owner}}}


class RefreshTests(unittest.TestCase):
    def test_refresh_waits_for_worker_preserves_history_and_skips_same_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with closing(sqlite3.connect(root / 'telegram_control.sqlite3')) as db, \
                    closing(sqlite3.connect(root / 'watcher.sqlite3')) as history:
                control = DigControl(db, 'bot', 42)
                queue = VacancyQueue(history)
                queue.add({'id': 'old'}, 'support')
                queue.add({'id': 'done'}, 'support', 'completed')
                control.accept(update(1, START))
                generation = control.state()[2]
                self.assertTrue(control.accept(update(2, REFRESH)))
                self.assertFalse(digging_enabled(root, 'bot', 42, generation))
                self.assertTrue(control.state()[0])
                self.assertIsNone(apply_refresh(control, root, SimpleNamespace(poll=lambda: None)))
                self.assertEqual(queue.remaining(), 1)
                self.assertEqual(apply_refresh(control, root, SimpleNamespace(poll=lambda: 0)), 1)
                self.assertEqual(queue.status('done'), 'completed')
                self.assertEqual(queue.status('old'), 'dismissed')
                self.assertFalse(queue.add({'id': 'old'}, 'support'))
                self.assertTrue(queue.add({'id': 'new'}, 'support'))
                self.assertEqual(queue.next(), ('new', 'support'))
                self.assertIsNone(apply_refresh(control, root, None))
                self.assertFalse(control.accept(update(2, REFRESH)))

    def test_paused_refresh_survives_restart_without_enabling_search(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with closing(sqlite3.connect(root / 'telegram_control.sqlite3')) as db:
                control = DigControl(db, 'bot', 42)
                self.assertFalse(control.accept(update(1, REFRESH, owner=99)))
                self.assertEqual(control.refresh_request(), 0)
                control.accept(update(2, REFRESH))
            with closing(sqlite3.connect(root / 'telegram_control.sqlite3')) as db:
                control = DigControl(db, 'bot', 42)
                self.assertEqual(apply_refresh(control, root, None), 0)
                self.assertFalse(control.state()[0])
                control.accept(update(3, START))
                control.accept(update(4, STOP))
                self.assertFalse(control.state()[0])

    def test_reset_replay_does_not_discard_new_candidates(self):
        with closing(sqlite3.connect(':memory:')) as db:
            queue = VacancyQueue(db)
            queue.add({'id': '1'}, 'support')
            self.assertEqual(queue.dismiss_pending(123), 1)
            queue.add({'id': '2'}, 'support')
            self.assertEqual(queue.dismiss_pending(123), 1)
            self.assertEqual(queue.next(), ('2', 'support'))

    def test_migrates_existing_controller_state_without_resetting_offset(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('''CREATE TABLE dig_control (bot_id TEXT, chat_id INTEGER,
                       enabled INTEGER, next_offset INTEGER, generation INTEGER,
                       PRIMARY KEY(bot_id, chat_id))''')
            db.execute("INSERT INTO dig_control VALUES ('bot',42,1,99,7)")
            db.commit()
            control = DigControl(db, 'bot', 42)
            self.assertEqual(control.state(), (1, 99, 7))
            self.assertEqual(control.refresh_request(), 0)
