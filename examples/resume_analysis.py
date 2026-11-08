"""Продолжить подготовленную партию без повторной отправки прежних попыток."""

import argparse
import json
import os
from pathlib import Path

from des_job_watcher.analysis_cache import analysis_scope, import_attempts
from des_job_watcher.history import History
from des_job_watcher.openai_adapter import analyze_once, prepare_body
from des_job_watcher.operational_policy import apply_policy
from des_job_watcher.evaluation_run import save_json
from des_job_watcher.secret_input import read_secret
from examples.report_saved import render_card

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    try:
        jobs = []
        with History(ROOT / 'data/watcher.sqlite3') as history:
            import_attempts(history, ROOT / 'data/analysis_batches')
            for path in sorted(args.batch.glob('*_input.json')):
                payload = json.loads(path.read_text(encoding='utf-8'))
                _, metadata = prepare_body(payload)
                scope = analysis_scope(payload)
                status = history.attempt_status(scope)
                print(f"{payload['vacancy']['id']} | {payload['vacancy']['name']} | {status or 'ожидает анализа'}")
                if not status:
                    jobs.append((path, payload, metadata, scope))
            print(f'Осталось платных запросов: {len(jobs)}. Повторов нет.')
            if not args.live or not jobs:
                print('Сеть и ключи не использовались.')
                return 0
            key = os.environ.get('OPENAI_API_KEY') or read_secret('OpenAI API key (*): ').strip()
            if not key or any(char.isspace() for char in key):
                raise ValueError('Ключ пуст или содержит пробелы.')
            cards = ['# Продолжение партии', '']
            for path, payload, metadata, scope in jobs:
                output = path.with_name(path.name.replace('_input.json', '_result.json'))
                if output.exists():
                    raise ValueError('Файл результата уже существует; перезапись запрещена.')
                if not history.reserve_attempt(scope, metadata['request_sha256'], output):
                    continue
                record = analyze_once(payload, key)
                save_json(output, record)
                history.finish_attempt(scope, record['status'])
                if record['status'] != 'completed':
                    print(f"Остановлено: {record.get('error', record['status'])}")
                    return 1
                review = apply_policy(record['assessment'], payload['vacancy'], profile_id=payload['profile']['profile_id'])
                review.update(vacancy_id=payload['vacancy']['id'], profile_id=payload['profile']['profile_id'],
                              kind='new_analysis_with_operational_policy', source_path=str(output.resolve()))
                history.save_review(review)
                cards.extend(render_card(payload, review))
                (args.batch / 'continuation_report.md').write_text('\n'.join(cards), encoding='utf-8')
                print(f"{payload['vacancy']['id']}: {review['assessment']['decision']} / {review['assessment']['delivery']['action']}")
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(f'Продолжение остановлено: {error}')
        return 1
    except KeyboardInterrupt:
        print('\nПрервано; зарегистрированная попытка не будет повторена автоматически.')
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
