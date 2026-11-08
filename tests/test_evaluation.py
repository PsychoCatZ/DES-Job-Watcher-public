import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from des_job_watcher.evaluation import check_expected_fields, load_cases, make_snapshot
from des_job_watcher.prompting import ROOT


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.case = {'id': 'support_demo', 'profile_id': 'support', 'label': 'Не передавать',
                     'readiness': 'ready', 'prerequisites': [], 'text_file': 'job.txt',
                     'checks': [{'path': 'decision', 'allowed': ['clarify']}],
                     'human_checks': ['НЕ ПЕРЕДАВАТЬ ЭТО МОДЕЛИ']}

    def dataset(self, directory, text='Текст вакансии'):
        root = Path(directory)
        (root / 'job.txt').write_text(text, encoding='utf-8')
        self.case['text_sha256'] = hashlib.sha256(text.encode('utf-8')).hexdigest()
        path = root / 'cases.json'
        path.write_text(json.dumps({'dataset_version': 1, 'split': 'development',
                                   'cases': [self.case]}, ensure_ascii=False), encoding='utf-8')
        return path

    def test_expectations_and_editorial_labels_never_enter_snapshot(self):
        snapshot = make_snapshot(self.case, 'Исходный текст')
        serialized = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn('НЕ ПЕРЕДАВАТЬ', serialized)
        self.assertNotIn('clarify', serialized)
        self.assertNotIn('Не передавать', serialized)
        self.assertEqual(snapshot['detail']['description_text'], 'Исходный текст')

    def test_blocked_case_cannot_be_prepared(self):
        self.case['readiness'] = 'blocked'
        with self.assertRaises(ValueError):
            make_snapshot(self.case, 'Текст')

    def test_missing_result_field_cannot_pass(self):
        checked = check_expected_fields({}, self.case['checks'])
        self.assertFalse(checked[0]['passed'])
        self.assertTrue(check_expected_fields({'decision': 'clarify'}, self.case['checks'])[0]['passed'])

    def test_changed_source_invalidates_expectations(self):
        temp_root = ROOT / 'tmp'
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as directory:
            path = self.dataset(directory)
            self.assertEqual(len(load_cases(path)[1]), 1)
            (path.parent / 'job.txt').write_text('Изменено', encoding='utf-8')
            with self.assertRaises(ValueError):
                load_cases(path)

    def test_duplicate_case_and_outside_path_rejected(self):
        temp_root = ROOT / 'tmp'
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as directory:
            path = self.dataset(directory)
            data = json.loads(path.read_text(encoding='utf-8'))
            data['cases'].append(self.case)
            path.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_cases(path)
            data['cases'] = [dict(self.case, text_file='../outside.txt')]
            path.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_cases(path)


if __name__ == '__main__':
    unittest.main()
