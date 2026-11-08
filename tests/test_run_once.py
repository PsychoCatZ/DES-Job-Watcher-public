import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from examples import run_once
from des_job_watcher.telegram_delivery import save_binding


class RunOnceTests(unittest.TestCase):
    def test_report_uses_exact_batches_and_delivery_uses_exact_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            save_binding(root / 'data/telegram_binding.json', '123', 42)
            with patch.object(run_once, 'ROOT', root), patch.dict('os.environ', {
                    'HH_USER_AGENT': 'test', 'HH_ACCESS_TOKEN': 'test',
                    'OPENAI_API_KEY': 'test', 'TELEGRAM_BOT_TOKEN': '123:fake'}), \
                    patch('sys.argv', ['run_once', '--telegram', '--live']), \
                    patch.object(run_once, 'run_step', return_value=True) as step:
                self.assertEqual(run_once.main(), 0)
            calls = [call.args[1] for call in step.call_args_list]
            analyses = [args for args in calls if args[0] == 'examples.analyze_saved']
            report = next(args for args in calls if args[0] == 'examples.report_saved')
            for analysis in analyses:
                self.assertIn(analysis[analysis.index('--output-directory') + 1], report)
                profile = analysis[analysis.index('--profile') + 1]
                details = next(args for args in calls if args[0] == 'examples.fetch_hh_details'
                               and args[args.index('--profile') + 1] == profile)
                self.assertEqual(analysis[analysis.index('--input') + 1], details[details.index('--input') + 1])
            delivery = calls[-1]
            self.assertEqual(delivery[0], 'examples.send_telegram')
            self.assertEqual(delivery[delivery.index('--report') + 1],
                             report[report.index('--output-directory') + 1])

    def test_analysis_failure_prevents_delivery(self):
        with patch.dict('os.environ', {'HH_USER_AGENT': 'test', 'HH_ACCESS_TOKEN': 'test',
                                      'OPENAI_API_KEY': 'test'}), \
                patch('sys.argv', ['run_once', '--live']), \
                patch.object(run_once, 'run_step', side_effect=[True, True, True, True, True, False]) as step:
            self.assertEqual(run_once.main(), 1)
            self.assertEqual(step.call_count, 6)
