"""Очередь по уникальным ID HH, в порядке добавления."""

import json


class VacancyQueue:
    def __init__(self, db):
        self.db = db
        with db:
            db.execute('''CREATE TABLE IF NOT EXISTS vacancy_queue (
                vacancy_id TEXT PRIMARY KEY, profile TEXT NOT NULL,
                item_json TEXT NOT NULL, status TEXT NOT NULL)''')

    def status(self, vacancy_id):
        row = self.db.execute('SELECT status FROM vacancy_queue WHERE vacancy_id=?', (vacancy_id,)).fetchone()
        return row[0] if row else None

    def add(self, item, profile, status='pending'):
        with self.db:
            return bool(self.db.execute('INSERT OR IGNORE INTO vacancy_queue VALUES (?, ?, ?, ?)',
                                        (item['id'], profile, json.dumps(item, ensure_ascii=False), status)).rowcount)

    def next(self):
        return self.db.execute('''SELECT vacancy_id, profile FROM vacancy_queue
            WHERE status='pending' ORDER BY rowid LIMIT 1''').fetchone()

    def finish(self, vacancy_id, status):
        with self.db:
            self.db.execute('UPDATE vacancy_queue SET status=? WHERE vacancy_id=?', (status, vacancy_id))

    def remaining(self):
        return self.db.execute("SELECT count(*) FROM vacancy_queue WHERE status='pending'").fetchone()[0]

    def dismiss_pending(self, request):
        """Идемпотентный сброс остатка: ID и аудит сохраняются даже после рестарта."""
        with self.db:
            self.db.execute('''CREATE TABLE IF NOT EXISTS queue_refreshes (
                request INTEGER PRIMARY KEY, dismissed INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            old = self.db.execute('SELECT dismissed FROM queue_refreshes WHERE request=?', (request,)).fetchone()
            if old:
                return old[0]
            count = self.db.execute("UPDATE vacancy_queue SET status='dismissed' WHERE status='pending'").rowcount
            self.db.execute('INSERT INTO queue_refreshes(request, dismissed) VALUES (?, ?)', (request, count))
        return count
