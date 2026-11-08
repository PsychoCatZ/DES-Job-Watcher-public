"""Поиск через официальный API. По умолчанию только план, без сети и ключей."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from des_job_watcher.hh_api import HHClient, HHError, collect_candidates
from des_job_watcher.secret_input import read_secret
from examples.fetch_hh_page import load_search_plan

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--issue-token', action='store_true', help='Получить первый токен; прежний будет отозван')
    parser.add_argument('--profile', action='append', choices=['support', 'ai_data', 'developer'])
    parser.add_argument('--per-page', type=int, default=20, choices=range(1, 101), metavar='1..100')
    parser.add_argument('--run-directory', type=Path, help='Новый каталог для сохранения результатов поиска')
    args = parser.parse_args()
    plan = load_search_plan()
    profiles = list(dict.fromkeys(args.profile or plan['default_profiles']))
    for profile in profiles:
        print(f"{profile}: {plan['profiles'][profile]['label']}")
        for query in plan['profiles'][profile]['queries']:
            print(f"  {query['id']}: {query['text']}")
    if not args.live:
        print('ПЛАН: сеть и ключи не использовались. Для поиска добавьте --live.')
        return 0
    try:
        agent = os.environ.get('HH_USER_AGENT') or input('HH-User-Agent (DES-Job-Watcher/0.1 (ваша почта)): ').strip()
        token = None
        if not args.issue_token:
            token = os.environ.get('HH_ACCESS_TOKEN') or read_secret('Токен приложения HH (*): ').strip()
            if not token:
                raise ValueError('Пустой токен HH.')
        with HHClient(agent, token) as client:
            if args.issue_token:
                print('Получение токена один раз. Прежний токен будет отозван.')
                client.issue_token(read_secret('Client ID (*): ').strip(),
                                   read_secret('Client Secret (*): ').strip())
                print('Токен получен и используется в памяти. Для следующих запусков он доступен в кабинете HH.')
            result = collect_candidates(client, plan, profiles, per_page=args.per_page)
        result['fetched_at'] = datetime.now(timezone.utc).isoformat()
        result['status'] = 'search_candidates_not_recommendations'
        directory = args.run_directory or ROOT / 'data' / 'hh_api' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
        directory.mkdir(parents=True, exist_ok=False)
        (directory / 'candidates.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        lines = ['# Кандидаты из поиска HH', '',
                 'Полные описания и соответствие резюме пока не проверены. Это не рекомендации.', '']
        for record in result['candidates']:
            item = record['vacancy']
            sources = ', '.join(dict.fromkeys(source['profile'] for source in record['sources']))
            lines.extend([f"## {item['name']} ({sources})", '',
                          f"HH ID: {item['id']}", '',
                          f"Работодатель: {(item.get('employer') or {}).get('name', 'не указан')}", '',
                          f"Ссылка: https://hh.ru/vacancy/{item['id']}", ''])
        (directory / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
        print(f"Получено уникальных ID: {len(result['candidates'])}")
        print(f"Отчёт: {directory / 'report.md'}")
        print('LLM не вызывалась; фильтрация и чтение полных описаний — следующий шаг.')
    except (HHError, ValueError, OSError) as error:
        print(f'Запуск остановлен: {error}')
        return 1
    except (EOFError, KeyboardInterrupt):
        print('\nВвод отменён.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
