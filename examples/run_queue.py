"""Один проход с постоянной очередью HH и общим бюджетом Luna."""

import argparse
from datetime import datetime, timezone
from itertools import zip_longest
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import re

import httpx

from des_job_watcher.analysis_cache import analysis_scope, import_attempts
from des_job_watcher.candidate_selection import rank_candidate, clean
from des_job_watcher.dig_control import KEYBOARD, requests_allowed
from des_job_watcher.hh_api import HHClient, HHError
from des_job_watcher.history import History
from des_job_watcher.openai_adapter import analyze_once, prepare_body
from des_job_watcher.operational_policy import add_workplace_evidence, equipment_barriers, load_candidate_feedback
from des_job_watcher.paid_digest import recommended_cards
from des_job_watcher.telegram_client import TelegramClient, TelegramError
from des_job_watcher.telegram_delivery import load_binding
from des_job_watcher.vacancy_queue import VacancyQueue
from examples.analyze_saved import make_api_snapshot
from examples.fetch_hh_page import load_search_plan
from examples.prepare_analysis import build_input
from examples.select_candidates import cached_skip_reason

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ('support', 'ai_data')

LABELS = {'received': 'Получено с HH.ru', 'duplicates': 'Повторы в выдаче',
          'processed': 'Уже обработаны', 'filtered': 'Отсеяны быстрым фильтром',
          'new': 'Новых кандидатов', 'attempted': 'Попыток анализа Luna',
          'analyzed': 'Полностью проанализировано', 'matched': 'Подходящих обнаружено',
          'consider': 'Можно рассмотреть',
          'sent': 'Отправлено в Telegram', 'remaining': 'Осталось для следующего прогона'}


def fast_rejection(item, description=''):
    employer = item.get('employer') or {}
    if any(clean(employer.get(key)) in ('data light', 'data-light', 'дата лайт')
           for key in ('name', 'visibleName')):
        return 'Работодатель исключён'
    if item.get('archived') is True:
        return 'Архивная вакансия'
    formats = item.get('work_format') or []
    if formats and all(isinstance(value, dict) and value.get('id') in ('HYBRID', 'ON_SITE') for value in formats):
        return 'Только офис или гибрид'
    if equipment_barriers(description):
        return 'Обязательное оборудование для голосовой связи'
    for line in description.splitlines():
        line = clean(line).strip(' —–-•.;!')
        if re.fullmatch(r'(?:принимать|совершать|обрабатывать) (?:входящие |исходящие |холодные )?звонки(?: клиентов)?', line):
            return 'Звонки прямо указаны среди обязанностей'
    return None


def ingest(items, queue, history, stats, seen, audit):
    eligible = {profile: [] for profile in PROFILES}
    for item, profiles in items.values():
        vacancy_id = item['id']
        if vacancy_id in seen:
            stats['duplicates'] += 1
            continue
        seen.add(vacancy_id)
        status = queue.status(vacancy_id)
        if status is not None:
            stats['duplicates' if status == 'pending' else 'processed'] += 1
            continue
        ranked = [(rank_candidate(item, profile), profile) for profile in profiles]
        rank, profile = max(ranked, key=lambda pair: pair[0]['score'])
        reason = fast_rejection(item)
        if not reason and rank['action'] != 'priority':
            reason = rank['reasons'][-1]
        if reason:
            stats['filtered'] += 1
            audit.append({'id': vacancy_id, 'reason': reason})
            continue
        if any(cached_skip_reason(history.db, vacancy_id, candidate) for candidate in PROFILES):
            stats['processed'] += 1
            queue.add(item, profile, 'processed')
            continue
        eligible[profile].append((rank['score'], item, profile))
    for candidates in eligible.values():
        candidates.sort(key=lambda candidate: -candidate[0])
    for pair in zip_longest(*(eligible[profile] for profile in PROFILES)):
        for candidate in pair:
            if candidate is not None:
                _, item, profile = candidate
                if queue.add(item, profile):
                    stats['new'] += 1


def collect_and_analyze(args, history, queue, batch, stats, audit):
    plan = load_search_plan()
    queries = [(profile, query['text']) for profile in PROFILES for query in plan['profiles'][profile]['queries']]
    pages = dict.fromkeys(queries, args.max_pages)
    seen = set()
    page = 0
    with HHClient(os.environ['HH_USER_AGENT'], os.environ['HH_ACCESS_TOKEN']) as hh:
        while stats['attempted'] < args.analysis_limit and requests_allowed():
            if queue.remaining() < args.analysis_limit - stats['attempted'] and page < max(pages.values()):
                items = {}
                for profile, query in queries:
                    if page >= pages[profile, query]:
                        continue
                    data = hh.search(query, page=page, per_page=args.page_size, order_by='relevance')
                    with (batch / 'search_pages.jsonl').open('a', encoding='utf-8') as output:
                        output.write(json.dumps({'profile': profile, 'query': query, 'page': page + 1,
                                                 'order_by': 'relevance',
                                                 'items': [{'id': item['id'], 'name': item['name'],
                                                            'employer': (item.get('employer') or {}).get('name')}
                                                           for item in data['items']]}, ensure_ascii=False) + '\n')
                    pages[profile, query] = min(args.max_pages, data.get('pages', args.max_pages))
                    stats['received'] += len(data['items'])
                    for item in data['items']:
                        _, profiles = items.setdefault(item['id'], (item, []))
                        if profiles:
                            stats['duplicates'] += 1
                        if profile not in profiles:
                            profiles.append(profile)
                    time.sleep(0.6)
                ingest(items, queue, history, stats, seen, audit)
                page += 1
            entry = queue.next()
            if entry is None:
                if page < max(pages.values()):
                    continue
                break
            vacancy_id, profile = entry
            time.sleep(0.6)
            if not requests_allowed():
                break
            try:
                raw = hh.detail(vacancy_id)
            except HHError as error:
                if error.status_code != 404:
                    raise
                queue.finish(vacancy_id, 'unavailable')
                stats['filtered'] += 1
                audit.append({'id': vacancy_id, 'reason': 'HH вернул HTTP 404'})
                continue
            history.save_detail(raw)
            snapshot = make_api_snapshot(raw)
            description = snapshot['detail']['description_text']
            reason = fast_rejection(raw, description)
            if not reason and load_candidate_feedback({'id': vacancy_id, 'description': description}, profile):
                reason = 'Кандидат отклонил эту версию'
            if reason:
                queue.finish(vacancy_id, 'filtered')
                stats['filtered'] += 1
                audit.append({'id': vacancy_id, 'reason': reason})
                continue
            payload = add_workplace_evidence(build_input(profile, snapshot))
            payload['analysis_contract_version'] = 4
            payload['include_model_verdict'] = True
            _, metadata = prepare_body(payload)
            prefix = f"{stats['attempted'] + 1:03}"
            source = batch / f'{prefix}_input.json'
            result_path = batch / f'{prefix}_result.json'
            if not requests_allowed():
                break
            scope = analysis_scope(payload)
            if not history.reserve_attempt(scope, metadata['request_sha256'], result_path):
                queue.finish(vacancy_id, 'processed')
                stats['processed'] += 1
                continue
            source.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            stats['attempted'] += 1
            result = analyze_once(payload, os.environ['OPENAI_API_KEY'])
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            history.finish_attempt(scope, result['status'])
            queue.finish(vacancy_id, result['status'])
            if result['status'] == 'completed':
                stats['analyzed'] += 1
            else:
                audit.append({'id': vacancy_id, 'reason': result.get('error', result['status'])})
                if result['status'] != 'analysis_failed':
                    break


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis-limit', type=int, choices=(10, 20, 30), default=10)
    parser.add_argument('--page-size', type=int, choices=range(1, 101), default=50)
    parser.add_argument('--max-pages', type=int, choices=range(1, 11), default=3)
    parser.add_argument('--telegram', action='store_true')
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    print(f'До {args.page_size} вакансий на страницу HH, до {args.max_pages} страниц на запрос, '
          f'до {args.analysis_limit} попыток Luna на проход.', flush=True)
    if not args.live:
        return 0
    required = ['HH_USER_AGENT', 'HH_ACCESS_TOKEN', 'OPENAI_API_KEY']
    if args.telegram:
        required.append('TELEGRAM_BOT_TOKEN')
    if any(not os.environ.get(key, '').strip() for key in required):
        print('Не хватает реквизитов. Запусти scripts/start_session.ps1 в текущем окне.')
        return 1
    bot_id = os.environ.get('TELEGRAM_BOT_TOKEN', '').split(':')[0]
    chat_id = load_binding(ROOT / 'data/telegram_binding.json', bot_id) if args.telegram else None
    if args.telegram and chat_id is None:
        print('Сначала привяжи чат.')
        return 1
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    batch = ROOT / 'data' / 'analysis_batches' / f'{stamp}_queue'
    batch.mkdir(parents=True)
    report = ROOT / 'data' / 'reports' / stamp
    stats = dict.fromkeys(LABELS, 0)
    audit = []
    error = None
    with History(ROOT / 'data/watcher.sqlite3') as history:
        queue = VacancyQueue(history.db)
        try:
            import_attempts(history, batch.parent)
            collect_and_analyze(args, history, queue, batch, stats, audit)
        except (HHError, OSError, ValueError, sqlite3.Error, KeyboardInterrupt) as failure:
            error = str(failure) or 'Проход прерван'
        stats['remaining'] = queue.remaining()
    # Отчёт нужен и после остановки. Этот этап читает только локальные результаты.
    from subprocess import run
    report_status = run([sys.executable, '-m', 'examples.report_saved', '--batch', str(batch),
                         '--output-directory', str(report)], cwd=ROOT, check=False).returncode
    if report_status == 0:
        summary = json.loads((report / 'summary.json').read_text(encoding='utf-8'))
        recommendations = recommended_cards(report, summary)
        stats['matched'] = sum(verdict == 'suitable' for verdict, _ in recommendations)
        stats['consider'] = len(recommendations) - stats['matched']
        if args.telegram and requests_allowed():
            try:
                with httpx.Client(timeout=25, follow_redirects=False) as client:
                    telegram = TelegramClient(os.environ['TELEGRAM_BOT_TOKEN'], client)
                    for number, (_, message) in enumerate(recommendations, 1):
                        if number > 1:
                            time.sleep(1.1)
                        if not requests_allowed():
                            break
                        receipt = report / f'telegram_digest_{number}.json'
                        with receipt.open('x', encoding='utf-8') as output:
                            json.dump({'status': 'reserved_delivery_unknown', 'cards': 1}, output)
                        message_id = telegram.send(chat_id, message, reply_markup=KEYBOARD)
                        stats['sent'] += 1
                        receipt.write_text(json.dumps({'status': 'sent', 'cards': 1,
                                                       'message_id': message_id}), encoding='utf-8')
            except (TelegramError, ValueError, OSError) as failure:
                error = error or f'Доставка остановилась: {failure}'
    else:
        error = error or 'Не удалось собрать отчёт анализа'
        report.mkdir(parents=True, exist_ok=True)
    lines = ['# Статистика прохода DES Job Watcher', '', '| Показатель | Число |', '| --- | ---: |']
    lines.extend(f'| {label} | {stats[key]} |' for key, label in LABELS.items())
    if error:
        lines += ['', f'Проход завершён с замечанием: {error}']
    (report / 'run_stats.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (report / 'run_stats.json').write_text(json.dumps({'counts': stats, 'audit': audit, 'error': error},
                                                      ensure_ascii=False, indent=2), encoding='utf-8')
    print('\n'.join(lines), flush=True)
    print(f'Статистика: {report / "run_stats.md"}', flush=True)
    return int(error is not None)


if __name__ == '__main__':
    raise SystemExit(main())
