"""Доставка сохранённых карточек в личный чат владельца."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys

import httpx

from des_job_watcher.notification_card import render_notification
from des_job_watcher.dig_control import KEYBOARD, requests_allowed
from des_job_watcher.secret_input import read_secret
from des_job_watcher.telegram_client import TelegramClient, TelegramError
from des_job_watcher.telegram_delivery import load_binding, save_binding, receipt_path, next_card

ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--bind-only', action='store_true', help='Только привязать личный чат, без отправки')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--limit', type=int, choices=range(1, 4), default=1)
    parser.add_argument('--suitable-only', action='store_true')
    args = parser.parse_args()
    if not args.bind_only and args.report is None:
        parser.error('Укажи --report или --bind-only.')
    directory = args.report.resolve() if args.report else None
    try:
        summary = (json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
                   if not args.bind_only else {'cards': []})
        if not args.bind_only and summary.get('kind') != 'combined_saved_analysis_report':
            raise ValueError('Нужен единый отчёт сохранённых анализов.')
        if args.suitable_only:
            summary['cards'] = [item for item in summary['cards'] if item['decision'] == 'suitable']
        summary['cards'].sort(key=lambda item: item['decision'] != 'suitable')
        card = next((item for item in summary['cards'] if item['group'] == 'consider'), None)
        if card is None and not args.bind_only:
            print('В отчёте нет карточек для рассмотрения. Отправлять нечего; сеть и ключи не использовались.')
            return 0
        if not args.live:
            if card:
                path = (directory / card['review_file']).resolve()
                if path.parent != directory:
                    raise ValueError('Оценка должна находиться в папке отчёта.')
                print(render_notification(card, json.loads(path.read_text(encoding='utf-8'))))
            print('\nПЛАН. Для выполнения добавь --live. Ключи и сеть не использовались. История доставки в этом режиме не фильтруется.')
            return 0
        token = os.environ.get('TELEGRAM_BOT_TOKEN') or read_secret('Токен бота (*): ').strip()
        with httpx.Client(timeout=25, follow_redirects=False) as client:
            telegram = TelegramClient(token, client)
            bot_id = token.split(':')[0]
            binding = ROOT / 'data' / 'telegram_binding.json'
            chat_id = load_binding(binding, bot_id)
            if chat_id is None:
                code = secrets.token_hex(8)
                print('\nОтправь своему боту в личном чате эту команду:\n/start ' + code)
                input('После отправки нажми Enter здесь: ')
                chat_id = telegram.find_private_chat(code)
                save_binding(binding, bot_id, chat_id)
                print('Личный чат привязан. Токен в файл не записан.')
            else:
                print('Используется сохранённая привязка личного чата.')
            if args.bind_only:
                print('Привязка проверена локально. Сообщения не отправлялись.')
                return 0
            # Резервируем попытку до отправки. При таймауте доставка неизвестна.
            receipts = ROOT / 'data' / 'telegram_deliveries'
            sent = 0
            for _ in range(args.limit):
                card = next_card(summary['cards'], receipts, bot_id, chat_id)
                if card is None:
                    break
                path = (directory / card['review_file']).resolve()
                if path.parent != directory:
                    raise ValueError('Оценка должна находиться в папке отчёта.')
                text = render_notification(card, json.loads(path.read_text(encoding='utf-8')))
                print(text)
                if not requests_allowed():
                    print('Раскопки выключены. Дальнейшая доставка остановлена.')
                    break
                receipts.mkdir(parents=True, exist_ok=True)
                receipt = receipt_path(receipts, bot_id, chat_id, card)
                record = {'status': 'reserved_delivery_unknown', 'vacancy_id': card['vacancy_id'],
                          'profile_id': card['profile_id'], 'created_at': datetime.now(timezone.utc).isoformat(),
                          'text_sha256': hashlib.sha256(text.encode()).hexdigest()}
                try:
                    with receipt.open('x', encoding='utf-8') as output:
                        json.dump(record, output, ensure_ascii=False, indent=2)
                except FileExistsError:
                    print('Для этой вакансии и профиля уже есть попытка доставки в этот чат. Повтор остановлен.')
                    return 1
                message_id = telegram.send(chat_id, text, reply_markup=KEYBOARD)
                record.update(status='sent', message_id=message_id)
                receipt.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
                sent += 1
            print(f'Карточек отправлено: {sent}.')
            return 0
    except (TelegramError, ValueError, OSError, sqlite3.Error) as error:
        print(f'Остановлено: {error}')
        return 1
    except (KeyboardInterrupt, EOFError):
        print('\nВвод отменён.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
