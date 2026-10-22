"""Run with scratch/services then final/services on PYTHONPATH (Python >=3.8)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import instagram_diagnostics as diagnostics
from instagram_download import DownloadError, DownloadService


class PermanentDiagnosticsTests(unittest.TestCase):
    def test_exact_internal_tokens(self):
        for code in ('too_large', 'invalid_file'):
            with self.subTest(code=code):
                self.assertEqual(diagnostics.classify(DownloadError(code))['code'], code)
                self.assertEqual(diagnostics.classify(code)['code'], code)

    def test_provider_substrings_are_not_internal_tokens(self):
        for code in ('too_large', 'invalid_file'):
            for text in ('provider says ' + code, code + ' SECRET',
                         'https://example.test/?token=' + code, ' ' + code,
                         code + '\n', code.upper(), code + 'x' * 17000):
                with self.subTest(text=text[:80]):
                    value = diagnostics.classify(text)
                    self.assertEqual(value['code'], 'unknown')
                    self.assertNotIn('SECRET', json.dumps(value))
                    self.assertNotIn('https://', json.dumps(value))

    def test_safe_roundtrip_and_nested_errors(self):
        for code in ('too_large', 'invalid_file'):
            for nested in ('direct', 'exc_info', 'cause', 'nested_cause'):
                with self.subTest(code=code, nested=nested), tempfile.TemporaryDirectory() as raw:
                    directory = Path(raw)
                    diagnostic = diagnostics.Diagnostic(directory)
                    diagnostic.set_phase('media')
                    diagnostic.warning('cookie=SECRET https://u:p@host/?token=SECRET')
                    error = DownloadError(code)
                    if nested != 'direct':
                        wrapper = RuntimeError('cookie=SECRET https://host/?token=SECRET')
                        if nested == 'exc_info':
                            wrapper.exc_info = (DownloadError, error, None)
                        elif nested == 'cause':
                            wrapper.__cause__ = error
                        else:
                            cause = RuntimeError('SECRET')
                            cause.cause = error
                            wrapper.exc_info = (RuntimeError, cause, None)
                        error = wrapper
                    diagnostic.write(error)
                    text = diagnostics.read_diagnostic(directory)
                    value = json.loads(text)
                    self.assertEqual(value['code'], code)
                    self.assertEqual(value['phase'], 'media')
                    self.assertEqual(value['events'][0]['code'], 'unknown')
                    self.assertNotIn('SECRET', text)
                    self.assertNotIn('https://', text)
                    self.assertNotIn('SECRET', (directory / 'diagnostic.json').read_text())
                    safe = diagnostics.safe_record(dict(code=code, message='SECRET', extra='SECRET'))
                    self.assertEqual(safe['code'], code)
                    self.assertEqual(set(safe), {'code', 'message', 'phase', 'http_status', 'exception'})
                    self.assertNotIn('SECRET', json.dumps(safe))
        self.assertEqual(diagnostics.safe_record({'code': 'untrusted_SECRET'})['code'], 'unknown')


class ParentPermanentDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_run_worker_seam_never_retries_permanent_errors(self):
        class Process:
            returncode = 2

            async def wait(self):
                return 2

        for code in ('too_large', 'invalid_file'):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as raw:
                async def create(*args, **kwargs):
                    diagnostics.Diagnostic(Path(args[-1])).write(DownloadError(code))
                    return Process()

                service = DownloadService(raw, {-1})
                send = AsyncMock()
                with patch('instagram_download.asyncio.create_subprocess_exec', side_effect=create) as spawn, \
                        patch('instagram_download.asyncio.sleep', new_callable=AsyncMock) as sleep:
                    with self.assertRaisesRegex(DownloadError, '^' + code + '$'):
                        await service.handle(-1, 'https://instagram.com/p/abc/', send)
                self.assertEqual(spawn.call_count, 1)
                sleep.assert_not_awaited()
                send.assert_not_awaited()
                self.assertFalse(service.active)
                self.assertFalse(service.inflight)
                self.assertFalse(service.pending)


if __name__ == '__main__':
    unittest.main()
