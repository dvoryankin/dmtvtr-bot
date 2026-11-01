"""Offline bounded mux-overflow regressions (Python 3.8 syntax)."""
import json
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from services import youtube_video_worker as w


def formats(count=4):
    return [dict(url='https://rr.googlevideo.com/videoplayback?id=%d' % i,
                 protocol='https', ext='mp4', vcodec='avc1', acodec='mp4a.40.2',
                 filesize=20_000_000 - i * 1_000_000, width=1920 - i * 320,
                 height=1080 - i * 180, fps=30) for i in range(count)]


class RankingTests(unittest.TestCase):
    def test_ranked_distinct_lower_quality_known_fit_max_three(self):
        candidates = formats(5)
        alias = dict(candidates[0], width=2000, height=1200)
        unknown = dict(candidates[1], filesize=None)
        huge = dict(candidates[1], filesize=w.MAX_FILE + 1, height=2160)
        plans = w.ranked_candidates([unknown, huge, candidates[0], alias] + candidates)
        self.assertEqual(len(plans), 3)
        self.assertEqual([p[0]['url'] for p in plans], [p['url'] for p in candidates[:3]])
        self.assertEqual(plans[0], w.choose_formats([unknown, huge, candidates[0], alias] + candidates))
        self.assertTrue(all(sum(f['filesize'] for f in p) <= w.MAX_FILE for p in plans))

    def test_alternate_audio_does_not_use_up_lower_video_budget(self):
        videos = [dict(v, acodec='none', filesize=v['filesize'] - 1_000_000) for v in formats()]
        audios = [dict(url='https://rr.googlevideo.com/videoplayback?audio=%d' % rate,
                       protocol='https', ext='m4a', vcodec='none', acodec='mp4a.40.2',
                       filesize=1_000_000, abr=rate) for rate in (128, 96, 64)]
        plans = w.ranked_candidates(videos + audios)
        self.assertEqual([p[0] for p in plans], videos[:3])
        self.assertEqual([p[1]['abr'] for p in plans], [128, 128, 128])


class OverflowClassificationTests(unittest.TestCase):
    def test_code1_at_cap_aborts_actual_scheduler_without_fallback(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            downloads = []
            def download(fmt, target, used):
                downloads.append(fmt['url'])
                target.write_bytes(b'input')
                used[0] += 5
            def run(command, **kwargs):
                self.assertIs(kwargs['stderr'], subprocess.DEVNULL)
                with Path(command[-1]).open('wb') as sink:
                    sink.truncate(w.MAX_FILE)
                raise subprocess.CalledProcessError(1, command)
            with patch.object(w, 'download_stream', side_effect=download), \
                 patch.object(w.subprocess, 'run', side_effect=run) as tool, \
                 patch.object(w, 'probe_file') as probe:
                with self.assertRaises(subprocess.CalledProcessError) as caught:
                    w.process_info({'duration':1, 'formats':formats()}, directory)
            self.assertEqual(caught.exception.returncode, 1)
            self.assertEqual(downloads, [formats()[0]['url']])
            tool.assert_called_once()
            probe.assert_not_called()
            self.assertEqual(list(directory.iterdir()), [])

    def test_mux_fsize_failure_requires_positive_overflow(self):
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / 'video.mp4'
            for size, code, expected in ((w.MAX_FILE, 1, None),
                                          (w.MAX_FILE + 1, 1, 'too_large'),
                                          (w.MAX_FILE, -signal.SIGXFSZ, 'too_large'),
                                          (12, -signal.SIGXFSZ, 'too_large'),
                                          (w.MAX_FILE, -signal.SIGKILL, None),
                                          (w.MAX_FILE, -signal.SIGSEGV, None),
                                          (12, 1, None), (w.MAX_FILE - 1, 1, None),
                                          (w.MAX_FILE, -signal.SIGTERM, None),
                                          (w.MAX_FILE, -signal.SIGXCPU, None),
                                          (w.MAX_FILE, 2, None)):
                with self.subTest(size=size, code=code):
                    def run(command, **kwargs):
                        with output.open('wb') as sink:
                            sink.truncate(size)
                        raise subprocess.CalledProcessError(code, command)
                    with patch.object(w.subprocess, 'run', side_effect=run):
                        error = w.WorkerError if expected else subprocess.CalledProcessError
                        with self.assertRaises(error) as caught:
                            w.mux((Path(raw) / 'input.mp4',), output)
                        if expected:
                            self.assertEqual(str(caught.exception), expected)

    def test_probe_actual_oversize_classifies_without_launching_tool(self):
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / 'video.mp4'
            with output.open('wb') as sink:
                sink.truncate(w.MAX_FILE + 1)
            with patch.object(w.subprocess, 'run') as run:
                with self.assertRaisesRegex(w.WorkerError, '^too_large$'):
                    w.probe_file(output)
            run.assert_not_called()

    def test_successful_mux_tiny_invalid_output_is_not_overflow(self):
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / 'video.mp4'
            output.write_bytes(b'bad')
            with patch.object(w.subprocess, 'run'):
                with self.assertRaisesRegex(w.WorkerError, '^invalid_file$'):
                    w.mux((Path(raw) / 'input.mp4',), output)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'local tools unavailable')
class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = self.root / 'fixture.mp4'
        subprocess.run(['/usr/bin/ffmpeg', '-nostdin', '-v', 'fatal',
                        '-f', 'lavfi', '-i', 'color=c=black:s=240x320:r=25',
                        '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=mono',
                        '-t', '1', '-c:v', 'libx264', '-threads', '1', '-c:a', 'aac',
                        str(self.fixture)], check=True, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.directory = self.root / 'work'
        self.directory.mkdir()
        self.downloads = []

    def download(self, fmt, target, used):
        if not self.downloads or self.downloads[-1] != fmt['url']:
            self.assertFalse((self.directory / 'video.mp4').exists())
            self.assertFalse((self.directory / 'manifest.json').exists())
            self.assertEqual(list(self.directory.rglob('input*')), [])
        self.downloads.append(fmt['url'])
        shutil.copyfile(str(self.fixture), str(target))
        used[0] += target.stat().st_size
        self.assertLessEqual(used[0], w.MAX_FILE)

    def test_three_overflows_exhaust_without_fourth_or_disk_accumulation(self):
        def mux(inputs, output):
            with output.open('wb') as sink:
                sink.truncate(w.MAX_FILE + 1)
            raise w.WorkerError('too_large')
        with patch.object(w, 'download_stream', side_effect=self.download), \
             patch.object(w, 'mux', side_effect=mux) as mux_call:
            with self.assertRaisesRegex(w.WorkerError, '^too_large$'):
                w.process_info({'duration':1, 'formats':formats(5)}, self.directory)
        self.assertEqual(mux_call.call_count, 3)
        self.assertEqual(self.downloads, [f['url'] for f in formats(5)[:3]])
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_nonoverflow_errors_never_fall_through(self):
        errors = [w.WorkerError('invalid_file'), w.WorkerError('network_denied'),
                  w.WorkerError('timeout'), w.WorkerError('youtube_unavailable'),
                  subprocess.TimeoutExpired('ffmpeg', 10),
                  subprocess.CalledProcessError(1, ['ffmpeg'])]
        from urllib.error import HTTPError
        errors.append(HTTPError('https://rr.googlevideo.com/videoplayback', 403, '', {}, None))
        for stage in ('download_stream', 'mux', 'probe_file'):
            for error in errors + ([w.WorkerError('too_large')] if stage == 'download_stream' else []):
                with self.subTest(stage=stage, error=type(error).__name__, code=str(error)):
                    self.downloads = []
                    real_mux = w.mux
                    with patch.object(w, 'download_stream', side_effect=self.download) as download, \
                         patch.object(w, 'mux', wraps=real_mux) as mux_call, \
                         patch.object(w, stage, side_effect=error) as failure:
                        with self.assertRaises(type(error)):
                            w.process_info({'duration':1, 'formats':formats()}, self.directory)
                    self.assertEqual(failure.call_count, 1)
                    self.assertLessEqual(download.call_count, 1)
                    self.assertLessEqual(mux_call.call_count, 1)
                    self.assertEqual(list(self.directory.iterdir()), [])

    def test_timeout_during_overflow_cleanup_never_starts_next_candidate(self):
        real_tempdir = tempfile.TemporaryDirectory
        class TimeoutOnExit:
            def __init__(self, *args, **kwargs):
                self.inner = real_tempdir(*args, **kwargs)
            def __enter__(self):
                return self.inner.__enter__()
            def __exit__(self, *args):
                self.inner.__exit__(*args)
                raise w.WorkerError('timeout')
        with patch.object(w, 'download_stream', side_effect=self.download), \
             patch.object(w, 'mux', side_effect=w.WorkerError('too_large')) as mux_call, \
             patch.object(w.tempfile, 'TemporaryDirectory', TimeoutOnExit):
            with self.assertRaisesRegex(w.WorkerError, '^timeout$'):
                w.process_info({'duration':1, 'formats':formats()}, self.directory)
        self.assertEqual(mux_call.call_count, 1)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_probe_overflow_also_falls_back(self):
        real_probe = w.probe_file
        count = [0]
        def probe(path):
            count[0] += 1
            if count[0] == 1:
                with path.open('wb') as sink:
                    sink.truncate(w.MAX_FILE + 1)
            return real_probe(path)
        with patch.object(w, 'download_stream', side_effect=self.download), \
             patch.object(w, 'probe_file', side_effect=probe):
            self.assertEqual(w.process_info({'duration':1, 'formats':formats()}, self.directory), (240, 320))
        self.assertEqual(count[0], 2)

    def test_exact_final_cap_accepted_without_quality_fallback(self):
        real_mux = w.mux
        def mux(inputs, output):
            real_mux(inputs, output)
            with output.open('ab') as sink:
                sink.truncate(w.MAX_FILE)
        with patch.object(w, 'download_stream', side_effect=self.download), \
             patch.object(w, 'mux', side_effect=mux):
            self.assertEqual(w.process_info({'duration':1, 'formats':formats()}, self.directory), (240, 320))
        self.assertEqual(len(self.downloads), 1)
        self.assertEqual((self.directory / 'video.mp4').stat().st_size, w.MAX_FILE)
        w.validate_files(self.directory)

    def test_main_fallback_keeps_single_metadata_and_65_second_alarm(self):
        real_run = w.subprocess.run
        count = [0]
        def run(command, **kwargs):
            if command[0].endswith('ffmpeg'):
                count[0] += 1
                if count[0] == 1:
                    with Path(command[-1]).open('wb') as sink:
                        sink.truncate(w.MAX_FILE)
                    raise subprocess.CalledProcessError(-signal.SIGXFSZ, command)
            return real_run(command, **kwargs)
        with patch.object(w, 'download_stream', side_effect=self.download), \
             patch.object(w.subprocess, 'run', side_effect=run), \
             patch.object(w, 'extract_metadata', return_value={'duration':1, 'formats':formats()}) as metadata, \
             patch.object(w, 'install_guard') as guard, \
             patch.object(w.signal, 'signal'), patch.object(w.signal, 'alarm') as alarm, \
             patch.object(w.resource, 'setrlimit') as limits, \
             patch.object(w.sys, 'argv', ['worker', 'https://youtube.com/shorts/2bZeMfMUhUc', str(self.directory)]):
            self.assertEqual(w.main(), 0)
        self.assertEqual([c.args[0] for c in alarm.call_args_list], [65, 0])
        metadata.assert_called_once()
        guard.assert_called_once()
        limits.assert_any_call(w.resource.RLIMIT_FSIZE, (w.MAX_FILE, w.MAX_FILE))
        self.assertEqual(count[0], 2)
        self.assertEqual(json.loads((self.directory / 'diagnostic.json').read_text()), {'code':'ok'})

    def test_real_streaming_cap_and_cleanup_across_fsize_fallback(self):
        import io
        from urllib.parse import parse_qs, urlsplit
        fixture = self.fixture.read_bytes()
        transferred, peaks, opened = [0], [], []
        test = self
        class Response(io.BytesIO):
            def __init__(self, url, data):
                super().__init__(data)
                self.url = url
                self.headers = {'Content-Length':str(len(data))}
            def geturl(self):
                return self.url
            def read(self, size=-1):
                chunk = super().read(size)
                transferred[0] += len(chunk)
                return chunk
        class Opener:
            def open(self, request, timeout):
                index = int(parse_qs(urlsplit(request.full_url).query)['id'][0])
                test.assertFalse((test.directory / 'video.mp4').exists())
                test.assertEqual(list(test.directory.rglob('input*')), [])
                opened.append(index)
                data = fixture + b'\0' * (w.MAX_FILE - len(fixture)) if index == 0 else fixture
                return Response(request.full_url, data)
        real_run = w.subprocess.run
        def run(command, **kwargs):
            if command[0].endswith('ffmpeg') and opened == [0]:
                with Path(command[-1]).open('wb') as sink:
                    sink.truncate(w.MAX_FILE)
                peaks.append(sum(p.stat().st_size for p in self.directory.rglob('*') if p.is_file()))
                raise subprocess.CalledProcessError(-signal.SIGXFSZ, command)
            return real_run(command, **kwargs)
        with patch.object(w.urllib.request, 'build_opener', return_value=Opener()), \
             patch.object(w.subprocess, 'run', side_effect=run):
            self.assertEqual(w.process_info({'duration':1, 'formats':formats()}, self.directory), (240, 320))
        self.assertEqual(opened, [0, 1])
        self.assertEqual(transferred[0], w.MAX_FILE + len(fixture))
        self.assertLessEqual(transferred[0], 3 * w.MAX_FILE)
        self.assertEqual(peaks, [2 * w.MAX_FILE])
        self.assertLessEqual(max(peaks), w.MAX_TOTAL)
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), ['manifest.json', 'video.mp4'])

    def test_actual_mux_overflow_falls_back_with_cleanup_and_real_probe(self):
        real_mux = w.mux
        calls = []

        def mux(inputs, output):
            calls.append(inputs)
            if len(calls) == 1:
                with output.open('wb') as sink:
                    sink.truncate(w.MAX_FILE + 1)
                raise w.WorkerError('too_large')
            real_mux(inputs, output)

        with patch.object(w, 'download_stream', side_effect=self.download), \
             patch.object(w, 'mux', side_effect=mux), \
             patch.object(w.signal, 'alarm') as alarm, \
             patch.object(w, 'extract_metadata') as metadata:
            dimensions = w.process_info({'duration':1, 'formats':formats()}, self.directory)
        self.assertEqual(dimensions, (240, 320))
        self.assertEqual(self.downloads, [f['url'] for f in formats()[:2]])
        self.assertEqual(len(calls), 2)
        self.assertFalse(calls[0][0].exists())
        alarm.assert_not_called()
        metadata.assert_not_called()
        item = w.validate_files(self.directory)[0]
        self.assertEqual((item.width, item.height), (240, 320))
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), ['manifest.json', 'video.mp4'])
