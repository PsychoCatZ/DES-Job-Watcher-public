import copy
import json
import unittest
from unittest.mock import patch

from examples import prepare_analysis as example
from des_job_watcher.profile_audit import verify_coverage
from des_job_watcher.prompting import build_request


class PrepareAnalysisTests(unittest.TestCase):
    def setUp(self):
        # Публичные тесты не читают личные резюме владельца проекта.
        profile_patch = patch.object(example, 'PROFILE_DIR', example.ROOT / 'config/profile_examples')
        profile_patch.start()
        self.addCleanup(profile_patch.stop)
        self.snapshot = {
            'search': {'items': [{'id': '42', 'name': 'Технический ассистент',
                                 'url': 'https://hh.ru/vacancy/42',
                                 'employer': {'id': 1, 'name': 'Учебная компания'},
                                 'salary': None}]},
            'detail': {'id': '42', 'description_text': 'Поддержка, Linux и AI-скрипты.',
                       'work_formats': ['REMOTE'], 'archived': False},
        }

    def test_each_profile_has_its_own_evidence(self):
        all_ids = set()
        for profile_id in example.PROFILE_IDS:
            payload = example.build_input(profile_id, self.snapshot)
            profile = payload['profile']
            self.assertEqual(profile['profile_id'], profile_id)
            ids = {entry['id'] for entry in profile['evidence']}
            self.assertFalse(ids & all_ids)
            all_ids.update(ids)
            self.assertNotIn('source_resume', profile)

    def test_incomplete_or_unrelated_description_is_rejected(self):
        for detail in (None, {'id': '42', 'description_text': ''},
                       {'id': '43', 'description_text': 'Другая вакансия'}):
            snapshot = copy.deepcopy(self.snapshot)
            snapshot['detail'] = detail
            with self.subTest(detail=detail), self.assertRaises(ValueError):
                example.build_input('support', snapshot)

    def test_discovery_profile_does_not_override_selected_resume(self):
        self.snapshot['discovery'] = {'profile_id': 'developer'}
        payload = example.build_input('support', self.snapshot)
        self.assertEqual(payload['profile']['profile_id'], 'support')
        self.assertEqual(payload['vacancy']['description'],
                         self.snapshot['detail']['description_text'])

    def test_salary_is_information_and_no_evaluation_is_fabricated(self):
        self.snapshot['search']['items'][0]['salary'] = {'from': 100}
        payload = example.build_input('developer', self.snapshot)
        self.assertEqual(payload['vacancy']['salary_information_only'], {'from': 100})
        self.assertEqual(payload['rules']['information_only'],
                         ['salary', 'schedule', 'employment_type'])
        self.assertNotIn('decision', payload)
        self.assertNotIn('assessment', payload)

    def test_unknown_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            example.load_profile('../other')

    def test_profile_data_has_no_contacts_or_date_of_birth(self):
        for profile_id in example.PROFILE_IDS:
            text = json.dumps(example.load_profile(profile_id), ensure_ascii=False)
            for forbidden in ('mail@', '+7', '@private_handle'):
                self.assertNotIn(forbidden, text)

    def test_developer_keeps_resume_git_and_database_evidence(self):
        profile = example.load_profile('developer')
        self.assertEqual(profile['version'], 2)
        facts = {entry['id']: entry['fact'] for entry in profile['evidence']}
        self.assertIn('Git и GitHub', facts['developer_07'])
        self.assertIn('баз данных 1С', facts['developer_08'])
        self.assertIn('конкретные SQL/NoSQL', facts['developer_08'])

    def test_all_profiles_preserve_each_of_their_own_source_sections(self):
        for profile_id in example.PROFILE_IDS:
            profile = example.load_profile(profile_id)
            self.assertTrue(verify_coverage(profile))
            self.assertEqual({s['section'] for s in profile['resume_audit']['sections']},
                             {'target', 'experience', 'education', 'skills', 'about'})
            self.assertEqual(profile['education']['level'], 'secondary_vocational')
            self.assertIn('Среднее специальное', next(
                e['fact'] for e in profile['evidence'] if e['id'] == profile_id + '_source_education'))

    def test_annotation_profile_does_not_lose_technical_history(self):
        profile = example.load_profile('ai_data')
        fact = next(e['fact'] for e in profile['evidence'] if e['id'] == 'ai_data_source_experience')
        self.assertIn('Администрирование рабочих станций и серверов (Windows, Linux)', fact)
        self.assertIn('слияние и обслуживание баз 1С', fact)
        about = next(e['fact'] for e in profile['evidence'] if e['id'] == 'ai_data_source_about')
        self.assertIn('Python, JS/TS', about)

    def test_developer_does_not_lose_transcription_and_client_server_projects(self):
        profile = example.load_profile('developer')
        facts = '\n'.join(e['fact'] for e in profile['evidence'])
        self.assertIn('Speech-to-Text', facts)
        self.assertIn('клиент-серверные приложения', facts)

    def test_removing_or_rewriting_a_source_section_fails_audit(self):
        profile = example.load_profile('ai_data')
        broken = copy.deepcopy(profile)
        broken['evidence'] = [e for e in broken['evidence'] if e['id'] != 'ai_data_source_experience']
        with self.assertRaises(ValueError):
            verify_coverage(broken)
        broken = copy.deepcopy(profile)
        next(e for e in broken['evidence'] if e['id'] == 'ai_data_source_experience')['fact'] = 'Короткое резюме'
        with self.assertRaises(ValueError):
            verify_coverage(broken)

    def test_full_source_sections_and_education_reach_model_request(self):
        payload = example.build_input('ai_data', self.snapshot)
        data = json.loads(build_request(payload, mode='synthetic')['messages'][1]['content'])
        self.assertEqual(data['profile']['education']['level'], 'secondary_vocational')
        ids = {e['id'] for e in data['profile']['evidence']}
        self.assertIn('ai_data_source_experience', ids)
        self.assertIn('ai_data_source_education', ids)


if __name__ == '__main__':
    unittest.main()
