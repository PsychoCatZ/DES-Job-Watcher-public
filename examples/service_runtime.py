"""Загрузка секретов systemd и контрольный запрос перед запуском на VPS."""

import argparse
import json
import os
from pathlib import Path
import sys

import httpx

from des_job_watcher.hh_api import HHClient, HHError
from des_job_watcher.telegram_delivery import load_binding

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path('/etc/des-job-watcher/credentials.json')
FIELDS = ('HH_USER_AGENT', 'HH_ACCESS_TOKEN', 'OPENAI_API_KEY', 'TELEGRAM_BOT_TOKEN')


def validate_credentials(data):
    if not isinstance(data, dict) or set(data) != set(FIELDS):
        raise ValueError('Нужны четыре настройки Watcher.')
    if any(not isinstance(data[key], str) or not data[key].strip()
           or '\n' in data[key] or '\r' in data[key] for key in FIELDS):
        raise ValueError('Настройки пусты или содержат переносы строк.')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-credentials', action='store_true')
    parser.add_argument('--preflight', action='store_true')
    args = parser.parse_args()
    try:
        if args.install_credentials:
            data = validate_credentials(json.load(sys.stdin))
            CONFIG.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temp = CONFIG.with_suffix('.new')
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as output:
                json.dump(data, output, ensure_ascii=False)
            temp.replace(CONFIG)
            print('Настройки приняты. Значения скрыты.')
            return 0
        path = (Path(os.environ['CREDENTIALS_DIRECTORY']) / 'watcher'
                if 'CREDENTIALS_DIRECTORY' in os.environ else CONFIG)
        data = validate_credentials(json.loads(path.read_text(encoding='utf-8')))
        os.environ.update(data)
        if args.preflight:
            bot_id = data['TELEGRAM_BOT_TOKEN'].split(':')[0]
            if load_binding(ROOT / 'data/telegram_binding.json', bot_id) is None:
                raise ValueError('Нет привязки чата.')
            with HHClient(data['HH_USER_AGENT'], data['HH_ACCESS_TOKEN']) as hh:
                result = hh.search('техническая поддержка', per_page=1, order_by='relevance')
                print(f"HH: рабочий поиск прошёл, найдено {result.get('found')}, получено {len(result['items'])}.")
            with httpx.Client(timeout=25, follow_redirects=False) as client:
                response = client.get('https://api.openai.com/v1/models',
                                      headers={'Authorization': 'Bearer ' + data['OPENAI_API_KEY']})
                if response.status_code != 200:
                    raise ValueError(f'OpenAI: HTTP {response.status_code}')
                print('OpenAI: авторизованный запрос прошёл.')
                response = client.post('https://api.telegram.org/bot' + data['TELEGRAM_BOT_TOKEN'] + '/getMe')
                if response.status_code != 200:
                    raise ValueError(f'Telegram: HTTP {response.status_code}')
                bot = response.json()
                if not bot.get('ok') or str(bot['result']['id']) != bot_id:
                    raise ValueError('Telegram: бот не подтверждён.')
                print('Telegram: бот подтверждён, привязка соответствует.')
            return 0
        os.execv(sys.executable, [sys.executable, '-B', '-m', 'examples.control_telegram',
                                 '--live', '--schedule'])
    except (OSError, ValueError, HHError, httpx.HTTPError, KeyError, TypeError):
        print('Запуск остановлен: ошибка настройки или проверки API. Значения секретов скрыты.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
