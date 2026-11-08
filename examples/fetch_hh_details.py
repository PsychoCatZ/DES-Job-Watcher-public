"""Загрузить новые карточки из сохранённого поиска в SQLite. Без LLM."""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import time

from des_job_watcher.hh_api import HHClient, HHError
from des_job_watcher.history import History
from des_job_watcher.secret_input import read_secret

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='candidates.json из поиска')
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--refresh', action='store_true', help='Перепроверить также сохранённые ID')
    parser.add_argument('--profile', choices=['support', 'ai_data', 'developer'])
    args = parser.parse_args()
    try:
        if not 1 <= args.limit <= 200:
            raise ValueError('Лимит должен быть от 1 до 200.')
        records = json.loads(args.input.read_text(encoding='utf-8'))['candidates']
        if args.profile:
            records = [record for record in records if any(source['profile'] == args.profile for source in record['sources'])]
        ids = list(dict.fromkeys(record['vacancy']['id'] for record in records))
        if any(not isinstance(value, str) or not value.isascii() or not value.isdigit() for value in ids):
            raise ValueError('Некорректный HH ID во входе.')
        if not args.live:
            print(f'ПЛАН: до {min(len(ids), args.limit)} карточек, без сети, ключей и записи в БД.')
            return 0
        path = ROOT / 'data' / 'watcher.sqlite3'
        with History(path) as history:
            selected = [value for value in ids if args.refresh or not history.has_detail(value)][:args.limit]
            if not selected:
                print('Новых ID нет. Сеть и ключи не использовались.')
                return 0
            agent = os.environ.get('HH_USER_AGENT') or input('HH-User-Agent: ').strip()
            token = os.environ.get('HH_ACCESS_TOKEN') or read_secret('Токен приложения HH (*): ').strip()
            if not token:
                raise ValueError('Пустой токен.')
            with HHClient(agent, token) as client:
                for index, vacancy_id in enumerate(selected):
                    if index:
                        time.sleep(0.6)
                    detail = client.detail(vacancy_id)
                    status = history.save_detail(detail)
                    print(f"{index + 1}/{len(selected)} | {vacancy_id} | {status} | {detail.get('name', '')}")
        print(f'База: {path}')
        print('Каждая карточка сохранена отдельно. LLM не вызывалась; рекомендации ещё не сформированы.')
    except (HHError, ValueError, OSError, KeyError, TypeError, sqlite3.Error):
        print('Запуск остановлен: ошибка HH, входных данных или базы. Уже сохранённые карточки остаются в БД. Повторов нет.')
        return 1
    except (EOFError, KeyboardInterrupt):
        print('\nЗапуск прерван. Уже сохранённые карточки остаются в БД.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
