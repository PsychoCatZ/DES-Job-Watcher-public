"""Изолированное сравнение effort на замороженных личных входах."""

from copy import deepcopy
import json
from pathlib import Path

from des_job_watcher.assessment import validate_and_decide, parse_response
from des_job_watcher.openai_adapter import prepare_body
from des_job_watcher.prompting import canonical_json, fingerprint
from des_job_watcher.evaluation_run import save_json


def prepare_comparison(cases, directory):
    directory = Path(directory)
    jobs = []
    for index, case in enumerate(cases, 1):
        payload = deepcopy(case['payload'])
        bodies = {}
        for effort in ('medium', 'high'):
            body, metadata = prepare_body(payload, effort=effort)
            bodies[effort] = body
            jobs.append({'id': f'{index:02}_{effort}', 'case_id': case['id'],
                         'effort': effort, 'payload': payload, 'request': metadata,
                         'checks_for_human': case['checks_for_human']})
        medium = deepcopy(bodies['medium'])
        medium['reasoning']['effort'] = 'high'
        if medium != bodies['high']:
            raise ValueError('В сравниваемых запросах различается не только effort.')
    if not jobs:
        raise ValueError('Пустой набор сравнения.')
    directory.mkdir(parents=True, exist_ok=False)
    for job in jobs:
        save_json(directory / f"{job['id']}.input.json", job['payload'])
        del job['payload']
    plan = {'kind': 'effort_comparison_development_not_market_accuracy', 'version': 1,
            'jobs': jobs, 'planned_calls': len(jobs)}
    save_json(directory / 'plan.json', plan)
    return plan


def load_jobs(directory):
    directory = Path(directory)
    plan = json.loads((directory / 'plan.json').read_text(encoding='utf-8'))
    jobs = []
    for job in plan['jobs']:
        # План создаётся нашим кодом: разрешаем только фиксированные имена файлов.
        if job['id'] not in [f'{i:02}_{e}' for i in range(1, 101) for e in ('medium', 'high')]:
            raise ValueError('Некорректный ID сравнения.')
        payload = json.loads((directory / f"{job['id']}.input.json").read_text(encoding='utf-8'))
        _, metadata = prepare_body(payload, effort=job['effort'])
        if metadata != job['request']:
            raise ValueError('Пакет устарел или изменился. Не запускайте его автоматически после изменения правил.')
        jobs.append({**job, 'payload': payload})
    return jobs


def reuse_completed(job, source, directory):
    """Только тот же API-body; копия и provenance, без изменения исходника."""
    source = Path(source)
    record = json.loads(source.read_text(encoding='utf-8'))
    if record.get('status') != 'completed' or record.get('request', {}).get('api_body_sha256') != job['request']['api_body_sha256']:
        return False
    validate_and_decide(record['assessment']['analysis'], job['payload'])
    save_json(Path(directory) / f"{job['id']}.result.json", {
        **record, 'comparison_reuse': {'source_path': str(source.resolve()),
                                     'source_sha256': fingerprint(source.read_text(encoding='utf-8'))}})
    return True


def write_comparison_report(directory, jobs):
    directory = Path(directory)
    lines = ['# Luna: medium и high', '',
             'Известные диагностические случаи. Один ответ на режим не доказывает статистическое превосходство.', '',
             '| Случай | Effort | Статус | Итог / маршрут | Основные задачи | Токены вывода | Reasoning | Время, с |',
             '|---|---|---|---|---|---:|---:|---:|']
    for job in jobs:
        path = directory / f"{job['id']}.result.json"
        if not path.exists():
            lines.append(f"| {job['case_id']} | {job['effort']} | не выполнен | — | — | — | — | — |")
            continue
        record = json.loads(path.read_text(encoding='utf-8'))
        assessment = record.get('assessment', {})
        usage = record.get('usage') or {}
        tasks = assessment.get('analysis', {}).get('main_work', {}).get('fit', '—')
        decision = assessment.get('decision', '—') + ' / ' + assessment.get('delivery', {}).get('action', '—')
        status = record['status'] + (' (прежний ответ)' if record.get('comparison_reuse') else '')
        lines.append(f"| {job['case_id']} | {job['effort']} | {status} | {decision} | {tasks} | {usage.get('output_tokens', '—')} | {(usage.get('output_tokens_details') or {}).get('reasoning_tokens', '—')} | {record.get('elapsed_seconds', '—')} |")
    for job in jobs[::2]:
        lines += ['', f"## {job['case_id']}", '', *['- ' + check for check in job['checks_for_human']]]
    lines += ['', 'Общий вердикт вычисляется прежним Python-кодом. Новая маршрутизация не вводится в это сравнение.',
              'Лимит 8192 включает reasoning. Незавершённый ответ — отдельный результат; лимит не меняется после ошибки.',
              'Исходные требования, цитаты и объяснения находятся в *.result.json. Денежная стоимость здесь не рассчитана.', '']
    (directory / 'report.md').write_text('\n'.join(lines), encoding='utf-8')


def run_comparison(directory, jobs, history, analyze, *, skip_saved_failures=False):
    directory = Path(directory)
    for job in jobs:
        output = directory / f"{job['id']}.result.json"
        if output.exists():
            record = json.loads(output.read_text(encoding='utf-8'))
            if record['status'] != 'completed':
                if not skip_saved_failures:
                    raise ValueError('Есть неуспешный результат: автоматического повтора нет.')
                print(f"{job['id']}: сохранённая ошибка остаётся в сравнении, без повтора.", flush=True)
            continue
        scope = 'effort_comparison:' + job['request']['api_body_sha256']
        if not history.reserve_attempt(scope, job['request']['api_body_sha256'], output):
            raise ValueError('Этот экспериментальный запрос уже зарегистрирован. Нужен разбор сохранённой попытки.')
        print(f"API: {job['case_id']} / {job['effort']}", flush=True)
        record = analyze(job['payload'], job['effort'])
        save_json(output, record)
        history.finish_attempt(scope, record['status'])
        write_comparison_report(directory, jobs)
        if record['status'] != 'completed':
            print(f"Остановлено: {record['status']}. {record.get('error', '')}", flush=True)
            return False
        if record['request']['api_body_sha256'] != job['request']['api_body_sha256']:
            raise ValueError('Отпечаток фактического запроса отличается от плана.')
    return True
