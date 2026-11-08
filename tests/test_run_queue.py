import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from des_job_watcher.history import History
from des_job_watcher.vacancy_queue import VacancyQueue
from examples import run_queue


class FakeHH:
    def __init__(self):
        self.searches = []
        self.details = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def search(self, query, *, page, per_page, order_by):
        self.searches.append((query, page, per_page, order_by))
        ids = range(1, 3) if page == 0 else range(3, 15)
        return {'pages': 2, 'items': [{'id': str(i), 'name': 'Асессор'} for i in ids]}

    def detail(self, vacancy_id):
        self.details.append(vacancy_id)
        return {'id': vacancy_id, 'name': 'Асессор', 'description': 'Разметка данных',
                'archived': False, 'work_format': [{'id': 'REMOTE'}]}


class QueueRunTests(unittest.TestCase):
    def test_pagination_budget_and_restart_continue_from_saved_queue(self):
        args = SimpleNamespace(analysis_limit=10, page_size=50, max_pages=3)
        plan = {'profiles': {'support': {'queries': []}, 'ai_data': {'queries': [{'text': 'разметка'}]}}}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            hh = FakeHH()
            with patch.multiple(run_queue, HHClient=lambda *_: hh, load_search_plan=lambda: plan,
                                add_workplace_evidence=lambda x: x, requests_allowed=lambda: True,
                                build_input=lambda profile, snap: {
                                    'profile': {'profile_id': profile},
                                    'vacancy': {'id': snap['detail']['id'], 'description': snap['detail']['description_text']},
                                }, prepare_body=lambda _: ({}, {'request_sha256': 'mock'}),
                                analyze_once=lambda *_: {'status': 'completed'}), \
                    patch('examples.run_queue.time.sleep'), patch.dict('os.environ', {
                        'HH_USER_AGENT': 'fake', 'HH_ACCESS_TOKEN': 'fake', 'OPENAI_API_KEY': 'fake'}):
                for turn, expected in ((1, 10), (2, 4)):
                    batch = root / str(turn)
                    batch.mkdir()
                    with History(root / 'watcher.sqlite3') as history:
                        queue = VacancyQueue(history.db)
                        counts = dict.fromkeys(run_queue.LABELS, 0)
                        run_queue.collect_and_analyze(args, history, queue, batch, counts, [])
                        self.assertEqual(counts['analyzed'], expected)
                        self.assertEqual(queue.remaining(), 4 if turn == 1 else 0)
                self.assertEqual(hh.details, [str(i) for i in range(1, 15)])
                self.assertIn(('разметка', 1, 50, 'relevance'), hh.searches)
