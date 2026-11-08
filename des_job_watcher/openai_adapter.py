"""Один запрос Responses API через HTTPX; без повторов и журналирования ключа."""

import copy
import json
import time

import httpx

from des_job_watcher.assessment import AnalysisValidationError, parse_response, validate_and_decide
from des_job_watcher.prompting import ROOT, build_request, canonical_json, fingerprint
from des_job_watcher.quote_recovery import repair_terminal_punctuation
from des_job_watcher.source_fragments import response_schema


MODEL = 'gpt-6-luna'
EFFORT = 'medium'
MAX_OUTPUT_TOKENS = 8192
ENDPOINT = 'https://api.openai.com/v1/responses'


def api_schema(schema):
    """Упростить служебные элементы схемы; полную проверку сохраняет Python."""
    result = copy.deepcopy(schema)
    def convert(node):
        if isinstance(node, dict):
            node.pop('$schema', None)
            node.pop('uniqueItems', None)  # Уникальность ID проверяет наш валидатор.
            if 'const' in node:
                node['enum'] = [node.pop('const')]
            for value in node.values():
                convert(value)
        elif isinstance(node, list):
            for value in node:
                convert(value)
    convert(result)
    return result


def prepare_body(payload, *, mode='production', effort=EFFORT):
    if effort not in ('medium', 'high'):
        raise ValueError('Для этого адаптера допустимы medium и high.')
    request = build_request(payload, mode=mode)
    if sum(len(message['content']) for message in request['messages']) > 100_000:
        raise ValueError('Вход превышает лимит первого примера: 100 000 символов.')
    schema = response_schema(payload)
    body = {
        'model': MODEL, 'input': request['messages'],
        'reasoning': {'effort': effort}, 'max_output_tokens': MAX_OUTPUT_TOKENS,
        'store': False,
        'text': {'format': {'type': 'json_schema', 'name': 'vacancy_assessment',
                            'strict': True, 'schema': api_schema(schema)}},
    }
    metadata = {key: value for key, value in request.items() if key != 'messages'}
    metadata['api_body_sha256'] = fingerprint(canonical_json(body))
    metadata['reasoning_effort'] = effort
    return body, metadata


def extract_output(envelope):
    if not isinstance(envelope, dict) or envelope.get('status') != 'completed':
        raise AnalysisValidationError('Ответ API не завершён. Частичный анализ не используется.')
    output = envelope.get('output')
    if not isinstance(output, list):
        raise AnalysisValidationError('В ответе API отсутствует список output.')
    texts = []
    for item in output:
        if not isinstance(item, dict):
            raise AnalysisValidationError('Неверный элемент output.')
        if item.get('type') != 'message':
            continue
        if item.get('role') != 'assistant' or item.get('status') != 'completed':
            raise AnalysisValidationError('Сообщение модели не завершено.')
        content = item.get('content')
        if not isinstance(content, list):
            raise AnalysisValidationError('В сообщении отсутствует content.')
        for part in content:
            if not isinstance(part, dict):
                raise AnalysisValidationError('Неверная часть сообщения.')
            if part.get('type') == 'refusal':
                raise AnalysisValidationError('Модель отказалась от анализа.')
            if part.get('type') == 'output_text' and isinstance(part.get('text'), str):
                texts.append(part['text'])
    if len(texts) != 1 or not texts[0].strip():
        raise AnalysisValidationError('Ожидался один непустой JSON-ответ модели.')
    return texts[0]


def analyze_once(payload, api_key, client=None, *, mode='production', effort=EFFORT):
    """Вернуть запись запуска, включая неуспешный анализ. Ключ в запись не входит."""
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError('OPENAI_API_KEY не задан.')
    if any(char.isspace() for char in api_key):
        raise ValueError('Ключ содержит пробельные символы. Введите его заново.')
    body, metadata = prepare_body(payload, mode=mode, effort=effort)
    record = {'provider': 'openai', 'requested_model': MODEL,
              'reasoning_effort': effort, 'max_output_tokens': MAX_OUTPUT_TOKENS,
              'request': metadata, 'status': 'analysis_failed'}
    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=httpx.Timeout(120, connect=15), follow_redirects=False)
    started = time.monotonic()
    try:
        response = client.post(ENDPOINT, headers={'Authorization': f'Bearer {api_key}'}, json=body)
        record['http_status'] = response.status_code
        request_id = response.headers.get('x-request-id', '')
        if request_id and len(request_id) < 200 and all(c.isalnum() or c in '_-' for c in request_id):
            record['provider_request_id'] = request_id
        if response.status_code != 200:
            # Не сохраняем тело ошибки: оно может отражать пользовательские данные.
            record['error'] = f'HTTP {response.status_code}; автоматического повтора нет.'
            return record
        try:
            envelope = parse_response(response.text)
            if not isinstance(envelope, dict):
                raise AnalysisValidationError('Ответ API должен быть объектом.')
            record['response_id'] = envelope.get('id')
            record['actual_model'] = envelope.get('model')
            record['provider_status'] = envelope.get('status')
            record['usage'] = envelope.get('usage')
            record['incomplete_details'] = envelope.get('incomplete_details')
            output_text = extract_output(envelope)
            record['output_text'] = output_text
            analysis = parse_response(output_text)
            if not isinstance(analysis, dict):
                raise AnalysisValidationError('Ожидался объект анализа.')
            if payload.get('analysis_contract_version') == 4 and analysis.get('contract_version') != 4:
                raise AnalysisValidationError('Ожидался ответ по контракту 4.')
            try:
                record['assessment'] = validate_and_decide(analysis, payload)
            except AnalysisValidationError:
                if payload.get('analysis_contract_version') == 4:
                    raise
                corrected, changes = repair_terminal_punctuation(analysis, payload)
                if not changes:
                    raise
                # Пунктуационная правка не разрешает остальные ошибки ответа.
                record['assessment'] = validate_and_decide(corrected, payload)
                record['validation_recovery'] = {
                    'strategy': 'terminal_period_semicolon_v1', 'changes': changes,
                    'note': 'Исходный output_text сохранён; assessment содержит локально исправленные цитаты.'}
            record['status'] = 'completed'
        except AnalysisValidationError as error:
            record['error'] = str(error)
        return record
    except httpx.RequestError:
        record['error'] = ('Сетевая ошибка или таймаут. Неизвестно, обработан ли запрос сервером; '
                           'автоматического повтора нет.')
        return record
    finally:
        record['elapsed_seconds'] = round(time.monotonic() - started, 3)
        if own_client:
            client.close()
