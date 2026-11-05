import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from instagram_download import DownloadService, DownloadError

NATIVE_EMPTY_RESPONSE = (
    'Instagram sent an empty media response. Check if this post is accessible in your '
    'browser without being logged-in. If it is not, then use --cookies-from-browser or '
    '--cookies for the authentication. See  https://github.com/yt-dlp/yt-dlp/wiki/'
    'FAQ#how-do-i-pass-cookies-to-yt-dlp  for how to manually pass cookies. '
    'Otherwise, if the post is accessible in browser without being logged-in, '
    'please report this issue on  https://github.com/yt-dlp/yt-dlp/issues?q= , '
    'filling out the appropriate issue template. Confirm you are on the latest '
    'version using  yt-dlp -U'
)

class DiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def _assert_serialized_failure_never_opens_session(self, error, warning=None):
        from instagram_diagnostics import Diagnostic
        class Process:
            returncode = 2
            async def wait(self): return 2
        async def create(*args, **kwargs):
            diagnostic = Diagnostic(Path(args[-1])); diagnostic.set_phase('metadata')
            if warning is not None: diagnostic.warning(warning)
            diagnostic.write(error)
            return Process()
        with tempfile.TemporaryDirectory() as raw:
            service = DownloadService(Path(raw), {-1}); send = AsyncMock()
            with patch('instagram_download.asyncio.create_subprocess_exec', side_effect=create), \
                 patch('instagram_download.open_session', return_value=None) as session, \
                 patch.object(service, 'run_authenticated_worker', new_callable=AsyncMock) as auth, \
                 patch('instagram_download.asyncio.sleep', new_callable=AsyncMock), \
                 patch('socket.socket.connect', side_effect=AssertionError('network forbidden')):
                with self.assertRaises(DownloadError):
                    await service.handle(-1, 'https://www.instagram.com/p/B7/', send)
                session.assert_not_called(); auth.assert_not_called(); send.assert_not_called()

    async def test_deep_context_cycle_and_overflow_are_auth_vetoes(self):
        for mode in ('deep-unsafe', 'context', 'cycle', 'overflow', 'deep-unknown'):
            with self.subTest(mode=mode):
                error = DownloadError(NATIVE_EMPTY_RESPONSE)
                if mode == 'context':
                    error.__context__ = ValueError('Non-public DNS answer denied')
                elif mode == 'cycle':
                    error.__cause__ = error
                else:
                    current = error
                    for _ in range(33 if mode == 'overflow' else 2):
                        current.__cause__ = DownloadError(NATIVE_EMPTY_RESPONSE)
                        current = current.__cause__
                    if mode != 'overflow':
                        current.__cause__ = ValueError('Non-public DNS answer denied' if mode == 'deep-unsafe' else 'foreign failure')
                await self._assert_serialized_failure_never_opens_session(error)

        # A shared cause/context alias is not a cycle and must retain clean auth.
        from instagram_diagnostics import Diagnostic, read_diagnostic
        error = DownloadError(NATIVE_EMPTY_RESPONSE)
        child = DownloadError(NATIVE_EMPTY_RESPONSE)
        error.__cause__ = child; error.__context__ = child
        with tempfile.TemporaryDirectory() as raw:
            diagnostic = Diagnostic(Path(raw)); diagnostic.set_phase('metadata')
            diagnostic.write(error)
            self.assertTrue(json.loads(read_diagnostic(Path(raw)))['auth_eligible'])

    async def test_mixed_csrf_warning_cannot_hide_unknown_or_unsafe_evidence(self):
        for warning in ('No CSRF token set; foreign ambiguous failure',
                        'No CSRF token set by Instagram API; foreign ambiguous failure',
                        'foreign ambiguous failure; No CSRF token set by Instagram API',
                        'No CSRF token set by Instagram API; Non-public DNS answer denied',
                        'No CSRF token set by Instagram API; operation timed out'):
            with self.subTest(warning=warning):
                await self._assert_serialized_failure_never_opens_session(DownloadError(NATIVE_EMPTY_RESPONSE), warning)

    async def test_native_ytdlp_long_empty_response_is_exact_not_substring(self):
        from instagram_diagnostics import Diagnostic, read_diagnostic
        for extra, expected in [('', True), ('; foreign ambiguous failure', False),
                                ('; Non-public DNS answer denied', False),
                                ('; operation timed out', False), ('; HTTP Error 429', False)]:
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as raw:
                diagnostic = Diagnostic(Path(raw)); diagnostic.set_phase('metadata')
                text = NATIVE_EMPTY_RESPONSE + extra
                diagnostic.warning('No CSRF token set by Instagram API')
                diagnostic.error('ERROR: [Instagram] DeulWNPIVnO: ' + text)
                diagnostic.write(DownloadError('ERROR: [Instagram] DeulWNPIVnO: ' + text))
                result = json.loads(read_diagnostic(Path(raw)))
                self.assertIs(result['auth_eligible'], expected)
                self.assertNotIn('https://', json.dumps(result))

    async def test_parent_logs_bounded_worker_diagnostic_with_message_id(self):
        class Process:
            returncode = 2
            async def wait(self): return 2
        with tempfile.TemporaryDirectory() as raw:
            async def create(*args, **kwargs):
                Path(args[-1], 'diagnostic.json').write_text(json.dumps({
                    'phase':'metadata', 'code':'http_error', 'http_status':429,
                    'exception':'DownloadError', 'message':'cookie=SECRET https://user:password@host/?signature=SECRET',
                    'events':[]}))
                return Process()
            service = DownloadService(Path(raw), {-1})
            with patch('instagram_download.asyncio.create_subprocess_exec', side_effect=create):
                with self.assertLogs(level='INFO') as logs:
                    with self.assertRaises(DownloadError):
                        await service.handle(-1, 'https://instagram.com/reel/Dd_us59i9DF/?igsh=SECRET', AsyncMock(), message_id=123)
            text = ' '.join(logs.output)
            for value in ['Dd_us59i9DF','123','429','metadata','elapsed','returncode=2']:
                self.assertIn(value,text)
            for value in ['SECRET','password','cookie','signature','https://']:
                self.assertNotIn(value,text)

    async def test_mixed_single_messages_and_nested_causes_veto_auth_in_real_service(self):
        from instagram_diagnostics import Diagnostic, read_diagnostic
        eligible = 'Instagram sent an empty media response'
        unsafe = [('Non-public DNS answer denied', 'dns_denied'),
                  ('Outbound host/port denied', 'host_denied'),
                  ('Non-public connection denied', 'connect_denied'),
                  ('operation timed out', 'timeout'), ('HTTP Error 500', 'http_error'),
                  ('HTTP Error 403', 'http_error'), ('HTTP Error 429', 'rate_limited'),
                  ('challenge_required', 'challenge_required'),
                  ('Connection reset by peer', 'unknown'), ('foreign ambiguous failure', 'unknown')]
        class Process:
            returncode = 2
            async def wait(self): return 2
        for marker, expected in unsafe:
            for mode in ('forward', 'reverse', 'outer-unsafe', 'inner-unsafe', 'exc-info'):
                with self.subTest(marker=marker, mode=mode), tempfile.TemporaryDirectory() as raw:
                    if mode in ('forward', 'reverse'):
                        parts = [eligible, marker] if mode == 'forward' else [marker, eligible]
                        error = DownloadError('; '.join(parts))
                    else:
                        error = DownloadError(marker if mode == 'outer-unsafe' else eligible)
                        error.__cause__ = DownloadError(eligible if mode == 'outer-unsafe' else marker)
                        if mode == 'exc-info':
                            error.exc_info = (DownloadError, error.__cause__, None)
                            error.__cause__ = None
                    async def create(*args, **kwargs):
                        diagnostic = Diagnostic(Path(args[-1]))
                        diagnostic.set_phase('metadata')
                        diagnostic.write(error)
                        value = json.loads(read_diagnostic(Path(args[-1])))
                        self.assertEqual(value['code'], expected)
                        self.assertFalse(value['auth_eligible'])
                        return Process()
                    service = DownloadService(Path(raw), {-1})
                    send = AsyncMock()
                    with patch('instagram_download.asyncio.create_subprocess_exec', side_effect=create) as spawn, \
                         patch('instagram_download.open_session') as session, \
                         patch.object(service, 'run_authenticated_worker', new_callable=AsyncMock) as auth, \
                         patch('instagram_download.asyncio.sleep', new_callable=AsyncMock), \
                         patch('socket.socket.connect', side_effect=AssertionError('network forbidden')) as network:
                        with self.assertRaises(DownloadError):
                            await service.handle(-1, 'https://www.instagram.com/p/B7/', send)
                        self.assertGreaterEqual(spawn.call_count, 1)
                        self.assertLessEqual(spawn.call_count, 3)
                        session.assert_not_called(); auth.assert_not_called(); send.assert_not_called()
                        network.assert_not_called()

    async def test_login_and_exact_ytdlp_empty_message_auth_contract(self):
        from instagram_diagnostics import Diagnostic, read_diagnostic
        for text, expected in [
            ('ERROR: [Instagram] B7: Instagram sent an empty media response', True),
            ('login required', True),
            ('login required; Non-public DNS answer denied', False),
            ('operation timed out; login required', False),
            ('login required; foreign ambiguous failure', False),
            ('Instagram API is not granting access', False),
            ('', False)]:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as raw:
                diagnostic = Diagnostic(Path(raw)); diagnostic.set_phase('metadata')
                diagnostic.write(DownloadError(text))
                self.assertIs(json.loads(read_diagnostic(Path(raw)))['auth_eligible'], expected)

    async def test_truncated_warning_history_cannot_erase_auth_veto(self):
        from instagram_diagnostics import Diagnostic, read_diagnostic
        with tempfile.TemporaryDirectory() as raw:
            diagnostic = Diagnostic(Path(raw))
            diagnostic.set_phase('metadata')
            diagnostic.warning('HTTP Error 403: forbidden')
            for _ in range(9):
                diagnostic.warning('Instagram sent an empty media response')
            diagnostic.write(DownloadError('Instagram sent an empty media response'))
            value = json.loads(read_diagnostic(Path(raw)))
            self.assertFalse(value['auth_eligible'])
            self.assertLessEqual(len(value['events']), 8)

    async def test_auth_eligibility_rejects_malformed_or_nonmetadata_evidence(self):
        from instagram_diagnostics import read_diagnostic
        clean = {'code': 'login_required', 'phase': 'metadata', 'http_status': None,
                 'exception': 'DownloadError', 'events': []}
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw)
            for changes, expected in [({}, True), ({'code': 'empty_media'}, True),
                                      ({'code': 'unavailable'}, False),
                                      ({'phase': 'media'}, False),
                                      ({'http_status': '403'}, False),
                                      ({'http_status': 403}, False),
                                      ({'exception': 'OSError'}, False),
                                      ({'events': None}, False),
                                      ({'events': [{}]}, False),
                                      ({'events_truncated': True}, False)]:
                with self.subTest(changes=changes):
                    (path / 'diagnostic.json').write_text(json.dumps(dict(clean, **changes)))
                    self.assertIs(json.loads(read_diagnostic(path))['auth_eligible'], expected)

    async def test_classifier_keeps_http_and_guard_evidence_not_payload(self):
        import instagram_diagnostics as d
        for raw,code,status in [
            ('HTTP Error 429: Too Many Requests cookie=SECRET', 'rate_limited',429),
            ('Non-public DNS answer denied https://u:p@x/?token=SECRET','dns_denied',None),
            ('Requested content is not available, rate-limit reached or login required','rate_limited',None)]:
            result=d.classify(raw)
            self.assertEqual(result['code'],code)
            self.assertEqual(result['http_status'],status)
            self.assertNotIn('SECRET',json.dumps(result))
        self.assertEqual(d.classify('arbitrary secret')['code'],'unknown')

    async def test_worker_warning_and_nested_http_are_persisted_safely(self):
        from instagram_diagnostics import Diagnostic, read_diagnostic
        with tempfile.TemporaryDirectory() as raw:
            diagnostic = Diagnostic(Path(raw))
            diagnostic.set_phase('metadata')
            diagnostic.warning('No CSRF token set by Instagram API secret=PRIVATE')
            error = RuntimeError('secret=PRIVATE')
            error.exc_info = (ValueError, ValueError('HTTP Error 403: https://x/?sig=PRIVATE'), None)
            diagnostic.write(error)
            text = read_diagnostic(Path(raw))
            value = json.loads(text)
            self.assertEqual(value['events'][0]['code'], 'unknown')
            self.assertEqual(value['http_status'], 403)
            self.assertNotIn('PRIVATE', text)
            self.assertLess(len(text), 4096)
            self.assertEqual(__import__('instagram_diagnostics').classify('Instagram sent an empty media response')['code'], 'empty_media')
