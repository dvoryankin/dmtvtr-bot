import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from instagram_download import DownloadService, DownloadError
from instagram_diagnostics import classify

class RetryTests(unittest.IsolatedAsyncioTestCase):
    def test_exact_photo_error(self):
        self.assertEqual(classify('ERROR: [Instagram] Dd9MZl4NKmg: There is no video in this post')['code'], 'no_video')

    async def test_worker_preserves_permanent_diagnostic(self):
        import json
        class Process:
            returncode = 2
            async def wait(self): return 2
        with tempfile.TemporaryDirectory() as raw:
            directory=Path(raw)
            (directory/'diagnostic.json').write_text(json.dumps({'code':'no_video'}))
            with patch('instagram_download.asyncio.create_subprocess_exec', new=AsyncMock(return_value=Process())):
                with self.assertRaisesRegex(DownloadError, '^no_video$'):
                    await DownloadService('/tmp', {-1}).run_worker('https://instagram.com/p/abc/', directory)

    async def test_third_attempt_success_fresh_cleanup_and_reservations(self):
        paths = []
        async def runner(url, directory):
            self.assertEqual(service.active, {-1})
            self.assertEqual(service.inflight, {url})
            self.assertTrue(all(not p.exists() for p in paths))
            paths.append(directory)
            if len(paths) < 3:
                raise DownloadError('unavailable')
            (directory/'01.mp4').write_bytes(b'\x00\x00\x00\x18ftypisom')
        send = AsyncMock(return_value=['id'])
        with tempfile.TemporaryDirectory() as raw:
            service = DownloadService(raw, {-1}, runner=runner)
            with patch('instagram_download.asyncio.sleep', new=AsyncMock()):
                await service.handle(-1, 'https://instagram.com/p/abc/', send)
        self.assertEqual(len(set(paths)), 3)
        self.assertTrue(all(not p.exists() for p in paths))
        send.assert_awaited_once()
        self.assertFalse(service.active)

    async def test_timeout_retries_and_budget_stops_new_attempt(self):
        runner=AsyncMock(side_effect=asyncio.TimeoutError())
        service=DownloadService('/tmp', {-1}, runner=runner)
        with patch('instagram_download.asyncio.sleep', new=AsyncMock()):
            with self.assertRaisesRegex(DownloadError, 'timeout'):
                await service.handle(-1, 'https://instagram.com/p/abc/', AsyncMock())
        self.assertEqual(runner.await_count, 3)
        now=[0]
        paths=[]
        async def slow(url, directory):
            paths.append(directory)
            now[0]=91
            raise DownloadError('unavailable')
        service=DownloadService('/tmp', {-1}, runner=slow, clock=lambda:now[0])
        with self.assertRaisesRegex(DownloadError, 'timeout'):
            await service.handle(-1, 'https://instagram.com/p/abc/', AsyncMock())
        self.assertEqual(len(paths),1)
        self.assertFalse(paths[0].exists())

    async def test_cancellation_during_backoff_releases_reservations(self):
        entered=asyncio.Event()
        paths=[]
        async def runner(url, directory):
            paths.append(directory)
            raise DownloadError('unavailable')
        async def sleep(delay):
            entered.set()
            await asyncio.Event().wait()
        service=DownloadService('/tmp', {-1}, runner=runner)
        with patch('instagram_download.asyncio.sleep', new=sleep):
            task=asyncio.create_task(service.handle(-1, 'https://instagram.com/p/abc/', AsyncMock()))
            await entered.wait()
            self.assertEqual(service.active, {-1})
            self.assertFalse(paths[0].exists())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
        self.assertFalse(service.active)
        self.assertFalse(service.inflight)

    async def test_exhaustion_permanent_and_send_not_retried(self):
        for error,count in [('unavailable',3),('no_video',1),('invalid_file',1),('dns_denied',1)]:
            runner = AsyncMock(side_effect=DownloadError(error))
            service = DownloadService('/tmp', {-1}, runner=runner)
            send=AsyncMock()
            with patch('instagram_download.asyncio.sleep', new=AsyncMock()):
                with self.assertRaises(DownloadError):
                    await service.handle(-1, 'https://instagram.com/p/abc/', send)
            self.assertEqual(runner.await_count,count)
            send.assert_not_awaited()
            self.assertFalse(service.active)
        async def runner(url, directory):
            (directory/'01.mp4').write_bytes(b'\x00\x00\x00\x18ftypisom')
        send=AsyncMock(side_effect=OSError('send failed'))
        service=DownloadService('/tmp', {-1}, runner=runner)
        with self.assertRaises(OSError):
            await service.handle(-1, 'https://instagram.com/p/abc/', send)
        send.assert_awaited_once()
