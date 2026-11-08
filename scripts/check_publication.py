"""Проверить файлы индекса Git, не печатая обнаруженные значения."""

import re
import subprocess


PATTERNS = {
    'API credential': re.compile(r'\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{25,})'),
    'private key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'Telegram credential': re.compile(r'\b\d{7,12}:[A-Za-z0-9_-]{30,}\b'),
    'local user path': re.compile(r'[A-Za-z]:[\\/]Users[\\/](?!Public(?:[\\/]|\b))[^\s"\']+'),
    'email': re.compile(r'[A-Za-z0-9._%+-]+@(?!(?:example\.(?:com|org)|users\.noreply\.github\.com)\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}'),
    'phone': re.compile(r'(?<!\w)\+7[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}\b'),
}


def main():
    output = subprocess.run(['git', 'ls-files', '--stage', '-z'], capture_output=True, check=True).stdout
    entries = [entry for entry in output.split(b'\0') if entry]
    findings = []
    for entry in entries:
        metadata, raw_path = entry.split(b'\t', 1)
        path = raw_path.decode('utf-8')
        mode, digest, stage = metadata.decode('ascii').split()
        if mode != '100644' or stage != '0':
            findings.append((path, 0, 'unexpected file mode or unmerged entry'))
            continue
        if (path.startswith(('data/', 'tmp/', 'logs/', '.venv/', 'config/profiles/'))
                or path.endswith(('.pdf', '.pem', '.key', '.pfx', '.sqlite', '.db'))
                or path.split('/')[-1].startswith('.env')):
            findings.append((path, 0, 'private path'))
            continue
        content = subprocess.run(['git', 'cat-file', 'blob', digest], capture_output=True, check=True).stdout
        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError:
            findings.append((path, 0, 'non-text file requires manual review'))
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for category, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append((path, number, category))
    for path, number, category in findings:
        print(f'{path}:{number}: {category}; value omitted')
    print(f'Indexed files: {len(entries)}; findings: {len(findings)}')
    return 1 if findings or not entries else 0


if __name__ == '__main__':
    raise SystemExit(main())
