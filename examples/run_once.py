"""Один ограниченный проход HH → Luna → отчёт; Telegram включается явно."""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys

from des_job_watcher.dig_control import requests_allowed
from des_job_watcher.telegram_delivery import load_binding

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ('support', 'ai_data')


def run_step(name, arguments):
    if not requests_allowed():
        print('Разрешение на этот проход закончилось. Следующий этап пропущен.', flush=True)
        return False
    print(f'\n=== {name} ===', flush=True)
    try:
        result = subprocess.run([sys.executable, '-m', *arguments], cwd=ROOT, check=False)
    except KeyboardInterrupt:
        print(f'Этап прерван: {name}. Сохранённые результаты остаются на месте.', flush=True)
        return False
    if result.returncode:
        print(f'Этап остановлен: {name}; код {result.returncode}. Сохранённые результаты остаются на месте.', flush=True)
        return False
    return True


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Сеть HH и платные запросы Luna')
    parser.add_argument('--details-per-profile', type=int, default=10)
    parser.add_argument('--analyses-per-profile', type=int, default=3)
    parser.add_argument('--telegram', action='store_true', help='После отчёта отправить новые карточки')
    parser.add_argument('--telegram-limit', type=int, choices=range(1, 4), default=1)
    args = parser.parse_args()
    if not 1 <= args.details_per_profile <= 100 or not 1 <= args.analyses_per_profile <= 15:
        parser.error('Допустимые лимиты: 1–100 карточек и 1–15 анализов на профиль.')
    print('Профили: поддержка и AI-data. Один проход, без фонового режима.', flush=True)
    print('Telegram: ' + (f'максимум карточек за проход: {args.telegram_limit}.' if args.telegram else 'выключен.'), flush=True)
    print(f'Максимум: {2 * args.details_per_profile} новых карточек и {2 * args.analyses_per_profile} платных анализов.', flush=True)
    if not args.live:
        print('ПЛАН: сеть, ключи и база не использовались. Для выполнения добавь --live.', flush=True)
        return 0
    required = ['HH_USER_AGENT', 'HH_ACCESS_TOKEN', 'OPENAI_API_KEY']
    if args.telegram:
        required.append('TELEGRAM_BOT_TOKEN')
    missing = [name for name in required if not os.environ.get(name, '').strip()]
    if missing:
        print('Сначала настрой текущую сессию PowerShell через .\\scripts\\start_session.ps1. Не заданы: ' + ', '.join(missing), flush=True)
        return 1
    if args.telegram:
        try:
            if load_binding(ROOT / 'data/telegram_binding.json', os.environ['TELEGRAM_BOT_TOKEN'].split(':')[0]) is None:
                raise ValueError('Сначала привяжи чат через examples.send_telegram --bind-only --live.')
        except (OSError, ValueError) as error:
            print(f'Привязка Telegram: {error}', flush=True)
            return 1
    run_dir = ROOT / 'data' / 'hh_api' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    if not run_step('Поиск HH', ['examples.collect_hh', '--live', '--run-directory', str(run_dir)]):
        return 1
    candidates = str(run_dir / 'candidates.json')
    selected_paths = {}
    for profile in PROFILES:
        selected = str(run_dir / f'selected_{profile}.json')
        if not run_step(f'Отбор до Luna: {profile}', ['examples.select_candidates', '--input', candidates,
                        '--profile', profile, '--limit', str(args.details_per_profile), '--output', selected,
                        '--history', str(ROOT / 'data/watcher.sqlite3')]):
            return 1
        selected_paths[profile] = selected
        if not run_step(f'Полные карточки: {profile}', ['examples.fetch_hh_details', '--input', selected,
                        '--profile', profile, '--limit', str(args.details_per_profile), '--live']):
            return 1
    batches = []
    for profile in PROFILES:
        batch = ROOT / 'data' / 'analysis_batches' / f'{run_dir.name}_{profile}'
        if not run_step(f'Анализ Luna: {profile}', ['examples.analyze_saved', '--input', selected_paths[profile],
                        '--profile', profile, '--limit', str(args.analyses_per_profile),
                        '--output-directory', str(batch), '--live']):
            return 1
        batches.extend(['--batch', str(batch)])
    report = ROOT / 'data' / 'reports' / run_dir.name
    if not run_step('Общий отчёт', ['examples.report_saved', *batches, '--output-directory', str(report)]):
        return 1
    if args.telegram and not run_step('Telegram: доставка карточек', [
            'examples.send_telegram', '--report', str(report), '--limit', str(args.telegram_limit), '--live']):
        return 1
    print(f'\nПроход завершён. Поиск: {run_dir}. Общий отчёт: {report}.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
