"""Подготовить сохранённые карточки к анализу и явно запустить ограниченную партию."""

import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import sqlite3

from des_job_watcher.openai_adapter import analyze_once, prepare_body
from des_job_watcher.secret_input import read_secret
from examples.prepare_analysis import build_input
from des_job_watcher.operational_policy import add_workplace_evidence, equipment_barriers, apply_policy, load_candidate_feedback, load_policy
from des_job_watcher.history import History
from des_job_watcher.dig_control import requests_allowed
from examples.report_saved import render_card
from des_job_watcher.analysis_cache import analysis_scope, import_attempts
from des_job_watcher.source_fragments import response_schema

ROOT = Path(__file__).resolve().parents[1]


class DescriptionParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in ('br', 'p', 'li', 'div', 'h2', 'h3'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('p', 'li', 'div', 'h2', 'h3'):
            self.parts.append('\n')


def make_api_snapshot(detail):
    parser = DescriptionParser()
    parser.feed(detail['description'])
    text = '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())
    employer = detail.get('employer') or {}
    return {'search': {'items': [{
        'id': detail['id'], 'name': detail['name'],
        'url': f"https://hh.ru/vacancy/{detail['id']}",
        'employer': employer, 'salary': detail.get('salary'),
    }]}, 'detail': {'id': detail['id'], 'description_text': text,
                   'work_formats': [item['id'] for item in detail.get('work_format', [])],
                   'archived': detail.get('archived')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='Исходный candidates.json')
    parser.add_argument('--limit', type=int, default=5, help='Максимум пар вакансия–профиль')
    parser.add_argument('--vacancy', action='append', help='Анализировать только указанные HH ID; можно повторять')
    parser.add_argument('--live', action='store_true', help='Платный анализ Luna, без повторов')
    parser.add_argument('--profile', choices=['support', 'ai_data'])
    parser.add_argument('--output-directory', type=Path, help='Уникальная папка партии для общего прохода')
    args = parser.parse_args()
    try:
        if not 1 <= args.limit <= 30:
            raise ValueError('Лимит от 1 до 30.')
        records = json.loads(args.input.read_text(encoding='utf-8'))['candidates']
        jobs = []
        seen = set()
        with History(ROOT / 'data/watcher.sqlite3') as history:
            imported = import_attempts(history, ROOT / 'data/analysis_batches')
            if imported:
                print(f'Учтено прежних API-попыток: {imported}.')
        with sqlite3.connect(f'file:{ROOT / "data" / "watcher.sqlite3"}?mode=ro', uri=True) as db:
            for record in records:
                vacancy_id = record['vacancy']['id']
                if args.vacancy and vacancy_id not in args.vacancy:
                    continue
                row = db.execute('SELECT raw_json FROM versions WHERE vacancy_id=? ORDER BY id DESC LIMIT 1', (vacancy_id,)).fetchone()
                if row is None:
                    continue
                detail = json.loads(row[0])
                employer = detail.get('employer') or {}
                if any(' '.join(str(employer.get(field, '')).casefold().split())
                       in ('data light', 'data-light', 'дата лайт') for field in ('name', 'visibleName')):
                    print(f'{vacancy_id}: исключённый работодатель; платного запроса не будет.')
                    continue
                if detail.get('archived') is True:
                    continue
                snapshot = make_api_snapshot(detail)
                barriers = equipment_barriers(snapshot['detail']['description_text'])
                if barriers:
                    with History(ROOT / 'data/watcher.sqlite3') as history:
                        history.save_review({'vacancy_id': vacancy_id, 'profile_id': 'pre_filter',
                                             'kind': 'equipment_filter_before_llm',
                                             'description': snapshot['detail']['description_text'],
                                             'quotes': barriers, 'operational_policy_version': load_policy()['version']})
                    print(f'{vacancy_id}: исключено до LLM — требование оборудования для голосовой/видеосвязи.')
                    continue
                for source in record['sources']:
                    profile = source['profile']
                    if args.profile and profile != args.profile:
                        continue
                    pair = (vacancy_id, profile)
                    if profile not in ('support', 'ai_data') or pair in seen:
                        continue
                    seen.add(pair)
                    feedback = load_candidate_feedback({'id': vacancy_id, 'description': snapshot['detail']['description_text']}, profile)
                    if feedback:
                        print(f'{vacancy_id} | {profile}: уже отклонено кандидатом для этой версии; платного запроса не будет.')
                        continue
                    payload = add_workplace_evidence(build_input(profile, snapshot))
                    payload['analysis_contract_version'] = 4
                    payload['response_contract'] = response_schema(payload)
                    if not isinstance(payload['vacancy']['employer'], dict):
                        raise ValueError('Работодатель должен быть объектом до вызова LLM.')
                    with History(ROOT / 'data/watcher.sqlite3') as history:
                        status = history.attempt_status(analysis_scope(payload))
                    if status:
                        print(f'{vacancy_id} | {profile}: прежняя попытка {status}; повторной оплаты не будет.')
                        continue
                    prepare_body(payload)
                    jobs.append(payload)
                    if len(jobs) >= args.limit:
                        break
                if len(jobs) >= args.limit:
                    break
        if not jobs:
            if args.output_directory:
                args.output_directory.mkdir(parents=True, exist_ok=False)
            print('Нет сохранённых карточек для выбранного поиска.')
            return 0
        directory = args.output_directory or ROOT / 'data' / 'analysis_batches' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
        directory.mkdir(parents=True, exist_ok=False)
        for index, payload in enumerate(jobs):
            (directory / f'{index + 1:03}_input.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f"{index + 1}: {payload['vacancy']['id']} | {payload['profile']['profile_id']} | {payload['vacancy']['name']}")
        print(f'Входы: {directory}')
        if not args.live:
            print(f'Подготовлено: {len(jobs)}. Сеть и ключ не использовались. Для платного анализа добавьте --live.')
            return 0
        print(f'ПЛАТНЫЙ АНАЛИЗ: до {len(jobs)} запросов Luna. Автоматических повторов нет.')
        key = os.environ.get('OPENAI_API_KEY') or read_secret('OpenAI API key (*): ').strip()
        cards = ['# Результаты личного анализа', '']
        for index, payload in enumerate(jobs):
            if not requests_allowed():
                print('Раскопки остановлены. Следующий анализ Luna пропущен.')
                return 0
            _, metadata = prepare_body(payload)
            scope = analysis_scope(payload)
            with History(ROOT / 'data/watcher.sqlite3') as history:
                reserved = history.reserve_attempt(scope, metadata['request_sha256'], directory / f'{index + 1:03}_result.json')
            if not reserved:
                print('Попытка уже зарегистрирована другим запуском; пропускаем.')
                continue
            marker = directory / f'{index + 1:03}_in_flight.json'
            marker.write_text('{"status":"in_flight"}', encoding='utf-8')
            result = analyze_once(payload, key)
            if result['status'] == 'completed':
                result['operational_review'] = apply_policy(result['assessment'], payload['vacancy'], profile_id=payload['profile']['profile_id'])
            (directory / f'{index + 1:03}_result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            with History(ROOT / 'data/watcher.sqlite3') as history:
                history.finish_attempt(scope, result['status'])
            if result['status'] == 'completed':
                review = result['operational_review']
                persisted = {**review, 'vacancy_id': payload['vacancy']['id'],
                             'profile_id': payload['profile']['profile_id'],
                             'kind': 'new_analysis_with_operational_policy',
                             'request': result['request'], 'source_path': str(directory / f'{index + 1:03}_result.json')}
                with History(ROOT / 'data/watcher.sqlite3') as history:
                    history.save_review(persisted)
                cards.extend(render_card(payload, {**review, 'kind': 'new_analysis_with_operational_policy'}))
                (directory / 'report.md').write_text('\n'.join(cards), encoding='utf-8')
            marker.unlink()
            if result['status'] != 'completed':
                print(f"Остановлено: {result['status']}. Результат сохранён.")
                return 1
            assessment = result['operational_review']['assessment']
            print(f"{index + 1}/{len(jobs)}: {assessment['decision']} / {assessment['delivery']['action']}")
        return 0
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        print('Ошибка входных данных, профиля или базы. Запуск остановлен; сохранённые файлы остаются на месте.')
        return 1
    except (EOFError, KeyboardInterrupt):
        print('\nПрервано. Не повторяйте платный запуск без проверки сохранённых результатов.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
