import copy
import json
from pathlib import Path
import unittest

from des_job_watcher.assessment import (
    AnalysisValidationError, parse_response, validate_and_decide,
)


FIXTURES = Path(__file__).resolve().parents[1] / 'examples' / 'fixtures'


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads((FIXTURES / 'analysis_input.json').read_text(encoding='utf-8'))
        self.response = json.loads((FIXTURES / 'analysis_response.json').read_text(encoding='utf-8'))

    def decide(self):
        return validate_and_decide(self.response, self.payload)['decision']

    def confirm_communication(self):
        quote = 'Собеседование, обучение и вся работа только текстом.'
        self.payload['vacancy']['description'] += ' ' + quote
        self.response['conditions']['communication'] = {
            'status': 'confirmed', 'quotes': [quote], 'field_refs': [], 'reason': 'Текстовая альтернатива явная.'}

    def test_unknown_communication_is_neutral_for_decision_and_delivery(self):
        result = validate_and_decide(self.response, self.payload)
        self.assertEqual(result['decision'], 'suitable')
        self.assertEqual(result['delivery']['action'], 'show')
        self.assertNotIn('conditions.communication', result['uncertainties'])
        self.assertEqual(result['analysis']['conditions']['communication']['status'], 'unknown')
        self.confirm_communication()
        self.assertEqual(self.decide(), 'suitable')

    def test_conflict_overrides_professional_match(self):
        quote = 'Обязательны голосовые звонки без текстовой альтернативы.'
        self.payload['vacancy']['description'] += ' ' + quote
        self.response['conditions']['communication'] = {
            'status': 'conflict', 'quotes': [quote], 'field_refs': [], 'reason': 'Голос обязателен.'}
        self.assertEqual(self.decide(), 'unsuitable')

    def test_meeting_without_channel_does_not_change_rating(self):
        before = validate_and_decide(self.response, self.payload)
        self.payload['vacancy']['description'] += ' На первой встрече обсудим задачу.'
        after = validate_and_decide(self.response, self.payload)
        self.assertEqual(after['decision'], before['decision'])
        self.assertEqual(after['delivery'], before['delivery'])

    def test_explicit_mandatory_video_is_excluded(self):
        quote = 'Ежедневные обязательные видеовстречи без письменной альтернативы.'
        self.payload['vacancy']['description'] += ' ' + quote
        self.response['conditions']['communication'] = {
            'status': 'conflict', 'quotes': [quote], 'field_refs': [], 'reason': 'Обязательное видео.'}
        result = validate_and_decide(self.response, self.payload)
        self.assertEqual(result['decision'], 'unsuitable')
        self.assertEqual(result['delivery']['action'], 'exclude')

    def test_text_alternative_and_unknown_have_same_nonblocking_effect(self):
        before = validate_and_decide(self.response, self.payload)
        quote = 'Видеовстречи можно полностью заменить письменной перепиской.'
        self.payload['vacancy']['description'] += ' ' + quote
        self.response['conditions']['communication'] = {
            'status': 'confirmed', 'quotes': [quote], 'field_refs': [], 'reason': 'Письменная альтернатива.'}
        after = validate_and_decide(self.response, self.payload)
        self.assertEqual(after['decision'], before['decision'])
        self.assertEqual(after['delivery'], before['delivery'])

    def test_neutral_communication_does_not_neutralize_unknown_remote_or_country(self):
        for key in ('remote', 'work_from_russia'):
            response = copy.deepcopy(self.response)
            response['conditions'][key] = {
                'status': 'unknown', 'quotes': [], 'field_refs': [], 'reason': 'Не указано.'}
            with self.subTest(key=key):
                result = validate_and_decide(response, self.payload)
                self.assertEqual(result['decision'], 'clarify')
                self.assertEqual(result['uncertainties'], ['conditions.' + key])

    def test_historical_rules_two_reproduce_old_policy(self):
        self.payload['rules']['version'] = 2
        self.response['rules_version'] = 2
        result = validate_and_decide(self.response, self.payload)
        self.assertEqual(result['decision'], 'clarify')
        self.assertIn('conditions.communication', result['uncertainties'])
        self.assertEqual(result['assessment_policy_version'], 2)

    def test_missing_experience_is_uncertainty_and_preferred_gap_is_neutral(self):
        self.confirm_communication()
        quote = 'Требуется Zendesk.'
        self.payload['vacancy']['description'] += ' ' + quote
        self.response['requirements'].append({
            'text': 'Zendesk', 'importance': 'mandatory', 'status': 'unconfirmed',
            'quote': quote, 'profile_evidence_ids': [], 'reason': 'Не указан в резюме.'})
        self.assertEqual(self.decide(), 'clarify')
        self.response['requirements'][-1]['importance'] = 'preferred'
        self.assertEqual(self.decide(), 'suitable')

    def test_technical_assistant_and_auxiliary_ai_are_not_rejections(self):
        self.confirm_communication()
        self.assertEqual(self.response['ai_role']['kind'], 'auxiliary')
        self.assertIn('ассистент', self.payload['vacancy']['name'])
        self.assertEqual(self.decide(), 'suitable')

    def test_salary_schedule_and_employment_metadata_do_not_change_decision(self):
        self.confirm_communication()
        before = self.decide()
        self.payload['vacancy'].update(salary_information_only={'from': 1},
                                       schedule='6/1', employment_type='part_time')
        self.assertEqual(self.decide(), before)

    def test_wrong_ids_versions_and_boolean_version_rejected(self):
        for key, value in (('vacancy_id', 'other'), ('profile_id', 'developer'),
                           ('profile_version', 2), ('rules_version', 4),
                           ('contract_version', True)):
            bad = copy.deepcopy(self.response)
            bad[key] = value
            with self.subTest(key=key), self.assertRaises(AnalysisValidationError):
                validate_and_decide(bad, self.payload)

    def test_foreign_or_missing_evidence_and_fake_quotes_rejected(self):
        for field, value in (('profile_evidence_ids', ['developer_01']),
                             ('profile_evidence_ids', []),
                             ('quotes', ['Несуществующее требование'])):
            bad = copy.deepcopy(self.response)
            bad['main_work'][field] = value
            with self.subTest(value=value), self.assertRaises(AnalysisValidationError):
                validate_and_decide(bad, self.payload)

    def test_model_cannot_supply_final_decision_or_salary_score(self):
        for key in ('decision', 'salary_score'):
            bad = copy.deepcopy(self.response)
            bad[key] = 'suitable'
            with self.subTest(key=key), self.assertRaises(AnalysisValidationError):
                validate_and_decide(bad, self.payload)

    def test_incomplete_conditions_or_unknown_status_rejected(self):
        bad = copy.deepcopy(self.response)
        del bad['conditions']['remote']
        with self.assertRaises(AnalysisValidationError):
            validate_and_decide(bad, self.payload)
        self.response['conditions']['remote']['status'] = 'probably'
        with self.assertRaises(AnalysisValidationError):
            self.decide()

    def test_forbidden_employer_and_archive_are_deterministic(self):
        self.confirm_communication()
        self.payload['vacancy']['employer']['name'] = 'Data Light'
        self.assertEqual(self.decide(), 'unsuitable')
        self.payload['vacancy']['employer']['name'] = 'Another Company'
        self.payload['vacancy']['archived'] = True
        self.assertEqual(self.decide(), 'unsuitable')

    def test_explicit_ai_ban_is_critical_for_developer_but_silence_is_not(self):
        self.confirm_communication()
        self.payload['profile']['profile_id'] = 'developer'
        self.response['profile_id'] = 'developer'
        self.payload['profile']['evidence'][0]['id'] = 'developer_01'
        self.response['main_work']['profile_evidence_ids'] = ['developer_01']
        self.response['requirements'][0]['profile_evidence_ids'] = ['developer_01']
        self.response['conditions']['ai_policy'] = {
            'status': 'unknown', 'quotes': [], 'field_refs': [], 'reason': 'Политика не определена.'}
        self.assertEqual(self.decide(), 'suitable')
        quote = 'Использовать AI при разработке запрещено.'
        self.payload['vacancy']['description'] += ' ' + quote
        self.response['conditions']['ai_policy'] = {
            'status': 'conflict', 'quotes': [quote], 'field_refs': [], 'reason': 'Прямой запрет.'}
        self.assertEqual(self.decide(), 'unsuitable')

    def test_invalid_json_duplicates_and_constants_rejected(self):
        for text in ('not json', '{"a":1,"a":2}', '{"a":NaN}'):
            with self.subTest(text=text), self.assertRaises(AnalysisValidationError):
                parse_response(text)
        self.assertEqual(parse_response(json.dumps(self.response)), self.response)

    def test_malformed_input_is_validation_failure(self):
        for payload in ([], {}, {'input_version': 1, 'profile': [], 'vacancy': {}, 'rules': {}}):
            with self.subTest(payload=payload), self.assertRaises(AnalysisValidationError):
                validate_and_decide(self.response, payload)

    def test_remote_can_use_checked_structured_field_without_text_quote(self):
        self.payload['vacancy']['work_formats'] = ['REMOTE']
        self.response['conditions']['remote'] = {
            'status': 'confirmed', 'quotes': [], 'field_refs': ['vacancy.work_formats'],
            'reason': 'В карточке указан REMOTE.'}
        self.assertEqual(self.decide(), 'suitable')  # Неизвестное общение нейтрально.
        self.confirm_communication()
        self.assertEqual(self.decide(), 'suitable')

    def test_remote_reference_cannot_confirm_voice_or_country(self):
        self.payload['vacancy']['work_formats'] = ['REMOTE']
        for key in ('communication', 'work_from_russia', 'ai_policy'):
            bad = copy.deepcopy(self.response)
            bad['conditions'][key]['field_refs'] = ['vacancy.work_formats']
            with self.subTest(key=key), self.assertRaises(AnalysisValidationError):
                validate_and_decide(bad, self.payload)

    def test_remote_reference_rejects_missing_mixed_or_office_formats(self):
        self.response['conditions']['remote'] = {
            'status': 'confirmed', 'quotes': [], 'field_refs': ['vacancy.work_formats'],
            'reason': 'Попытка подтвердить удалёнку.'}
        for formats in (None, [], ['ON_SITE'], ['REMOTE', 'HYBRID'], [{'id': 'REMOTE'}]):
            self.payload['vacancy']['work_formats'] = formats
            with self.subTest(formats=formats), self.assertRaises(AnalysisValidationError):
                self.decide()

    def test_unrecognized_field_reference_and_old_contract_rejected(self):
        self.response['conditions']['remote']['field_refs'] = ['vacancy.fake_remote']
        with self.assertRaises(AnalysisValidationError):
            self.decide()
        self.response['conditions']['remote']['field_refs'] = []
        self.response['contract_version'] = 1
        with self.assertRaises(AnalysisValidationError):
            self.decide()

    def test_atomic_requirements_preserve_confirmed_and_unconfirmed_parts(self):
        self.confirm_communication()
        quote = 'Нужен опыт Git и параллельной работы через worktree.'
        self.payload['vacancy']['description'] += ' ' + quote
        self.payload['profile']['evidence'].append({'id': 'support_git', 'fact': 'Git указан в навыках.'})
        self.response['requirements'] = [
            {'text': 'Git', 'importance': 'mandatory', 'status': 'confirmed',
             'quote': quote, 'profile_evidence_ids': ['support_git'], 'reason': 'Указан.'},
            {'text': 'Параллельная работа через worktree', 'importance': 'mandatory',
             'status': 'unconfirmed', 'quote': quote, 'profile_evidence_ids': ['support_git'],
             'reason': 'Git подтверждён, конкретная практика worktree не раскрыта.'},
        ]
        result = validate_and_decide(self.response, self.payload)
        self.assertEqual(result['decision'], 'clarify')
        self.assertEqual(result['uncertainties'], ['requirements[1]'])

    def test_insufficient_evidence_cannot_become_automatic_rejection(self):
        self.response['main_work']['fit'] = 'mismatch'
        self.response['main_work']['mismatch_basis'] = 'insufficient_evidence'
        result = validate_and_decide(self.response, self.payload)
        self.assertEqual(result['decision'], 'clarify')
        self.assertEqual(result['delivery']['action'], 'review')
        self.assertNotIn('main_work', result['blocking_reasons'])

    def test_different_profession_remains_visible_for_review(self):
        self.response['main_work']['fit'] = 'mismatch'
        self.response['main_work']['mismatch_basis'] = 'different_work'
        result = validate_and_decide(self.response, self.payload)
        self.assertEqual(result['decision'], 'unsuitable')
        self.assertEqual(result['delivery']['action'], 'review')

    def test_any_number_of_unconfirmed_skills_does_not_hide_vacancy(self):
        quote = self.response['requirements'][0]['quote']
        self.response['requirements'] = [
            {'text': f'Неуточнённая часть {number}', 'importance': 'mandatory',
             'status': 'unconfirmed', 'quote': quote, 'profile_evidence_ids': [],
             'reason': 'Не раскрыто, а не доказанное отсутствие опыта.'}
            for number in range(20)
        ]
        result = validate_and_decide(self.response, self.payload)
        self.assertEqual(result['decision'], 'clarify')
        self.assertEqual(result['delivery']['action'], 'show')

    def test_partial_task_overlap_is_shown_with_questions(self):
        self.response['main_work']['fit'] = 'partial'
        result = validate_and_decide(self.response, self.payload)
        self.assertEqual(result['decision'], 'clarify')
        self.assertEqual(result['delivery']['action'], 'show')

    def test_professional_conflict_is_visible_but_explicit_voice_conflict_is_excluded(self):
        self.confirm_communication()
        quote = 'Обязательно высшее образование.'
        self.payload['vacancy']['description'] += ' ' + quote
        self.payload['profile']['evidence'].append({
            'id': 'support_education', 'fact': 'Среднее специальное образование.'})
        self.response['requirements'].append({
            'text': 'Высшее образование', 'importance': 'mandatory', 'status': 'conflict',
            'quote': quote, 'profile_evidence_ids': ['support_education'],
            'reason': 'Явно указан другой уровень образования.'})
        result = validate_and_decide(self.response, self.payload)
        self.assertEqual(result['decision'], 'unsuitable')
        self.assertEqual(result['delivery']['action'], 'review')
        voice = 'Обязательные голосовые звонки без альтернативы.'
        self.payload['vacancy']['description'] += ' ' + voice
        self.response['conditions']['communication'] = {
            'status': 'conflict', 'quotes': [voice], 'field_refs': [], 'reason': 'Обязательный голос.'}
        self.assertEqual(validate_and_decide(self.response, self.payload)['delivery']['action'], 'exclude')

    def test_mismatch_reason_and_professional_conflict_require_evidence(self):
        self.response['main_work']['fit'] = 'mismatch'
        with self.assertRaises(AnalysisValidationError):
            self.decide()
        self.response['main_work']['fit'] = 'match'
        self.response['requirements'][0]['status'] = 'conflict'
        self.response['requirements'][0]['profile_evidence_ids'] = []
        with self.assertRaises(AnalysisValidationError):
            self.decide()


if __name__ == '__main__':
    unittest.main()
