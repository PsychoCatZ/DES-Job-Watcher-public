"""Проверить доступность одной вакансии через официальный API, без LLM и записи в БД."""

import argparse
import os
import sys

from des_job_watcher.hh_api import HHClient, HHError
from des_job_watcher.secret_input import read_secret


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--id', required=True)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if not args.id.isascii() or not args.id.isdigit():
        parser.error('Нужен числовой ID вакансии.')
    if not args.live:
        print(f'ПЛАН: GET /vacancies/{args.id}. Без сети и ключей. Добавь --live для проверки.')
        return 0
    try:
        agent = os.environ.get('HH_USER_AGENT') or input('HH-User-Agent (название приложения и контакт): ').strip()
        token = os.environ.get('HH_ACCESS_TOKEN') or read_secret('Токен приложения HH (*): ').strip()
        if not token:
            raise ValueError('Пустой токен HH.')
        with HHClient(agent, token) as client:
            vacancy = client.detail(args.id)
        print('API: карточка доступна для токена приложения.')
        print('Название:', vacancy['name'])
        print('Архив:', vacancy.get('archived', 'не указан'))
        print('Ссылка HH:', vacancy.get('alternate_url', 'не указана'))
        print('Доступность в браузере под твоей учётной записью — отдельная проверка.')
        return 0
    except (HHError, ValueError) as error:
        print('Проверка остановлена:', error)
        print('403 не доказывает удаление, а 404 не устанавливает причину недоступности. Повторов нет.')
        return 1
    except (EOFError, KeyboardInterrupt):
        print('\nВвод отменён.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
