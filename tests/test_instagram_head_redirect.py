"""Offline regression: exercise urllib's actual 30x dispatch, not redirect mocks."""
import io
from email.message import Message
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.request import HTTPSHandler
from urllib.response import addinfourl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / 'final' / 'services'))
sys.path.insert(0, str(ROOT / 'services'))
import instagram_video_fallback as fallback


class HeadRedirectTests(unittest.TestCase):
    def test_all_redirect_statuses_denied_without_second_request(self):
        for status in (301, 302, 303, 307, 308):
            for destination in ('https://scontent.cdninstagram.com/next.mp4',
                                'https://127.0.0.1/private'):
                with self.subTest(status=status, destination=destination):
                    calls = []

                    def intercepted(handler, request):
                        calls.append((request.full_url, request.get_method()))
                        headers = Message()
                        headers['Location'] = destination
                        headers['Content-Length'] = '123'
                        response = addinfourl(io.BytesIO(b''), headers,
                                              request.full_url,
                                              status if len(calls) == 1 else 200)
                        response.msg = 'offline response'
                        return response

                    with patch.object(HTTPSHandler, 'https_open', intercepted):
                        with self.assertRaisesRegex(ValueError, '^redirect denied$'):
                            fallback.head_size('https://scontent.cdninstagram.com/file.mp4')
                    self.assertEqual(calls, [
                        ('https://scontent.cdninstagram.com/file.mp4', 'HEAD')])

    def test_direct_head_keeps_length_validation_and_timeout(self):
        for length in ('123', '', '0', '-1', '1.5', '１２', '1' * 16):
            with self.subTest(length=length):
                def intercepted(handler, request):
                    self.assertEqual(request.get_method(), 'HEAD')
                    self.assertEqual(request.timeout, 3)
                    headers = Message()
                    headers['Content-Length'] = length
                    response = addinfourl(io.BytesIO(b''), headers, request.full_url, 200)
                    response.msg = 'OK'
                    return response
                with patch.object(HTTPSHandler, 'https_open', intercepted):
                    if length == '123':
                        self.assertEqual(fallback.head_size(
                            'https://scontent.cdninstagram.com/file.mp4'), 123)
                    else:
                        with self.assertRaises(fallback.DownloadError):
                            fallback.head_size('https://scontent.cdninstagram.com/file.mp4')


if __name__ == '__main__':
    unittest.main()
