"""Собрать запрос LLM в файл, ничего не отправляя."""

import argparse
import json
from pathlib import Path

from des_job_watcher.assessment import parse_response
from des_job_watcher.prompting import ROOT, build_request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, help='Подготовленный вход анализа')
    parser.add_argument('--demo', action='store_true', help='Вымышленная учебная вакансия')
    args = parser.parse_args()
    if bool(args.input) == args.demo:
        parser.error('Выберите ровно один вариант: --demo или --input путь.json')
    try:
        if args.demo:
            source = ROOT / 'examples' / 'fixtures' / 'analysis_input.json'
            payload = parse_response(source.read_text(encoding='utf-8'))
            payload['rules'] = json.loads((ROOT / 'config' / 'matching_rules.json').read_text(encoding='utf-8'))
        else:
            source = args.input
            payload = parse_response(source.read_text(encoding='utf-8'))
        request = build_request(payload)
        directory = ROOT / 'data' / 'llm_requests'
        directory.mkdir(parents=True, exist_ok=True)
        output = directory / f"{source.stem}_{payload['profile']['profile_id']}_request.json"
        output.write_text(json.dumps(request, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('ЛОКАЛЬНЫЙ ПРОСМОТР: запрос не отправлялся, модель не вызывалась.')
        print(f"Версия промпта: {request['prompt_version']}; профиль: {payload['profile']['profile_id']}")
        print(f"Сообщений: {len(request['messages'])}; символов: {sum(len(m['content']) for m in request['messages'])}")
        print(f"Отпечаток: {request['request_sha256']}")
        print(f'Сохранено: {output}')
    except (OSError, ValueError) as error:
        print(f'Ошибка сборки запроса: {error}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
