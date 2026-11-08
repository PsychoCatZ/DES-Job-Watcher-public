"""Минимальный Telegram-клиент. Исключения не содержат URL с токеном."""

import re

import httpx


class TelegramError(Exception):
    pass


class TelegramClient:
    def __init__(self, token, client):
        if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token):
            raise ValueError('Неверный формат токена Telegram.')
        self._token = token
        self.client = client

    def call(self, method, data):
        if method not in ('getUpdates', 'sendMessage'):
            raise ValueError('Неподдерживаемый метод Telegram.')
        try:
            response = self.client.post(
                f'https://api.telegram.org/bot{self._token}/{method}', json=data)
            if response.status_code != 200:
                raise TelegramError(f'Telegram HTTP {response.status_code}; повтор не выполнялся.')
            body = response.json()
            if body.get('ok') is not True:
                raise TelegramError('Telegram отклонил запрос; повтор не выполнялся.')
            return body['result']
        except (httpx.HTTPError, ValueError, KeyError):
            raise TelegramError('Ошибка связи или ответа Telegram; повтор не выполнялся.') from None

    def find_private_chat(self, pairing_code):
        updates = self.call('getUpdates', {'timeout': 0, 'allowed_updates': ['message']})
        chats = set()
        for update in updates:
            message = update.get('message', {})
            chat = message.get('chat', {})
            sender = message.get('from', {})
            if (message.get('text', '').strip() == '/start ' + pairing_code
                    and chat.get('type') == 'private'
                    and chat.get('id') == sender.get('id') and not sender.get('is_bot')):
                chats.add(chat['id'])
        if len(chats) != 1:
            raise TelegramError('Не найден единственный личный чат с текущим кодом. Отправь команду боту и запусти снова.')
        return chats.pop()

    def send(self, chat_id, text, *, reply_markup=None):
        if len(text.encode('utf-16-le')) // 2 > 4096:
            raise ValueError('Карточка слишком длинная для одного сообщения Telegram.')
        data = {'chat_id': chat_id, 'text': text, 'link_preview_options': {'is_disabled': True}}
        if reply_markup is not None:
            data['reply_markup'] = reply_markup
        return self.call('sendMessage', data)['message_id']
