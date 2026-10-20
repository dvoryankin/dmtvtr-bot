"""Public Songlink HTML matching; no API keys, audio, or provider URL fetching."""
import asyncio
import html
import ipaddress
import re
import socket
import time
from collections import OrderedDict
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode, quote, urljoin
import aiohttp


class MatchError(Exception):
    pass


def album_link(value):
    if not isinstance(value, str) or len(value) > 2048 or re.search(r'[\s\\\x00-\x1f]', value):
        return None
    try:
        p = urlsplit(value)
        if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443):
            return None
        host, path = p.hostname, p.path.rstrip('/')
        query = parse_qs(p.query, keep_blank_values=True)
        if 'i' in query or 'trackAsin' in query:
            return None
        patterns = [
            ('Spotify', ('open.spotify.com',), r'/album/[A-Za-z0-9]{22}'),
            ('Apple Music', ('music.apple.com',), r'/[a-z]{2}/album/[^/]+/\d+'),
            ('Deezer', ('deezer.com', 'www.deezer.com'), r'/(?:[a-z]{2}/)?album/\d+'),
            ('Яндекс Музыка', ('music.yandex.ru', 'music.yandex.com', 'music.yandex.kz'), r'/album/\d+'),
            ('Amazon Music', ('music.amazon.com','music.amazon.co.uk','music.amazon.de','music.amazon.co.jp','music.amazon.fr','music.amazon.it','music.amazon.es','music.amazon.ca','music.amazon.com.au'), r'/albums/[A-Z0-9]{10}'),
            ('Tidal', ('tidal.com', 'listen.tidal.com'), r'/(?:browse/)?album/\d+'),
            ('Anghami', ('play.anghami.com',), r'/album/\d+'),
            ('Boomplay', ('boomplay.com', 'www.boomplay.com'), r'/albums/\d+'),
        ]
        for label, hosts, pattern in patterns:
            if host in hosts and re.fullmatch(pattern, path):
                host = 'www.deezer.com' if label == 'Deezer' else host
                return label, urlunsplit(('https', host, path, '', ''))
        lists = query.get('list', [])
        if host == 'music.youtube.com' and path == '/playlist' and len(lists) == 1 and re.fullmatch(r'OLAK5uy_[A-Za-z0-9_-]+', lists[0]) and 'v' not in query:
            return 'YouTube Music', urlunsplit(('https', host, path, urlencode({'list': lists[0]}), ''))
    except (ValueError, TypeError):
        pass
    return None


def canonical_url(value):
    album = album_link(value)
    if album:
        return album[1]
    if not isinstance(value, str) or len(value) > 2048 or re.search(r'[\s\\\x00-\x1f]', value):
        return None
    try:
        p = urlsplit(value)
        if p.scheme != 'https' or p.username or p.password or p.port not in (None,443):
            return None
        host, path = p.hostname, p.path.rstrip('/')
        query = ''
        if host == 'open.spotify.com' and re.fullmatch(r'/track/[A-Za-z0-9]{22}', path):
            pass
        elif host in ('music.apple.com',) and re.fullmatch(r'/[a-z]{2}/(?:album|song)/[^/]+/\d+', path):
            song = parse_qs(p.query).get('i', [''])[0]
            if '/album/' in path and not song.isdigit(): return None
            query = urlencode({'i':song}) if song.isdigit() else ''
        elif host in ('deezer.com','www.deezer.com') and re.fullmatch(r'/(?:[a-z]{2}/)?track/\d+',path):
            host = 'www.deezer.com'
        elif host in ('music.yandex.ru','music.yandex.com','music.yandex.kz') and re.fullmatch(r'/(?:album/\d+/)?track/\d+',path):
            pass
        elif host in ('soundcloud.com','www.soundcloud.com') and re.fullmatch(r'/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+',path) and path.split('/')[1] not in ('discover','search','charts','stations','you','sets') and path.split('/')[2] not in ('sets','tracks','albums','likes','reposts'):
            host = 'soundcloud.com'
        elif host == 'music.youtube.com' and path == '/watch' and re.fullmatch(r'[A-Za-z0-9_-]{11}',parse_qs(p.query).get('v',[''])[0]):
            query = urlencode({'v':parse_qs(p.query)['v'][0]})
        else:
            return None
        return urlunsplit(('https',host,path,query,''))
    except (ValueError,TypeError):
        return None


def matched_link(value, kind='track'):
    if kind == 'album':
        return album_link(value)
    if kind != 'track' or album_link(value):
        return None
    canonical = canonical_url(value)
    if canonical:
        host = urlsplit(canonical).hostname
        label = ('Spotify' if host == 'open.spotify.com' else 'Apple Music' if host == 'music.apple.com' else 'Deezer' if 'deezer' in host else 'Яндекс Музыка' if 'yandex' in host else 'SoundCloud' if 'soundcloud' in host else 'YouTube Music')
        return label, canonical
    try:
        p = urlsplit(value)
        if p.scheme != 'https' or p.username or p.password or p.port not in (None,443) or re.search(r'[\s\\\x00-\x1f]',value): return None
        host = p.hostname
        if host in ('music.amazon.com','music.amazon.co.uk','music.amazon.de','music.amazon.co.jp','music.amazon.fr','music.amazon.it','music.amazon.es','music.amazon.ca','music.amazon.com.au'):
            track = parse_qs(p.query).get('trackAsin',[''])[0]
            if re.fullmatch(r'/albums/[A-Z0-9]{10}',p.path) and re.fullmatch(r'[A-Z0-9]{10}',track):
                return 'Amazon Music', urlunsplit(('https',host,p.path,urlencode({'trackAsin':track}),''))
            if re.fullmatch(r'/tracks/[A-Z0-9]{10}',p.path):
                return 'Amazon Music', urlunsplit(('https',host,p.path,'',''))
        patterns = [
            ('Amazon', ('amazon.com','www.amazon.com'), r'/dp/[A-Z0-9]{10}'),
            ('Pandora', ('pandora.com','www.pandora.com'), r'/TR:\d+'),
            ('Anghami', ('play.anghami.com',), r'/song/\d+'),
            ('Boomplay', ('boomplay.com','www.boomplay.com'), r'/songs/\d+'),
            ('SoundCloud', ('api.soundcloud.com',), r'/tracks/\d+'),
        ]
        for label, hosts, pattern in patterns:
            if host in hosts and re.fullmatch(pattern,p.path):
                return label, urlunsplit(('https',host,p.path,'',''))
        if host in ('youtube.com','www.youtube.com') and p.path == '/watch':
            video = parse_qs(p.query).get('v',[''])[0]
            if re.fullmatch(r'[A-Za-z0-9_-]{11}',video):
                return 'YouTube', urlunsplit(('https',host,p.path,urlencode({'v':video}),''))
        if p.hostname in ('tidal.com','listen.tidal.com') and re.fullmatch(r'/(?:browse/)?track/\d+',p.path):
            return 'Tidal', urlunsplit(('https',p.hostname,p.path,'',''))
    except (ValueError,TypeError):
        pass
    return None


def public_ip(value):
    try:
        ip = ipaddress.ip_address(value)
        return ip.is_global and not ip.is_multicast and not ip.is_reserved and not getattr(ip, 'ipv4_mapped', None)
    except ValueError:
        return False


def validate_endpoint(value):
    try:
        p = urlsplit(value)
        if (p.scheme != 'https' or p.hostname not in ('song.link', 'album.link') or p.username or p.password
                or p.port not in (None,443) or re.search(r'[\s\\\\\x00-\x1f]',value)):
            raise ValueError()
    except (ValueError,TypeError):
        raise MatchError('unsafe_redirect')
    return value


class PublicResolver(aiohttp.abc.AbstractResolver):
    async def resolve(self, host, port=0, family=socket.AF_INET):
        if host not in ('song.link', 'album.link') or port != 443: raise MatchError('unsafe_host')
        records = await asyncio.get_running_loop().getaddrinfo(host, port, family=family, type=socket.SOCK_STREAM)
        if not records or any(not public_ip(r[4][0]) for r in records): raise MatchError('unsafe_dns')
        # aiohttp connects directly to these numeric IPs; TLS retains song.link SNI.
        return [dict(hostname=host, host=r[4][0], port=port, family=r[0], proto=r[2], flags=socket.AI_NUMERICHOST) for r in records]
    async def close(self):
        pass


class MatchService:
    def __init__(self):
        self.active = 0
        self.cache = OrderedDict()
    async def match(self, url):
        url = canonical_url(url)
        if not url: raise MatchError('invalid_url')
        now = time.monotonic()
        cached = self.cache.get(url)
        if cached and cached[0] > now:
            self.cache.move_to_end(url)
            return cached[1]
        if self.active >= 2: raise MatchError('busy')
        self.active += 1
        try:
            result = await asyncio.wait_for(self._fetch(url), timeout=20)
            self.cache[url] = (time.monotonic()+900,result)
            self.cache.move_to_end(url)
            while len(self.cache) > 128: self.cache.popitem(last=False)
            return result
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, UnicodeError, ValueError):
            raise MatchError('unavailable') from None
        finally:
            self.active -= 1
    async def _fetch(self, url):
        kind = 'album' if album_link(url) else 'track'
        endpoint = 'https://{}/'.format('album.link' if kind == 'album' else 'song.link') + quote(url, safe='')
        connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False, limit=2)
        async with aiohttp.ClientSession(connector=connector, trust_env=False, auto_decompress=False,
                timeout=aiohttp.ClientTimeout(total=18, connect=6),
                headers={'Accept-Encoding':'identity','User-Agent':'dmtvtr-music-links/1.0'}) as session:
            for step in range(4):
                validate_endpoint(endpoint)
                async with session.get(endpoint, allow_redirects=False) as response:
                    if response.status in (301,302,303,307,308):
                        location = response.headers.get('Location')
                        if not location: raise MatchError('unavailable')
                        endpoint = urljoin(endpoint,location)
                        continue
                    if response.status != 200: raise MatchError('unavailable')
                    if response.headers.get('Content-Encoding','identity').lower() not in ('','identity'):
                        raise MatchError('compressed_response')
                    if 'text/html' not in response.headers.get('Content-Type','').lower(): raise MatchError('not_html')
                    chunks, size = [], 0
                    async for chunk in response.content.iter_chunked(32768):
                        size += len(chunk)
                        if size > 2 * 1024 * 1024: raise MatchError('too_large')
                        chunks.append(chunk)
                    return parse_page(b''.join(chunks).decode('utf-8'), kind=kind, source_url=url if kind == 'album' else None)
            raise MatchError('redirect_limit')


class Page(HTMLParser):
    def __init__(self, kind='track'):
        super().__init__(convert_charrefs=True)
        self.kind = kind
        self.title = ''
        self.in_title = False
        self.links = OrderedDict()
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'title' and not self.title: self.in_title = True
        if tag == 'a':
            link = matched_link(attrs.get('href',''), kind=self.kind)
            if link and link[0] not in self.links: self.links[link[0]] = link[1]
    def handle_endtag(self, tag):
        if tag == 'title': self.in_title = False
    def handle_data(self, data):
        if self.in_title: self.title += data[:500]


def parse_page(text, kind='track', source_url=None):
    parser = Page(kind=kind)
    parser.feed(text)
    title = re.sub(r'\s*[-|]\s*(?:Songlink|Odesli|song\.link).*$', '', parser.title, flags=re.I).strip()[:300]
    if not title or not parser.links or title.lower() in ('songlink','odesli'): raise MatchError('unavailable')
    if kind == 'album' and (len(parser.links) < 2 or (source_url is not None and source_url not in parser.links.values())):
        raise MatchError('album_unavailable')
    return title, list(parser.links.items())


def render(result):
    title, links = result
    # Telegram previews the first eligible link: prefer compact Deezer cards.
    links = sorted(links, key=lambda item: item[0] != 'Deezer')
    return '<b>{}</b>\n{}'.format(html.escape(title), ' | '.join('<a href="{}">{}</a>'.format(html.escape(url,quote=True),html.escape(label)) for label,url in links))
