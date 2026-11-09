from contextlib import closing
import sqlite3
from types import SimpleNamespace
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from des_job_watcher.dig_control import DigControl, ONCE, START, STOP, REFRESH
from examples.control_telegram import finish_worker
from examples import control_telegram
from tests.test_refresh_search import update


class OnceTests(unittest.TestCase):
    def test_controller_runs_one_child_then_waits_with_disabled_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'data').mkdir()
            telegram = Mock()
            telegram.call.side_effect = [[update(1, ONCE)], [], KeyboardInterrupt()]
            worker = SimpleNamespace(poll=lambda: 0, returncode=0)
            with patch.object(control_telegram, 'ROOT', root), \
                    patch.object(control_telegram, 'load_binding', return_value=42), \
                    patch.object(control_telegram, 'TelegramClient', return_value=telegram), \
                    patch.object(control_telegram.subprocess, 'Popen', return_value=worker) as popen, \
                    patch('sys.argv', ['control', '--live', '--schedule']), \
                    patch.dict('os.environ', dict(TELEGRAM_BOT_TOKEN='fake', HH_ACCESS_TOKEN='fake',
                                                 HH_USER_AGENT='fake', OPENAI_API_KEY='fake')):
                self.assertEqual(control_telegram.main(), 0)
            self.assertEqual(popen.call_count, 1)
            self.assertIn('Раскопки закончены', [call.args[1] for call in telegram.send.call_args_list])
            with closing(sqlite3.connect(root / 'data/telegram_control.sqlite3')) as db:
                self.assertEqual(db.execute('select enabled, once_mode from dig_control').fetchone(), (0, 0))

    def test_single_party_finishes_with_notification_even_without_cards(self):
        with closing(sqlite3.connect(':memory:')) as db:
            control = DigControl(db, 'bot', 42)
            self.assertTrue(control.accept(update(1, ONCE)))
            generation = control.state()[2]
            control.mark_once_started()
            telegram = Mock()
            self.assertFalse(finish_worker(control, SimpleNamespace(poll=lambda: None), generation, telegram, 42))
            telegram.send.assert_not_called()
            self.assertTrue(finish_worker(control, SimpleNamespace(poll=lambda: 0, returncode=0), generation, telegram, 42))
            self.assertEqual(telegram.send.call_args.args, (42, 'Раскопки закончены'))
            self.assertEqual(control.state()[0], 0)
            self.assertEqual(control.once_mode(), 0)

    def test_repeated_once_does_not_interrupt_or_enqueue_second_party(self):
        with closing(sqlite3.connect(':memory:')) as db:
            control = DigControl(db, 'bot', 42)
            control.accept(update(1, ONCE))
            generation = control.state()[2]
            control.mark_once_started()
            control.accept(update(2, ONCE))
            self.assertEqual(control.state()[2], generation)
            self.assertEqual(control.once_mode(), 2)
            self.assertTrue(control.finish_once(generation))
            self.assertFalse(control.finish_once(generation))

    def test_start_switches_to_schedule_stop_cancels_and_refresh_restarts_once(self):
        with closing(sqlite3.connect(':memory:')) as db:
            control = DigControl(db, 'bot', 42)
            control.accept(update(1, ONCE))
            generation = control.state()[2]
            control.mark_once_started()
            control.accept(update(2, REFRESH))
            self.assertFalse(control.finish_once(generation))
            self.assertEqual(control.once_mode(), 1)
            control.accept(update(3, START))
            self.assertEqual(control.once_mode(), 0)
            self.assertEqual(control.state()[0], 1)
            control.accept(update(4, STOP))
            self.assertEqual(control.state()[0], 0)

    def test_failure_stops_once_with_error_instead_of_success(self):
        with closing(sqlite3.connect(':memory:')) as db:
            control = DigControl(db, 'bot', 42)
            control.accept(update(1, ONCE))
            telegram = Mock()
            finish_worker(control, SimpleNamespace(poll=lambda: 1, returncode=1), control.state()[2], telegram, 42)
            self.assertIn('ошибки', telegram.send.call_args.args[1])
            self.assertEqual(control.state()[0], 0)

    def test_running_once_persists_for_restart_recovery(self):
        with closing(sqlite3.connect(':memory:')) as db:
            control = DigControl(db, 'bot', 42)
            control.accept(update(1, ONCE))
            control.mark_once_started()
            recovered = DigControl(db, 'bot', 42)
            self.assertEqual(recovered.once_mode(), 2)
            recovered.finish_once(recovered.state()[2])
            self.assertEqual(recovered.state()[0], 0)
