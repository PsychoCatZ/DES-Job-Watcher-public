"""Локальная привязка получателя и ключи истории доставки. Токены не сохраняются."""

import hashlib
import json


def load_binding(path, bot_id):
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('bot_id') != bot_id:
        raise ValueError('Сохранённая привязка относится к другому боту.')
    chat_id = value.get('chat_id')
    if type(chat_id) is not int or chat_id <= 0:
        raise ValueError('В привязке нужен ID личного чата.')
    return chat_id


def save_binding(path, bot_id, chat_id):
    if type(chat_id) is not int or chat_id <= 0:
        raise ValueError('В привязке нужен ID личного чата.')
    path.parent.mkdir(parents=True, exist_ok=True)
    # Не заменяем уже существующую привязку, в том числе при параллельном запуске.
    with path.open('x', encoding='utf-8') as output:
        json.dump({'bot_id': bot_id, 'chat_id': chat_id}, output, indent=2)


def receipt_path(directory, bot_id, chat_id, card):
    identity = f"{bot_id}:{chat_id}:{card['vacancy_id']}:{card['profile_id']}"
    return directory / (hashlib.sha256(identity.encode()).hexdigest() + '.json')


def next_card(cards, directory, bot_id, chat_id):
    return next((card for card in cards if card['group'] == 'consider'
                 and not receipt_path(directory, bot_id, chat_id, card).exists()), None)
