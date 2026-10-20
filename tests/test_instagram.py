import unittest
from instagram_download import canonical_url, extract_urls

class UrlTests(unittest.TestCase):
    def test_canonical_and_exact_origin(self):
        self.assertEqual(canonical_url('https://instagram.com/reel/DWuGIV2iTcr/?igsh=tracking#x'), 'https://www.instagram.com/reel/DWuGIV2iTcr/')
        for bad in ['https://instagram.com.evil/reel/abc/', 'https://evil@instagram.com/reel/abc/', 'https://instagram.com:8443/p/abc/', 'http://instagram.com/p/abc/', 'https://instagram.com/stories/abc/', 'https://instagram.com/p/../', 'https://127.0.0.1/p/abc/', 'https://instagram.com/p/abc/extra', 'https://instagram.com/p/a%2fb/']:
            with self.subTest(bad=bad): self.assertIsNone(canonical_url(bad))
        self.assertEqual(extract_urls('Смотри https://www.instagram.com/p/abc/?igsh=x и https://instagram.com/p/abc/'), ['https://www.instagram.com/p/abc/'])

class NetworkTests(unittest.TestCase):
    def test_dns_and_connections_fail_closed(self):
        import socket
        from instagram_network import resolve_public, allowed_host, public_ip
        self.assertTrue(allowed_host('scontent.cdninstagram.com'))
        self.assertFalse(allowed_host('cdninstagram.com.evil.org'))
        for ip in ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', '::ffff:127.0.0.1', '224.0.0.1']:
            self.assertFalse(public_ip(ip))
        record = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))
        def public(*a, **kw): return [record]
        self.assertEqual(resolve_public(public, 'www.instagram.com', 443), [record])
        for host, port in [('evil.com', 443), ('127.0.0.1', 443), ('www.instagram.com', 80)]:
            with self.assertRaises(ValueError): resolve_public(public, host, port)
        def mixed(*a, **kw): return [record, (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.1', 443))]
        with self.assertRaises(ValueError): resolve_public(mixed, 'www.instagram.com', 443)

class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_lifecycle_cache_scope_and_cleanup(self):
        import tempfile
        from pathlib import Path
        from instagram_download import DownloadService, DownloadError
        paths = []
        calls = []
        now = [0]
        async def runner(url, directory):
            calls.append(url)
            p = directory / '01.mp4'; p.write_bytes(b'\x00\x00\x00\x18ftypisom')
        async def send(items):
            paths.extend(p for p in items if isinstance(p, Path))
            return ['telegram-id']
        with tempfile.TemporaryDirectory() as base:
            service = DownloadService(Path(base), {-1001}, runner=runner, clock=lambda: now[0])
            url = 'https://www.instagram.com/reel/abc/'
            with self.assertRaises(DownloadError): await service.handle(-1002, url, send)
            self.assertFalse(calls)
            await service.handle(-1001, url, send)
            self.assertFalse(paths[0].exists())
            await service.handle(-1001, 'https://www.instagram.com/reel/next/', send)
            await service.handle(-1001, url, send)
            self.assertEqual(len(calls), 2)
            self.assertEqual(service.active, set())

    async def test_capacity_inflight_and_cancellation_cleanup(self):
        import asyncio
        import tempfile
        from pathlib import Path
        from instagram_download import DownloadService, DownloadError
        entered = asyncio.Event()
        directories = []
        async def runner(url, directory):
            directories.append(directory)
            entered.set()
            await asyncio.Event().wait()
        async def send(items): self.fail('cancelled job must not send')
        with tempfile.TemporaryDirectory() as base:
            service = DownloadService(Path(base), {-1, -2, -3}, runner=runner)
            first = asyncio.create_task(service.handle(-1, 'https://instagram.com/p/one/', send))
            await entered.wait(); entered.clear()
            with self.assertRaises(DownloadError): await service.handle(-2, 'https://instagram.com/p/one/', send)
            second = asyncio.create_task(service.handle(-2, 'https://instagram.com/p/two/', send))
            await entered.wait()
            third = asyncio.create_task(service.handle(-3, 'https://instagram.com/p/three/', send))
            await asyncio.sleep(.01)
            self.assertEqual(len(directories), 2)
            for task in [third, first, second]:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
            self.assertFalse(service.active)
            self.assertFalse(service.inflight)
            self.assertTrue(all(not p.exists() for p in directories))

    async def test_worker_cancel_kills_and_reaps_with_clean_environment(self):
        import asyncio
        from pathlib import Path
        from unittest.mock import AsyncMock, patch
        from instagram_download import DownloadService
        entered = asyncio.Event()
        class Process:
            returncode = None
            killed = False
            async def wait(self):
                if self.killed: return -9
                entered.set()
                await asyncio.Event().wait()
            def kill(self): self.killed = True; self.returncode = -9
        process = Process()
        factory = AsyncMock(return_value=process)
        with patch('instagram_download.asyncio.create_subprocess_exec', factory):
            task = asyncio.create_task(DownloadService(Path('/bot'), {-1}).run_worker('https://www.instagram.com/p/a/', Path('/tmp/test')))
            await entered.wait(); task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(process.killed)
        self.assertEqual(factory.call_args.kwargs['env'].keys(), {'PATH','HOME','TMPDIR','LANG'})
        self.assertNotIn('shell', factory.call_args.kwargs)
        self.assertIn('-I', factory.call_args.args)

    async def test_bad_media_and_send_failure_cleanup(self):
        import tempfile
        from pathlib import Path
        from instagram_download import DownloadService, DownloadError, validate_files
        directories = []
        async def runner(url, directory):
            directories.append(directory)
            (directory / '01.mp4').write_bytes(b'<html>not a video</html>')
        async def send(items): self.fail('invalid media must not send')
        with tempfile.TemporaryDirectory() as base:
            service = DownloadService(Path(base), {-1}, runner=runner)
            with self.assertRaises(DownloadError): await service.handle(-1, 'https://instagram.com/p/one/', send)
            self.assertFalse(directories[0].exists())
            self.assertFalse(service.cache)
            directory = Path(base)
            (directory / '01.mp4').symlink_to('/etc/hosts')
            with self.assertRaises(DownloadError): validate_files(directory)

class WorkerTests(unittest.TestCase):
    def test_worker_options_and_size_guard(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from instagram_worker import build_options, check_disk
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            options = build_options(directory)
            self.assertEqual(options['proxy'], '')
            self.assertEqual(options['format'], 'best[ext=mp4][protocol=https]')
            self.assertEqual(options['fixup'], 'never')
            self.assertFalse(options['cachedir'])
            (directory / '01.mp4.part').write_bytes(b'1234')
            with patch('instagram_worker.MAX_TOTAL', 3):
                with self.assertRaises(ValueError): check_disk(directory)

if __name__ == '__main__': unittest.main()
