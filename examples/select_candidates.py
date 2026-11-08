"""Локальный отбор из candidates.json, с необязательной проверкой истории."""

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

from des_job_watcher.candidate_selection import select_candidates
from des_job_watcher.analysis_cache import analysis_scope
from des_job_watcher.operational_policy import equipment_barriers
from examples.analyze_saved import make_api_snapshot


def cached_skip_reason(db, vacancy_id, profile):
    row = db.execute('SELECT raw_json FROM versions WHERE vacancy_id=? ORDER BY id DESC LIMIT 1',
                     (vacancy_id,)).fetchone()
    if row is None:
        return None
    raw = json.loads(row[0])
    snapshot = make_api_snapshot(raw)
    detail = snapshot['detail']
    if detail['archived'] is True:
        return 'Сохранённая версия архивная.'
    if equipment_barriers(detail['description_text']):
        return 'Сохранённый текст содержит известное обязательное оборудование для голосовой связи.'
    vacancy = {'id': vacancy_id, 'name': raw['name'], 'description': detail['description_text'],
               'work_formats': detail['work_formats'], 'archived': detail['archived']}
    scope = analysis_scope({'vacancy': vacancy, 'profile': {'profile_id': profile}})
    attempt = db.execute('SELECT status FROM analysis_attempts WHERE scope_key=?', (scope,)).fetchone()
    if attempt:
        return f'По этой версии и профилю уже есть попытка Luna ({attempt[0]}).'
    return None


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--profile', choices=['support', 'ai_data'], required=True)
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--history', type=Path, help='SQLite-история, только чтение')
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error('Лимит: 1–100.')
    source = json.loads(args.input.read_text(encoding='utf-8'))
    if args.history and args.history.exists():
        with closing(sqlite3.connect(args.history.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            selected, audit = select_candidates(source['candidates'], args.profile, args.limit,
                skip_reason=lambda vacancy_id: cached_skip_reason(db, vacancy_id, args.profile))
    else:
        selected, audit = select_candidates(source['candidates'], args.profile, args.limit)
    result = {'kind': 'selected_candidates', 'selection_version': 2,
              'profile': args.profile, 'source': str(args.input.resolve()),
              'candidates': selected, 'selection_audit': audit}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    for row in audit:
        print(f"{row['id']} | {row['score']} | {'selected' if row['selected'] else row['action']} | {row['name']}")
    print(f'Выбрано: {len(selected)}. Все основания: {args.output}. Сети и LLM не было.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
