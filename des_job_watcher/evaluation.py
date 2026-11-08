"""Рабочий корпус: источники отдельно от ожиданий, без сетевых вызовов."""

import hashlib
import json
from pathlib import Path


PROFILES = {'support', 'developer', 'ai_data'}


def load_cases(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    dataset = json.loads(manifest_path.read_text(encoding='utf-8'))
    if not isinstance(dataset, dict) or type(dataset.get('dataset_version')) is not int or dataset['dataset_version'] not in (1, 2, 3):
        raise ValueError('Неизвестная версия корпуса.')
    if dataset.get('split') != 'development':
        raise ValueError('Этот инструмент предназначен для известных рабочих случаев.')
    cases = dataset.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('Корпус должен содержать случаи.')
    seen = set()
    loaded = []
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError('Неверная запись случая.')
        case_id = case.get('id')
        if (not isinstance(case_id, str) or not case_id or
                any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_' for c in case_id)
                or case_id in seen):
            raise ValueError('Неверный или повторяющийся ID случая.')
        seen.add(case_id)
        if case.get('profile_id') not in PROFILES:
            raise ValueError(f'{case_id}: неизвестный профиль.')
        if case.get('readiness') not in ('ready', 'blocked'):
            raise ValueError(f'{case_id}: неверная готовность.')
        if case['readiness'] == 'blocked' and not case.get('prerequisites'):
            raise ValueError(f'{case_id}: нужна причина блокировки.')
        relative = case.get('text_file')
        if not isinstance(relative, str):
            raise ValueError(f'{case_id}: нет пути к тексту.')
        text_path = (manifest_path.parent / relative).resolve()
        if not text_path.is_relative_to(manifest_path.parent):
            raise ValueError(f'{case_id}: текст должен находиться внутри корпуса.')
        text = text_path.read_text(encoding='utf-8')
        if not text.strip():
            raise ValueError(f'{case_id}: пустой текст.')
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        if digest != case.get('text_sha256'):
            raise ValueError(f'{case_id}: текст изменился; проверьте ожидания и обновите отпечаток.')
        if not isinstance(case.get('checks'), list) or not case['checks']:
            raise ValueError(f'{case_id}: нет ожидаемых проверок.')
        for check in case['checks']:
            if not isinstance(check, dict) or not isinstance(check.get('path'), str) or not check.get('allowed'):
                raise ValueError(f'{case_id}: неверная проверка.')
        loaded.append((case, text))
    return dataset, loaded


def make_snapshot(case, text):
    """Не переносить ожидаемый результат, внешний разбор и название из разметки в запрос."""
    if case['readiness'] != 'ready':
        raise ValueError(f"{case['id']}: сначала выполнить prerequisites.")
    local_id = 'eval:' + case['id']
    # Заголовки и работодатели из чужих разборов не считаются полями оригинала.
    item = {'id': local_id, 'name': 'Название не предоставлено отдельно от текста',
            'employer': {}, 'url': None, 'salary': None}
    return {'search': {'items': [item]},
            'detail': {'id': local_id, 'description_text': text,
                       'work_formats': None, 'archived': None}}


def check_expected_fields(assessment, checks):
    """Только проверки полей; смысл цитат/требований всё ещё требует человека."""
    results = []
    for check in checks:
        value = assessment
        missing = False
        for key in check['path'].split('.'):
            if not isinstance(value, dict) or key not in value:
                missing = True
                value = None
                break
            value = value[key]
        results.append({'path': check['path'], 'expected': check['allowed'],
                        'actual': value, 'passed': not missing and value in check['allowed']})
    return results
