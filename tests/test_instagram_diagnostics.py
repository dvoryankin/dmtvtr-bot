import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from instagram_download import DownloadService, DownloadError

class DiagnosticsTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_classifier_keeps_http_and_guard_evidence_not_payload(self):
        import instagram_diagnostics as d
        for raw,code,status in [
            ('HTTP Error 429: Too Many Requests cookie=SECRET', 'http_error',429),
            ('Non-public DNS answer denied https://u:p@x/?token=SECRET','dns_denied',None),
            ('Requested content is not available, rate-limit reached or login required','login_or_rate_limit',None)]:
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
            self.assertEqual(value['events'][0]['code'], 'csrf_missing')
            self.assertEqual(value['http_status'], 403)
            self.assertNotIn('PRIVATE', text)
            self.assertLess(len(text), 4096)
            self.assertEqual(__import__('instagram_diagnostics').classify('Instagram sent an empty media response')['code'], 'empty_media')
