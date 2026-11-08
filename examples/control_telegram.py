"""Кнопки раскопок и опциональный периодический поиск в привязанном чате."""

import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import httpx

from des_job_watcher.dig_control import DigControl, KEYBOARD
from des_job_watcher.secret_input import read_secret
from des_job_watcher.telegram_client import TelegramClient, TelegramError
from des_job_watcher.telegram_delivery import load_binding

ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--schedule', action='store_true', help='Запускать проходы по сохранённому состоянию')
    parser.add_argument('--interval-minutes', type=int, default=60)
    parser.add_argument('--analysis-limit', type=int, choices=(10, 20, 30), default=10)
    parser.add_argument('--page-size', type=int, choices=range(1, 101), default=50)
    parser.add_argument('--max-pages', type=int, choices=range(1, 11), default=3)
    args = parser.parse_args()
    if args.interval_minutes < 30:
        parser.error('Интервал должен быть не менее 30 минут.')
    if not args.live:
        print('План: показать кнопки в привязанном чате и принимать команды до Ctrl+C.')
        if args.schedule:
            print(f'При включённых раскопках: проход каждые {args.interval_minutes} мин., '
                  f'до {args.analysis_limit} попыток Luna и трёх карточек.')
        return 0
    worker = None
    try:
        if args.schedule:
            missing = [key for key in ('HH_ACCESS_TOKEN', 'HH_USER_AGENT', 'OPENAI_API_KEY')
                       if not os.environ.get(key, '').strip()]
            if missing:
                raise ValueError('Сначала настрой сессию через scripts/start_session.ps1. Нужны ' + ', '.join(missing))
        token = os.environ.get('TELEGRAM_BOT_TOKEN') or read_secret('Токен бота (*): ').strip()
        bot_id = token.split(':')[0]
        chat_id = load_binding(ROOT / 'data/telegram_binding.json', bot_id)
        if chat_id is None:
            raise ValueError('Сначала привяжи личный чат.')
        with httpx.Client(timeout=30, follow_redirects=False) as client, closing(
                sqlite3.connect(ROOT / 'data/telegram_control.sqlite3')) as db, closing(
                sqlite3.connect(ROOT / 'data/telegram_controller_lock.sqlite3', timeout=0)) as lock:
            lock.execute('BEGIN EXCLUSIVE')
            telegram = TelegramClient(token, client)
            control = DigControl(db, bot_id, chat_id)
            status = 'включены' if control.state()[0] else 'выключены'
            mode = f'Интервал {args.interval_minutes} мин.' if args.schedule else 'Проверка кнопок без автопоиска.'
            telegram.send(chat_id, f'Раскопки {status}. {mode}', reply_markup=KEYBOARD)
            print('Кнопки отправлены. Открой бота. Для выхода нажми Ctrl+C.', flush=True)
            next_run = 0
            while True:
                updates = telegram.call('getUpdates', {'offset': control.state()[1],
                                                       'timeout': 3 if args.schedule else 20,
                                                       'allowed_updates': ['message']})
                for update in sorted(updates, key=lambda item: item['update_id']):
                    was_enabled = control.state()[0]
                    if control.accept(update):
                        enabled = control.state()[0]
                        if enabled and not was_enabled:
                            next_run = 0
                        status = 'Раскопки включены.' if enabled else 'Раскопки выключены.'
                        telegram.send(chat_id, f'{status} {mode}' if enabled else status,
                                      reply_markup=KEYBOARD)
                if worker is not None and worker.poll() is not None:
                    print(f'Проход завершился с кодом {worker.returncode}.', flush=True)
                    worker = None
                if args.schedule and control.state()[0] and worker is None and time.monotonic() >= next_run:
                    worker = subprocess.Popen([sys.executable, '-m', 'examples.run_queue', '--live', '--telegram',
                                               '--analysis-limit', str(args.analysis_limit),
                                               '--page-size', str(args.page_size), '--max-pages', str(args.max_pages)],
                                              cwd=ROOT, env={**os.environ, 'TELEGRAM_BOT_TOKEN': token,
                                                            'WATCHER_CONTROLLED': '1',
                                                            'WATCHER_DIG_GENERATION': str(control.state()[2])})
                    next_run = time.monotonic() + args.interval_minutes * 60
    except KeyboardInterrupt:
        print('\nОбработчик остановлен. Состояние кнопок сохранено.')
        return 0
    except (TelegramError, ValueError, OSError, sqlite3.Error, EOFError) as error:
        print(f'Остановлено: {error}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
