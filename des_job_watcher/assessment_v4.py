"""Контракт 4: ID источников, готовность и доступность слуха."""

from copy import deepcopy
import re

from des_job_watcher.source_fragments import response_schema, source_fragments
from des_job_watcher.requirement_rules import generic_autonomy


def check_schema(value, schema, path='response'):
    from des_job_watcher.assessment import AnalysisValidationError
    types = {'object': dict, 'array': list, 'string': str, 'integer': int, 'boolean': bool}
    def fail():
        raise AnalysisValidationError(f'{path}: нарушение контракта 4')
    if 'type' in schema and type(value) is not types[schema['type']]:
        fail()
    if 'const' in schema and value != schema['const']:
        fail()
    if 'enum' in schema and value not in schema['enum']:
        fail()
    if isinstance(value, dict):
        if set(schema.get('required', [])) - set(value):
            fail()
        if schema.get('additionalProperties') is False and set(value) - set(schema['properties']):
            fail()
        for key, item in value.items():
            check_schema(item, schema['properties'][key], f'{path}.{key}')
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0):
            fail()
        if schema.get('uniqueItems') and any(item in value[:index] for index, item in enumerate(value)):
            fail()
        for index, item in enumerate(value):
            check_schema(item, schema['items'], f'{path}[{index}]')
    if isinstance(value, str) and len(value.strip()) < schema.get('minLength', 0):
        fail()
    if type(value) is int and value < schema.get('minimum', value):
        fail()


def validate_v4(response, payload):
    from des_job_watcher.assessment import AnalysisValidationError, validate_and_decide
    if payload.get('analysis_contract_version') != 4:
        raise AnalysisValidationError('Контракт 4 не совпадает с версией входа.')
    check_schema(response, response_schema(payload))
    fragments = source_fragments(payload['vacancy'])
    texts = {item['id']: item['text'] for item in fragments}
    resolved = deepcopy(response)
    resolved.pop('model_verdict', None)
    resolved['contract_version'] = 3
    work = resolved['main_work']
    readiness = work.pop('entry_readiness')
    readiness_reason = work.pop('readiness_reason')
    for node in [work, resolved['ai_role'], *resolved['conditions'].values()]:
        node['quotes'] = [texts[identifier] for identifier in node.pop('quote_ids')]
    deaf_ids = [item['id'] for item in payload['profile']['evidence']
                if re.search(r'отсутстви[ея] слуха|\bя глух|\bкандидат глух|не слышу', item['fact'].lower())]
    corrections = []
    retained = []
    for index, item in enumerate(resolved['requirements']):
        if generic_autonomy(item['text']):
            corrections.append({'path': f'requirements[{index}]', 'before': item['text'],
                                'after': None, 'rule': 'generic_autonomy_not_a_requirement'})
        else:
            retained.append(item)
    resolved['requirements'] = retained
    country = resolved['conditions']['work_from_russia']
    # Отдельная текстовая цитата подтверждает страну; work_formats к ней не относится.
    explicit_russia = [quote for quote in country['quotes'] if re.fullmatch(
        r'удал[её]нная\s+работа\s+из\s+любого\s+(?:города|региона)\s+россии[.!;]?',
        quote.strip().casefold())]
    if (country['status'] == 'confirmed' and country['field_refs'] == ['vacancy.work_formats']
            and explicit_russia):
        corrections.append({'path': 'conditions.work_from_russia.field_refs',
                            'before': country['field_refs'][:], 'after': [],
                            'rule': 'explicit_russia_text_over_irrelevant_format_field',
                            'quotes': explicit_russia})
        country['field_refs'] = []
    remote = resolved['conditions']['remote']
    formats = payload['vacancy'].get('work_formats')
    # Поле со всеми вариантами не подтверждает полную удалёнку. Но его лишняя
    # ссылка не должна обесценивать отдельное явное текстовое подтверждение.
    explicit_remote = [quote for quote in remote['quotes'] if re.fullmatch(
        r'(?:полностью\s+)?удал[её]нн(?:ый\s+формат(?:\s+работы)?|ая\s+работа)[.!;]?'
        r'|работа\s+полностью\s+удал[её]нная[.!;]?'
        r'|(?:формат работы:\s*)?удал[её]нно или в офисе\s*\(?по (?:вашему )?желанию\)?[.!;]?',
        quote.strip().casefold())]
    explicit_remote.extend(quote for quote in remote['quotes'] if re.match(
        r'^гибридный или полностью удал[её]нный формат работы(?:\.|$)',
        quote.strip(), re.I))
    if (remote['status'] == 'confirmed' and remote['field_refs'] == ['vacancy.work_formats']
            and isinstance(formats, list) and 'REMOTE' in formats and set(formats) != {'REMOTE'}
            and explicit_remote):
        corrections.append({'path': 'conditions.remote.field_refs',
                            'before': remote['field_refs'][:], 'after': [],
                            'rule': 'explicit_remote_text_over_redundant_mixed_fields',
                            'quotes': explicit_remote})
        remote['field_refs'] = []
    elif (remote['status'] == 'confirmed' and remote['field_refs'] == ['vacancy.work_formats']
          and (not remote['quotes'] or all(re.search(
              r'гибридный\s*/\s*удал[её]нный формат|можно рассмотреть удал[её]нный формат',
              quote, re.I) for quote in remote['quotes'])) and isinstance(formats, list)
          and 'REMOTE' in formats and set(formats) != {'REMOTE'}):
        corrections.append({'path': 'conditions.remote.status', 'before': 'confirmed',
                            'after': 'unknown', 'rule': 'mixed_formats_without_text'})
        remote['status'] = 'unknown'
        remote['reason'] = 'HH указывает несколько форматов работы. Полная удалёнка отдельно не подтверждена.'
    core_gaps = []
    advanced_gaps = []
    mandatory_hearing = []
    for index, item in enumerate(resolved['requirements']):
        item['quote'] = texts[item.pop('quote_id')]
        role = item.pop('role')
        level = item.pop('required_level')
        hearing = item.pop('requires_hearing')
        explicit_hearing = r'на слух|прослушива\w*|слушать|listening'
        ambiguous_speech = (re.search(r'распознава?ни\w* речи', item['text'], re.I)
                            and not re.search(explicit_hearing, item['quote'], re.I))
        if hearing and ambiguous_speech:
            corrections.append({'path': f'requirements[{index}].requires_hearing', 'before': True,
                                'after': False, 'rule': 'speech_recognition_without_listening_evidence'})
            hearing = False
        if deaf_ids and (hearing or re.search(explicit_hearing, item['text'], re.I) and not ambiguous_speech):
            corrections.append({'path': f'requirements[{index}]', 'before': item['status'],
                                'after': 'conflict', 'rule': 'known_hearing_unavailable'})
            item['status'] = 'conflict'
            item['profile_evidence_ids'] = list(dict.fromkeys(item['profile_evidence_ids'] + deaf_ids))
            item['reason'] = 'В профиле прямо указано отсутствие слуха. Слуховое восприятие недоступно независимо от языка.'
            if item['importance'] == 'mandatory':
                mandatory_hearing.append(f'requirements[{index}]')
        if item['importance'] == 'mandatory' and role == 'core' and item['status'] != 'confirmed':
            core_gaps.append(f'requirements[{index}]')
            if level == 'advanced':
                advanced_gaps.append(f'requirements[{index}]')
    different_work = work['fit'] == 'mismatch' and work['mismatch_basis'] == 'different_work'
    if readiness == 'not_ready' and not core_gaps and not different_work:
        raise AnalysisValidationError('not_ready не обосновано ключевым пробелом или несоответствием основной работы.')
    if readiness == 'ready' and (core_gaps or different_work):
        raise AnalysisValidationError('ready противоречит неподтверждённым ключевым требованиям.')
    assessment = validate_and_decide(resolved, payload)
    if advanced_gaps or readiness == 'not_ready':
        assessment['decision'] = 'unsuitable'
    if core_gaps and assessment['delivery']['action'] != 'exclude':
        assessment['delivery'] = {'action': 'review', 'reasons': ['core_qualification_gap']}
    if mandatory_hearing:
        assessment['delivery'] = {'action': 'exclude', 'reasons': ['mandatory_hearing_required']}
    if advanced_gaps:
        assessment['review_reasons'].append('advanced_core_qualification_gap')
    # Исходный JSON v4 хранится отдельно от совместимого представления с цитатами.
    assessment.update(source_contract_version=4, source_analysis=deepcopy(response),
                      source_fragments=fragments, entry_readiness=readiness,
                      readiness_reason=readiness_reason, semantic_corrections=corrections,
                      readiness_routing={'core_gaps': core_gaps, 'advanced_core_gaps': advanced_gaps},
                      assessment_policy_version=4)
    assessment['validation_revision'] = 5
    return assessment
