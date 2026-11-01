import unittest
from pathlib import Path

class TikTokURLs(unittest.TestCase):
    def test_canonical_public_video_inputs(self):
        from services.tiktok_video import canonical_url
        cases = {
            'https://vm.tiktok.com/ZGdXNM57g/?foo=bar':'https://vm.tiktok.com/ZGdXNM57g/',
            'https://vt.tiktok.com/ABC123/':'https://vt.tiktok.com/ABC123/',
            'https://www.tiktok.com/@name/video/7698795265859341599?x=y':'https://www.tiktok.com/@name/video/7698795265859341599',
            'https://tiktok.com/@name/video/123':'https://www.tiktok.com/@name/video/123',
        }
        for raw,want in cases.items():
            self.assertEqual(canonical_url(raw),want)
        for raw in ('https://tiktok.com.evil/@x/video/123','https://user@tiktok.com/@x/video/123','https://tiktok.com:444/@x/video/123','file:///x','https://127.0.0.1/@x/video/123','https://www.tiktok.com/@x/photo/123','https://www.tiktok.com/@x/live','https://www.tiktok.com/@x/video/abc','https://www.tiktok.com/@x/video/123/evil',True,None):
            self.assertIsNone(canonical_url(raw))

class TikTokServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_isolated_worker_explicitly_disables_bytecode(self):
        from services.tiktok_video import TikTokService
        from unittest.mock import patch
        import tempfile
        class Process:
            pid=99999999
            async def wait(self):return 0
        with tempfile.TemporaryDirectory() as raw:
            svc=TikTokService(Path(raw),{1})
            with patch('services.youtube_video.asyncio.create_subprocess_exec',return_value=Process()) as spawn, patch('services.youtube_video.os.killpg'):
                await svc.run_worker('https://vm.tiktok.com/Test/',Path(raw))
            argv=spawn.call_args[0]
            self.assertIn('-I',argv);self.assertIn('-B',argv)

    async def test_service_validates_receipts_and_caches_and_cleans(self):
        from services.tiktok_video import TikTokService
        calls=[]; directories=[]
        async def runner(url,directory):
            calls.append(url); directories.append(directory)
            (directory/'video.mp4').write_bytes(b'\x00\x00\x00\x18ftypisom'+b'x'*128)
            (directory/'manifest.json').write_text('{"version":1,"coverage":"complete","items":[{"type":"video","file":"video.mp4","width":720,"height":1280}]}')
        with __import__('tempfile').TemporaryDirectory() as raw:
            svc=TikTokService(Path(raw),{1},runner=runner)
            async def send(items): return [(10,'file-id')]
            await svc.handle(1,'https://vm.tiktok.com/ABC/',send,message_id=1)
            await svc.handle(1,'https://vm.tiktok.com/ABC/?tracking=1',send,message_id=2)
            self.assertEqual(len(calls),1)
            self.assertTrue(all(not d.exists() for d in directories))
            async def uncertain(items):return True
            try: await svc.handle(1,'https://vm.tiktok.com/DEF/',uncertain,message_id=3)
            except Exception: pass
            self.assertTrue(all(not d.exists() for d in directories))
