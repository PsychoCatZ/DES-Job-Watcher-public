"""Сравнить первые страницы HH API без очереди, Luna и Telegram."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

from des_job_watcher.hh_api import HHClient, HHError
from des_job_watcher.secret_input import read_secret

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = (
    ('watcher', 'publication_time', '113', True),
    ('relevance', 'relevance', '113', True),
    ('relevance_without_remote_filter', 'relevance', '113', False),
    ('relevance_without_region_filter', 'relevance', None, False),
)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    queries = ('техническая поддержка', 'чат-поддержка')
    print('Сравнение: 8 запросов HH, по 50 позиций. Очередь, Luna и Telegram не используются.')
    if not args.live:
        return 0
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    path = ROOT / 'data' / 'search_comparison' / f'{stamp}.jsonl'
    try:
        agent = os.environ.get('HH_USER_AGENT') or input('HH-User-Agent: ').strip()
        token = os.environ.get('HH_ACCESS_TOKEN') or read_secret('Токен HH (*): ').strip()
        if not token:
            raise ValueError('Пустой токен HH.')
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f'Результаты: {path}', flush=True)
        with HHClient(agent, token) as hh, path.open('x', encoding='utf-8') as output:
            for query in queries:
                baseline = set()
                for label, order, area, remote in VARIANTS:
                    data = hh.search(query, per_page=50, order_by=order, area=area, remote_only=remote)
                    ids = {item['id'] for item in data['items']}
                    if label == 'watcher':
                        baseline = ids
                    record = {'query': query, 'variant': label, 'order_by': order, 'area': area,
                              'remote_only': remote, 'found': data.get('found'), 'items': data['items']}
                    output.write(json.dumps(record, ensure_ascii=False) + '\n')
                    output.flush()
                    print(f"{query} | {label} | найдено: {data.get('found')} | общих с baseline: {len(ids & baseline)}/{len(ids)}", flush=True)
                    time.sleep(0.6)
    except (HHError, OSError, ValueError, KeyboardInterrupt, EOFError) as error:
        print(f'Сравнение остановлено. {error}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
