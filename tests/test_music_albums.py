import unittest
from pathlib import Path
from services import music_match as m

ALBUM = 'https://open.spotify.com/album/18XNebQMj5PyWj2XgLsz3L'

class AlbumTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_fixture_fetch_album_type_and_scoped_network(self):
        from unittest.mock import patch
        import socket
        m.validate_endpoint('https://album.link/s/abc')
        loop = __import__('asyncio').get_running_loop()
        with patch.object(loop, 'getaddrinfo', return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]):
            self.assertEqual((await m.PublicResolver().resolve('album.link',443))[0]['host'], '8.8.8.8')
        class Response:
            status = 200
            headers = {'Content-Type':'text/html'}
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            @property
            def content(self): return self
            async def iter_chunked(self,n): yield (Path(__file__).parent/'fixtures/spotify_album.html').read_bytes()
        class Session:
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            def get(self,url,**kwargs):
                self_url.append(url)
                return Response()
        self_url=[]
        with patch.object(m.aiohttp,'ClientSession',return_value=Session()), patch.object(m.aiohttp,'TCPConnector'):
            result = await m.MatchService().match(ALBUM)
        self.assertEqual(result[1], [('Spotify',ALBUM),('Deezer','https://www.deezer.com/album/11793738')])
        self.assertTrue(self_url[0].startswith('https://album.link/'))

    async def test_album_safe_failure_message(self):
        from unittest.mock import AsyncMock, patch
        from aiogram.types import Message
        from aiogram.dispatcher.event.bases import SkipHandler
        from handlers.music import music_links, service
        msg=Message.model_validate({'message_id':1,'date':1700000000,'chat':{'id':-1003911850060,'type':'supergroup'},'text':ALBUM})
        with patch.object(service,'match',new_callable=AsyncMock,side_effect=m.MatchError('unavailable')), patch.object(Message,'reply',new_callable=AsyncMock) as reply:
            with self.assertRaises(SkipHandler): await music_links(msg,ALBUM)
            self.assertIn('альбом',reply.call_args.args[0])
            self.assertNotIn('трек',reply.call_args.args[0])

class AlbumTests(unittest.TestCase):
    def test_real_album_html_and_typed_links(self):
        text = (Path(__file__).parent/'fixtures/spotify_album.html').read_text()
        title, links = m.parse_page(text, kind='album')
        self.assertEqual(title, 'Время песок ... by Gosti iz Budushchego')
        self.assertEqual(links, [('Spotify', ALBUM), ('Deezer', 'https://www.deezer.com/album/11793738')])
        self.assertTrue(m.render((title, links)).split('\n')[1].startswith('<a href="https://www.deezer.com/album/'))

    def test_album_platform_types(self):
        examples = [
            ('Apple Music', 'https://music.apple.com/us/album/an-awesome-wave/12345'),
            ('Deezer', 'https://www.deezer.com/album/11793738'),
            ('Яндекс Музыка', 'https://music.yandex.ru/album/12345'),
            ('Amazon Music', 'https://music.amazon.com/albums/B06XSTDBSM'),
            ('Tidal', 'https://tidal.com/browse/album/12345'),
            ('YouTube Music', 'https://music.youtube.com/playlist?list=OLAK5uy_test'),
            ('Anghami', 'https://play.anghami.com/album/12345'),
            ('Boomplay', 'https://www.boomplay.com/albums/12345'),
        ]
        for label, url in examples:
            with self.subTest(url=url):
                self.assertEqual(m.matched_link(url, kind='album'), (label, url))
                self.assertIsNone(m.matched_link(url))
        tracks = [ALBUM.replace('/album/', '/track/'),
            examples[0][1]+'?i=23456', examples[0][1]+'?i=',
            'https://music.apple.com/us/song/track/12345',
            'https://www.deezer.com/track/12345',
            'https://music.yandex.ru/album/12345/track/23456',
            examples[3][1]+'?trackAsin=B06XSVS86F', examples[3][1]+'?trackAsin=',
            'https://tidal.com/track/12345',
            'https://music.youtube.com/watch?v=abcdefghijk',
            'https://music.youtube.com/playlist?list=PL_arbitrary',
            'https://amazon.com/dp/B06XSTDBSM']
        for url in tracks:
            with self.subTest(url=url): self.assertIsNone(m.matched_link(url, kind='album'))

    def test_album_mapping_requires_source_and_other_album(self):
        with self.assertRaises(m.MatchError):
            m.parse_page('<title>Album</title><a href="'+ALBUM+'">source</a>',kind='album',source_url=ALBUM)
        wrong = ALBUM.replace('18XNebQMj5PyWj2XgLsz3L','5VykLQtjCYF6qFq59HbUg9')
        with self.assertRaises(m.MatchError):
            m.parse_page('<title>Album</title><a href="'+wrong+'">source</a><a href="https://www.deezer.com/album/11793738">album</a>',kind='album',source_url=ALBUM)
        text=(Path(__file__).parent/'fixtures/spotify_album.html').read_text()
        text += '<a href="https://music.apple.com/us/album/name/12345?i=23456">track</a><a href="https://music.amazon.com/albums/B06XSTDBSM?trackAsin=B06XSVS86F">track</a>'
        self.assertEqual(len(m.parse_page(text,kind='album',source_url=ALBUM)[1]),2)

    def test_album_input(self):
        self.assertEqual(m.canonical_url(ALBUM+'?si=secret'), ALBUM)
        self.assertEqual(m.matched_link(ALBUM, kind='album'), ('Spotify', ALBUM))
