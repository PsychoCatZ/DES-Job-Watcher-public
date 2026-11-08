"""Локально собрать вход для будущего анализа. Сетевых запросов и LLM нет."""

import argparse
import json
from pathlib import Path
import sys

# Сохраняем прежний прямой запуск примера по пути файла.
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from des_job_watcher.profile_audit import verify_coverage


ROOT = Path(__file__).resolve().parents[1]
PROFILE_IDS = ("support", "developer", "ai_data")
PROFILE_DIR = ROOT / 'config' / 'profiles'


def load_profile(profile_id, profile_dir=None):
    if profile_id not in PROFILE_IDS:
        raise ValueError("Неизвестный профиль.")
    directory = Path(profile_dir) if profile_dir is not None else PROFILE_DIR
    path = directory / f'{profile_id}.json'
    if not path.is_file():
        raise ValueError('Личный профиль отсутствует. Для учебного запуска выполните '
                         'python -m examples.setup_demo_profiles; это вымышленные данные.')
    profile = json.loads(path.read_text(encoding='utf-8'))
    if (profile.get('profile_id') != profile_id or type(profile.get('version')) is not int
            or profile['version'] < 1):
        raise ValueError("ID или версия профиля не соответствуют ожидаемым.")
    evidence = profile.get('evidence')
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("В профиле нет оснований.")
    ids = set()
    for entry in evidence:
        if not isinstance(entry, dict) or any(
            not isinstance(entry.get(key), str) or not entry[key].strip()
            for key in ('id', 'fact', 'period', 'context')
        ):
            raise ValueError("Неполная запись опыта.")
        if not entry['id'].startswith(profile_id + '_') or entry['id'] in ids:
            raise ValueError("ID оснований должны быть уникальны и принадлежать профилю.")
        ids.add(entry['id'])
    verify_coverage(profile)
    return profile


def build_input(profile_id, snapshot, profile_dir=None):
    profile = load_profile(profile_id, profile_dir)
    rules = json.loads((ROOT / 'config' / 'matching_rules.json').read_text(encoding='utf-8'))
    if rules.get('version') != 3:
        raise ValueError("Неизвестная версия правил.")
    try:
        detail = snapshot['detail']
        if not isinstance(detail, dict) or not isinstance(detail.get('description_text'), str) or not detail['description_text'].strip():
            raise ValueError("Нужно полное текстовое описание, а не только поисковая выдача.")
        item = next((item for item in snapshot['search']['items'] if item['id'] == detail['id']), None)
        if item is None:
            raise ValueError("Описание не связано с ID в поисковой выдаче.")
        vacancy = {'id': item['id'], 'name': item['name'], 'url': item['url'],
                   'employer': item['employer'], 'description': detail['description_text'],
                   'work_formats': detail.get('work_formats'), 'archived': detail.get('archived'),
                   'salary_information_only': item.get('salary')}
    except (KeyError, TypeError) as error:
        raise ValueError("Неожиданная структура снимка.") from error
    # Имя локального PDF не требуется модели; сохраняем лишь нужные сведения профиля.
    model_profile = {key: value for key, value in profile.items() if key != 'source_resume'}
    contract = json.loads((ROOT / 'config' / 'analysis_response.schema.json').read_text(encoding='utf-8'))
    return {'input_version': 1, 'rules': rules, 'profile': model_profile,
            'vacancy': vacancy, 'response_contract': contract}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=PROFILE_IDS, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    args = parser.parse_args()
    try:
        snapshot = json.loads(args.snapshot.read_text(encoding='utf-8'))
        payload = build_input(args.profile, snapshot)
        directory = ROOT / 'data' / 'analysis_inputs'
        directory.mkdir(parents=True, exist_ok=True)
        profile_version = payload['profile']['version']
        contract_version = payload['response_contract']['properties']['contract_version']['const']
        output = directory / f"{args.snapshot.stem}_{args.profile}_p{profile_version}_c{contract_version}_r{payload['rules']['version']}.json"
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f"Профиль: {args.profile}; оснований: {len(payload['profile']['evidence'])}")
        print(f"Вакансия: {payload['vacancy']['name']}")
        print(f"Сохранено: {output}")
        print('Это только входные данные. Модель не вызывалась, оценка не получена.')
    except (OSError, ValueError) as error:
        print(f'Ошибка подготовки: {error}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
