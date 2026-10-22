import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

class VariantSelectionTests(unittest.TestCase):
    def test_instagram_file_budget_uses_documented_telegram_cap_not_45_mib(self):
        from instagram_download import MAX_FILE
        self.assertEqual(MAX_FILE, 50_000_000)

    def test_bounded_selector_chooses_smaller_real_mp4_instead_of_skipping_large_best(self):
        from instagram_worker import build_options
        with TemporaryDirectory() as raw:
            selector = build_options(Path(raw))['format']
        self.assertTrue(callable(selector), 'string best selector silently skips oversized chosen video')
        from instagram_download import MAX_FILE
        candidates = [
            {'format_id':'small','ext':'mp4','protocol':'https','url':'https://x.cdninstagram.com/small.mp4'},
            {'format_id':'large','ext':'mp4','protocol':'https','url':'https://x.cdninstagram.com/large.mp4'},
        ]
        with patch('instagram_video_fallback.head_size', side_effect=[MAX_FILE+1, MAX_FILE-1]) as head:
            result = list(selector({'formats': candidates}))
        self.assertEqual(result, [dict(candidates[0], filesize=MAX_FILE-1)])
        self.assertEqual(head.call_count, 2)

    def test_no_more_than_three_candidates_and_no_oversized_fallback(self):
        from instagram_video_fallback import fitting_mp4
        from instagram_download import MAX_FILE, DownloadError
        formats = [dict(ext='mp4', protocol='https', url='https://x.cdninstagram.com/x.mp4') for _ in range(8)]
        with patch('instagram_video_fallback.head_size', return_value=MAX_FILE+1) as head:
            with self.assertRaises(DownloadError):
                list(fitting_mp4({'formats': formats}))
        self.assertEqual(head.call_count, 3)

    def test_audio_only_and_video_only_streams_never_replace_progressive_video(self):
        from instagram_video_fallback import fitting_mp4
        good = dict(ext='mp4', protocol='https', url='https://x.cdninstagram.com/good.mp4')
        formats = [good, dict(good, acodec='none'), dict(good, vcodec='none'), dict(good, protocol='http')]
        with patch('instagram_video_fallback.head_size', return_value=100) as head:
            self.assertEqual(list(fitting_mp4({'formats': formats})), [dict(good, filesize=100)])
        head.assert_called_once_with(good['url'])

    def test_head_validates_url_before_open_and_does_not_read_body(self):
        from instagram_video_fallback import head_size
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = 'https://x.cdninstagram.com/x.mp4'
        response.headers = {'Content-Length':'49385450'}
        with patch('instagram_video_fallback.build_opener') as opener:
            with self.assertRaises(ValueError):
                head_size('https://127.0.0.1/secret')
            opener.assert_not_called()
            opener.return_value.open.return_value = response
            self.assertEqual(head_size(response.geturl()), 49385450)
            request = opener.return_value.open.call_args[0][0]
            self.assertEqual(request.get_method(), 'HEAD')
            response.read.assert_not_called()

    def test_missing_invalid_and_zero_content_length_fail_closed(self):
        from instagram_video_fallback import head_size
        from instagram_download import DownloadError
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = 'https://x.cdninstagram.com/x.mp4'
        for value in ('', '-1', '0', 'not-a-number', '9'*16):
            with self.subTest(value=value), patch('instagram_video_fallback.build_opener') as opener:
                response.headers = {'Content-Length':value}
                opener.return_value.open.return_value = response
                with self.assertRaises(DownloadError):
                    head_size(response.geturl())
