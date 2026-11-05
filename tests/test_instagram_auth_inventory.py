import io
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import instagram_worker as worker
from instagram_download import DownloadError


def inventory():
    return {'pk':'123', 'media_type':8, 'user':{'is_private':False},
        'audience':'default', 'product_type':'feed', 'carousel_media_count':2,
        'carousel_media':[{'pk':'124','media_type':1,'image_versions2':{'candidates':[
            {'url':'https://scontent.cdninstagram.com/photo.jpg'}]}},
            {'pk':'125','media_type':2,'video_versions':[
                {'url':'https://scontent.cdninstagram.com/video.mp4','width':640,'height':480}]}]}


@unittest.skipUnless(importlib.util.find_spec('yt_dlp'), 'requires dedicated yt-dlp worker runtime')
class AuthInventoryTests(unittest.TestCase):
    def test_real_ytdlp_auth_worker_video_and_wire_headers(self):
        import os
        import urllib.request
        from email.message import Message
        from urllib.response import addinfourl
        from yt_dlp.networking._urllib import UrllibRH
        from test_instagram_session import material
        data = {'pk':'123', 'media_type':2, 'user':{'is_private':False},
                'audience':'public', 'product_type':'clips',
                'video_versions':[{'url':'https://scontent.cdninstagram.com/video.mp4',
                                   'width':640,'height':480}]}
        wires = []
        class Wire(urllib.request.HTTPSHandler):
            def https_open(self, req):
                wires.append((req.full_url, dict(req.header_items())))
                body = (json.dumps({'status':'ok','items':[data]}).encode()
                        if '/info/' in req.full_url else b'\0\0\0\x18ftypisom')
                headers = Message(); headers['Content-Length'] = str(len(body))
                response = addinfourl(io.BytesIO(body), headers, req.full_url, 200)
                response.msg = 'OK'
                return response
        def instance(*args, **kwargs):
            return urllib.request.build_opener(urllib.request.ProxyHandler({}), Wire())
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)/'attempt'; directory.mkdir()
            p = Path(raw)/'fixture'; p.write_bytes(material()); p.chmod(0o600)
            fd = os.open(p, os.O_RDONLY)
            with patch.object(UrllibRH, '_create_instance', instance), \
                 patch('instagram_video_fallback.head_size', return_value=12), \
                 patch('instagram_worker.install_network_guard'), \
                 patch('instagram_worker.signal.alarm'), patch('instagram_worker.resource.setrlimit'), \
                 patch('socket.socket.connect', side_effect=AssertionError('network forbidden')), \
                 patch('instagram_worker.Diagnostic.write') as diagnostic, \
                 patch('sys.argv', ['worker','https://www.instagram.com/p/B7/',str(directory),'--auth-fd',str(fd)]):
                self.assertEqual(worker.main(), 0, str(diagnostic.call_args))
            self.assertTrue((directory/'manifest.json').is_file())
            self.assertGreaterEqual(len(wires), 2)
            first = {k.lower():v for k,v in wires[0][1].items()}
            self.assertIn('fixture-session', first['cookie'])
            for url, headers in wires[1:]:
                self.assertFalse({'cookie','authorization'} & {k.lower() for k in headers})
            self.assertNotIn('fixture-session', ''.join(p.read_text(errors='ignore') for p in directory.iterdir()))

    def test_mixed_inventory_complete_no_embed(self):
        self.assertTrue(hasattr(worker, 'extract_authenticated'), 'missing authoritative auth path')
        class DL:
            def urlopen(self, req):
                return io.BytesIO(json.dumps({'status':'ok','items':[inventory()]}).encode())
            def process_ie_result(self, info, download=True):
                (directory/'02.mp4').write_bytes(b'\0\0\0\x18ftypisom')
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            with patch('instagram_authenticated.fetch', return_value=b'\xff\xd8\xff'+b'x'*12), \
                 patch('instagram_worker.download_photo', side_effect=AssertionError('public embed forbidden')):
                files = worker.extract_authenticated(DL(), 'https://www.instagram.com/p/B7/', directory)
            self.assertEqual([f.type for f in files], ['photo','video'])
            self.assertEqual({f.coverage for f in files}, {'complete'})

    def test_session_accessible_media_does_not_require_public_visibility(self):
        cases = [({'user': {'is_private': True}}, 'private owner'),
                 ({'user': {}}, 'unknown owner privacy'),
                 ({'audience': 'besties'}, 'close friends'),
                 ({'audience': 'followers'}, 'followers'),
                 ({'audience': None}, 'no public label'),
                 ({'product_type': 'story', 'expiring_at': 9999999999}, 'available media'),
                 ({'audience': 'unknown'}, 'unrecognized audience')]
        for changes, label in cases:
            data = inventory()
            data.update(changes)
            class DL:
                def urlopen(self, req):
                    return io.BytesIO(json.dumps({'status': 'ok', 'items': [data]}).encode())
                def process_ie_result(self, info, download=True):
                    (directory / '02.mp4').write_bytes(b'\0\0\0\x18ftypisom')
            with self.subTest(case=label), tempfile.TemporaryDirectory() as raw, \
                 patch('instagram_authenticated.fetch', return_value=b'\xff\xd8\xff'+b'x'*12), \
                 patch('socket.socket.connect', side_effect=AssertionError('network forbidden')):
                directory = Path(raw)
                try:
                    files = worker.extract_authenticated(DL(), 'https://www.instagram.com/p/B7/', directory)
                except DownloadError as exc:
                    self.fail('Session-accessible inventory rejected: %s' % exc)
                self.assertEqual([item.type for item in files], ['photo', 'video'])
                self.assertEqual({item.coverage for item in files}, {'complete'})

    def test_unknown_private_partial_overflow_inventory_fails_before_download(self):
        self.assertTrue(hasattr(worker, 'extract_authenticated'), 'missing authoritative auth path')
        for mode in ['partial','overflow','wrong-id','unknown-type']:
            data = inventory()
            if mode == 'partial': data['carousel_media_count'] = 3
            elif mode == 'overflow': data['carousel_media'] *= 6; data['carousel_media_count'] = 12
            elif mode == 'wrong-id': data['pk'] = '999'
            else: data['carousel_media'][0]['media_type'] = 3
            class DL:
                def urlopen(self, req): return io.BytesIO(json.dumps({'status':'ok','items':[data]}).encode())
                def process_ie_result(self, *a, **kw): raise AssertionError('must reject before downloading')
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as raw:
                with self.assertRaisesRegex(DownloadError, '^inventory_incomplete$'):
                    worker.extract_authenticated(DL(), 'https://www.instagram.com/p/B7/', Path(raw))
                self.assertFalse(list(Path(raw).iterdir()))
