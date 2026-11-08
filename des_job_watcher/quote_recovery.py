"""Узкое восстановление . ↔ ; в конце цитаты с явным журналом изменений."""

import copy


def repair_terminal_punctuation(response, payload):
    """Вернуть копию и правки. Строгую валидацию всего ответа выполняет вызывающий код."""
    corrected = copy.deepcopy(response)
    changes = []
    if not isinstance(corrected, dict) or not isinstance(payload, dict):
        return corrected, changes
    vacancy = payload.get('vacancy')
    if not isinstance(vacancy, dict):
        return corrected, changes
    sources = [vacancy[key] for key in ('name', 'description')
               if isinstance(vacancy.get(key), str)]

    def repair(quote, path):
        if (not isinstance(quote, str) or len(quote) < 2 or quote[-1] not in '.;'
                or not quote[:-1].strip() or quote[-2] in '.;'
                or any(quote in source for source in sources)):
            return quote
        # Единственный кандидат: тот же текст с другим завершающим знаком.
        candidate = quote[:-1] + (';' if quote[-1] == '.' else '.')
        if any(candidate in source for source in sources):
            changes.append({'path': path, 'before': quote, 'after': candidate})
            return candidate
        return quote

    def repair_quotes(node, path):
        if isinstance(node, dict) and isinstance(node.get('quotes'), list):
            node['quotes'] = [repair(quote, f'{path}.quotes[{index}]')
                              for index, quote in enumerate(node['quotes'])]

    for key in ('main_work', 'ai_role'):
        repair_quotes(corrected.get(key), key)
    requirements = corrected.get('requirements')
    if isinstance(requirements, list):
        for index, requirement in enumerate(requirements):
            if isinstance(requirement, dict) and 'quote' in requirement:
                requirement['quote'] = repair(requirement['quote'], f'requirements[{index}].quote')
    conditions = corrected.get('conditions')
    if isinstance(conditions, dict):
        for key in ('remote', 'communication', 'work_from_russia', 'ai_policy'):
            repair_quotes(conditions.get(key), 'conditions.' + key)
    return corrected, changes
