"""Официальный HH API: одна сессия, ограниченный поиск, без повторов."""

import time

import httpx

from des_job_watcher.dig_control import requests_allowed


class HHError(Exception):
    """Безопасное сообщение без тела ответа, заголовков и секретов."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class HHClient:
    def __init__(self, user_agent, token=None, *, transport=None):
        if not user_agent or not user_agent.strip():
            raise ValueError('Нужен HH-User-Agent с названием приложения и контактом.')
        self.client = httpx.Client(
            base_url='https://api.hh.ru', timeout=30,
            headers={'HH-User-Agent': user_agent}, transport=transport,
        )
        if token:
            self.client.headers['Authorization'] = f'Bearer {token}'

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def _request(self, method, path, **kwargs):
        if not requests_allowed():
            raise HHError('Раскопки остановлены. Запрос к HH пропущен.')
        try:
            response = self.client.request(method, path, **kwargs)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            raise HHError(f'HH вернул HTTP {status}; повторов нет.', status) from None
        except httpx.RequestError:
            raise HHError('Ошибка сети при обращении к HH; повторов нет.') from None
        except ValueError:
            raise HHError('HH вернул некорректный JSON.') from None
        if not isinstance(data, dict):
            raise HHError('Ожидался JSON-объект HH.')
        return data

    def issue_token(self, client_id, client_secret):
        if not client_id.strip() or not client_secret.strip():
            raise ValueError('Пустые реквизиты приложения.')
        data = self._request('POST', '/token', data={
            'grant_type': 'client_credentials',
            'client_id': client_id, 'client_secret': client_secret,
        })
        token = data.get('access_token')
        if not isinstance(token, str) or not token.strip():
            raise HHError('В ответе HH нет access_token.')
        self.client.headers['Authorization'] = f'Bearer {token}'
        # Токен остаётся в памяти. Владелец может посмотреть его в кабинете HH.

    def detail(self, vacancy_id):
        if not isinstance(vacancy_id, str) or not vacancy_id.isascii() or not vacancy_id.isdigit():
            raise ValueError('Нужен числовой HH ID.')
        if 'Authorization' not in self.client.headers:
            raise ValueError('Не задан токен приложения HH.')
        data = self._request('GET', f'/vacancies/{vacancy_id}')
        if data.get('id') != vacancy_id or not isinstance(data.get('description'), str):
            raise HHError('Некорректное полное описание HH.')
        return data

    def search(self, text, *, page=0, per_page=20, order_by='publication_time',
               area='113', remote_only=True):
        if 'Authorization' not in self.client.headers:
            raise ValueError('Не задан токен приложения HH.')
        params = {
            'text': text, 'order_by': order_by, 'page': page,
            'per_page': per_page, 'host': 'hh.ru', 'locale': 'RU',
        }
        if area is not None:
            params['area'] = area
        if remote_only:
            params['work_format'] = 'REMOTE'
        data = self._request('GET', '/vacancies', params=params)
        items = data.get('items')
        if not isinstance(items, list) or any(
            not isinstance(item, dict) or not isinstance(item.get('id'), str)
            or not isinstance(item.get('name'), str) for item in items
        ):
            raise HHError('Некорректный список вакансий HH.')
        return data


def collect_candidates(client, plan, profiles, *, per_page=20, pause=time.sleep):
    """По одной странице каждого запроса. ID общий, источники профилей сохраняются."""
    candidates = {}
    searches = []
    for profile_id in profiles:
        for query in plan['profiles'][profile_id]['queries']:
            if searches:
                pause(0.6)
            data = client.search(query['text'], per_page=per_page)
            searches.append({'profile': profile_id, 'query': query['id'],
                             'found': data.get('found'), 'received': len(data['items'])})
            for item in data['items']:
                record = candidates.setdefault(item['id'], {'vacancy': item, 'sources': []})
                source = {'profile': profile_id, 'query': query['id']}
                if source not in record['sources']:
                    record['sources'].append(source)
    return {'searches': searches, 'candidates': list(candidates.values())}
