"""Показываем близкие вакансии по исходным выводам Luna."""

import json
from pathlib import Path

from des_job_watcher.notification_card import render_notification


def model_allows_review(analysis):
    if 'model_verdict' in analysis:
        return analysis['model_verdict'] in ('suitable', 'clarify')
    work = analysis['main_work']
    return (work['fit'] in ('match', 'partial') and work.get('entry_readiness') != 'not_ready'
            and not any(analysis['conditions'][key]['status'] == 'conflict'
                        for key in ('remote', 'communication', 'work_from_russia'))
            and not any(item['importance'] == 'mandatory' and item['status'] == 'conflict'
                        for item in analysis['requirements']))


def recommended_cards(report, summary):
    entries = []
    for card in summary['cards']:
        review = json.loads((report / card['review_file']).read_text(encoding='utf-8'))
        assessment = review['assessment']
        analysis = assessment['analysis']
        source = assessment.get('source_analysis', analysis)
        if not model_allows_review(source) or review.get('overrides'):
            continue
        if set(assessment.get('blocking_reasons', [])) & {'archived', 'excluded_employer'}:
            continue
        verdict = 'suitable' if source.get('model_verdict', card['decision']) == 'suitable' else 'clarify'
        entries.append((verdict, render_notification(card, review, model_verdict=verdict)))
    for item in summary['unfinished']:
        if item['status'] != 'analysis_failed' or not item.get('source_result'):
            continue
        try:
            record = json.loads(Path(item['source_result']).read_text(encoding='utf-8'))
            source = json.loads(record['output_text'])
            if (source['vacancy_id'] != item['vacancy_id'] or source['profile_id'] != item['profile_id']
                    or not model_allows_review(source)):
                continue
            verdict = source.get('model_verdict', 'clarify')
            review = {'assessment': {'analysis': source, 'decision': verdict, 'delivery': {'action': 'show'}}}
            message = render_notification(item, review, model_verdict=verdict, validation_error=True)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
        entries.append((verdict, message))
    entries.sort(key=lambda entry: entry[0] != 'suitable')
    return entries
