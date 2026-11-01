"""Offline integration regressions; compatible with Python 3.8 unittest."""
import asyncio
import json
import shutil
import subprocess
import sys
from functools import partial
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.instagram_download import DownloadError, DownloadService
from services.youtube_video import YouTubeService


class BytecodeTests(unittest.TestCase):
    def test_isolated_worker_disables_bytecode_before_sibling_imports(self):
        services = Path(__file__).resolve().parents[1] / 'services'
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            for name in ('youtube_video_worker.py', 'youtube_video.py',
                         'instagram_download.py', 'instagram_diagnostics.py'):
                shutil.copyfile(str(services / name), str(directory / name))
            result = subprocess.run([sys.executable, '-I', '-c',
                                     'import runpy, sys; sys.dont_write_bytecode = False; '
                                     'runpy.run_path(sys.argv[1]); print(sys.dont_write_bytecode)',
                                     str(directory / 'youtube_video_worker.py')],
                                    cwd=str(directory), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    timeout=10, check=True, universal_newlines=True)
            self.assertFalse(list(directory.rglob('*.pyc')))
            self.assertEqual(result.stdout.strip(), 'True')


class GeometryTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'local media tools unavailable')
    async def test_actual_probe_geometry_manifest_send_watch_shorts_canonical_cache(self):
        from services import youtube_video_worker as worker
        sent, calls = [], []
        with tempfile.TemporaryDirectory() as raw:
            fixture = Path(raw) / 'fixture.mp4'
            await asyncio.get_running_loop().run_in_executor(None, partial(subprocess.run,
                           ['/usr/bin/ffmpeg', '-nostdin', '-v', 'fatal',
                            '-f', 'lavfi', '-i', 'color=c=black:s=240x320:r=25',
                            '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=mono',
                            '-t', '1', '-c:v', 'libx264', '-threads', '1', '-c:a', 'aac', str(fixture)],
                           check=True, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

            def download(fmt, target, used):
                shutil.copyfile(str(fixture), str(target))
                used[0] += target.stat().st_size

            async def runner(url, directory):
                calls.append((url, directory))
                fmt = dict(url='https://rr.googlevideo.com/videoplayback', protocol='https',
                           ext='mp4', vcodec='avc1', acodec='mp4a.40.2', filesize=fixture.stat().st_size,
                           width=1920, height=1080)
                with patch.object(worker, 'download_stream', side_effect=download):
                    dimensions = await asyncio.get_running_loop().run_in_executor(
                        None, worker.process_info, {'duration':1, 'formats':[fmt]}, directory)
                    self.assertEqual(dimensions, (240, 320))
                item = json.loads((directory / 'manifest.json').read_text())['items'][0]
                self.assertEqual((item.get('width'), item.get('height')), (240, 320))

            async def send(items):
                sent.append(items[0])
                return [(123, 'cached-video-id', 'video')]

            service = YouTubeService(raw, {-1}, runner=runner)
            await service.handle(-1, 'https://youtube.com/watch?v=2bZeMfMUhUc', send)
            await service.handle(-1, 'https://youtube.com/shorts/2bZeMfMUhUc', send)
            self.assertEqual(len(calls), 1)
            self.assertFalse(calls[0][1].exists())
            self.assertEqual([(item.width, item.height) for item in sent], [(240, 320), (240, 320)])
            self.assertEqual(sent[1].value, 'cached-video-id')
            self.assertEqual(list(service.cache), ['https://www.youtube.com/watch?v=2bZeMfMUhUc'])

    def test_manifest_dimensions_fail_closed(self):
        from services.youtube_video import validate_files
        bad = [{}, {'width':720}, {'height':1280}, {'width':None, 'height':1280}]
        for width, height in ((True, 1280), ('720', 1280), (720.0, 1280), (0, 1280),
                              (-720, 1280), (15, 16), (4097, 720), (4096, 4096),
                              (16, 4096), (720, []), ({}, 1280)):
            bad.append({'width':width, 'height':height})
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            (directory / 'video.mp4').write_bytes(b'\x00\x00\x00\x18ftypisom')
            for dims in bad:
                with self.subTest(dimensions=dims):
                    entry = dict(type='video', file='video.mp4', **dims)
                    (directory / 'manifest.json').write_text(json.dumps({'version':1, 'items':[entry]}))
                    with self.assertRaisesRegex(DownloadError, '^invalid_file$'):
                        validate_files(directory)
            (directory / 'manifest.json').unlink()
            self.assertIsNone(validate_files(directory)[0].width)  # Existing bare runner compatibility.


class BudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_youtube_worker_budget_leaves_send_inside_90_seconds(self):
        now, timeouts = [0], []
        real_wait_for = asyncio.wait_for

        async def observed_wait_for(awaitable, timeout):
            timeouts.append(timeout)
            return await real_wait_for(awaitable, timeout)

        async def runner(url, directory):
            now[0] += 70
            (directory / 'video.mp4').write_bytes(b'\x00\x00\x00\x18ftypisom')

        async def send(items):
            return ['file-id']

        with tempfile.TemporaryDirectory() as raw:
            service = YouTubeService(raw, {-1}, runner=runner, clock=lambda: now[0])
            with patch('services.instagram_download.asyncio.wait_for', side_effect=observed_wait_for):
                await service._execute(-1, 'https://www.youtube.com/watch?v=2bZeMfMUhUc', send, None)
        self.assertEqual(timeouts, [70, 20])

    async def test_youtube_one_timeout_attempt_legacy_three_28_second_attempts(self):
        real_wait_for = asyncio.wait_for
        for cls, attempts, budget in ((YouTubeService, 1, 70), (DownloadService, 3, 28)):
            with self.subTest(service=cls.__name__):
                calls, timeouts = [], []

                async def runner(url, directory):
                    calls.append(directory)
                    raise asyncio.TimeoutError()

                async def observed_wait_for(awaitable, timeout):
                    timeouts.append(timeout)
                    return await real_wait_for(awaitable, timeout)

                async def no_sleep(delay):
                    pass

                service = cls('/stage', {-1}, runner=runner, clock=lambda: 0)
                with patch('services.instagram_download.asyncio.wait_for', side_effect=observed_wait_for), \
                     patch('services.instagram_download.asyncio.sleep', side_effect=no_sleep):
                    with self.assertRaisesRegex(DownloadError, '^timeout$'):
                        await service._execute(-1, 'https://www.youtube.com/watch?v=2bZeMfMUhUc', None, None)
                self.assertEqual(len(calls), attempts)
                self.assertEqual(timeouts, [budget] * attempts)
                self.assertTrue(all(not directory.exists() for directory in calls))

    def test_worker_alarm_65_keeps_resource_limits(self):
        from services import youtube_video_worker as worker
        with patch.object(worker.signal, 'signal'), patch.object(worker.signal, 'alarm') as alarm, \
             patch.object(worker.resource, 'setrlimit') as limits:
            worker.apply_limits()
        alarm.assert_called_once_with(65)
        self.assertEqual(limits.call_count, 3)
        limits.assert_any_call(worker.resource.RLIMIT_FSIZE, (20_000_000, 20_000_000))
