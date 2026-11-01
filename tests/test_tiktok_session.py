import io
import unittest
import urllib.request as u
from email.message import Message

class Sessions(unittest.TestCase):
    def test_fresh_site_cookie_reused_on_media_not_supplied_credentials(self):
        from services import tiktok_session as s
        jar=s.Jar(); headers=Message();headers['Set-Cookie']='ttwid=anonymous; Domain=.tiktok.com; Path=/; Secure'
        class Response(io.BytesIO):
            def info(self):return headers
        jar.extract_cookies(Response(),u.Request('https://www.tiktok.com/@x/video/123'))
        session=s.Session(jar)
        session.phase='media'
        req=u.Request('https://v16-webapp-prime.tiktok.com/video/test',headers={'Cookie':'sessionid=private','Authorization':'secret'})
        s.Clean().https_request(req);session.https_request(req)
        self.assertEqual(req.get_header('Cookie'),'ttwid=anonymous')
        self.assertIsNone(req.get_header('Authorization'))
        self.assertEqual(len(list(s.Session().jar)),0)

    def test_cookie_rejection_and_storage_caps(self):
        from services import tiktok_session as s
        from services.tiktok_video_worker import WorkerError
        def put(jar, text):
            h=Message();h['Set-Cookie']=text
            class R:
                def info(self):return h
            jar.extract_cookies(R(),u.Request('https://www.tiktok.com/@x/video/123'))
        jar=s.Jar()
        for text in ('sessionid=secret; Domain=.tiktok.com', '__ac_signature=x; Domain=.tiktok.com', 'ttwid=x; Domain=evil.test', 'ttwid='+('x'*4097)+'; Domain=.tiktok.com'):
            put(jar,text)
        self.assertEqual(len(list(jar)),0)
        for i in range(16):put(jar,'ttwid=x; Domain=.tiktok.com; Path=/p%d'%i)
        with self.assertRaises(WorkerError):put(jar,'ttwid=x; Domain=.tiktok.com; Path=/overflow')
        jar=s.Jar()
        for i in range(3):put(jar,'ttwid='+('x'*4096)+'; Domain=.tiktok.com; Path=/p%d'%i)
        with self.assertRaises(WorkerError):put(jar,'ttwid='+('x'*4096)+'; Domain=.tiktok.com; Path=/overflow')

class TransportGates(unittest.TestCase):
    URL = 'https://www.tiktok.com/@x/video/123'

    def opener(self, session, specs):
        from urllib.response import addinfourl
        events = []
        class Body(io.BytesIO):
            def read(self, n=-1):
                events.append(('read', n)); return super().read(n)
            def close(self):
                events.append(('close',)); super().close()
        class Wire(u.HTTPSHandler):
            def https_open(self, req):
                code, headers, body = specs.pop(0)
                h = Message()
                for k, v in headers.items(): h[k] = v
                response = addinfourl(Body(body), h, req.full_url, code)
                response.msg = 'fake'
                return response
        opener = session.opener()
        opener = u.build_opener(*[h for h in opener.handlers if not isinstance(h, u.HTTPSHandler)], Wire())
        return opener, events

    @unittest.skipIf(__import__('sys').version_info < (3, 10), 'yt-dlp worker requires modern Python')
    def test_compressed_metadata_rejected_before_urllib_rh_decompression(self):
        from services.tiktok_session import Session
        from services.tiktok_video_worker import WorkerError
        from yt_dlp.networking._urllib import UrllibRH
        from yt_dlp.networking import Request
        session = Session()
        opener, events = self.opener(session, [(200, {'Content-Encoding':'gzip'}, b'compressed-bomb')])
        class RH(UrllibRH):
            def _create_instance(self, *a, **kw): return opener
        with RH(logger=__import__('services.tiktok_video_worker', fromlist=['Quiet']).Quiet()) as rh:
            with self.assertRaises(WorkerError): rh.send(Request(self.URL))
        self.assertNotIn('read', [e[0] for e in events])
        self.assertIn(('close',), events)

    @unittest.skipIf(__import__('sys').version_info < (3, 10), 'yt-dlp worker requires modern Python')
    def test_shared_direct_error_and_adapter_budget(self):
        from services.tiktok_session import Session
        from services import tiktok_video_worker as w
        from urllib.error import HTTPError
        from yt_dlp.networking._urllib import UrllibRH
        from yt_dlp.networking import Request
        session = Session(); session.metadata_budget[0] = 5
        opener, events = self.opener(session, [(302, {'Location':self.URL}, b'never'), (200, {}, b'never'), (200, {}, b'abc'), (403, {}, b'abcdef')])
        self.assertEqual(w.resolve_url('https://vm.tiktok.com/ABC/', session, opener), self.URL)
        self.assertFalse(any(e[0] == 'read' for e in events))
        class RH(UrllibRH):
            def _create_instance(self, *a, **kw): return opener
        with RH(logger=w.Quiet()) as rh:
            with rh.send(Request(self.URL)) as response:
                self.assertEqual(response.read(0), b'')
                self.assertEqual(response.read(None), b'abc')
        with self.assertRaises(HTTPError) as caught: opener.open(self.URL)
        with caught.exception as response:
            self.assertEqual(response.read(2), b'ab')
            self.assertEqual(response.read(0), b'')
            with self.assertRaises(w.WorkerError): response.read(None)
        self.assertEqual(session.metadata_budget, [0])

    def test_observed_trace_persisted_safely(self):
        import tempfile, json
        from pathlib import Path
        from services.tiktok_session import Session
        from services import tiktok_video_worker as w
        session = Session()
        opener, events = self.opener(session, [(302, {'Location':self.URL}, b'no'), (200, {}, b'yes'), (403, {}, b'no')])
        w.resolve_url('https://vm.tiktok.com/ABC/', session, opener)
        with self.assertRaises(__import__('urllib.error', fromlist=['HTTPError']).HTTPError): opener.open(self.URL)
        with tempfile.TemporaryDirectory() as raw:
            w.write_diagnostic(Path(raw), 'ok', session)
            text = (Path(raw)/'diagnostic.json').read_text()
        data = json.loads(text)
        self.assertEqual(data, {'code':'ok', 'http_counts':{'metadata':3,'media':0,'head':0}, 'status_counts':{'302':1,'200':1,'403':1}})
        self.assertLessEqual(len(text), 1024)

if __name__=='__main__':unittest.main()
