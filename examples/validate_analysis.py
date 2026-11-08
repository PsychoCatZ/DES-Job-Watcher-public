"""Проверить учебный или сохранённый ответ анализа без вызова LLM."""

import argparse
import json
from pathlib import Path

from des_job_watcher.assessment import AnalysisValidationError, parse_response, validate_and_decide


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true', help='Учебные вход и ответ')
    parser.add_argument('--input', type=Path, help='Подготовленный вход анализа')
    parser.add_argument('--response', type=Path, help='JSON ответа модели')
    args = parser.parse_args()
    if args.demo and (args.input or args.response):
        parser.error('--demo не смешивается с --input/--response')
    if not args.demo and not (args.input and args.response):
        parser.error('Нужны --demo или оба --input и --response')
    input_path = ROOT / 'examples' / 'fixtures' / 'analysis_input.json' if args.demo else args.input
    response_path = ROOT / 'examples' / 'fixtures' / 'analysis_response.json' if args.demo else args.response
    try:
        payload = parse_response(input_path.read_text(encoding='utf-8'))
        response = parse_response(response_path.read_text(encoding='utf-8'))
        result = validate_and_decide(response, payload)
    except (OSError, AnalysisValidationError) as error:
        print('analysis_failed:', error)
        return 1
    if args.demo:
        print('УЧЕБНЫЙ ПРИМЕР: вымышленные вакансия и ответ. LLM не вызывалась.')
    print('Контракт ответа: OK')
    print(json.dumps({key: value for key, value in result.items() if key != 'analysis'},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
