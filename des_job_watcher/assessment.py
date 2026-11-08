"""Контракт v3: соответствие и маршрут показа — отдельные решения, без сети."""

import json


class AnalysisValidationError(ValueError):
    """Ответ нельзя использовать как оценку вакансии."""


def parse_response(text):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise AnalysisValidationError(f"Повтор ключа JSON: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise AnalysisValidationError(f"Недопустимая константа JSON: {value}")

    try:
        return json.loads(text, object_pairs_hook=unique_object, parse_constant=invalid_constant)
    except json.JSONDecodeError as error:
        raise AnalysisValidationError(f"Некорректный JSON: {error.msg}") from error


def check_object(value, keys, path):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise AnalysisValidationError(f"{path}: ожидаются только поля {', '.join(keys)}")


def check_text(value, path):
    if not isinstance(value, str) or not value.strip():
        raise AnalysisValidationError(f"{path}: нужна непустая строка")


def check_enum(value, allowed, path):
    if not isinstance(value, str) or value not in allowed:
        raise AnalysisValidationError(f"{path}: допустимы {', '.join(allowed)}")


def check_quotes(quotes, source_texts, path, required=True):
    if not isinstance(quotes, list) or (required and not quotes):
        raise AnalysisValidationError(f"{path}: нужен список цитат")
    for quote in quotes:
        check_text(quote, path)
        # Проверяем существование цитаты, а не правильность её интерпретации.
        if not any(quote in text for text in source_texts):
            raise AnalysisValidationError(f"{path}: цитата не найдена в названии или описании")


def check_evidence(ids, allowed_ids, path, required=False):
    if not isinstance(ids, list) or (required and not ids):
        raise AnalysisValidationError(f"{path}: нужен список ID опыта")
    if any(not isinstance(item, str) or item not in allowed_ids for item in ids):
        raise AnalysisValidationError(f"{path}: несуществующий или чужой ID опыта")
    if len(ids) != len(set(ids)):
        raise AnalysisValidationError(f"{path}: повтор ID опыта")


def validate_and_decide(response, payload):
    """Вернуть проверенный анализ с итогом; при ошибке поднять исключение."""
    if isinstance(response, dict) and response.get('contract_version') == 4:
        from des_job_watcher.assessment_v4 import validate_v4
        try:
            return validate_v4(response, payload)
        except (KeyError, TypeError, AttributeError) as error:
            raise AnalysisValidationError('Неполные или некорректные данные контракта 4.') from error
    if not isinstance(payload, dict):
        raise AnalysisValidationError("Вход анализа должен быть объектом")
    try:
        profile = payload['profile']
        vacancy = payload['vacancy']
        rules = payload['rules']
        if not all(isinstance(item, dict) for item in (profile, vacancy, rules)):
            raise AnalysisValidationError("Профиль, вакансия и правила должны быть объектами")
        if (type(payload['input_version']) is not int or payload['input_version'] != 1
                or type(rules['version']) is not int or rules['version'] not in (2, 3)):
            raise AnalysisValidationError("Неизвестная версия входа или правил")
        check_enum(profile['profile_id'], ('support', 'developer', 'ai_data'), 'input.profile_id')
        if type(profile['version']) is not int or profile['version'] < 1:
            raise AnalysisValidationError("Неверная версия профиля")
        description = vacancy['description']
        check_text(description, 'input.vacancy.description')
        check_text(vacancy['id'], 'input.vacancy.id')
        check_text(vacancy['name'], 'input.vacancy.name')
        if vacancy.get('employer') is not None and not isinstance(vacancy['employer'], dict):
            raise AnalysisValidationError("input.vacancy.employer должен быть объектом")
        if vacancy.get('archived') is not None and type(vacancy['archived']) is not bool:
            raise AnalysisValidationError("input.vacancy.archived должен быть boolean или null")
        evidence = profile['evidence']
        if not isinstance(evidence, list) or not evidence:
            raise AnalysisValidationError("В профиле нет оснований")
        evidence_ids = []
        for entry in evidence:
            if not isinstance(entry, dict):
                raise AnalysisValidationError("Неверная запись опыта")
            check_text(entry['id'], 'input.evidence.id')
            check_text(entry['fact'], 'input.evidence.fact')
            if not entry['id'].startswith(profile['profile_id'] + '_'):
                raise AnalysisValidationError("Чужое основание во входном профиле")
            evidence_ids.append(entry['id'])
        if len(evidence_ids) != len(set(evidence_ids)):
            raise AnalysisValidationError("Повтор основания во входном профиле")
        source_texts = (vacancy['name'], description)
        allowed_ids = set(evidence_ids)
    except (KeyError, TypeError) as error:
        raise AnalysisValidationError("Неполные входные данные анализа") from error

    check_object(response, ('contract_version', 'vacancy_id', 'profile_id',
                           'profile_version', 'rules_version', 'main_work',
                           'ai_role', 'requirements', 'conditions'), 'response')
    for key, expected in (
        ('contract_version', 3), ('vacancy_id', vacancy['id']),
        ('profile_id', profile['profile_id']), ('profile_version', profile['version']),
        ('rules_version', rules['version']),
    ):
        # bool в Python является подклассом int; сравнения True == 1 недостаточно.
        if type(response[key]) is not type(expected) or response[key] != expected:
            raise AnalysisValidationError(f"{key}: не совпадает с текущим входом")

    work = response['main_work']
    check_object(work, ('summary', 'fit', 'mismatch_basis', 'quotes', 'profile_evidence_ids', 'reason'), 'main_work')
    check_text(work['summary'], 'main_work.summary')
    check_text(work['reason'], 'main_work.reason')
    check_enum(work['fit'], ('match', 'partial', 'unknown', 'mismatch'), 'main_work.fit')
    check_enum(work['mismatch_basis'], ('not_applicable', 'different_work', 'insufficient_evidence'),
               'main_work.mismatch_basis')
    if work['fit'] == 'mismatch' and work['mismatch_basis'] == 'not_applicable':
        raise AnalysisValidationError('main_work: для mismatch нужна конкретная причина')
    if work['fit'] != 'mismatch' and work['mismatch_basis'] != 'not_applicable':
        raise AnalysisValidationError('main_work: причина mismatch не соответствует статусу')
    check_quotes(work['quotes'], source_texts, 'main_work.quotes')
    check_evidence(work['profile_evidence_ids'], allowed_ids, 'main_work.profile_evidence_ids',
                   required=work['fit'] in ('match', 'partial'))

    ai = response['ai_role']
    check_object(ai, ('kind', 'quotes'), 'ai_role')
    check_enum(ai['kind'], ('subject', 'development_method', 'auxiliary', 'absent', 'unknown'),
               'ai_role.kind')
    check_quotes(ai['quotes'], source_texts, 'ai_role.quotes',
                 required=ai['kind'] not in ('absent', 'unknown'))

    requirements = response['requirements']
    if not isinstance(requirements, list):
        raise AnalysisValidationError("requirements: нужен список")
    for number, requirement in enumerate(requirements):
        path = f'requirements[{number}]'
        check_object(requirement, ('text', 'importance', 'status', 'quote',
                                   'profile_evidence_ids', 'reason'), path)
        check_text(requirement['text'], path + '.text')
        check_text(requirement['reason'], path + '.reason')
        check_enum(requirement['importance'], ('mandatory', 'preferred'), path + '.importance')
        check_enum(requirement['status'], ('confirmed', 'unconfirmed', 'conflict'), path + '.status')
        check_quotes([requirement['quote']], source_texts, path + '.quote')
        check_evidence(requirement['profile_evidence_ids'], allowed_ids,
                       path + '.profile_evidence_ids',
                       required=requirement['status'] in ('confirmed', 'conflict'))

    conditions = response['conditions']
    check_object(conditions, ('remote', 'communication', 'work_from_russia', 'ai_policy'), 'conditions')
    for key, condition in conditions.items():
        path = 'conditions.' + key
        check_object(condition, ('status', 'quotes', 'field_refs', 'reason'), path)
        check_enum(condition['status'], ('confirmed', 'unknown', 'conflict'), path + '.status')
        check_text(condition['reason'], path + '.reason')
        refs = condition['field_refs']
        if (not isinstance(refs, list) or any(ref != 'vacancy.work_formats' for ref in refs)
                or len(refs) > 1):
            raise AnalysisValidationError(f'{path}.field_refs: неподдерживаемая ссылка')
        if refs:
            if key != 'remote':
                raise AnalysisValidationError(f'{path}: work_formats подтверждает только формат работы')
            formats = vacancy.get('work_formats')
            if not isinstance(formats, list) or not formats or any(
                not isinstance(value, str) for value in formats
            ):
                raise AnalysisValidationError(f'{path}: нет проверяемого work_formats')
            if condition['status'] == 'confirmed' and set(formats) != {'REMOTE'}:
                raise AnalysisValidationError(f'{path}: поле не подтверждает полную удалёнку')
            if condition['status'] == 'conflict' and 'REMOTE' in formats:
                raise AnalysisValidationError(f'{path}: поле не доказывает конфликт удалёнки')
        check_quotes(condition['quotes'], source_texts, path + '.quotes',
                     required=condition['status'] != 'unknown' and not refs)

    conflicts = []
    unknowns = []
    review_reasons = []
    if work['fit'] == 'mismatch' and work['mismatch_basis'] == 'different_work':
        conflicts.append('main_work')
        review_reasons.append('main_work')
    elif work['fit'] in ('partial', 'unknown', 'mismatch'):
        unknowns.append('main_work')
        if work['fit'] == 'mismatch':
            review_reasons.append('main_work.insufficient_evidence')
    for key in ('remote', 'communication', 'work_from_russia'):
        status = conditions[key]['status']
        if status == 'conflict':
            conflicts.append('conditions.' + key)
        elif status == 'unknown' and not (
                (key == 'communication' and rules['version'] >= 3)
                or (key == 'work_from_russia' and payload.get('analysis_contract_version') == 4)):
            unknowns.append('conditions.' + key)
    # Молчание об AI не является запретом. Явный запрет важен для developer.
    if profile['profile_id'] == 'developer' and conditions['ai_policy']['status'] == 'conflict':
        conflicts.append('conditions.ai_policy')
    for number, requirement in enumerate(requirements):
        if requirement['importance'] != 'mandatory':
            continue
        if requirement['status'] == 'conflict':
            conflicts.append(f'requirements[{number}]')
            review_reasons.append(f'requirements[{number}]')
        elif requirement['status'] == 'unconfirmed':
            unknowns.append(f'requirements[{number}]')

    # Точные известные варианты; связи компаний не угадываются.
    employer = vacancy.get('employer') or {}
    names = (employer.get('name', ''), employer.get('visibleName', ''))
    if any(isinstance(name, str) and ' '.join(name.casefold().split())
           in ('data light', 'data-light', 'дата лайт') for name in names):
        conflicts.append('excluded_employer')
    if vacancy.get('archived') is True:
        conflicts.append('archived')

    decision = 'unsuitable' if conflicts else 'clarify' if unknowns else 'suitable'
    # Профессиональные сомнения не дают права убрать вакансию из выбора пользователя.
    exclusions = [reason for reason in conflicts if reason in {
        'excluded_employer', 'archived', 'conditions.remote', 'conditions.communication',
        'conditions.work_from_russia', 'conditions.ai_policy',
    }]
    action = 'exclude' if exclusions else 'review' if review_reasons else 'show'
    return {'decision': decision, 'blocking_reasons': conflicts,
            'uncertainties': unknowns, 'review_reasons': review_reasons,
            'delivery': {'action': action, 'reasons': exclusions or review_reasons},
            'assessment_policy_version': 3 if rules['version'] >= 3 else 2, 'analysis': response}
