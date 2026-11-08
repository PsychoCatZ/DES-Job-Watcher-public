from pathlib import Path
import tempfile
import unittest

from examples.setup_demo_profiles import setup_profiles
from des_job_watcher.profile_audit import verify_coverage
from des_job_watcher.prompting import ROOT
import json


class DemoSetupTests(unittest.TestCase):
    def test_demo_profiles_are_valid_and_existing_data_is_not_overwritten(self):
        (ROOT / 'tmp').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp') as temporary:
            directory = Path(temporary) / 'profiles'
            setup_profiles(directory)
            originals = {path.name: path.read_bytes() for path in directory.glob('*.json')}
            self.assertEqual(len(originals), 3)
            for path in directory.glob('*.json'):
                self.assertTrue(verify_coverage(json.loads(path.read_text(encoding='utf-8'))))
            with self.assertRaises(ValueError):
                setup_profiles(directory)
            self.assertEqual(originals, {path.name: path.read_bytes() for path in directory.glob('*.json')})


if __name__ == '__main__':
    unittest.main()
