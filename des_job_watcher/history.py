"""Локальная история: вакансия и неизменяемые снимки её содержимого."""

import hashlib
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone


class History:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS vacancies (
                id TEXT PRIMARY KEY, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS versions (
                id INTEGER PRIMARY KEY, vacancy_id TEXT NOT NULL REFERENCES vacancies(id),
                digest TEXT NOT NULL, fetched_at TEXT NOT NULL, raw_json TEXT NOT NULL,
                UNIQUE(vacancy_id, digest));
            CREATE TABLE IF NOT EXISTS assessment_reviews (
                review_key TEXT PRIMARY KEY, vacancy_id TEXT NOT NULL,
                profile_id TEXT NOT NULL, created_at TEXT NOT NULL,
                review_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS analysis_attempts (
                scope_key TEXT PRIMARY KEY, request_hash TEXT NOT NULL,
                status TEXT NOT NULL, source_path TEXT NOT NULL, created_at TEXT NOT NULL);
        ''')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def has_detail(self, vacancy_id):
        return self.db.execute('SELECT 1 FROM versions WHERE vacancy_id=? LIMIT 1',
                               (vacancy_id,)).fetchone() is not None

    def save_review(self, review):
        raw = json.dumps(review, ensure_ascii=False, sort_keys=True)
        key = hashlib.sha256(raw.encode()).hexdigest()
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO assessment_reviews VALUES (?,?,?,?,?)',
                            (key, review['vacancy_id'], review['profile_id'],
                             datetime.now(timezone.utc).isoformat(), raw))
        return key

    def attempt_status(self, scope_key):
        row = self.db.execute('SELECT status FROM analysis_attempts WHERE scope_key=?', (scope_key,)).fetchone()
        return row[0] if row else None

    def reserve_attempt(self, scope_key, request_hash, source_path):
        with self.db:
            cursor = self.db.execute('INSERT OR IGNORE INTO analysis_attempts VALUES (?,?,?,?,?)',
                                     (scope_key, request_hash, 'in_flight', str(source_path),
                                      datetime.now(timezone.utc).isoformat()))
        return cursor.rowcount == 1

    def finish_attempt(self, scope_key, status):
        with self.db:
            self.db.execute('UPDATE analysis_attempts SET status=? WHERE scope_key=?', (status, scope_key))

    def save_detail(self, detail):
        vacancy_id = detail['id']
        # Не включаем счётчики просмотров и время скачивания в отпечаток содержания.
        content = {key: detail.get(key) for key in (
            'name', 'description', 'employer', 'archived', 'work_format',
            'work_formats', 'area', 'key_skills', 'experience', 'employment',
            'schedule', 'salary', 'salary_range', 'working_hours',
        )}
        digest = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        existed = self.has_detail(vacancy_id)
        with self.db:
            self.db.execute('INSERT INTO vacancies VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen',
                            (vacancy_id, now, now))
            cursor = self.db.execute('INSERT OR IGNORE INTO versions(vacancy_id,digest,fetched_at,raw_json) VALUES (?,?,?,?)',
                                     (vacancy_id, digest, now, json.dumps(detail, ensure_ascii=False)))
        return 'unchanged' if cursor.rowcount == 0 else ('changed' if existed else 'new')
