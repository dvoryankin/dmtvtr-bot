import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from PIL import Image
from aiogram.dispatcher.event.bases import SkipHandler
from services.instagram_download import DownloadService, MediaItem, media_complete
import test_instagram_delivery as delivery_tests


class VerificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_typed_local_sink_copies_and_cleans_without_telegram(self):
        import importlib.util
        import contextlib
        import io
        spec = importlib.util.spec_from_file_location('verify_instagram', str(Path(__file__).parents[1] / 'scripts/verify_instagram.py'))
        verify = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verify)
        temporary = []
        async def runner(url, directory):
            temporary.append(directory)
            (directory / 'video.mp4').write_bytes(b'\x00\x00\x00\x18ftyp' + b'0' * 100)
            (directory / 'manifest.json').write_text(json.dumps(dict(version=1, items=[dict(type='video', file='video.mp4')])))
        def service(base, allowed):
            return DownloadService(base, allowed, runner=runner)
        with tempfile.TemporaryDirectory() as raw:
            output = io.StringIO()
            with patch.object(verify, 'BASE', Path(raw)), patch.object(verify, 'DownloadService', side_effect=service), patch.object(verify.sys, 'argv', ['verify', 'https://instagram.com/p/a/']), contextlib.redirect_stdout(output):
                await verify.main()
            self.assertTrue((Path(raw) / 'instagram-verification/video.mp4').exists())
            self.assertIn('type=video', output.getvalue())
            self.assertIn('width=None height=None', output.getvalue())
            self.assertIn('TEMP_CLEANUP_OK', output.getvalue())
        self.assertFalse(temporary[0].exists())


class CoverageTests(unittest.IsolatedAsyncioTestCase):
    def test_media_complete_known_video_markers_only(self):
        self.assertTrue(media_complete(MediaItem('video', 'v', coverage='extracted_videos')))
        self.assertFalse(media_complete(MediaItem('photo', 'p', coverage='extracted_videos')))
        self.assertFalse(media_complete(MediaItem('video', 'v', coverage='future_coverage')))
        self.assertTrue(media_complete(MediaItem('video', 'v')))
        self.assertTrue(media_complete(MediaItem('video', 'v', coverage='complete')))
        self.assertTrue(media_complete(MediaItem('photo', 'p', coverage='complete')))

    async def test_incomplete_photo_initial_and_cache_keep_source(self):
        from handlers import instagram as h
        runs = []
        async def runner(url, directory):
            runs.append(directory)
            Image.new('RGB', (200, 300)).save(directory / 'slide.jpg')
            manifest = dict(version=1, coverage=getattr(self, 'coverage', 'embed_first_image'),
                            items=[dict(type='photo', file='slide.jpg')])
            if manifest['coverage'] == 'missing':
                del manifest['coverage']
            (directory / 'manifest.json').write_text(json.dumps(manifest))
        service = DownloadService(h.BASE, {-1003911850060}, runner=runner)
        for attempt in range(2):
            m = delivery_tests.DeliveryTests().message()
            with patch.object(h, 'service', service):
                with self.assertRaises(SkipHandler):
                    await h.instagram_video(m, instagram_urls=['https://www.instagram.com/p/a/'])
            m.bot.send_photo.assert_awaited_once()
            with self.subTest(delivery='initial' if attempt == 0 else 'cached'):
                m.bot.delete_message.assert_not_awaited()
        self.assertEqual(len(runs), 1)
        self.assertFalse(runs[0].exists())

    async def test_unknown_photo_coverage_keeps_source(self):
        for coverage in ('missing', None, 'unknown', 'future_coverage', False):
            with self.subTest(coverage=coverage):
                self.coverage = coverage
                await self.test_incomplete_photo_initial_and_cache_keep_source()

    async def test_complete_video_initial_and_cache_delete(self):
        from handlers import instagram as h
        async def runner(url, directory):
            (directory / 'video.mp4').write_bytes(b'\x00\x00\x00\x18ftyp' + b'0' * 100)
            (directory / 'manifest.json').write_text(json.dumps(dict(
                version=1, coverage='extracted_videos', items=[dict(type='video', file='video.mp4')])))
        service = DownloadService(h.BASE, {-1003911850060}, runner=runner)
        for attempt in range(2):
            m = delivery_tests.DeliveryTests().message()
            with patch.object(h, 'service', service), patch.object(h, 'probe_video_dimensions', return_value=None):
                with self.assertRaises(SkipHandler):
                    await h.instagram_video(m, instagram_urls=['https://www.instagram.com/p/a/'])
            m.bot.send_video.assert_awaited_once()
            m.bot.delete_message.assert_awaited_once()
