import unittest
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch, AsyncMock


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_url_confirmed_tuple_cache_cleanup_and_limits(self):
        from services.youtube_video import YouTubeService
        from services.instagram_download import DownloadService, MediaItem, DownloadError
        calls, directories, sent = [], [], []
        async def runner(url, directory):
            calls.append(url); directories.append(directory)
            (directory / 'video.mp4').write_bytes(b'\x00\x00\x00\x18ftypisom')
        async def send(items):
            sent.append(items)
            return [(42, 'confirmed_file', 'video')]
        with tempfile.TemporaryDirectory() as raw:
            service = YouTubeService(raw, {-1}, runner=runner)
            self.assertIsInstance(service, DownloadService)
            await service.handle(-1, 'https://youtu.be/2bZeMfMUhUc', send)
            await service.handle(-1, 'https://youtube.com/shorts/2bZeMfMUhUc', send)
            self.assertEqual(calls, ['https://www.youtube.com/watch?v=2bZeMfMUhUc'])
            self.assertIsInstance(sent[0][0], MediaItem)
            self.assertEqual(sent[1][0].value, 'confirmed_file')
            self.assertFalse(directories[0].exists())
            self.assertFalse(service.pending)
            self.assertFalse(service.inflight)
            with self.assertRaises(DownloadError):
                await service.handle(-2, 'https://youtu.be/2bZeMfMUhUc', send)

    async def test_failure_no_cache_retry_or_files_and_cancel_cleanup(self):
        from services.youtube_video import YouTubeService
        from services.instagram_download import DownloadError
        directories = []
        async def runner(url, directory):
            directories.append(directory)
            (directory / 'partial.mp4').write_bytes(b'partial')
            raise DownloadError('youtube_unavailable')
        send = AsyncMock()
        service = YouTubeService('/stage', {-1}, runner=runner)
        with self.assertRaises(DownloadError):
            await service.handle(-1, 'https://youtu.be/2bZeMfMUhUc', send)
        self.assertEqual(len(directories), 1)
        self.assertFalse(directories[0].exists()); self.assertFalse(service.cache)
        send.assert_not_awaited()
        entered = asyncio.Event()
        async def blocked(url, directory):
            directories.append(directory); entered.set(); await asyncio.Event().wait()
        service.runner = blocked
        task = asyncio.create_task(service.handle(-1, 'https://youtu.be/2bZeMfMUhUc', send))
        await entered.wait(); task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertFalse(directories[-1].exists()); self.assertFalse(service.inflight)

    async def test_worker_start_failure_is_sanitized(self):
        from services.youtube_video import YouTubeService
        from services.instagram_download import DownloadError
        with patch('services.youtube_video.asyncio.create_subprocess_exec', side_effect=OSError('SECRET ENV')):
            with self.assertRaises(DownloadError) as error:
                await YouTubeService('/stage',{-1}).run_worker('https://youtu.be/2bZeMfMUhUc',Path('/tmp'))
        self.assertEqual(str(error.exception),'youtube_unavailable')

    async def test_worker_cancellation_kills_process_group_clean_env(self):
        from services.youtube_video import YouTubeService
        entered = asyncio.Event()
        class Process:
            returncode = None
            pid = 12345
            async def wait(self):
                if self.returncode is not None: return self.returncode
                entered.set(); await asyncio.Event().wait()
        process = Process()
        def killpg(pid, sig): process.returncode = -9
        factory = AsyncMock(return_value=process)
        with patch('services.youtube_video.asyncio.create_subprocess_exec', factory), patch('services.youtube_video.os.killpg', side_effect=killpg) as kill:
            task = asyncio.create_task(YouTubeService('/stage', {-1}).run_worker('https://youtu.be/2bZeMfMUhUc', Path('/tmp')))
            await entered.wait(); task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
        kill.assert_called_once()
        self.assertTrue(factory.call_args.kwargs['start_new_session'])
        self.assertEqual(factory.call_args.args[:3], ('/stage/.instagram-venv/bin/python', '-I', '/stage/services/youtube_video_worker.py'))
        self.assertEqual(set(factory.call_args.kwargs['env']), {'PATH', 'HOME', 'TMPDIR', 'LANG'})
        self.assertIs(factory.call_args.kwargs['stderr'], asyncio.subprocess.DEVNULL)

    def test_final_file_exact_size_boundary(self):
        from services.youtube_video import validate_files
        from services.instagram_download import DownloadError
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            with (directory / 'video.mp4').open('wb') as stream:
                stream.write(b'\x00\x00\x00\x18ftypisom'); stream.truncate(20000000)
            self.assertEqual(len(validate_files(directory)), 1)
            with (directory / 'video.mp4').open('ab') as stream: stream.write(b'x')
            with self.assertRaises(DownloadError): validate_files(directory)


class URLTests(unittest.TestCase):
    def test_supported_urls_and_generic_links(self):
        from services.youtube_video import canonical_url, URL_RE
        expected = 'https://www.youtube.com/watch?v=2bZeMfMUhUc'
        for url in ['https://youtube.com/watch?v=2bZeMfMUhUc&list=abc&t=3',
                    'https://www.youtube.com/shorts/2bZeMfMUhUc?si=abc',
                    'http://m.youtube.com/watch?v=2bZeMfMUhUc',
                    'https://youtu.be/2bZeMfMUhUc?list=abc']:
            self.assertEqual(canonical_url(url), expected)
        self.assertEqual(len(URL_RE.findall('https://youtu.be/2bZeMfMUhUc http://example.org/x https://instagram.com/p/a/')), 3)

    def test_hostile_or_non_single_video_urls(self):
        from services.youtube_video import canonical_url
        for url in ['https://youtube.com.evil/watch?v=2bZeMfMUhUc',
                    'https://user@youtube.com/watch?v=2bZeMfMUhUc',
                    'https://youtube.com:443/watch?v=2bZeMfMUhUc',
                    'https://youtube.com/playlist?list=x', 'https://youtube.com/live/2bZeMfMUhUc',
                    'https://youtube.com/watch?v=short', 'https://youtu.be/2bZeMfMUhUc/extra',
                    'https://youtube.com/watch?v=2bZeMfMUhUc&v=aaaaaaaaaaa',
                    'https://youtube.com/watch?v=%32bZeMfMUhUc',
                    'https://youtube.com/shorts/2bZeMfMUhUc\n', 'https://127.0.0.1/watch?v=2bZeMfMUhUc',
                    'https://youtube.com\\@evil/watch?v=2bZeMfMUhUc', None]:
            with self.subTest(url=url): self.assertIsNone(canonical_url(url))
