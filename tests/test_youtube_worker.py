import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch


def video(size, height=720, audio='none', **kw):
    f = dict(url='https://rr1---sn-test.googlevideo.com/videoplayback?secret=abc',
             protocol='https', ext='mp4', vcodec='avc1.64001f', acodec=audio,
             filesize=size, width=height*16//9, height=height, fps=30, quality=1)
    f.update(kw)
    return f


def audio(size=1000000, **kw):
    f = dict(url='https://rr1---sn-test.googlevideo.com/videoplayback?secret=def',
             protocol='https', ext='m4a', vcodec='none', acodec='mp4a.40.2',
             filesize=size, abr=128)
    f.update(kw)
    return f


class RedirectBodyTests(unittest.TestCase):
    """Real urllib opener/error dispatch; only HTTPS transport is replaced."""
    good = 'https://rr1---sn-test.googlevideo.com/videoplayback?sig=test'
    codes = (301, 302, 303, 307, 308)

    def make_opener(self, replies):
        import io
        import urllib.request
        from email.message import Message
        from urllib.response import addinfourl
        from services import youtube_video_worker as w
        self.assertEqual(Path(w.__file__).resolve(),
                         Path(__file__).resolve().parents[1] / 'services/youtube_video_worker.py')
        owner = self
        bodies, requests = [], []

        class HugeBody(io.BytesIO):
            # Virtual oversized intermediate body, never allocated on GREEN.
            read_calls = 0
            transferred = 0
            def read(self, size=-1):
                self.read_calls += 1
                size = w.MAX_FILE + 1 if size < 0 else min(size, w.MAX_FILE + 1)
                chunk = b'x' * size
                self.transferred += len(chunk)
                return chunk

        class Transport(urllib.request.HTTPSHandler):
            def https_open(self, request):
                for body in bodies:
                    owner.assertTrue(body.closed, 'previous response must close before next open')
                    owner.assertEqual((body.read_calls, body.transferred), (0, 0))
                requests.append(request)
                code, location = replies[len(requests) - 1]
                headers = Message()
                if location is not None:
                    headers['Location'] = location
                body = HugeBody() if code in owner.codes else io.BytesIO(b'ok')
                if code in owner.codes:
                    bodies.append(body)
                    headers['Content-Length'] = str(w.MAX_FILE + 1)
                else:
                    headers['Content-Length'] = '2'
                response = addinfourl(body, headers, request.full_url, code)
                response.msg = 'test response'
                return response

        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                             w.CDNRedirect(), Transport())
        return opener, bodies, requests

    def assert_discarded(self, bodies):
        self.assertTrue(bodies)
        for body in bodies:
            self.assertTrue(body.closed)
            self.assertEqual((body.read_calls, body.transferred), (0, 0))

    def test_full_opener_all_redirect_codes_close_without_read_before_follow(self):
        for code in self.codes:
            with self.subTest(code=code):
                destination = self.good + '&next=1'
                opener, bodies, requests = self.make_opener([(code, destination), (200, None)])
                with opener.open(self.good, timeout=8) as response:
                    self.assertEqual(response.read(), b'ok')
                    self.assertEqual(response.geturl(), destination)
                self.assertEqual(len(requests), 2)
                self.assertEqual([r.get_method() for r in requests], ['GET', 'GET'])
                self.assertEqual([r.timeout for r in requests], [8, 8])
                self.assert_discarded(bodies)

    def test_forbidden_locations_close_without_follow_for_every_code(self):
        from services.youtube_video_worker import WorkerError
        destinations = [
            'https://evil.org/videoplayback',
            'https://127.0.0.1/videoplayback',
            'https://[::1]/videoplayback',
            'http://rr.googlevideo.com/videoplayback',
            'https://user:pass@rr.googlevideo.com/videoplayback',
            'https://rr.googlevideo.com:444/videoplayback',
            'https://rr.googlevideo.com/other',
            'https://rr.googlevideo.com/videoplayback#fragment',
        ]
        for code in self.codes:
            for destination in destinations:
                with self.subTest(code=code, destination=destination):
                    opener, bodies, requests = self.make_opener([(code, destination)])
                    with self.assertRaisesRegex(WorkerError, '^network_denied$'):
                        opener.open(self.good, timeout=8)
                    self.assertEqual(len(requests), 1)
                    self.assert_discarded(bodies)

    def test_missing_and_malformed_locations_close_without_follow(self):
        from urllib.error import HTTPError
        for code in self.codes:
            for location, error in [(None, HTTPError), ('https://[broken', ValueError),
                                    ('file:///etc/passwd', HTTPError)]:
                with self.subTest(code=code, location=location):
                    opener, bodies, requests = self.make_opener([(code, location)])
                    with self.assertRaises(error):
                        opener.open(self.good, timeout=8)
                    self.assertEqual(len(requests), 1)
                    self.assert_discarded(bodies)

    def test_exactly_three_redirects_follow_but_fourth_is_closed_and_denied(self):
        from services.youtube_video_worker import WorkerError
        for code in self.codes:
            for count in (3, 4):
                with self.subTest(code=code, redirects=count):
                    replies = [(code, self.good + '&hop=%d' % i) for i in range(count)]
                    opener, bodies, requests = self.make_opener(replies + [(200, None)])
                    if count == 3:
                        with opener.open(self.good, timeout=8) as response:
                            self.assertEqual(response.read(), b'ok')
                    else:
                        with self.assertRaisesRegex(WorkerError, '^network_denied$'):
                            opener.open(self.good, timeout=8)
                    self.assertEqual(len(requests), 4)
                    self.assertEqual(len(bodies), count)
                    self.assert_discarded(bodies)

    def test_existing_method_restrictions_survive_full_error_dispatch(self):
        from urllib.error import HTTPError
        from urllib.request import Request
        for code in self.codes:
            for method in ('PUT', 'DELETE', 'POST'):
                if method == 'POST' and code in (301, 302, 303):
                    continue  # urllib permits POST -> GET for these codes.
                with self.subTest(code=code, method=method):
                    opener, bodies, requests = self.make_opener([(code, self.good)])
                    with self.assertRaises(HTTPError):
                        opener.open(Request(self.good, method=method), timeout=8)
                    self.assertEqual(len(requests), 1)
                    self.assert_discarded(bodies)

    def test_redirect_private_or_mixed_dns_denied_before_next_transport(self):
        import socket
        import urllib.request
        from services import instagram_network as guard
        from services.youtube_video_worker import allowed_host
        destination = 'https://rr2.googlevideo.com/videoplayback'
        public = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))
        private = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))
        owner = self
        # Exercise the existing resolver policy with synthetic DNS answers,
        # not real sockets; real connect-address pinning remains unchanged.
        for code in self.codes:
            for records in ([private], [public, private]):
                with self.subTest(code=code, records=records):
                    opener, bodies, requests = self.make_opener([(code, destination)])
                    class DNSPolicy(urllib.request.BaseHandler):
                        def https_request(self, request):
                            if request.full_url == destination:
                                owner.assert_discarded(bodies)
                                guard.resolve_public(lambda *a: records, request.host, 443)
                            return request
                    opener.add_handler(DNSPolicy())
                    with patch.object(guard, 'allowed_host', allowed_host):
                        with self.assertRaisesRegex(ValueError, 'Non-public DNS answer denied'):
                            opener.open(self.good, timeout=8)
                    self.assertEqual(len(requests), 1)
                    self.assert_discarded(bodies)


class NetworkTests(unittest.TestCase):
    def test_cdn_urls_and_bounded_redirects(self):
        from services.youtube_video_worker import cdn_url, CDNRedirect, WorkerError
        import urllib.request
        good = 'https://rr1---sn-test.googlevideo.com/videoplayback?sig=secret'
        self.assertTrue(cdn_url(good))
        for url in ['http://rr.googlevideo.com/videoplayback', 'https://googlevideo.com/videoplayback',
                    'https://rr.googlevideo.com.evil/videoplayback', 'https://user@rr.googlevideo.com/videoplayback',
                    'https://rr.googlevideo.com:444/videoplayback', 'https://127.0.0.1/videoplayback',
                    'https://rr.googlevideo.com/other', 'https://rr.googlevideo.com/videoplayback#f',
                    'https://rr.googlevideo.com/videoplayback\n']:
            self.assertFalse(cdn_url(url))
        redirect = CDNRedirect()
        req = urllib.request.Request(good)
        for _ in range(3):
            req = redirect.redirect_request(req,None,302,'',{},good)
        with self.assertRaises(WorkerError): redirect.redirect_request(req,None,302,'',{},good)
        with self.assertRaises(WorkerError): CDNRedirect().redirect_request(req,None,302,'',{},'https://evil.org/x')

    def test_metadata_policy_prevents_early_media_manifests_and_player_js(self):
        from services.youtube_video_worker import MetadataPolicy, WorkerError
        import urllib.request
        policy = MetadataPolicy()
        request = urllib.request.Request('https://www.youtube.com/watch?v=2bZeMfMUhUc')
        self.assertIs(policy.https_request(request),request)
        for url in ['https://rr.googlevideo.com/videoplayback',
                    'https://www.youtube.com/s/player/test/player.js',
                    'https://www.youtube.com/api/manifest/hls/a',
                    'https://www.google.com/sorry', 'http://www.youtube.com/watch']:
            with self.assertRaises(WorkerError): policy.https_request(urllib.request.Request(url))

    def test_endpoint_guard_and_mixed_dns_fail_closed_without_global_changes(self):
        from services.youtube_video_worker import allowed_host, metadata_url
        from services import instagram_network as guard
        import socket
        self.assertTrue(guard.allowed_host('www.instagram.com'))
        for host in ['youtube.com','www.youtube.com','m.youtube.com','youtubei.googleapis.com','rr.googlevideo.com']:
            self.assertTrue(allowed_host(host))
        for host in ['www.google.com','google.com','youtube.com.evil','googlevideo.com','127.0.0.1','evil.youtube.com','i.ytimg.com']:
            self.assertFalse(allowed_host(host))
        for url in ['http://www.youtube.com/watch', 'https://u@www.youtube.com/watch',
                    'https://www.youtube.com:80/watch', 'https://www.google.com/sorry', 'file:///etc/passwd']:
            self.assertFalse(metadata_url(url))
        record = (socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))
        with patch.object(guard,'allowed_host',allowed_host):
            self.assertEqual(guard.resolve_public(lambda *a:[record], 'www.youtube.com',443), [record])
            private = (socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))
            with self.assertRaises(ValueError): guard.resolve_public(lambda *a:[record,private], 'rr.googlevideo.com',443)
        self.assertTrue(guard.allowed_host('www.instagram.com'))


class PipelineTests(unittest.TestCase):
    def test_stream_read_budget_unknown_length_rejects_at_cap_without_sentinel(self):
        from services import youtube_video_worker as w
        import io
        for count in (16, 17):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as raw:
                class Response(io.BytesIO):
                    headers = {}
                    transferred = 0
                    requests = None
                    def geturl(self): return video(1)['url']
                    def read(self, size=-1):
                        self.requests.append(size)
                        chunk = super().read(size)
                        self.transferred += len(chunk)
                        return chunk
                response = Response(b'x' * count)
                response.requests = []
                class Opener:
                    def open(self, request, timeout): return response
                target = Path(raw) / 'input.mp4'
                used = [0]
                with patch.object(w, 'MAX_FILE', 16):
                    with self.assertRaisesRegex(w.WorkerError, '^too_large$'):
                        w.download_stream(video(1), target, used, Opener())
                self.assertEqual(response.transferred, 16)
                self.assertEqual(response.requests, [16])
                self.assertEqual(used, [16])
                self.assertFalse(target.exists())

    def test_stream_known_length_exact_cap_accepted_without_extra_read(self):
        from services import youtube_video_worker as w
        import io
        class Response(io.BytesIO):
            headers = {'Content-Length': '16'}
            def geturl(self): return video(1)['url']
            def read(self, size=-1):
                requests.append(size)
                chunk = super().read(size)
                transferred[0] += len(chunk)
                return chunk
        requests, transferred = [], [0]
        class Opener:
            def open(self, request, timeout): return Response(b'x' * 16)
        with tempfile.TemporaryDirectory() as raw, patch.object(w, 'MAX_FILE', 16):
            target = Path(raw) / 'input.mp4'
            used = [0]
            w.download_stream(video(16), target, used, Opener())
            self.assertEqual(target.read_bytes(), b'x' * 16)
            self.assertEqual(used, [16])
        self.assertEqual(transferred, [16])
        self.assertEqual(requests, [16])

    def test_streaming_hard_sum_boundary_and_partial_cleanup(self):
        from services.youtube_video_worker import download_stream, WorkerError
        import io
        class Response(io.BytesIO):
            headers = {}
            def geturl(self): return video(1)['url']
        class Opener:
            def __init__(self, count, known=False): self.count, self.known = count, known
            def open(self, req, timeout):
                response = Response(b'x' * self.count)
                if self.known:
                    response.headers = {'Content-Length': str(self.count)}
                return response
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw)/'input.mp4'
            used = [19999995]
            download_stream(video(5), target, used, Opener(5, known=True))
            self.assertEqual(used[0],20000000); self.assertEqual(target.stat().st_size,5)
            target.unlink()
            with self.assertRaises(WorkerError): download_stream(video(6),target,[19999995],Opener(6))
            self.assertFalse(target.exists())
            class Oversize(Response): headers = {'Content-Length':'20000001'}
            opener = Opener(1); opener.open = lambda *a,**kw: Oversize(b'x')
            with self.assertRaises(WorkerError): download_stream(video(1),target,[0],opener)
            self.assertFalse(target.exists())

    def test_final_mux_probe_and_disk_size_limits_remain_strict(self):
        from services import youtube_video_worker as w
        import json
        probe = {'format': {'duration': '1'}, 'streams': [
            {'codec_type': 'video', 'codec_name': 'h264', 'width': 320, 'height': 240},
            {'codec_type': 'audio', 'codec_name': 'aac'}]}
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            output = directory / 'video.mp4'
            def run(command, **kwargs):
                if command[0].endswith('ffprobe'):
                    kwargs['stdout'].write(json.dumps(probe).encode())
            with patch.object(w.subprocess, 'run', side_effect=run) as tool:
                for size in (20_000_000, 20_000_001):
                    with self.subTest(size=size):
                        with output.open('wb') as sink:
                            sink.truncate(size)
                        if size == 20_000_000:
                            w.mux((directory / 'input.mp4',), output)
                            self.assertEqual(w.probe_file(output), (320, 240))
                        else:
                            with self.assertRaisesRegex(w.WorkerError, '^too_large$'):
                                w.mux((directory / 'input.mp4',), output)
                            tool.reset_mock()
                            with self.assertRaisesRegex(w.WorkerError, '^too_large$'):
                                w.probe_file(output)
                            tool.assert_not_called()
            for size in (45_000_000, 45_000_001):
                with output.open('wb') as sink:
                    sink.truncate(size)
                if size == 45_000_000:
                    w.check_disk(directory)
                else:
                    with self.assertRaisesRegex(w.WorkerError, '^too_large$'):
                        w.check_disk(directory)

    def test_metadata_gate_precedes_bytes_and_failure_removes_own_files(self):
        from services import youtube_video_worker as w
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            with patch.object(w,'download_stream') as download:
                with self.assertRaises(w.WorkerError):
                    w.process_info({'duration':91,'formats':[video(1),audio(1)]}, directory)
                download.assert_not_called()
            def fail(fmt,target,used,opener=None):
                target.write_bytes(b'partial')
                raise w.WorkerError('network_denied')
            with patch.object(w,'download_stream',side_effect=fail):
                with self.assertRaises(w.WorkerError):
                    w.process_info({'duration':90,'formats':[video(1),audio(1)]},directory)
            self.assertEqual(list(directory.iterdir()),[])

    def test_mux_local_copy_protocol_limits_and_probe_boundary(self):
        from services import youtube_video_worker as w
        import json
        calls = []
        probe = dict(format={'duration':'90'}, streams=[
            {'codec_type':'video','codec_name':'h264','width':720,'height':1280},
            {'codec_type':'audio','codec_name':'aac'}])
        def run(command, **kwargs):
            calls.append((command,kwargs))
            self.assertIs(kwargs['stderr'],w.subprocess.DEVNULL)
            self.assertEqual(set(kwargs['env']), {'PATH','HOME','LANG'})
            self.assertTrue(callable(kwargs['preexec_fn']))
            if command[0].endswith('ffmpeg'):
                Path(command[-1]).write_bytes(b'\x00\x00\x00\x18ftypisom')
            else: kwargs['stdout'].write(json.dumps(probe).encode())
        with tempfile.TemporaryDirectory() as raw:
            d = Path(raw)
            v,a,out = d/'in.mp4',d/'in.m4a',d/'video.mp4'
            v.write_bytes(b'x'); a.write_bytes(b'x')
            with patch.object(w.subprocess,'run',side_effect=run):
                w.mux((v,a),out)
                self.assertEqual(w.probe_file(out),(720,1280))
                command = calls[0][0]
                for index, word in enumerate(command):
                    if word == '-i': self.assertEqual(command[index-2:index], ['-protocol_whitelist','file,pipe'])
                self.assertEqual(command[command.index('-c')+1],'copy')
                self.assertIn('+faststart',command)
                probe['format']['duration']='91'
                with self.assertRaises(w.WorkerError): w.probe_file(out)
                probe['format']['duration']='90'
                probe['streams'][1]['codec_name']='opus'
                with self.assertRaises(w.WorkerError): w.probe_file(out)

    @unittest.skipUnless(__import__('shutil').which('ffmpeg') and __import__('shutil').which('ffprobe'), 'local media tools unavailable')
    def test_real_local_ffmpeg_mux_probe_manifest_no_network(self):
        from services import youtube_video_worker as w
        import shutil
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = root/'fixture.mp4'
            w.subprocess.run(['/usr/bin/ffmpeg','-nostdin','-v','fatal',
                '-f','lavfi','-i','color=c=black:s=320x240:r=25',
                '-f','lavfi','-i','anullsrc=r=48000:cl=mono',
                '-t','1','-c:v','libx264','-threads','1','-c:a','aac',str(fixture)],
                check=True,timeout=15,stdout=w.subprocess.DEVNULL,stderr=w.subprocess.DEVNULL)
            directory = root/'work'; directory.mkdir()
            def local_download(fmt,target,used):
                shutil.copyfile(fixture,target); used[0] += target.stat().st_size
            with patch.object(w,'download_stream',side_effect=local_download):
                dimensions = w.process_info({'duration':1,'formats':[video(fixture.stat().st_size,240,audio='mp4a.40.2')]},directory)
            self.assertEqual(dimensions,(320,240))
            self.assertEqual(sorted(p.name for p in directory.iterdir()),['manifest.json','video.mp4'])
            self.assertEqual(w.validate_files(directory)[0].type,'video')
            self.assertEqual(w.probe_file(directory/'video.mp4'),(320,240))

    def test_main_real_pipeline_wiring_and_fixed_failure_diagnostic(self):
        from services import youtube_video_worker as w
        with tempfile.TemporaryDirectory() as raw:
            d = Path(raw)
            url = 'https://youtube.com/shorts/2bZeMfMUhUc'
            with patch.object(w,'apply_limits'), patch.object(w,'install_guard') as guard, \
                 patch.object(w,'extract_metadata',return_value={'duration':91}) as metadata, \
                 patch.object(w.sys,'argv',['worker',url,str(d)]):
                self.assertEqual(w.main(),2)
                guard.assert_called_once()
                metadata.assert_called_once_with('https://www.youtube.com/watch?v=2bZeMfMUhUc')
                self.assertEqual(__import__('json').loads((d/'diagnostic.json').read_text())['code'],'duration_denied')
            with patch.object(w,'apply_limits'), patch.object(w,'install_guard'), \
                 patch.object(w,'extract_metadata',side_effect=RuntimeError('Sign in bot check https://SECRET')), \
                 patch.object(w.sys,'argv',['worker',url,str(d)]):
                self.assertEqual(w.main(),2)
                self.assertEqual((d/'diagnostic.json').read_text(),'{"code": "youtube_unavailable"}')

    def test_options_no_js_credentials_proxy_or_retries_and_sanitized_codes(self):
        from services.youtube_video_worker import build_options, write_diagnostic
        options = build_options()
        for key in ['retries','extractor_retries','fragment_retries']:
            self.assertEqual(options[key],0)
        self.assertEqual(options['js_runtimes'],{})
        self.assertEqual(options['remote_components'],[])
        self.assertEqual(options['proxy'],'')
        self.assertIsNone(options['cookiefile'])
        self.assertFalse(options['cachedir'])
        self.assertTrue(options['noplaylist'])
        with tempfile.TemporaryDirectory() as raw:
            write_diagnostic(Path(raw),'https://signed.googlevideo.com/SECRET')
            self.assertNotIn('SECRET',(Path(raw)/'diagnostic.json').read_text())


class SelectionTests(unittest.TestCase):
    def test_known_size_inclusive_20m_candidates_keep_best_quality(self):
        from services.youtube_video_worker import choose_formats, WorkerError
        for size in (19_500_001, 19_600_000, 20_000_000, 20_000_001):
            for separate in (False, True):
                with self.subTest(size=size, separate=separate):
                    track = audio(1_000_000)
                    best = video(size - track['filesize'] if separate else size,
                                 1080, audio='none' if separate else 'mp4a.40.2')
                    candidate = (best, track) if separate else (best,)
                    if size > 20_000_000:
                        with self.assertRaisesRegex(WorkerError, '^no_video$'):
                            choose_formats(list(candidate))
                    else:
                        self.assertEqual(choose_formats(list(candidate)), candidate)
                    # A smaller/lower-quality format must not displace a fitting one.
                    small = video(1_000_000, 360, audio='mp4a.40.2')
                    expected = (small,) if size > 20_000_000 else candidate
                    self.assertEqual(choose_formats([small] + list(candidate)), expected)

    def test_duration_inclusive_live_and_playlist_rejected(self):
        from services.youtube_video_worker import check_metadata, WorkerError
        check_metadata({'duration':90, 'is_live':False, 'live_status':'not_live'})
        for info in [{'duration':91}, {'duration':90.01}, {'duration':float('nan')},
                     {'duration':0}, {'duration':True}, {'duration':None},
                     {'duration':30, 'is_live':True}, {'duration':30, 'live_status':'is_upcoming'},
                     {'duration':30, 'live_status':'post_live'}, {'duration':30, '_type':'playlist'}]:
            with self.subTest(info=info), self.assertRaises(WorkerError): check_metadata(info)

    def test_best_fitting_known_size_h264_aac_only(self):
        from services.youtube_video_worker import choose_formats, WorkerError
        small, best, huge = video(2000000,360), video(18000000,1080), video(19000001,2160)
        track = audio()
        self.assertEqual(choose_formats([small, best, huge, track]), (best, track))
        self.assertEqual(choose_formats([video(18500000), track])[0]['filesize'],18500000)
        for formats in [[video(None),track], [video(None,filesize_approx=100), track],
                        [video(100)], [video(100),audio(acodec='opus')],
                        [video(100, protocol='m3u8_native'), track],
                        [video(100, vcodec='vp9'),track],
                        [video(100, url='https://evil.org/videoplayback'), track]]:
            with self.subTest(formats=formats), self.assertRaises(WorkerError): choose_formats(formats)
        muxed = video(19000000,1080,audio='mp4a.40.2')
        self.assertEqual(choose_formats([small, track, muxed]),(muxed,))
        self.assertEqual(choose_formats([video(100,1080),audio(100,abr=64),track])[1],track)
