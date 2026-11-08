"""Сборка переносимого запроса анализа без вызова внешних сервисов."""

import hashlib
import json
from pathlib import Path
from des_job_watcher.operational_policy import load_policy
from des_job_watcher.source_fragments import response_schema, source_fragments


ROOT = Path(__file__).resolve().parents[1]
PROMPT_VERSION = 5

SYNTHETIC_CONTEXT = (
    'ДОВЕРЕННЫЙ РЕЖИМ: СИНТЕТИЧЕСКИЙ СЦЕНАРИЙ. '
    'Оцени соответствие условного кандидата условной вакансии. '
    'Сведения профиля являются заданными фактами только внутри этого сценария; '
    'пометки вымышленности сохраняются и не являются причиной снижать fit или статус навыка. '
    'Не требуй доказать существование реального человека или реальность его биографии. '
    'Это не подтверждение опыта какого-либо реального кандидата. '
    'Сопоставляй только заданные факты; отсутствующие компетенции не выдумывай. '
    'Тестовый режим не сообщает ожидаемое решение и не отменяет правила вакансий.'
)


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def build_request(payload, *, mode='production'):
    """Отделить доверенные инструкции от данных и сохранить их отпечатки."""
    if mode not in ('production', 'synthetic'):
        raise ValueError('Неизвестный режим анализа.')
    rules = json.loads((ROOT / 'config' / 'matching_rules.json').read_text(encoding='utf-8'))
    if not isinstance(payload, dict) or payload.get('input_version') != 1:
        raise ValueError('Неизвестный формат входа анализа.')
    contract_version = payload.get('analysis_contract_version', 3)
    if type(contract_version) is not int or contract_version not in (3, 4):
        raise ValueError('Неизвестная версия контракта.')
    prompt_version = 9 if contract_version == 4 else PROMPT_VERSION
    if contract_version == 4 and payload.get('include_model_verdict') is True:
        prompt_version = 10
    instruction = (ROOT / 'prompts' / f'assessment_v{prompt_version}.txt').read_text(encoding='utf-8').strip()
    if payload.get('rules') != rules:
        raise ValueError('Правила входа устарели или отличаются от текущих. Пересоберите вход.')
    try:
        profile = payload['profile']
        vacancy = payload['vacancy']
        if not isinstance(profile, dict) or profile['profile_id'] not in ('support', 'developer', 'ai_data'):
            raise ValueError('Неизвестный профиль.')
        if type(profile['version']) is not int or profile['version'] < 1:
            raise ValueError('Неверная версия профиля.')
        if not isinstance(profile['evidence'], list) or not profile['evidence']:
            raise ValueError('Профиль не содержит оснований.')
        synthetic_profile = profile.get('profile_kind') == 'synthetic'
        if mode == 'synthetic' and not synthetic_profile:
            raise ValueError('Синтетический режим требует явно помеченный учебный профиль.')
        if mode == 'production' and synthetic_profile:
            raise ValueError('Учебный профиль требует явный синтетический режим; личный анализ не выполняется.')
        if not isinstance(vacancy, dict) or any(
            not isinstance(vacancy.get(key), str) or not vacancy[key].strip()
            for key in ('id', 'name', 'description')
        ):
            raise ValueError('Нужны ID, название и полное описание вакансии.')
    except (KeyError, TypeError) as error:
        raise ValueError('Неполный вход анализа.') from error
    schema = response_schema(payload)

    # Явный список полей не пропускает локальные пути и служебные метаданные.
    profile_fields = ('profile_id', 'version', 'label', 'evidence_note', 'target_tasks',
                      'working_method', 'evidence', 'education', 'boundaries')
    vacancy_fields = ('id', 'name', 'employer', 'description', 'work_formats', 'archived')
    data = {
        'profile': {key: profile[key] for key in profile_fields if key in profile},
        'vacancy': {key: vacancy[key] for key in vacancy_fields if key in vacancy},
    }
    if contract_version == 4:
        data['vacancy'].pop('description')
        data['vacancy']['description_fragments'] = source_fragments(vacancy)
    user_content = canonical_json(data)
    system_content = (instruction + '\n\nДОВЕРЕННЫЕ ПРАВИЛА:\n' + canonical_json(rules)
                      + '\n\nКОНТРАКТ ОТВЕТА:\n' + canonical_json(schema))
    policy = load_policy()
    system_content += '\n\nДОПОЛНИТЕЛЬНАЯ ПОЛИТИКА ОТБОРА:\n' + canonical_json(policy)
    if mode == 'synthetic':
        system_content += '\n\n' + SYNTHETIC_CONTEXT
    messages = [{'role': 'system', 'content': system_content},
                {'role': 'user', 'content': user_content}]
    return {
        'request_version': 1, 'prompt_version': prompt_version,
        **({'contract_version': 4} if contract_version == 4 else {}),
        'rules_version': rules['version'], 'analysis_mode': mode,
        'operational_policy_version': policy['version'],
        'input_sha256': fingerprint(user_content),
        'instructions_sha256': fingerprint(system_content),
        'request_sha256': fingerprint(canonical_json(messages)),
        'messages': messages,
    }
