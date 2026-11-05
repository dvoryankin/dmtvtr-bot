import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from instagram_download import DownloadService, DownloadError
from instagram_diagnostics import classify


class AuthFallbackTests(unittest.IsolatedAsyncioTestCase):
    def test_login_and_rate_limit_are_not_conflated(self):
        self.assertEqual(classify('login required')['code'], 'login_required')
        for text in ['login required: rate-limit', 'HTTP Error 429: login required']:
            self.assertEqual(classify(text)['code'], 'rate_limited')
        self.assertEqual(classify('age-restricted')['code'], 'login_required')
        self.assertEqual(classify('HTTP Error 403: login required')['code'], 'http_error')

    async def test_public_success_does_not_inspect_session(self):
        async def public(url, directory):
            (directory/'01.mp4').write_bytes(b'\0\0\0\x18ftypisom')
        service = DownloadService('/tmp', {-1}, runner=public)
        with patch('instagram_download.open_session') as opened:
            await service.handle(-1, 'https://instagram.com/p/abc/', AsyncMock(return_value=['id']))
        opened.assert_not_called()

    async def test_spawn_auth_fd_only_clean_env_cancel_kills(self):
        entered = asyncio.Event()
        class Process:
            returncode = None
            async def wait(self):
                if self.returncode is not None: return self.returncode
                entered.set(); await asyncio.Event().wait()
            def kill(self): self.returncode = -9
        process = Process()
        factory = AsyncMock(return_value=process)
        with patch('instagram_download.asyncio.create_subprocess_exec', factory):
            task = asyncio.create_task(DownloadService('/bot', {-1}).run_authenticated_worker(
                'https://www.instagram.com/p/abc/', Path('/tmp/attempt'), 123))
            await entered.wait(); task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(process.returncode, -9)
        args, kwargs = factory.call_args
        self.assertEqual(args[-2:], ('--auth-fd','123'))
        self.assertEqual(kwargs['pass_fds'], (123,))
        self.assertEqual(set(kwargs['env']), {'PATH','HOME','TMPDIR','LANG'})
        self.assertNotIn('session.cookies', str(factory.call_args))

    async def test_one_auth_after_login_fresh_directory_and_fd_closed(self):
        dirs = []
        async def public(url, directory):
            dirs.append(directory)
            (directory / 'old.part').write_bytes(b'partial')
            raise DownloadError('login_required')
        async def authenticated(url, directory, fd):
            self.assertFalse(dirs[0].exists())
            self.assertFalse(list(directory.iterdir()))
            dirs.append(directory)
            os.fstat(fd)
            (directory/'01.mp4').write_bytes(b'\0\0\0\x18ftypisom')
            (directory/'manifest.json').write_text(json.dumps({'version':1,'coverage':'complete',
                'items':[{'type':'video','file':'01.mp4'}]}))
        with tempfile.TemporaryDirectory() as raw:
            p = Path(raw)/'fixture'; p.write_bytes(b'fixture')
            fd = os.open(p, os.O_RDONLY)
            service = DownloadService(raw, {-1}, runner=public)
            service.run_authenticated_worker = AsyncMock(side_effect=authenticated)
            send = AsyncMock(return_value=['id'])
            with patch('instagram_download.open_session', return_value=fd, create=True):
                await service.handle(-1, 'https://instagram.com/p/abc/', send)
            self.assertEqual(service.run_authenticated_worker.await_count, 1)
            send.assert_awaited_once()
            with self.assertRaises(OSError): os.fstat(fd)
            self.assertTrue(all(not d.exists() for d in dirs))

    async def test_observed_empty_metadata_launches_one_auth_worker(self):
        from instagram_diagnostics import Diagnostic
        from test_instagram_diagnostics import NATIVE_EMPTY_RESPONSE
        class Process:
            returncode = 2
            async def wait(self): return 2
        async def create(*args, **kwargs):
            diagnostic = Diagnostic(Path(args[-1])); diagnostic.set_phase('metadata')
            diagnostic.warning('No CSRF token set by Instagram API')
            text = 'ERROR: [Instagram] DeulWNPIVnO: ' + NATIVE_EMPTY_RESPONSE
            diagnostic.error(text); diagnostic.write(DownloadError(text))
            return Process()
        async def auth(url, directory, fd):
            (directory / '01.mp4').write_bytes(b'\0\0\0\x18ftypisom')
            (directory / 'manifest.json').write_text(json.dumps({
                'version': 1, 'coverage': 'complete',
                'items': [{'type': 'video', 'file': '01.mp4'}]}))
        with tempfile.TemporaryDirectory() as raw:
            fixture = Path(raw) / 'fixture'; fixture.write_bytes(b'fixture')
            fd = os.open(fixture, os.O_RDONLY)
            service = DownloadService(raw, {-1})
            service.run_authenticated_worker = AsyncMock(side_effect=auth)
            factory = AsyncMock(side_effect=create)
            try:
                with patch('instagram_download.asyncio.create_subprocess_exec', factory), \
                        patch('instagram_download.open_session', return_value=fd), \
                        patch('instagram_download.asyncio.sleep', new=AsyncMock()):
                    try:
                        await service.handle(-1, 'https://instagram.com/p/DeulWNPIVnO/', AsyncMock(return_value=['id']))
                    except DownloadError as exc:
                        self.fail('clean observed metadata must reach optional auth, got %s' % exc)
                self.assertEqual(factory.await_count, 1)
                service.run_authenticated_worker.assert_awaited_once()
                with self.assertRaises(OSError): os.fstat(fd)
            finally:
                try: os.close(fd)
                except OSError: pass

    async def test_login_on_last_public_attempt_cannot_launch_fourth_worker(self):
        public = AsyncMock(side_effect=[DownloadError('unavailable'),
                                       DownloadError('unavailable'), DownloadError('login_required')])
        service = DownloadService('/tmp', {-1}, runner=public)
        service.run_authenticated_worker = AsyncMock(side_effect=DownloadError('session_invalid'))
        with tempfile.TemporaryFile() as fixture:
            with patch('instagram_download.open_session', side_effect=lambda: os.dup(fixture.fileno())) as opened, \
                    patch('instagram_download.asyncio.sleep', new=AsyncMock()):
                with self.assertRaises(DownloadError):
                    await service.handle(-1, 'https://instagram.com/p/abc/', AsyncMock())
            self.assertEqual(public.await_count + service.run_authenticated_worker.await_count, 3)
            opened.assert_not_called()

    async def test_missing_optional_session_keeps_three_anonymous_attempts(self):
        public = AsyncMock(side_effect=DownloadError('empty_media', auth_eligible=True))
        service = DownloadService('/tmp', {-1}, runner=public)
        service.run_authenticated_worker = AsyncMock()
        with patch('instagram_download.open_session', return_value=None) as opened, \
                patch('instagram_download.asyncio.sleep', new=AsyncMock()):
            with self.assertRaisesRegex(DownloadError, '^empty_media$'):
                await service.handle(-1, 'https://instagram.com/p/abc/', AsyncMock())
        self.assertEqual(public.await_count, 3)
        opened.assert_called_once()
        service.run_authenticated_worker.assert_not_awaited()

    async def test_poisoned_diagnostic_never_opens_session(self):
        class Process:
            returncode = 2
            async def wait(self): return 2
        for final in ('empty_media', 'login_required'):
            for code, status in [('http_error', 403), ('http_error', 429),
                                 ('api_denied', None), ('unknown', None),
                                 ('rate_limited', None), ('challenge_required', None),
                                 ('timeout', None), ('dns_denied', None), ('host_denied', None),
                                 ('connect_denied', None)]:
                with self.subTest(final=final, poison=code, status=status):
                    async def create(*args, **kwargs):
                        Path(args[-1], 'diagnostic.json').write_text(json.dumps({
                            'code': final, 'phase': 'metadata', 'http_status': None,
                            'exception': 'DownloadError', 'events': [
                                {'code': code, 'phase': 'metadata', 'http_status': status, 'exception': 'none'},
                                {'code': final, 'phase': 'metadata', 'http_status': None, 'exception': 'none'}]}))
                        return Process()
                    service = DownloadService('/tmp', {-1})
                    service.run_authenticated_worker = AsyncMock()
                    with patch('instagram_download.asyncio.create_subprocess_exec', side_effect=create), \
                            patch('instagram_download.open_session') as opened, \
                            patch('instagram_download.asyncio.sleep', new=AsyncMock()):
                        with self.assertRaises(DownloadError):
                            await service.handle(-1, 'https://instagram.com/p/abc/', AsyncMock())
                    opened.assert_not_called()
                    service.run_authenticated_worker.assert_not_awaited()

    async def test_generic_empty_runner_keeps_anonymous_retries(self):
        public = AsyncMock(side_effect=DownloadError('empty_media'))
        service = DownloadService('/tmp', {-1}, runner=public)
        with patch('instagram_download.open_session') as opened, \
                patch('instagram_download.asyncio.sleep', new=AsyncMock()):
            with self.assertRaisesRegex(DownloadError, '^empty_media$'):
                await service.handle(-1, 'https://instagram.com/p/abc/', AsyncMock())
        self.assertEqual(public.await_count, 3)
        opened.assert_not_called()

    async def test_prior_unknown_attempt_vetoes_later_clean_login(self):
        public = AsyncMock(side_effect=[DownloadError('unavailable', auth_eligible=False),
                                       DownloadError('login_required')])
        service = DownloadService('/tmp', {-1}, runner=public)
        service.run_authenticated_worker = AsyncMock(side_effect=DownloadError('session_invalid'))
        with tempfile.TemporaryFile() as fixture:
            with patch('instagram_download.open_session', side_effect=lambda: os.dup(fixture.fileno())) as opened, \
                    patch('instagram_download.asyncio.sleep', new=AsyncMock()):
                with self.assertRaises(DownloadError):
                    await service.handle(-1, 'https://instagram.com/p/abc/', AsyncMock())
            opened.assert_not_called()
            service.run_authenticated_worker.assert_not_awaited()

    async def test_auth_uses_remaining_absolute_deadline_and_never_sends_after_it(self):
        clock = [0]
        timeouts = []
        wait_for = asyncio.wait_for
        async def bounded(operation, timeout):
            timeouts.append(timeout)
            return await wait_for(operation, timeout)
        async def public(url, directory):
            clock[0] = 80
            raise DownloadError('login_required')
        async def auth(url, directory, fd):
            clock[0] = 91
            (directory / '01.mp4').write_bytes(b'\0\0\0\x18ftypisom')
            (directory / 'manifest.json').write_text(json.dumps({
                'version': 1, 'coverage': 'complete',
                'items': [{'type': 'video', 'file': '01.mp4'}]}))
        service = DownloadService('/tmp', {-1}, runner=public, clock=lambda: clock[0])
        service.run_authenticated_worker = AsyncMock(side_effect=auth)
        send = AsyncMock()
        with tempfile.TemporaryFile() as fixture:
            with patch('instagram_download.open_session', side_effect=lambda: os.dup(fixture.fileno())), \
                    patch('instagram_download.asyncio.wait_for', side_effect=bounded):
                with self.assertRaisesRegex(DownloadError, '^timeout$'):
                    await service.handle(-1, 'https://instagram.com/p/abc/', send)
        self.assertEqual(timeouts[-2:], [28, 10])
        service.run_authenticated_worker.assert_awaited_once()
        send.assert_not_awaited()

    async def test_auth_incomplete_inventory_cannot_send_or_retry(self):
        public = AsyncMock(side_effect=DownloadError('login_required'))
        async def auth(url, directory, fd):
            (directory / '01.mp4').write_bytes(b'\0\0\0\x18ftypisom')
        service = DownloadService('/tmp', {-1}, runner=public)
        service.run_authenticated_worker = AsyncMock(side_effect=auth)
        send = AsyncMock()
        with tempfile.TemporaryFile() as fixture:
            with patch('instagram_download.open_session', side_effect=lambda: os.dup(fixture.fileno())):
                with self.assertRaisesRegex(DownloadError, '^inventory_incomplete$'):
                    await service.handle(-1, 'https://instagram.com/p/abc/', send)
        self.assertEqual(public.await_count, 1)
        service.run_authenticated_worker.assert_awaited_once()
        send.assert_not_awaited()

    async def test_other_provider_login_never_opens_instagram_session(self):
        public = AsyncMock(side_effect=DownloadError('login_required'))
        service = DownloadService('/tmp', {-1}, runner=public, canonicalizer=lambda url: url)
        with patch('instagram_download.open_session') as opened:
            with self.assertRaisesRegex(DownloadError, '^login_required$'):
                await service.handle(-1, 'https://example.invalid/item', AsyncMock())
        opened.assert_not_called()
        self.assertEqual(public.await_count, 1)

    async def test_non_login_never_opens_session(self):
        for reason in ['rate_limited', 'http_error', 'dns_denied', 'challenge_required', 'session_invalid']:
            service = DownloadService('/tmp', {-1}, runner=AsyncMock(side_effect=DownloadError(reason)))
            with patch('instagram_download.open_session', create=True) as opened:
                with self.assertRaises(DownloadError):
                    await service.handle(-1, 'https://instagram.com/p/abc/', AsyncMock())
                opened.assert_not_called()

    async def test_auth_failure_no_retry_and_cancel_closes_fd(self):
        for reason in ['unavailable', 'login_required', 'cancel']:
            with tempfile.TemporaryDirectory() as raw:
                p = Path(raw)/'fixture'; p.write_bytes(b'fixture'); fd = os.open(p, os.O_RDONLY)
                public = AsyncMock(side_effect=DownloadError('login_required'))
                auth = AsyncMock(side_effect=asyncio.CancelledError() if reason == 'cancel' else DownloadError(reason))
                service = DownloadService(raw, {-1}, runner=public); service.run_authenticated_worker = auth
                send = AsyncMock()
                with patch('instagram_download.open_session', return_value=fd, create=True):
                    with self.assertRaises(asyncio.CancelledError if reason == 'cancel' else DownloadError):
                        await service.handle(-1, 'https://instagram.com/p/abc/', send)
                self.assertEqual(auth.await_count, 1)
                self.assertEqual(public.await_count, 1)
                send.assert_not_awaited()
                with self.assertRaises(OSError): os.fstat(fd)
