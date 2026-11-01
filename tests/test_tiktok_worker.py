import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request
from email.message import Message

class TikTokWorker(unittest.TestCase):
    def test_select_only_single_sound_h264_fitting_video(self):
        from services import tiktok_video_worker as w
        good={'url':'https://v16-webapp-prime.tiktok.com/video/tos/clip','filesize':19991808,'vcodec':'h264','acodec':'aac','ext':'mp4','width':720,'height':1280}
        info={'id':'123','duration':90,'formats':[dict(good, vcodec='h265'),good]}
        self.assertEqual(w.choose(info),good)
        for update in ({'duration':91},{'duration':True},{'is_live':True},{'entries':[]},{'imagePost':{}},{'formats':[dict(good,acodec='none')]},{'formats':[dict(good,filesize=20000001)]},{'formats':[dict(good,url='https://127.0.0.1/v')]}):
            with self.assertRaises(w.WorkerError): w.choose(dict(info,**update))

    def test_redirect_never_drains_and_validates_every_hop(self):
        from services import tiktok_video_worker as w
        for code in (301,302,303,307,308):
            for target in ('https://www.tiktok.com/@name/video/123','https://127.0.0.1/x','https://evil.test/x',None):
                events=[]
                class Body(io.BytesIO):
                    def read(self,*a): events.append('read');raise AssertionError('drained')
                    def close(self): events.append('close');super().close()
                body=Body(b'x'*10)
                handler=w.Redirect();headers=Message()
                if target: headers['Location']=target
                class Parent:
                    def open(self,*a,**kw):
                        self.assert_closed=body.closed
                        events.append('open')
                        return 'ok'
                parent=Parent();handler.parent=parent
                method=getattr(handler,'http_error_'+str(code))
                request=Request('https://vm.tiktok.com/ABC/'); request.timeout=8
                if target and target.startswith('https://www.tiktok.com/'):
                    self.assertEqual(method(request,body,code,'x',headers),'ok')
                    self.assertTrue(parent.assert_closed)
                else:
                    with self.assertRaises(Exception): method(request,body,code,'x',headers)
                self.assertNotIn('read',events)
                self.assertTrue(body.closed)
        req=Request('https://vm.tiktok.com/ABC/'); req.count=3
        with self.assertRaises(w.WorkerError): w.Redirect().redirect_request(req,None,302,'',{},'https://www.tiktok.com/@x/video/123')

    def test_private_or_mixed_dns_is_rejected(self):
        from services import instagram_network as guard
        from services import tiktok_video_worker as w
        for addresses in (['127.0.0.1'],['1.1.1.1','10.0.0.1'],['::1']):
            resolver=lambda *a: [(2,1,6,'',(ip,443)) for ip in addresses]
            with patch.object(guard,'allowed_host',w.allowed_host):
                with self.assertRaises(ValueError):guard.resolve_public(resolver,'www.tiktok.com',443)

    def test_metadata_read_cap_is_received_not_just_written(self):
        from services import tiktok_video_worker as w
        raw=io.BytesIO(b'x'*2000001)
        stream=w.Bounded(raw)
        with self.assertRaises(w.WorkerError):stream.read()
        self.assertEqual(raw.tell(),2000000)

    def test_download_preserves_public_format_headers_not_credentials(self):
        from services import tiktok_video_worker as w
        class Response(io.BytesIO):
            headers={'Content-Length':'12'}
            def geturl(self):return 'https://v16-webapp-prime.tiktok.com/video/test'
        observed=[]
        class Opener:
            def open(self,req,**kw):
                observed.append(dict((k.lower(),v) for k,v in req.header_items()))
                return Response(b'0000ftypisom')
        fmt={'url':'https://v16-webapp-prime.tiktok.com/video/test','http_headers':{'User-Agent':'PublicBrowser','Referer':'https://www.tiktok.com/@x/video/123','Cookie':'secret','Authorization':'secret'}}
        with tempfile.TemporaryDirectory() as raw,patch.object(w.urllib.request,'build_opener',return_value=Opener()):
            w.download(fmt,Path(raw)/'video.mp4')
        self.assertEqual(observed[0]['user-agent'],'PublicBrowser')
        self.assertNotIn('cookie',observed[0]);self.assertNotIn('authorization',observed[0])

    def test_process_merges_info_and_format_public_headers(self):
        from services import tiktok_video_worker as w
        fmt={'url':'https://v16-webapp-prime.tiktok.com/video/test','filesize':12,'vcodec':'h264','acodec':'aac','ext':'mp4','http_headers':{'uSeR-aGeNt':'FormatUA','Cookie':'secret'}}
        info={'id':'123','duration':16,'formats':[fmt],'http_headers':{'User-Agent':'InfoUA','Referer':'https://www.tiktok.com/','Accept':'*/*','Authorization':'secret'}}
        observed=[]
        def capture(selected,target):
            observed.append({k.lower():v for k,v in selected.get('http_headers',{}).items()})
        with tempfile.TemporaryDirectory() as raw, patch.object(w,'download',side_effect=capture), patch.object(w,'probe_file',return_value=(720,1280)), patch('services.tiktok_video.validate_files',return_value=[]):
            w.process_info(info,Path(raw))
        self.assertEqual(observed,[{'user-agent':'FormatUA','referer':'https://www.tiktok.com/','accept':'*/*'}])
        self.assertEqual(info['http_headers']['User-Agent'],'InfoUA')
        self.assertIn('Cookie',fmt['http_headers'])

    def test_no_challenge_solver_or_cookie_set(self):
        from services import tiktok_video_worker as w
        self.assertTrue(w.metadata_url('https://vm.tiktok.com/ABC/'))
        for url in ('https://www.tiktok.com/login','https://www.tiktok.com/api/foo','https://www.tiktok.com/@x/photo/123','https://www.tiktok.com:444/@x/video/123'):
            self.assertFalse(w.metadata_url(url))

    def test_public_get_resolution_binds_dynamic_identity(self):
        from services import tiktok_video_worker as w
        from services.tiktok_session import Session
        for ident in ('123456', '987654321'):
            session=Session(); seen=[]
            class R(io.BytesIO):
                def geturl(self):return 'https://www.tiktok.com/@different/video/'+ident
            class O:
                def open(self,req,**kw):
                    seen.append(req.get_method());return R(b'page')
            resolved=w.resolve_url('https://vm.tiktok.com/Dynamic/',session,O())
            self.assertEqual(seen,['GET'])
            w.bind_identity({'id':ident,'webpage_url':resolved},resolved)
            with self.assertRaises(w.WorkerError):w.bind_identity({'id':'999','webpage_url':resolved},resolved)
            with self.assertRaises(w.WorkerError):w.bind_identity({'id':ident,'webpage_url':'https://www.tiktok.com/@x/video/999'},resolved)

if __name__=='__main__':unittest.main()
