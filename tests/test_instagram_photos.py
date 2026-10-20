import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

class EmbedTests(unittest.TestCase):
    def test_only_post_media_not_avatar_or_recommendation(self):
        from instagram_photos import embedded_photo_urls
        html = '''<img src="https://x.cdninstagram.com/avatar.jpg">
        <img class="EmbeddedMediaImage" src="https://x.cdninstagram.com/post.jpg?a=1&amp;b=2">
        <img src="https://x.cdninstagram.com/recommendation.jpg">'''
        self.assertEqual(embedded_photo_urls(html), ['https://x.cdninstagram.com/post.jpg?a=1&b=2'])
        self.assertEqual(embedded_photo_urls('<img src="https://x.cdninstagram.com/avatar.jpg">'), [])

    def test_wrong_permalink_and_ambiguous_images_rejected(self):
        from instagram_photos import embedded_photo_urls
        url = 'https://www.instagram.com/p/abc/'
        self.assertEqual(embedded_photo_urls('<a class="EmbeddedMedia" href="https://www.instagram.com/p/other/"><img class="EmbeddedMediaImage" src="https://x.cdninstagram.com/photo.jpg"></a>', expected_url=url), [])
        self.assertEqual(embedded_photo_urls('<img class="EmbeddedMediaImage" src="https://x.cdninstagram.com/1.jpg"><img class="EmbeddedMediaImage" src="https://x.cdninstagram.com/2.jpg">'), [])

class FetchTests(unittest.TestCase):
    def test_response_byte_budget_and_partial_video_fail_closed(self):
        from instagram_photos import fetch, download_photo
        from instagram_download import DownloadError
        from unittest.mock import Mock, patch, MagicMock
        for headers, body in [({'Content-Length': '101'}, b''), ({}, b'x' * 101)]:
            response = MagicMock()
            response.__enter__.return_value = response
            response.geturl.return_value = 'https://www.instagram.com/p/abc/embed/'
            response.headers = headers
            response.read.return_value = body
            with patch('instagram_photos.build_opener', return_value=Mock(open=Mock(return_value=response))):
                with self.assertRaises(DownloadError): fetch(response.geturl(), 100)
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            for name in ['01.mp4', '01.mp4.part']:
                (directory / name).write_bytes(b'x')
                with patch('instagram_photos.fetch') as request:
                    with self.assertRaises(DownloadError): download_photo('https://www.instagram.com/p/a/', directory)
                    request.assert_not_called()
                (directory / name).unlink()

    def test_fetch_url_and_redirect_policy(self):
        from instagram_photos import validate_fetch_url, SafeRedirect
        from urllib.request import Request
        good = 'https://scontent.cdninstagram.com/a.jpg'
        self.assertEqual(validate_fetch_url(good), good)
        bad = ['http://www.instagram.com/a', 'https://127.0.0.1/a',
               'https://www.instagram.com.evil/a', 'https://user@www.instagram.com/a',
               'https://www.instagram.com:80/a', 'file:///etc/passwd',
               'https://www.instagram.com/a\nX']
        for url in bad:
            with self.subTest(url=url):
                with self.assertRaises(ValueError): validate_fetch_url(url)
                with self.assertRaises(ValueError):
                    SafeRedirect().redirect_request(Request(good), None, 302, 'found', {}, url)

    def test_download_only_main_image_bounded_and_manifest(self):
        from instagram_photos import download_photo
        from unittest.mock import patch
        import json
        page = '<a class="EmbeddedMedia" href="https://www.instagram.com/p/abc/"><img class="EmbeddedMediaImage" src="https://x.cdninstagram.com/p.jpg"></a>'
        with TemporaryDirectory() as raw, patch('instagram_photos.fetch', side_effect=[page.encode(), b'\xff\xd8\xff' + b'x' * 100]) as fetch:
            directory = Path(raw)
            download_photo('https://www.instagram.com/p/abc/', directory)
            manifest = json.loads((directory / 'manifest.json').read_text())
            self.assertEqual(manifest['items'], [{'type': 'photo', 'file': '01.jpg'}])
            self.assertEqual(manifest['coverage'], 'embed_first_image')
            self.assertEqual(fetch.call_count, 2)

class ManifestTests(unittest.TestCase):
    def fixture(self, directory, items=None):
        import json
        from PIL import Image
        Image.new('RGB', (640, 480), 'red').save(directory / '01.webp')
        (directory / '02.mp4').write_bytes(b'\x00\x00\x00\x18ftypisom')
        (directory / 'manifest.json').write_text(json.dumps({'version': 1, 'items': items or [
            {'type': 'photo', 'file': '01.webp'}, {'type': 'video', 'file': '02.mp4'}]}))

    def test_mixed_manifest_webp_converted_to_verified_jpeg(self):
        from instagram_download import validate_files
        from PIL import Image
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            self.fixture(directory)
            files = validate_files(directory)
            self.assertEqual([x.type for x in files], ['photo', 'video'])
            self.assertEqual(files[1].value, directory / '02.mp4')
            with Image.open(files[0].value) as image:
                self.assertEqual(image.format, 'JPEG')
                self.assertEqual(image.size, (640, 480))
                image.verify()

    def test_photo_validation_disk_budget_includes_raw_and_prepared(self):
        from instagram_download import validate_files, DownloadError
        from unittest.mock import patch
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            self.fixture(directory)
            # A large leftover input/part cannot escape the combined disk cap.
            (directory / 'leftover.part').write_bytes(b'x' * 100000)
            with patch('instagram_download.MAX_TOTAL', 99999):
                with self.assertRaises(DownloadError): validate_files(directory)

    def test_photo_symlinks_avatars_and_bad_dimensions_rejected(self):
        from instagram_download import validate_files, DownloadError
        from PIL import Image
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            self.fixture(directory)
            (directory / '01.webp').unlink()
            (directory / '01.webp').symlink_to('/etc/hosts')
            with self.assertRaises(DownloadError): validate_files(directory)
            (directory / '01.webp').unlink()
            for size in [(100, 100), (161, 4000)]:
                Image.new('RGB', size).save(directory / '01.webp')
                with self.assertRaises(DownloadError): validate_files(directory)

    def test_invalid_manifest_and_photo_rejected(self):
        from instagram_download import validate_files, DownloadError
        import json
        bad = [
            {'version': 1, 'items': [{'type': 'photo', 'file': '../x.jpg'}]},
            {'version': 1, 'items': [{'type': 'document', 'file': '01.webp'}]},
            {'version': 1, 'items': [{'type': 'video', 'file': '01.webp'}]},
            {'version': 1, 'items': [{'type': 'photo', 'file': '01.webp'}] * 11},
            {'version': 1, 'items': [{'type': 'photo', 'file': '01.webp'}] * 2},
            {'version': 1, 'items': []}, {'version': 2, 'items': []}, [],
        ]
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            self.fixture(directory)
            for value in bad:
                (directory / 'manifest.json').write_text(json.dumps(value))
                with self.subTest(value=value), self.assertRaises(DownloadError): validate_files(directory)
            self.fixture(directory)
            (directory / '01.webp').write_bytes(b'RIFFxxxxWEBPinvalid')
            with self.assertRaises(DownloadError): validate_files(directory)

class PhotoCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_preserves_photo_video_types_and_cleanup(self):
        from instagram_download import DownloadService
        calls, sent, directories = [], [], []
        async def runner(url, directory):
            calls.append(url); directories.append(directory)
            ManifestTests().fixture(directory)
        async def send(items):
            sent.append([(x.type, x.value) for x in items])
            return ['photo-id', 'video-id']
        service = DownloadService(Path('/unused'), {-1}, runner=runner)
        for _ in range(2): await service.handle(-1, 'https://instagram.com/p/abc/', send)
        self.assertEqual(len(calls), 1)
        self.assertEqual(sent[1], [('photo', 'photo-id'), ('video', 'video-id')])
        self.assertTrue(all(not x.exists() for x in directories))

class FallbackTests(unittest.TestCase):
    def test_only_no_video_can_enter_photo_fallback(self):
        from instagram_worker import extract_media
        from instagram_download import DownloadError
        from unittest.mock import Mock, patch
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            for reason in ['login required', 'HTTP Error 403', 'network_guard', 'timed out']:
                with patch('instagram_worker.download_photo') as photo:
                    with self.assertRaises(Exception):
                        extract_media(Mock(extract_info=Mock(side_effect=Exception(reason))), 'https://www.instagram.com/p/a/', directory)
                    photo.assert_not_called()
            def make_photo(*args): ManifestTests().fixture(directory)
            with patch('instagram_worker.download_photo', side_effect=make_photo) as photo:
                files = extract_media(Mock(extract_info=Mock(side_effect=Exception('There is no video in this post'))), 'https://www.instagram.com/p/a/', directory)
                self.assertEqual(len(files), 2)
                photo.assert_called_once()

    def test_video_success_never_fetches_photo(self):
        from instagram_worker import extract_media
        from unittest.mock import Mock, patch
        import json
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            def video(*args, **kwargs):
                (directory / '01.mp4').write_bytes(b'\x00\x00\x00\x18ftypisom')
            with patch('instagram_worker.download_photo') as photo:
                files = extract_media(Mock(extract_info=Mock(side_effect=video)), 'https://www.instagram.com/p/a/', directory)
                photo.assert_not_called()
                self.assertEqual(json.loads((directory / 'manifest.json').read_text())['items'], [{'type':'video','file':'01.mp4'}])
                self.assertEqual(len(files), 1)

if __name__ == '__main__': unittest.main()
