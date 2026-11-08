"""Версионированный дополнительный фильтр. Ответ модели не изменяется."""

from copy import deepcopy
import json
from pathlib import Path
import re
import hashlib

ROOT = Path(__file__).resolve().parents[1]


def load_policy():
    return json.loads((ROOT / 'config/operational_policy.json').read_text(encoding='utf-8'))


def equipment_barriers(description):
    """Консервативно распознать явное требование оборудования, вернуть цитаты."""
    found = []
    for line in re.split(r'[\n;.!?]+', description):
        line = line.strip(' \t—-•')
        lower = line.lower().replace('ё', 'е')
        if not re.search(r'\b(гарнитур\w*|микрофон\w*|(?:веб[- ]?)?камер\w*)\b', lower):
            continue
        if re.search(r'\bне\s+(?:нуж\w*|требу\w*|обязател\w*|использ\w*)|без\s+(?:гарнитур|микрофон|камер)', lower):
            continue
        # Камеры наблюдения/аннотирование изображений не означают оборудование кандидата.
        if re.search(r'наблюдени|видеонаблюдени|изображени|разметк|ремонт|продаж', lower):
            continue
        requirement = re.search(r'\b(?:необходим\w*|потребу\w*|понадоб\w*|требу\w*|наличи\w*|иметь|нуж\w*|обязател\w*)\b', lower)
        equipment_item = re.match(r'^(?:гарнитура|микрофон|(?:веб[- ]?)?камера)\b', lower)
        if requirement or equipment_item:
            found.append(line)
    return found


def load_candidate_feedback(vacancy, profile_id, path=None):
    path = Path(path) if path else ROOT / 'data/private/vacancy_feedback.json'
    if not profile_id or not path.exists():
        return []
    data = json.loads(path.read_text(encoding='utf-8'))
    digest = hashlib.sha256(vacancy['description'].encode('utf-8')).hexdigest()
    return [item for item in data['decisions']
            if item['vacancy_id'] == vacancy['id'] and item['profile_id'] == profile_id
            and item['description_sha256'] == digest
            and item['quote'] in vacancy['description']]


def apply_policy(assessment, vacancy, *, profile_id=None, feedback_path=None):
    result = deepcopy(assessment)
    quotes = equipment_barriers(vacancy['description'])
    overrides = []
    if quotes:
        result['decision'] = 'unsuitable'
        result['delivery'] = {'action': 'exclude', 'reasons': ['required_communication_equipment']}
        overrides.append({'rule': 'required_communication_equipment', 'quotes': quotes})
    feedback = load_candidate_feedback(vacancy, profile_id, feedback_path)
    for item in feedback:
        result['decision'] = 'unsuitable'
        if result['delivery']['action'] != 'exclude':
            result['delivery'] = {'action': 'review', 'reasons': ['candidate_declined_current_readiness']}
        overrides.append({'rule': 'candidate_declined_current_readiness',
                          'quotes': [item['quote']], 'reason': item['reason'],
                          'source': 'explicit_candidate_feedback', 'feedback_id': item['id']})
    return {'operational_policy_version': load_policy()['version'],
            'assessment': result, 'overrides': overrides,
            'candidate_feedback': feedback}


def add_workplace_evidence(payload, path=None):
    """Локальные факты владельца только для личного запуска, не учебных профилей."""
    path = Path(path) if path else ROOT / 'data/private/workplace.json'
    result = deepcopy(payload)
    if result['profile'].get('profile_kind') == 'synthetic' or not path.exists():
        return result
    context = json.loads(path.read_text(encoding='utf-8'))
    prefix = result['profile']['profile_id']
    for item in context['facts']:
        result['profile']['evidence'].append({
            'id': f"{prefix}_workplace_{item['id']}", 'fact': item['fact'],
            'period': 'Подтверждено владельцем 2026-10-29',
            'context': 'Локальный контекст рабочего места; не сведения об опыте из резюме.',
        })
    result['workplace_context_version'] = context['version']
    candidate_path = ROOT / 'data/private/candidate_facts.json'
    if path == ROOT / 'data/private/workplace.json' and candidate_path.exists():
        candidate = json.loads(candidate_path.read_text(encoding='utf-8'))
        for item in candidate['facts']:
            result['profile']['evidence'].append({
                'id': f"{prefix}_candidate_{item['id']}", 'fact': item['fact'],
                'period': item['confirmed_at'], 'context': 'Прямое уточнение кандидата об актуальности опыта; не текст резюме.',
            })
        result['candidate_context_version'] = candidate['version']
    return result
