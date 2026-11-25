import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from examples.rotate_openai_key import rotate


class KeyRotationTests(unittest.TestCase):
    def test_rejected_key_preserves_file_success_changes_only_openai(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / 'credentials.json'
            control = root / 'control.sqlite3'
            before = {'OPENAI_API_KEY': 'old-demo', 'HH_ACCESS_TOKEN': 'hh-demo',
                      'HH_USER_AGENT': 'example', 'TELEGRAM_BOT_TOKEN': 'bot-demo'}
            config.write_text(json.dumps(before))
            with closing(sqlite3.connect(control)) as db, db:
                db.execute('CREATE TABLE dig_control(enabled INTEGER)')
                db.execute('INSERT INTO dig_control VALUES (0)')
            client = Mock()
            client.__enter__ = Mock(return_value=client)
            client.__exit__ = Mock(return_value=False)
            with patch('examples.rotate_openai_key.httpx.Client', return_value=client), \
                    patch('examples.rotate_openai_key.subprocess.run', return_value=Mock(returncode=0)) as command:
                client.get.return_value.status_code = 401
                with self.assertRaisesRegex(ValueError, 'HTTP 401'):
                    rotate('new-demo', config, control)
                self.assertEqual(json.loads(config.read_text()), before)
                self.assertEqual(command.call_count, 1)
                command.reset_mock()
                client.get.return_value.status_code = 200
                rotate('new-demo', config, control)
                self.assertEqual(json.loads(config.read_text()), {**before, 'OPENAI_API_KEY': 'new-demo'})
                self.assertEqual(command.call_count, 3)
                self.assertFalse(list(root.glob('.openai-*')))
                with closing(sqlite3.connect(control)) as db, db:
                    db.execute('UPDATE dig_control SET enabled=1')
                command.reset_mock()
                with self.assertRaisesRegex(ValueError, 'Stop digging'):
                    rotate('another-demo', config, control)
                command.assert_not_called()
