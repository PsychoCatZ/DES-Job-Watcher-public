"""Создать локальные учебные профили. Существующие файлы никогда не заменяются."""

import json
from pathlib import Path

from des_job_watcher.profile_audit import verify_coverage
from des_job_watcher.prompting import ROOT


def setup_profiles(destination=None):
    directory = Path(destination) if destination is not None else ROOT / 'config/profiles'
    prepared = []
    for profile_id in ('support', 'developer', 'ai_data'):
        profile = json.loads((ROOT / 'config/profile_examples' / f'{profile_id}.json').read_text(encoding='utf-8'))
        verify_coverage(profile)
        prepared.append((directory / f'{profile_id}.json', profile))
    if any(path.exists() for path, _ in prepared):
        raise ValueError('В папке уже есть профили. Ничего не заменено; выберите другую папку или работайте с существующими данными.')
    directory.mkdir(parents=True, exist_ok=True)
    for path, profile in prepared:
        # Режим x защищает существующий файл даже при появлении между проверкой и записью.
        with path.open('x', encoding='utf-8') as stream:
            json.dump(profile, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    return directory


def main():
    try:
        directory = setup_profiles()
        print('Созданы ВЫМЫШЛЕННЫЕ учебные профили:', directory)
        print('Они не описывают реального кандидата и не предназначены для персональных рекомендаций.')
    except (OSError, ValueError) as error:
        print('Ошибка настройки:', error)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
