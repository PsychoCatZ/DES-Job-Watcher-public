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

from des_job_watcher.dig_control import DigControl, KEYBOARD, REFRESH, ONCE
from des_job_watcher.vacancy_queue import VacancyQueue
from des_job_watcher.secret_input import read_secret
from des_job_watcher.telegram_client import TelegramClient, TelegramError
from des_job_watcher.telegram_delivery import load_binding

ROOT = Path(__file__).resolve().parents[1]


def apply_refresh(control, data_directory, worker):
    """Дождаться конца старого прохода перед изменением его очереди."""
    request = control.refresh_request()
    if not request or (worker is not None and worker.poll() is None):
        return None
    with closing(sqlite3.connect(data_directory / 'watcher.sqlite3')) as queue_db:
        count = VacancyQueue(queue_db).dismiss_pending(request)
    control.finish_refresh(request)
    return count


def finish_worker(control, worker, generation, telegram, chat_id):
    if worker is None or worker.poll() is None:
        return False
    print(f'Проход завершился с кодом {worker.returncode}.', flush=True)
    if control.finish_once(generation):
        text = ('Раскопки закончены' if worker.returncode == 0 else
                'Раскопки остановлены из-за ошибки. Результат мог быть неполным. Автоповтора нет.')
        telegram.send(chat_id, text, reply_markup=KEYBOARD)
    return True


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
                  f'до {args.analysis_limit} попыток Luna, рекомендации отдельными карточками.')
        return 0
    worker = None
    worker_generation = None
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
            if control.once_mode() == 2:
                control.finish_once(control.state()[2])
                telegram.send(chat_id, 'Разовый проход был прерван перезапуском службы. '
                              'Раскопки выключены, автоматического повтора нет.', reply_markup=KEYBOARD)
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
                    if finish_worker(control, worker, worker_generation, telegram, chat_id):
                        worker = None
                    was_enabled = control.state()[0]
                    if control.accept(update):
                        enabled = control.state()[0]
                        if update.get('message', {}).get('text') == ONCE:
                            if not args.schedule:
                                control.finish_once(control.state()[2])
                                telegram.send(chat_id, 'В этом режиме поиск не включён.', reply_markup=KEYBOARD)
                                continue
                            next_run = 0
                            if worker is not None and worker.poll() is None and worker_generation == control.state()[2]:
                                control.mark_once_started()
                                text = 'Текущая партия станет последней. После неё раскопки остановятся.'
                            else:
                                text = 'Копаю одну партию. После результата раскопки остановятся.'
                            telegram.send(chat_id, text, reply_markup=KEYBOARD)
                            continue
                        if update.get('message', {}).get('text') == REFRESH:
                            telegram.send(chat_id, 'Обновление поиска принято. Если запрос уже выполняется, '
                                          'дождусь его завершения и сброшу необработанный остаток.', reply_markup=KEYBOARD)
                            continue
                        if enabled and not was_enabled:
                            next_run = 0
                        status = 'Раскопки включены.' if enabled else 'Раскопки выключены.'
                        telegram.send(chat_id, f'{status} {mode}' if enabled else status,
                                      reply_markup=KEYBOARD)
                if finish_worker(control, worker, worker_generation, telegram, chat_id):
                    worker = None
                dismissed = apply_refresh(control, ROOT / 'data', worker)
                if dismissed is not None:
                    next_run = 0
                    followup = ('Начинаю новый поиск HH.' if args.schedule and control.state()[0]
                                else 'Новый поиск начнётся после включения раскопок.' if args.schedule
                                else 'Автопоиск в этом режиме не включён.')
                    telegram.send(chat_id, f'Остаток очереди сброшен: {dismissed}. История сохранена. '
                                  + followup, reply_markup=KEYBOARD)
                if args.schedule and control.state()[0] and worker is None and time.monotonic() >= next_run:
                    worker_generation = control.state()[2]
                    control.mark_once_started()
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
