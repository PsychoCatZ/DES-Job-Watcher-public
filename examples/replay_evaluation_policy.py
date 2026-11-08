"""Пересчитать решения Python по сохранённым анализам, без нового анализа LLM."""

import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path

from des_job_watcher.assessment import validate_and_decide
from des_job_watcher.evaluation_run import save_json
from des_job_watcher.prompting import ROOT, fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-directory', type=Path, required=True)
    args = parser.parse_args()
    try:
        source = args.run_directory.resolve()
        summary = json.loads((source / 'summary.json').read_text(encoding='utf-8'))
        rules = json.loads((ROOT / 'config/matching_rules.json').read_text(encoding='utf-8'))
        rows = []
        for item in summary['results']:
            if item['status'] != 'completed':
                continue
            case_id = item['case_id']
            if not case_id or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_' for c in case_id):
                raise ValueError('Неверный ID в сводке.')
            result_text = (source / f'{case_id}.result.json').read_text(encoding='utf-8')
            record = json.loads(result_text)
            payload = json.loads((source / f'{case_id}.input.json').read_text(encoding='utf-8'))
            analysis = record['assessment']['analysis']
            old = validate_and_decide(analysis, payload)
            if old != record['assessment']:
                raise ValueError(f'{case_id}: историческое решение не воспроизвелось.')
            # Только копии для локального расчёта. Ответ модели и его версии не переписываются.
            target_payload = copy.deepcopy(payload)
            target_payload['rules'] = rules
            target_analysis = copy.deepcopy(analysis)
            target_analysis['rules_version'] = rules['version']
            new = validate_and_decide(target_analysis, target_payload)
            rows.append({'case_id': case_id, 'source_result_sha256': fingerprint(result_text),
                         'source_prompt_version': record['request']['prompt_version'],
                         'source_rules_version': analysis['rules_version'],
                         'before': {k: old[k] for k in ('decision', 'delivery', 'uncertainties')},
                         'after': {k: new[k] for k in ('decision', 'delivery', 'uncertainties')},
                         'removed_uncertainties': [v for v in old['uncertainties'] if v not in new['uncertainties']]})
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
        output = ROOT / 'data/evaluation/policy_replays' / stamp
        output.mkdir(parents=True)
        save_json(output / 'comparison.json', {
            'kind': 'local_policy_replay_not_new_model_analysis', 'source_run': source.name,
            'target_rules_version': rules['version'], 'rows': rows})
        lines = ['# Локальный пересчёт правил Python', '',
                 'Новых запросов к LLM нет. Смысловые выводы модели взяты из старых ответов.', '',
                 '| Случай | Было | Стало | Убрано из причин уточнения |',
                 '| --- | --- | --- | --- |']
        for row in rows:
            before, after = row['before'], row['after']
            removed = ', '.join(row['removed_uncertainties']) or '—'
            lines.append(f"| {row['case_id']} | {before['decision']}/{before['delivery']['action']} | "
                         f"{after['decision']}/{after['delivery']['action']} | {removed} |")
        (output / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        print('Пересчитано случаев:', len(rows))
        print('Снято неопределённостей:', sum(len(row['removed_uncertainties']) for row in rows))
        print('Отчёт:', output / 'report.md')
        print('Исторические ответы не изменены. Новая инструкция модели не проверялась.')
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('Ошибка пересчёта:', error)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
