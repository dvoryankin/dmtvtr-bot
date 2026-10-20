"""Public embed's explicit post image only; never avatars, OG or recommendations.

An embed may expose just the first slide. Do not label it a complete carousel.
Called only after yt-dlp conclusively reports no_video, under socket guard.
"""
from html.parser import HTMLParser
import json
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler, Request
from instagram_download import canonical_url, DownloadError
from instagram_network import allowed_host

MAX_PHOTO = 10 * 1024 * 1024
MAX_HTML = 2 * 1024 * 1024


def validate_fetch_url(url):
    p = urlsplit(url)
    if (p.scheme != 'https' or not allowed_host(p.hostname)
            or p.port not in (None, 443) or p.username is not None
            or p.password is not None or any(ord(c) < 33 for c in url)):
        raise ValueError('Outbound host/port denied')
    return url


class SafeRedirect(HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_fetch_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, limit):
    # Socket guard is installed by worker before this code is ever invoked.
    # Every request + redirect also enforces HTTPS, port and explicit hostname.
    opener = build_opener(ProxyHandler({}), SafeRedirect())
    request = Request(validate_fetch_url(url), headers={'User-Agent': 'Mozilla/5.0',
                                                       'Accept-Encoding': 'identity'})
    with opener.open(request, timeout=8) as response:
        validate_fetch_url(response.geturl())
        length = response.headers.get('Content-Length')
        if length is not None and int(length) > limit:
            raise DownloadError('too_large')
        data = response.read(limit + 1)
        if len(data) > limit:
            raise DownloadError('too_large')
        return data


def photo_extension(data):
    if data.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return '.webp'
    raise DownloadError('invalid_file')


def download_photo(url, directory):
    # Do not turn a partial video playlist or a failed video into its thumbnail.
    if any(directory.glob('*.mp4')) or any(directory.glob('*.part')):
        raise DownloadError('no_video')
    text = fetch(url + 'embed/', MAX_HTML).decode('utf-8')
    images = embedded_photo_urls(text, expected_url=url)
    if not images:
        raise DownloadError('no_video')
    data = fetch(images[0], MAX_PHOTO)
    name = '01' + photo_extension(data)
    (directory / name).write_bytes(data)
    (directory / 'manifest.json').write_text(json.dumps({
        'version': 1, 'coverage': 'embed_first_image',
        'items': [{'type': 'photo', 'file': name}]}))


def embedded_photo_urls(text, expected_url=None):
    class Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.urls = []
            self.post_anchor = False

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'a':
                self.post_anchor = ('EmbeddedMedia' in attrs.get('class', '').split()
                                    and canonical_url(attrs.get('href', '')) == expected_url)
            if (tag == 'img' and 'EmbeddedMediaImage' in attrs.get('class', '').split()
                    and (expected_url is None or self.post_anchor)):
                url = attrs.get('src')
                if url and url not in self.urls:
                    self.urls.append(url)

        def handle_endtag(self, tag):
            if tag == 'a':
                self.post_anchor = False
    parser = Parser()
    parser.feed(text)
    # More than one explicit main image is ambiguous rather than a proven album.
    return parser.urls if len(parser.urls) == 1 else []
