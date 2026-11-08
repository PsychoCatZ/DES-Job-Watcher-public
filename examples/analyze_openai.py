"""Один анализ GPT-6 Luna; сетевой вызов выполняется только с --live."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from des_job_watcher.assessment import parse_response
from des_job_watcher.openai_adapter import analyze_once, prepare_body
from des_job_watcher.prompting import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--live', action='store_true', help='Выполнить один платный запрос API')
    args = parser.parse_args()
    try:
        payload = parse_response(args.input.read_text(encoding='utf-8'))
        body, metadata = prepare_body(payload)
        print(f"Модель: {body['model']}; reasoning: {body['reasoning']['effort']}")
        print(f"Лимит выходных токенов (включая reasoning): {body['max_output_tokens']}")
        print(f"Вакансия: {payload['vacancy']['id']}; профиль: {payload['profile']['profile_id']}")
        if not args.live:
            print('Проверка сборки: OK. Запрос не отправлен. Для одного вызова нужен --live.')
            return 0
        record = analyze_once(payload, os.environ.get('OPENAI_API_KEY'))
        record['started_input'] = args.input.name
        record['finished_at'] = datetime.now(timezone.utc).isoformat()
        directory = ROOT / 'data' / 'llm_results'
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
        output = directory / f'openai_{stamp}.json'
        output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f"Статус: {record['status']}")
        print(f"Результат: {output}")
        if record['status'] != 'completed':
            print(record.get('error', 'Анализ не завершён.'))
            return 1
        result = record['assessment']
        print(f"Итог: {result['decision']}")
        print(f"Маршрут: {result['delivery']['action']} (show/review доступны пользователю)")
        print('Противоречия:', ', '.join(result['blocking_reasons']) or 'нет')
        print('Неопределённость:', ', '.join(result['uncertainties']) or 'нет')
        print('Токены:', json.dumps(record.get('usage'), ensure_ascii=False))
    except (OSError, ValueError) as error:
        print(f'Ошибка запуска: {error}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
