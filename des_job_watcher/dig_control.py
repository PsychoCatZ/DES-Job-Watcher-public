"""Состояние раскопок и обработка кнопок владельца."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3

from des_job_watcher.telegram_delivery import load_binding

START = 'Начать раскопки'
STOP = 'Перестать рыть'
KEYBOARD = {'keyboard': [[{'text': START}, {'text': STOP}]],
            'resize_keyboard': True, 'is_persistent': True}


def digging_enabled(data_directory, bot_id, chat_id, generation=None):
    path = data_directory / 'telegram_control.sqlite3'
    if not path.is_file():
        return False
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        row = db.execute('SELECT enabled, generation FROM dig_control WHERE bot_id=? AND chat_id=?',
                         (bot_id, chat_id)).fetchone()
    return bool(row and row[0] and (generation is None or row[1] == generation))


def requests_allowed():
    if os.environ.get('WATCHER_CONTROLLED') != '1':
        return True
    directory = Path(__file__).resolve().parents[1] / 'data'
    bot_id = os.environ.get('TELEGRAM_BOT_TOKEN', '').split(':')[0]
    try:
        chat_id = load_binding(directory / 'telegram_binding.json', bot_id)
        generation = int(os.environ['WATCHER_DIG_GENERATION'])
        return digging_enabled(directory, bot_id, chat_id, generation)
    except (OSError, ValueError, KeyError, sqlite3.Error):
        return False


class DigControl:
    def __init__(self, db, bot_id, chat_id):
        self.db = db
        self.identity = (bot_id, chat_id)
        with db:
            db.execute('''CREATE TABLE IF NOT EXISTS dig_control (
                bot_id TEXT, chat_id INTEGER, enabled INTEGER NOT NULL DEFAULT 0,
                next_offset INTEGER NOT NULL DEFAULT 0, generation INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (bot_id, chat_id))''')
            columns = {row[1] for row in db.execute('PRAGMA table_info(dig_control)')}
            if 'generation' not in columns:
                db.execute('ALTER TABLE dig_control ADD COLUMN generation INTEGER NOT NULL DEFAULT 0')
            db.execute('INSERT OR IGNORE INTO dig_control(bot_id, chat_id) VALUES (?, ?)', self.identity)

    def state(self):
        return self.db.execute('SELECT enabled, next_offset, generation FROM dig_control WHERE bot_id=? AND chat_id=?',
                               self.identity).fetchone()

    def accept(self, update):
        update_id = update['update_id']
        message = update.get('message', {})
        chat = message.get('chat', {})
        sender = message.get('from', {})
        owner = self.identity[1]
        command = message.get('text') if (chat.get('type') == 'private'
                  and chat.get('id') == sender.get('id') == owner and not sender.get('is_bot')) else None
        enabled = {START: 1, STOP: 0}.get(command)
        with self.db:
            changed = self.db.execute('''UPDATE dig_control SET
                generation=generation+CASE WHEN enabled<>? THEN 1 ELSE 0 END,
                enabled=COALESCE(?, enabled), next_offset=?
                WHERE bot_id=? AND chat_id=? AND next_offset<=?''',
                (enabled, enabled, update_id + 1, *self.identity, update_id)).rowcount
        return bool(changed and enabled is not None)
