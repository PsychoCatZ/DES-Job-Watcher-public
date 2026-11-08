import unittest

import httpx

from des_job_watcher.telegram_client import TelegramClient, TelegramError


class TelegramTests(unittest.TestCase):
    def test_pairing_ignores_group_and_wrong_code(self):
        updates = [
            {'message': {'text': '/start code', 'chat': {'id': -1, 'type': 'group'}, 'from': {'id': 7}}},
            {'message': {'text': '/start other', 'chat': {'id': 8, 'type': 'private'}, 'from': {'id': 8}}},
            {'message': {'text': '/start code', 'chat': {'id': 7, 'type': 'private'}, 'from': {'id': 7}}}]
        with httpx.Client(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={'ok': True, 'result': updates}))) as client:
            self.assertEqual(TelegramClient('123:fake', client).find_private_chat('code'), 7)

    def test_timeout_does_not_expose_token_or_retry(self):
        calls = []
        def fail(request):
            calls.append(request)
            raise httpx.ReadTimeout(str(request.url))
        with httpx.Client(transport=httpx.MockTransport(fail)) as client:
            with self.assertRaises(TelegramError) as error:
                TelegramClient('123:fake', client).send(7, 'Привет')
        self.assertNotIn('123:fake', str(error.exception))
        self.assertEqual(len(calls), 1)

    def test_oversized_message_never_sent(self):
        with httpx.Client(transport=httpx.MockTransport(
                lambda request: self.fail('Unexpected network request'))) as client:
            with self.assertRaises(ValueError):
                TelegramClient('123:fake', client).send(7, '🐈' * 2049)
