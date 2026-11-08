import unittest

from des_job_watcher.candidate_selection import rank_candidate, select_candidates


def vacancy(name, tasks=''):
    return {'id': '1', 'name': name, 'snippet': {'responsibility': tasks}}


class SelectionTests(unittest.TestCase):
    def test_unrelated_roles_do_not_consume_budget(self):
        for name, profile in [('Рекрутер', 'support'), ('Head of Organic Growth', 'ai_data')]:
            self.assertEqual(rank_candidate(vacancy(name, 'Поддержка, разметка данных'), profile)['action'], 'exclude')

    def test_unusual_title_with_relevant_tasks_is_retained(self):
        self.assertGreater(rank_candidate(vacancy('Технический помощник',
                           'Разметка данных и проверка ответов LLM'), 'ai_data')['score'], 0)

    def test_no_signals_is_deferred_not_rejected(self):
        self.assertEqual(rank_candidate(vacancy('Начинающий специалист'), 'support')['action'], 'defer')

    def test_domain_and_tool_names_do_not_prove_fit(self):
        self.assertEqual(rank_candidate(vacancy('Финансовый аналитик', 'Работа с Claude и AI'), 'ai_data')['score'], 0)

    def test_manager_is_deferred_and_calls_are_not_automatic_rejection(self):
        self.assertEqual(rank_candidate(vacancy('Head of IT Support'), 'support')['action'], 'defer')
        self.assertNotEqual(rank_candidate(vacancy('Поддержка: чаты и звонки'), 'support')['action'], 'exclude')

    def test_salary_schedule_and_requirements_do_not_affect_priority(self):
        original = vacancy('Асессор в VK')
        changed = {**original, 'salary': {'from': 1}, 'schedule': 'night',
                   'snippet': {'requirement': 'Необходимо знать Python'}}
        self.assertEqual(rank_candidate(original, 'ai_data'), rank_candidate(changed, 'ai_data'))

    def test_stable_order_deduplication_and_profile_scope(self):
        records = [{'vacancy': {**vacancy(name), 'id': str(i)}, 'sources': [{'profile': p}]}
                   for i, name, p in [(1, 'Рекрутер', 'support'), (2, 'IT support specialist', 'support'),
                                      (3, 'Асессор в VK', 'ai_data')]]
        selected, audit = select_candidates(records + [records[1]], 'support', 2)
        self.assertEqual([r['vacancy']['id'] for r in selected], ['2'])
        self.assertEqual(len(audit), 2)
