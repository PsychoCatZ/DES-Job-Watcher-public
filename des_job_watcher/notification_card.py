"""Текст уведомления из сохранённой оценки, без сети и вызовов модели."""

from des_job_watcher.requirement_rules import generic_autonomy

PROFILES = {'support': 'Поддержка', 'ai_data': 'AI / данные',
            'developer': 'Разработка / AI-интеграции'}


def compact(text, limit):
    """Ограничиваем длину поля; полный разбор остаётся в локальном отчёте."""
    text = ' '.join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def device_form_factor_only(item, fragments):
    quote = item.get('quote', '').casefold()
    if 'ноутбук' in quote and 'только на пк' in quote and any(
            'исключительно на ноутбуке' in fragment['text'].casefold()
            for fragment in fragments):
        return True
    return False


def render_notification(card, review, *, model_verdict=None, validation_error=False):
    """card — строка summary.json; review — её сохранённая оценка политики."""
    assessment = review['assessment']
    analysis = assessment['analysis']
    if (str(analysis['vacancy_id']), analysis['profile_id']) != (
            str(card['vacancy_id']), card['profile_id']):
        raise ValueError('Карточка и оценка относятся к разным вакансиям или профилям.')
    action = assessment['delivery']['action']
    if model_verdict:
        label = '🟢 Подходит' if model_verdict == 'suitable' else '🔎 Можно рассмотреть'
    elif action == 'exclude':
        label = '⛔ Исключена по условиям'
    elif action == 'review' or assessment['decision'] == 'unsuitable':
        label = '🟡 Профессиональный разбор'
    elif assessment['decision'] == 'suitable':
        label = '🟢 Предварительно подходит'
    else:
        label = '🔎 Можно рассмотреть — есть вопросы'
    work = analysis['main_work']
    lines = [label, compact(card['name'], 180),
             'Профиль: ' + PROFILES.get(card['profile_id'], card['profile_id']), '',
             'Задачи: ' + compact(work['summary'], 480), '',
             'Соответствие: ' + compact(work['reason'], 700)]
    if validation_error:
        lines += ['', 'Ответ Luna не прошёл автоматическую проверку.']
    if action == 'review' and assessment.get('readiness_reason'):
        lines += ['', 'Готовность: ' + compact(assessment['readiness_reason'], 400)]
    conditions = analysis['conditions']
    for key, title in [('remote', 'Удалёнка'), ('communication', 'Общение'),
                       ('work_from_russia', 'Работа из России')]:
        condition = conditions[key]
        if key == 'work_from_russia' and condition['status'] == 'unknown':
            continue
        status = {'confirmed': 'подтверждено', 'unknown': 'не уточнено',
                  'conflict': 'противоречие'}.get(condition['status'], condition['status'])
        lines += ['', f'{title}: {status}. ' + compact(condition['reason'], 200)]
    fragments = assessment.get('source_fragments', [])
    gaps = [item for item in analysis['requirements']
            if item['importance'] == 'mandatory' and item['status'] != 'confirmed'
            and not generic_autonomy(item['text'])
            and not device_form_factor_only(item, fragments)]
    if gaps:
        # Сначала показываем явные конфликты, затем неподтверждённые требования.
        gaps.sort(key=lambda item: item['status'] != 'conflict')
        lines += ['', 'Что уточнить:']
        lines += ['• ' + compact(item['text'], 160) for item in gaps[:3]]
        if len(gaps) > 3:
            lines += [f'Ещё требований в полном отчёте: {len(gaps) - 3}.']
    elif (action == 'show' and assessment['decision'] == 'clarify'
          and conditions['remote']['status'] == 'confirmed'
          and not set(assessment.get('uncertainties', [])) - {
              'conditions.communication', 'conditions.work_from_russia'}):
        lines[0] = '🔎 Можно рассмотреть'
    if review.get('overrides'):
        lines += ['', 'Ограничения: ' + compact(' '.join(
            item.get('reason', 'Обязательное оборудование для голосовой/видеосвязи.')
            for item in review['overrides']), 250)]
    lines += ['', 'Сохранённый анализ; актуальность вакансии сейчас не проверялась.',
              f"https://hh.ru/vacancy/{card['vacancy_id']}"]
    return '\n'.join(lines)
