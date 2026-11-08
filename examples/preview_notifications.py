"""Локальный предпросмотр будущих сообщений Telegram из готового отчёта."""

import argparse
import json
from pathlib import Path
import sys

from des_job_watcher.notification_card import render_notification


def main():
    # Windows pipes can use cp1251, which cannot represent Telegram emoji.
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True,
                        help='Папка с summary.json и отдельными оценками')
    parser.add_argument('--include-review', action='store_true')
    args = parser.parse_args()
    directory = args.report.resolve()
    summary = json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
    if summary.get('kind') != 'combined_saved_analysis_report':
        raise ValueError('Нужен единый отчёт сохранённых анализов.')
    print('ПРЕДПРОСМОТР: без сети, ключей, записи в базу и отправки сообщений.\n')
    count = 0
    for card in summary['cards']:
        if card['group'] != 'consider' and not (
                args.include_review and card['group'] == 'professional_review'):
            continue
        path = (directory / card['review_file']).resolve()
        if path.parent != directory:
            raise ValueError('Файл оценки должен находиться в папке отчёта.')
        review = json.loads(path.read_text(encoding='utf-8'))
        print(render_notification(card, review))
        print('\n' + '─' * 40 + '\n')
        count += 1
    print(f'Карточек: {count}. Незавершённых входов: {len(summary.get("unfinished", []))}.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
