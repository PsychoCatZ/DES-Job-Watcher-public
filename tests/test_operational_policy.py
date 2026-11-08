from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import hashlib

from des_job_watcher.operational_policy import equipment_barriers, apply_policy, add_workplace_evidence
from des_job_watcher.history import History


class OperationalPolicyTests(unittest.TestCase):
    def test_required_equipment_and_negative_cases(self):
        for text in ('Гарнитура (наушники и микрофон) и камера;',
                     'Для обучения понадобится микрофон.', 'Необходима веб-камера'):
            self.assertTrue(equipment_barriers(text), text)
        for text in ('Гарнитура не нужна', 'Камера не требуется',
                     'Разметка изображений с камер наблюдения',
                     'Настройка систем видеонаблюдения', 'Работа без микрофона',
                     'Знакомство с устройством микрофонов'):
            self.assertFalse(equipment_barriers(text), text)

    def test_policy_preserves_original_and_exact_quote(self):
        original = {'decision': 'suitable', 'delivery': {'action': 'show', 'reasons': []}}
        before = deepcopy(original)
        review = apply_policy(original, {'description': 'Гарнитура и камера;'})
        self.assertEqual(original, before)
        self.assertEqual(review['assessment']['delivery']['action'], 'exclude')
        self.assertEqual(review['overrides'][0]['quotes'], ['Гарнитура и камера'])

    def test_context_does_not_change_resume_and_never_enriches_synthetic(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'workplace.json'
            path.write_text(json.dumps({'version': 1, 'facts': [{'id': 'ram', 'fact': '32 ГБ RAM'}]}), encoding='utf-8')
            payload = {'profile': {'profile_id': 'support', 'evidence': []}}
            result = add_workplace_evidence(payload, path)
            self.assertEqual(payload['profile']['evidence'], [])
            self.assertEqual(result['profile']['evidence'][0]['id'], 'support_workplace_ram')
            payload['profile']['profile_kind'] = 'synthetic'
            self.assertEqual(add_workplace_evidence(payload, path), payload)

    def test_review_persistence_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            with History(Path(directory) / 'test.sqlite3') as history:
                review = {'vacancy_id': '123', 'profile_id': 'support', 'source_sha256': 'test'}
                self.assertEqual(history.save_review(review), history.save_review(review))
                self.assertEqual(history.db.execute('SELECT count(*) FROM assessment_reviews').fetchone()[0], 1)

    def test_candidate_decline_is_scoped_to_profile_and_exact_description(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'feedback.json'
            vacancy = {'id': '123', 'description': 'Отлично владеет SQL;'}
            decision = {'id': 'test', 'vacancy_id': '123', 'profile_id': 'support',
                        'description_sha256': hashlib.sha256(vacancy['description'].encode()).hexdigest(),
                        'quote': 'Отлично владеет SQL', 'reason': 'Кандидат не готов к требуемому уровню.'}
            path.write_text(json.dumps({'decisions': [decision]}), encoding='utf-8')
            original = {'decision': 'clarify', 'delivery': {'action': 'show', 'reasons': []}}
            review = apply_policy(original, vacancy, profile_id='support', feedback_path=path)
            self.assertEqual(review['assessment']['decision'], 'unsuitable')
            self.assertEqual(review['assessment']['delivery']['action'], 'review')
            for changed, profile in (({**vacancy, 'id': '456'}, 'support'),
                                     (vacancy, 'ai_data'),
                                     ({**vacancy, 'description': 'SQL будет плюсом'}, 'support')):
                self.assertEqual(apply_policy(original, changed, profile_id=profile, feedback_path=path)['assessment'], original)
            self.assertEqual(original['decision'], 'clarify')

    def test_no_sql_keyword_rejection_without_candidate_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / 'absent.json'
            original = {'decision': 'clarify', 'delivery': {'action': 'show', 'reasons': []}}
            for description in ('SQL будет плюсом', 'Основы SQL, обучим', 'Отлично владеет SQL'):
                review = apply_policy(original, {'id': 'test', 'description': description},
                                      profile_id='support', feedback_path=missing)
                self.assertEqual(review['assessment'], original)
