"""Проверить рабочий набор; --live выполняет по одному платному запросу на случай."""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path

import httpx

from des_job_watcher.evaluation_run import prepare_cases, run_cases
from des_job_watcher.openai_adapter import analyze_once
from des_job_watcher.prompting import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', action='append', dest='case_ids', help='ID случая; можно повторять')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--synthetic', action='store_true', help='Явно оценивать условные факты учебных профилей')
    parser.add_argument('--manifest', type=Path, default=ROOT / 'data/evaluation/development/cases.json',
                        help='Локальный корпус либо вымышленные examples/fixtures/evaluation/cases.json')
    parser.add_argument('--profile-directory', type=Path,
                        help='Явная папка профилей; для синтетического прогона config/profile_examples')
    args = parser.parse_args()
    try:
        mode = 'synthetic' if args.synthetic else 'production'
        dataset, jobs = prepare_cases(args.manifest, args.case_ids, profile_dir=args.profile_directory, mode=mode)
        print('РЕЖИМ:', 'СИНТЕТИЧЕСКИЙ — условные кандидаты, не личные рекомендации' if args.synthetic else 'ЛИЧНЫЙ АНАЛИЗ')
        for job in jobs:
            print(f"{job['case']['id']} | {job['payload']['profile']['profile_id']} "
                  f"v{job['payload']['profile']['version']} | {job['model']} / {job['reasoning']}")
        print(f'Запланировано запросов: {len(jobs)}; повторов нет.')
        if not args.live:
            print('Предварительная проверка завершена. На этом этапе API-запросов не было.')
            return 0
        api_key = os.environ.get('OPENAI_API_KEY', '')
        if not api_key or any(char.isspace() for char in api_key):
            raise ValueError('Нужен непустой ключ OPENAI_API_KEY без пробелов.')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
        directory = ROOT / 'data/evaluation/runs' / stamp
        print('Результаты:', directory, flush=True)
        def progress(result):
            checks = result.get('checks', [])
            print(f"{result['case_id']}: {result['status']} | "
                  f"{result.get('decision', '—')} / {result.get('delivery', '—')} | "
                  f"проверки {sum(check['passed'] for check in checks)}/{len(checks)}", flush=True)
        with httpx.Client(timeout=httpx.Timeout(120, connect=15), follow_redirects=False) as client:
            summary = run_cases(dataset, jobs, directory,
                                lambda payload: analyze_once(payload, api_key, client=client, mode=mode), progress)
        print('Отчёт:', directory / 'report.md')
        return 0 if summary['status'] == 'completed' else 1
    except (OSError, ValueError) as error:
        print('Ошибка прогона:', error)
        return 1
    except KeyboardInterrupt:
        print('Прервано. Запрос мог быть обработан; перед новым запуском проверьте сохранённую папку.')
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
