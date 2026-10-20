import unittest
from unittest.mock import AsyncMock, patch
from aiogram.types import Message
from aiogram.dispatcher.event.bases import SkipHandler

URL = 'https://open.spotify.com/track/5VykLQtjCYF6qFq59HbUg9'

class MusicTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_mapping_slice(self):
        try:
            from services.music_match import canonical_url, parse_page, render
        except ImportError:
            self.fail('music matching service is missing')
        self.assertEqual(canonical_url(URL+'?si=secret'), URL)
        result = parse_page('<title>Sen Bilmezsin by Dedublüman - Songlink</title><a href="https://www.deezer.com/track/2684821152">listen</a><a href="https://evil.test/search">no</a>')
        self.assertIn('Sen Bilmezsin', render(result))
        self.assertIn('2684821152', render(result))
        self.assertNotIn('evil.test', render(result))
        result = parse_page('<title>Sen Bilmezsin by Dedublüman</title><svg><title>tidal_circle icon</title></svg><a href="'+URL+'">Spotify</a>')
        self.assertEqual(result[0], 'Sen Bilmezsin by Dedublüman')

    async def test_compact_output_and_extra_platforms(self):
        from services.music_match import matched_link, render
        examples = [
            ('Amazon Music','https://music.amazon.com/albums/B06XSTDBSM?trackAsin=B06XSVS86F'),
            ('Amazon','https://amazon.com/dp/B06XSVS86F'),
            ('Pandora','https://www.pandora.com/TR:15080824'),
            ('Anghami','https://play.anghami.com/song/1148970975'),
            ('SoundCloud','https://soundcloud.com/artist/track'),
            ('SoundCloud','https://api.soundcloud.com/tracks/12345'),
            ('YouTube','https://www.youtube.com/watch?v=abcdefghijk')]
        for label,url in examples:
            self.assertEqual(matched_link(url),(label,url))
        for bad in ['https://music.amazon.com.evil/albums/B06XSTDBSM','https://music.amazon.com/search/track','https://soundcloud.com/search?q=track']:
            self.assertIsNone(matched_link(bad))
        text=render(('Track by Artist',examples))
        self.assertIn(' | ',text)
        self.assertEqual(text.count('\n'),1)
        self.assertNotIn('Источник:',text)

    async def test_network_security_and_capacity(self):
        from services import music_match as m
        self.assertTrue(hasattr(m, 'MatchService'), 'bounded production service missing')
        for value in ['http://song.link/s/a','https://song.link.evil/s/a','https://user@song.link/s/a','https://song.link:444/s/a','https://127.0.0.1/']:
            with self.assertRaises(m.MatchError): m.validate_endpoint(value)
        for ip in ['127.0.0.1','10.0.0.1','169.254.169.254','::1','::ffff:8.8.8.8']:
            self.assertFalse(m.public_ip(ip))
        service = m.MatchService()
        service.active = 2
        with self.assertRaisesRegex(m.MatchError, 'busy'): await service.match(URL)
        with patch.object(service, '_fetch', new_callable=AsyncMock) as fetch:
            service.active = 0
            fetch.return_value = ('Title', [('Spotify', URL)])
            self.assertEqual(await service.match(URL), await service.match(URL))
            fetch.assert_awaited_once()
        for bad in ['https://open.spotify.com/playlist/5VykLQtjCYF6qFq59HbUg9','https://youtube.com/watch?v=abcdefghijk','https://open.spotify.com.evil/track/5VykLQtjCYF6qFq59HbUg9','https://user@open.spotify.com/track/5VykLQtjCYF6qFq59HbUg9','https://soundcloud.com/a/sets']:
            self.assertIsNone(m.canonical_url(bad))
        self.assertIn('&lt;script&gt;',m.render(('<script>', [('Spotify',URL)])))

    async def test_transport_limits_dns_and_cache(self):
        import asyncio
        import socket
        from services import music_match as m
        loop = asyncio.get_running_loop()
        with patch.object(loop, 'getaddrinfo', new_callable=AsyncMock) as dns:
            dns.return_value = [(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))]
            with self.assertRaisesRegex(m.MatchError,'unsafe_dns'):
                await m.PublicResolver().resolve('song.link',443)
            dns.return_value = [(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]
            self.assertEqual((await m.PublicResolver().resolve('song.link',443))[0]['host'],'8.8.8.8')
        class Response:
            def __init__(self,status=200,headers=None,data=b''):
                self.status=status
                self.headers=headers or {'Content-Type':'text/html'}
                self.data=data
                self.content=self
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            async def iter_chunked(self,n):
                for i in range(0,len(self.data),n): yield self.data[i:i+n]
        class Session:
            def __init__(self,response): self.response=response; self.calls=0
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            def get(self,*args,**kwargs): self.calls+=1; return self.response
        for response,reason,calls in [
            (Response(302,{'Location':'https://127.0.0.1/'}),'unsafe_redirect',1),
            (Response(302,{'Location':'/loop'}),'redirect_limit',4),
            (Response(headers={'Content-Type':'text/html','Content-Encoding':'gzip'}),'compressed_response',1),
            (Response(data=b'x'*(2*1024*1024+1)),'too_large',1),
            (Response(401),'unavailable',1)]:
            session=Session(response)
            with patch.object(m.aiohttp,'ClientSession',return_value=session), patch.object(m.aiohttp,'TCPConnector'):
                with self.assertRaisesRegex(m.MatchError,reason): await m.MatchService().match(URL)
            self.assertEqual(session.calls,calls)
        service=m.MatchService()
        with patch.object(service,'_fetch',new_callable=AsyncMock,return_value=('Title',[('Spotify',URL)])):
            for i in range(130): await service.match('https://www.deezer.com/track/'+str(i))
            self.assertEqual(len(service.cache),128)
        with patch.object(service,'_fetch',new_callable=AsyncMock,side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError): await service.match(URL)
            self.assertEqual(service.active,0)

    async def test_routing_scope_first_url_and_skip(self):
        try:
            from handlers.music import MusicFilter, music_links, service
        except ImportError:
            self.fail('music router missing')
        from handlers import all_routers
        self.assertEqual([r.name for r in all_routers()][:2], ['instagram','music'])
        def msg(text=URL, **kwargs):
            data = {'message_id':12,'date':1700000000,'chat':{'id':-1003911850060,'type':'supergroup'},'from':{'id':42,'is_bot':False,'first_name':'Test'},'text':text}
            data.update(kwargs)
            return Message.model_validate(data)
        f = MusicFilter()
        self.assertEqual(await f(msg()), {'music_url':URL})
        self.assertFalse(await f(msg('https://example.com ' + URL)))
        self.assertFalse(await f(msg('hello', reply_to_message=msg().model_dump(by_alias=True))))
        self.assertFalse(await f(msg(chat={'id':2414729,'type':'private'})))
        self.assertFalse(await f(msg(chat={'id':-99,'type':'supergroup'})))
        self.assertFalse(await f(msg(**{'from':{'id':42,'is_bot':True,'first_name':'Bot'}})))
        for field in ('audio','photo','video','document','animation','voice','sticker','video_note'):
            self.assertFalse(await f(msg().model_copy(update={field:object()})))
        with patch.object(service,'match',new_callable=AsyncMock) as match, patch.object(Message,'reply',new_callable=AsyncMock) as reply:
            from services.music_match import MatchError
            match.side_effect = MatchError('busy')
            with self.assertRaises(SkipHandler): await music_links(msg(),URL)
            reply.assert_awaited_once()
            self.assertIn('занят',reply.call_args.args[0])
        import asyncio
        with patch.object(service,'match',new_callable=AsyncMock,side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError): await music_links(msg(),URL)

if __name__ == '__main__': unittest.main()
