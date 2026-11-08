from contextlib import redirect_stdout
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.check_publication import main


class PublicationTests(unittest.TestCase):
    def run_scan(self, path, indexed_content):
        index = ('100644 ' + 'a' * 40 + ' 0\t' + path + '\0').encode()
        replies = [SimpleNamespace(stdout=index), SimpleNamespace(stdout=indexed_content)]
        stream = io.StringIO()
        with patch('scripts.check_publication.subprocess.run', side_effect=replies), redirect_stdout(stream):
            status = main()
        return status, stream.getvalue()

    def test_scanner_reads_indexed_content_and_does_not_print_credential(self):
        fake_credential = 'sk-' + 'x' * 24
        status, output = self.run_scan('example.txt', fake_credential.encode())
        self.assertEqual(status, 1)
        self.assertIn('API credential', output)
        self.assertNotIn(fake_credential, output)

    def test_private_profile_path_is_rejected_even_without_credentials(self):
        status, output = self.run_scan('config/profiles/support.json', b'{}')
        self.assertEqual(status, 1)
        self.assertIn('private path', output)

    def test_clean_text_passes(self):
        status, output = self.run_scan('example.txt', b'fictional example')
        self.assertEqual(status, 0)
        self.assertIn('findings: 0', output)


if __name__ == '__main__':
    unittest.main()
