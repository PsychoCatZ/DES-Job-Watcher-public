"""Replace only the Watcher OpenAI key, supplied over SSH stdin."""

import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

import httpx

CONFIG = Path('/etc/des-job-watcher/credentials.json')
CONTROL = Path('/opt/des-job-watcher/data/telegram_control.sqlite3')
SERVICE = 'des-job-watcher.service'


def rotate(key, config=CONFIG, control=CONTROL):
    if not key or any(char.isspace() for char in key):
        raise ValueError('Key is empty or contains whitespace.')
    with closing(sqlite3.connect(control.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        if any(row[0] for row in db.execute('SELECT enabled FROM dig_control')):
            raise ValueError('Stop digging in Telegram first, then wait for the current pass to finish.')
    active = subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE]).returncode == 0
    # This endpoint does not run a model or send vacancy/profile content.
    with httpx.Client(timeout=25, follow_redirects=False) as client:
        response = client.get('https://api.openai.com/v1/models',
                              headers={'Authorization': 'Bearer ' + key})
    if response.status_code != 200:
        raise ValueError(f'OpenAI verification failed: HTTP {response.status_code}. Existing settings kept.')
    data = json.loads(config.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or 'OPENAI_API_KEY' not in data:
        raise ValueError('Unexpected credentials format. Existing settings kept.')
    data['OPENAI_API_KEY'] = key
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix='.openai-', dir=config.parent)
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(data, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, config)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    print('OpenAI key verified and replaced. Other credentials preserved.', flush=True)
    if active:
        subprocess.run(['systemctl', 'restart', SERVICE], check=True)
        subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE], check=True)
        print('Watcher restarted. Digging remains disabled.', flush=True)
    else:
        print('Watcher was inactive and has not been started.', flush=True)


def main():
    try:
        rotate(sys.stdin.read().strip())
        return 0
    except ValueError as error:
        # Only our fixed messages are printed; never dump provider bodies or keys.
        if isinstance(error, json.JSONDecodeError):
            print('Invalid credentials JSON. Rotation stopped.')
        else:
            print(str(error))
    except (OSError, sqlite3.Error, httpx.HTTPError, subprocess.CalledProcessError):
        print('Rotation or service verification failed. Secret values hidden; check service state.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
