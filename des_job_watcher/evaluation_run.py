"""Последовательный прогон известных случаев с сохранением каждого ответа."""

from datetime import datetime, timezone
import json
from pathlib import Path

from des_job_watcher.evaluation import check_expected_fields, load_cases, make_snapshot
from des_job_watcher.openai_adapter import prepare_body
from des_job_watcher.prompting import canonical_json, fingerprint
from examples.prepare_analysis import build_input


def prepare_cases(manifest, case_ids=None, profile_dir=None, *, mode='production'):
    """Проверить весь выбранный набор до первого сетевого запроса."""
    dataset, loaded = load_cases(manifest)
    if mode == 'synthetic' and (dataset.get('labels_status') != 'synthetic_examples' or profile_dir is None):
        raise ValueError('Синтетический прогон требует учебный корпус и явно выбранную папку учебных профилей.')
    selected = set(case_ids or [])
    unknown = selected - {case['id'] for case, _ in loaded}
    if unknown:
        raise ValueError('Неизвестные случаи: ' + ', '.join(sorted(unknown)))
    jobs = []
    for case, text in loaded:
        if selected and case['id'] not in selected:
            continue
        if case['readiness'] != 'ready':
            raise ValueError(f"{case['id']}: случай ещё не готов к анализу.")
        payload = build_input(case['profile_id'], make_snapshot(case, text), profile_dir=profile_dir)
        body, metadata = prepare_body(payload, mode=mode)
        jobs.append({'case': case, 'payload': payload, 'request': metadata,
                     'model': body['model'], 'reasoning': body['reasoning']['effort'],
                     'max_output_tokens': body['max_output_tokens'], 'analysis_mode': mode})
    return dataset, jobs


def save_json(path, value):
    """Замена через временный файл уменьшает риск частично записанного JSON."""
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def write_report(directory, summary):
    save_json(directory / 'summary.json', summary)
    lines = ['# Рабочий прогон вакансий', '',
             'Известный development-набор. Ожидания черновые; совпадение полей не доказывает качество объяснений.', '',
             f"Режим: {summary.get('analysis_mode', 'production')}. Синтетический результат не оценивает реального человека.", '',
             f"Состояние: {summary['status']}. Записей: {len(summary['results'])}/{summary['planned_calls']}.", '',
             '| Случай | Статус | Оценка | Показ | Проверки полей |',
             '| --- | --- | --- | --- | --- |']
    for result in summary['results']:
        checks = result.get('checks', [])
        count = f"{sum(check['passed'] for check in checks)}/{len(checks)}" if checks else '—'
        lines.append(f"| {result['case_id']} | {result['status']} | {result.get('decision', '—')} | "
                     f"{result.get('delivery', '—')} | {count} |")
    for result in summary['results']:
        if result['status'] != 'completed':
            continue
        lines.extend(['', f"## {result['case_id']}", ''])
        if result.get('validation_recovery'):
            count = len(result['validation_recovery']['changes'])
            lines.append(f'Локально восстановлено цитат: {count} (. ↔ ; в конце). '
                         'Исходный ответ и журнал правок сохранены в файле результата.')
        for check in result['checks']:
            if not check['passed']:
                lines.append(f"- Расхождение `{check['path']}`: получено `{check['actual']}`, "
                             f"ожидалось одно из `{check['expected']}`.")
        lines.extend(['', 'Ручная проверка:'])
        lines.extend('- ' + check for check in result['human_checks'])
    lines.extend(['', 'При ошибке запросы не повторяются. Уже выполненные случаи не запускайте заново автоматически.', ''])
    (directory / 'report.md').write_text('\n'.join(lines), encoding='utf-8')


def run_cases(dataset, jobs, directory, analyze, on_result=None):
    """analyze(payload) делает один запрос; в тестах подставляется вымышленный ответ."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    # Снимок ожиданий хранится для разбора, но analyze получает только payload.
    save_json(directory / 'plan.json', {
        'dataset_version': dataset['dataset_version'], 'dataset_revision': dataset.get('revision'),
        'split': dataset['split'],
        'labels_status': dataset.get('labels_status', 'draft_for_review'),
        'jobs': [{key: value for key, value in job.items() if key != 'payload'} for job in jobs]})
    for job in jobs:
        save_json(directory / (job['case']['id'] + '.input.json'), job['payload'])
    summary = {'status': 'running', 'planned_calls': len(jobs), 'results': [],
               'dataset_revision': dataset.get('revision'),
               'analysis_mode': jobs[0].get('analysis_mode', 'production') if jobs else 'production',
               'started_at': datetime.now(timezone.utc).isoformat(),
               'plan_sha256': fingerprint(canonical_json([
                   job['request']['api_body_sha256'] for job in jobs]))}
    write_report(directory, summary)
    try:
        for job in jobs:
            case = job['case']
            # Маркер остаётся при прерывании: сервер мог уже обработать запрос.
            summary['in_flight'] = case['id']
            write_report(directory, summary)
            record = analyze(job['payload'])
            save_json(directory / (case['id'] + '.result.json'), record)
            completed = record.get('status') == 'completed'
            if completed and record.get('request', {}).get('api_body_sha256') != job['request']['api_body_sha256']:
                completed = False
            result = {'case_id': case['id'], 'status': 'completed' if completed else 'failed',
                      'usage': record.get('usage'), 'elapsed_seconds': record.get('elapsed_seconds')}
            if record.get('validation_recovery'):
                result['validation_recovery'] = record['validation_recovery']
            if completed:
                assessment = record['assessment']
                result.update(decision=assessment['decision'], delivery=assessment['delivery']['action'],
                              checks=check_expected_fields(assessment, case['checks']),
                              human_checks=case.get('human_checks', []))
            summary['results'].append(result)
            summary.pop('in_flight')
            if not completed:
                summary['status'] = 'stopped_on_error'
            write_report(directory, summary)
            if on_result:
                on_result(result)
            if not completed:
                break
        else:
            summary['status'] = 'completed'
    except BaseException:
        # Сохраняем состояние и передаём исключение выше, в том числе Ctrl+C.
        summary['status'] = 'interrupted'
        write_report(directory, summary)
        raise
    summary['finished_at'] = datetime.now(timezone.utc).isoformat()
    write_report(directory, summary)
    return summary
