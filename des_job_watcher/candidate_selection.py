"""Объяснимый приоритет задач до LLM. Это отбор кандидатов, не оценка резюме."""

import html
import re


def clean(text):
    return ' '.join(html.unescape(re.sub(r'<[^>]*>', ' ', text or '')).casefold().split())


PATTERNS = {
    'support': [r'поддержк', r'tech(?:nical)? support|it support', r'помощь пользовател',
                r'обращени[яй].{0,35}(?:пользовател|клиент)', r'диагностик.{0,35}(?:ошиб|неисправност)',
                r'обработ\w* входящ\w* обращен|тикет[- ]систем|работ\w* с отзывами'],
    'ai_data': [r'размет[кч].{0,35}данных|аннотирован', r'ас[се]ессор|ассессор|асессор',
                r'ai[- ]?тренер|ии[- ]?тренер', r'обучени[яе] нейросет',
                r'(?:оценк|проверк).{0,30}(?:ответов|llm|модел)',
                r'промпт|prompt engineer', r'оператор.{0,20}(?:базы данных|пк)',
                r'качеств.{0,15}данных|контрол\w* качества',
                r'проверк\w* информации|проверк\w* объявлен|валидаци\w* данных|ввод\w* данных',
                r'модератор|модераци\w*'],
}


def rank_candidate(vacancy, profile):
    title = clean(vacancy.get('name'))
    snippet = vacancy.get('snippet') or {}
    tasks = clean(snippet.get('responsibility'))
    employer = clean((vacancy.get('employer') or {}).get('name'))
    if employer in ('data light', 'data-light', 'дата лайт'):
        return {'score': 0, 'action': 'exclude', 'reasons': ['Исключённый работодатель Data Light.']}
    title_hits = [p for p in PATTERNS[profile] if re.search(p, title)]
    task_hits = [p for p in PATTERNS[profile] if re.search(p, tasks)]
    # Только явно посторонние роли. Неизвестное название само по себе не отказ.
    unrelated = re.search(r'рекрутер|recruiter|seo|organic growth|директолог|таргетолог|'
                          r'менеджер по (?:активным )?продажам|агент по продажам|врач[- ]|'
                          r'телемаркетолог|fullstack|инженер-проектировщик|менеджер маркетплейса', title)
    if unrelated and not title_hits:
        return {'score': 0, 'action': 'exclude', 'reasons': ['Явно другая основная роль: ' + unrelated.group()]}
    score = 10 * len(title_hits) + 3 * len(task_hits)
    reasons = []
    if title_hits:
        reasons.append('Признаки задач профиля в названии: ' + ', '.join(title_hits))
    if task_hits:
        reasons.append('Признаки задач профиля в обязанностях: ' + ', '.join(task_hits))
    if re.search(r'руководител|head of|team lead|директор', title):
        score = 0
        reasons.append('Управленческая роль отложена относительно исполнительских задач профиля; не отказ по квалификации.')
    written = re.search(r'без звонков|только переписк|текстов\w* чат|чат[- ]поддержк|письменн\w* поддержк',
                        title + ' ' + tasks)
    if profile == 'support' and written and score:
        score += 12
        reasons.append('Прямой признак письменного канала в названии или обязанностях.')
    voice_title = re.sub(r'\bбез звонков\b', '', title)
    if profile == 'support' and re.search(r'звонк|колл[- ]центр|call.center', voice_title):
        score = max(0, score - 8)
        reasons.append('В названии есть голосовой канал: ниже приоритет, обязательность проверяется по полному тексту.')
    if not score:
        reasons.append('В названии и сниппете обязанностей нет прямых признаков задач профиля; отложено, не отказ.')
    return {'score': score, 'action': 'priority' if score else 'defer', 'reasons': reasons}


def select_candidates(records, profile, limit, *, skip_reason=None):
    ranked = []
    seen = set()
    for record in records:
        vacancy = record['vacancy']
        if vacancy['id'] in seen or not any(s['profile'] == profile for s in record['sources']):
            continue
        seen.add(vacancy['id'])
        rank = rank_candidate(vacancy, profile)
        ranked.append({'record': record, **rank})
    ranked.sort(key=lambda item: -item['score'])
    selected = []
    for item in ranked:
        if item['action'] != 'priority':
            continue
        reason = skip_reason(item['record']['vacancy']['id']) if skip_reason else None
        if reason:
            item['action'] = 'skip_cached'
            item['reasons'].append(reason)
        elif len(selected) < limit:
            selected.append(item['record'])
    selected_ids = {item['vacancy']['id'] for item in selected}
    audit = [{'id': item['record']['vacancy']['id'], 'name': item['record']['vacancy']['name'],
              'selected': item['record']['vacancy']['id'] in selected_ids,
              **{key: item[key] for key in ('score', 'action', 'reasons')}} for item in ranked]
    return selected, audit
