import copy
import unittest

from des_job_watcher.quote_recovery import repair_terminal_punctuation


class QuoteRecoveryTests(unittest.TestCase):
    def test_only_final_period_semicolon_is_repaired_and_original_is_preserved(self):
        response = {'conditions': {'remote': {'quotes': ['Гибридный/удаленный формат работы.']}}}
        original = copy.deepcopy(response)
        payload = {'vacancy': {'description': 'Условия: Гибридный/удаленный формат работы;'}}
        corrected, changes = repair_terminal_punctuation(response, payload)
        self.assertEqual(response, original)
        self.assertEqual(corrected['conditions']['remote']['quotes'], ['Гибридный/удаленный формат работы;'])
        self.assertEqual(changes[0]['path'], 'conditions.remote.quotes[0]')

    def test_changed_words_negation_numbers_or_internal_punctuation_are_not_repaired(self):
        for source, quote in (
            ('Звонки не обязательны;', 'Звонки обязательны.'),
            ('Опыт от 3 лет;', 'Опыт от 2 лет.'),
            ('Linux, Python;', 'Linux и Python.'),
            ('Нужны новые задачи;', 'Желание освоить новые задачи.'),
            ('Полностью удалённо;', 'Полностью удаленно.'),
            ('Работа удалённая;', 'Работа удалённая?'),
        ):
            response = {'requirements': [{'quote': quote}]}
            with self.subTest(quote=quote):
                corrected, changes = repair_terminal_punctuation(response, {'vacancy': {'description': source}})
                self.assertEqual(corrected, response)
                self.assertEqual(changes, [])

    def test_existing_exact_quote_is_not_rewritten(self):
        response = {'main_work': {'quotes': ['Работа удалённая.']}}
        payload = {'vacancy': {'description': 'Работа удалённая. Работа удалённая;'}}
        self.assertEqual(repair_terminal_punctuation(response, payload), (response, []))

    def test_no_source_match_means_no_repair(self):
        response = {'requirements': [{'quote': 'Несуществующая цитата.'}]}
        self.assertEqual(repair_terminal_punctuation(response, {'vacancy': {'description': 'Другой текст;'}}),
                         (response, []))
