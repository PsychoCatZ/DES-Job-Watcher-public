"""Посмотреть рабочий корпус или подготовить входы без вызова LLM."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from des_job_watcher.evaluation import load_cases, make_snapshot
from des_job_watcher.prompting import ROOT, build_request
from examples.prepare_analysis import build_input


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'data/evaluation/development/cases.json')
    parser.add_argument('--prepare', action='store_true', help='Сохранить готовые входы, без сети')
    args = parser.parse_args()
    try:
        dataset, loaded = load_cases(args.manifest)
        prepared = []
        for case, text in loaded:
            print(f"{case['id']} | {case['profile_id']} | {case['readiness']} | {case['label']}")
            if case['readiness'] == 'blocked':
                for reason in case['prerequisites']:
                    print('  Сначала:', reason)
                continue
            payload = build_input(case['profile_id'], make_snapshot(case, text))
            request = build_request(payload)
            prepared.append((case, payload, request['request_sha256']))
        print(f'Всего: {len(loaded)}; готово к сборке: {len(prepared)}; заблокировано: {len(loaded)-len(prepared)}')
        print('Это рабочий набор известных случаев, не независимая оценка качества.')
        if args.prepare:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
            directory = ROOT / 'data/evaluation/prepared' / stamp
            directory.mkdir(parents=True)
            index = []
            for case, payload, digest in prepared:
                output = directory / f"{case['id']}.json"
                output.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
                index.append({'case_id': case['id'], 'input_file': output.name,
                              'profile_version': payload['profile']['version'],
                              'contract_version': payload['response_contract']['properties']['contract_version']['const'],
                              'request_sha256': digest})
            (directory / 'preparation_index.json').write_text(json.dumps({
                'dataset_version': dataset['dataset_version'], 'split': dataset['split'],
                'inputs': index}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
            print('Подготовлено:', directory)
        print('HH и LLM не вызывались. Ожидаемые решения в запросы не включены.')
    except (OSError, ValueError) as error:
        print('Ошибка корпуса:', error)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
