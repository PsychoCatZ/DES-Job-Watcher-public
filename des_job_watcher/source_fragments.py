"""Стабильные ID исходных строк; опечатки и символы сохраняются."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source_fragments(vacancy):
    fragments = [{'id': 'title', 'field': 'name', 'start': 0,
                  'end': len(vacancy['name']), 'text': vacancy['name']}]
    offset = 0
    for number, line in enumerate(vacancy['description'].splitlines(keepends=True), 1):
        text = line.strip()
        if text:
            start = offset + len(line) - len(line.lstrip())
            fragments.append({'id': f'd{number:04}', 'field': 'description',
                              'start': start, 'end': start + len(text), 'text': text})
        offset += len(line)
    return fragments


def response_schema(payload):
    version = payload.get('analysis_contract_version', 3)
    if type(version) is not int or version not in (3, 4):
        raise ValueError('Неизвестная версия контракта.')
    path = ROOT / ('config/contracts/analysis_response_v4.schema.json' if version == 4
                   else 'config/analysis_response.schema.json')
    schema = json.loads(path.read_text(encoding='utf-8'))
    if version == 4:
        if payload.get('include_model_verdict') is True:
            schema['properties']['model_verdict'] = {
                'type': 'string', 'enum': ['suitable', 'clarify', 'unsuitable']}
            schema['required'].append('model_verdict')
        ids = [item['id'] for item in source_fragments(payload['vacancy'])]
        def bind(node):
            if isinstance(node, dict):
                for key, value in node.get('properties', {}).items():
                    if key == 'quote_id':
                        value['enum'] = ids
                    elif key == 'quote_ids':
                        value['items']['enum'] = ids
                for value in node.values():
                    bind(value)
            elif isinstance(node, list):
                for value in node:
                    bind(value)
        bind(schema)
    return schema
