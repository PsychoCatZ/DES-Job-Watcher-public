"""Защита от повторной отправки; неопределённые попытки тоже блокируют повтор."""

import hashlib
import json


def analysis_scope(payload):
    # Новая инструкция/профиль сами по себе не разрешают новую оплату того же текста.
    identity = {'vacancy': payload['vacancy'], 'profile_id': payload['profile']['profile_id']}
    identity['vacancy'] = {key: payload['vacancy'].get(key) for key in
                           ('id', 'name', 'description', 'work_formats', 'archived')}
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def import_attempts(history, directory):
    imported = 0
    for batch in sorted(directory.glob('*')):
        if not batch.is_dir():
            continue
        for path in sorted(batch.glob('*_input.json')):
            prefix = path.name.split('_')[0]
            result_path = batch / f'{prefix}_result.json'
            marker = batch / f'{prefix}_in_flight.json'
            if not result_path.exists() and not marker.exists():
                continue  # Подготовка без --live не является попыткой.
            payload = json.loads(path.read_text(encoding='utf-8'))
            record = json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else {}
            scope = analysis_scope(payload)
            if history.reserve_attempt(scope, record.get('request', {}).get('request_sha256', 'legacy'), result_path):
                history.finish_attempt(scope, record.get('status', 'in_flight'))
                imported += 1
    return imported
