"""Проверка сохранённых разделов резюме, без PDF-зависимостей при запуске."""

import hashlib


REQUIRED_SECTIONS = {'target', 'experience', 'education', 'skills', 'about'}


def verify_coverage(profile):
    audit = profile.get('resume_audit')
    if not isinstance(audit, dict) or not isinstance(audit.get('sections'), list):
        raise ValueError('Профиль не прошёл сверку разделов резюме.')
    facts = {entry['id']: entry for entry in profile['evidence']}
    seen = set()
    for section in audit['sections']:
        name = section.get('section')
        if name not in REQUIRED_SECTIONS or name in seen:
            raise ValueError('Неверный или повторный раздел аудита.')
        seen.add(name)
        entry = facts.get(section.get('evidence_id'))
        if entry is None or entry.get('kind') != 'resume_section':
            raise ValueError(f'Потерян раздел резюме: {name}')
        digest = hashlib.sha256(entry['fact'].encode('utf-8')).hexdigest()
        if digest != section.get('text_sha256'):
            raise ValueError(f'Раздел {name} изменён: нужна повторная сверка источника.')
        if not section.get('pages') or entry.get('source_pages') != section['pages']:
            raise ValueError(f'Нет подтверждённых страниц раздела {name}.')
    if seen != REQUIRED_SECTIONS:
        raise ValueError('Не все содержательные разделы резюме сохранены.')
    education = profile.get('education')
    if not isinstance(education, dict) or education.get('evidence_id') not in facts:
        raise ValueError('Образование не связано с исходным разделом.')
    return True
