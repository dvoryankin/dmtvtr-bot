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
    images = embedded_photo_urls(text, expected_url=url, signal_video=True)
    if not images:
        raise DownloadError('no_video')
    data = fetch(images[0], MAX_PHOTO)
    name = '01' + photo_extension(data)
    (directory / name).write_bytes(data)
    (directory / 'manifest.json').write_text(json.dumps({
        'version': 1, 'coverage': ('embed_single_image'
                                 if single_image_inventory(text, url, images[0])
                                 else 'embed_first_image'),
        'items': [{'type': 'photo', 'file': name}]}))


def single_image_inventory(text, expected_url, image_url):
    """Positive GraphImage inventory only, independently of the partial fallback.

    HTMLParser is tolerant of broken HTML: require a balanced, unambiguous
    structure ourselves. Standard void elements must never enter the stack.
    Duplicate attributes/elements are ambiguity, even with identical values.
    """
    void = frozenset('area base br col embed hr img input link meta param source track wbr'.split())

    class Inventory(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.roots, self.anchors, self.images = [], [], [], []
            self.valid = True

        def handle_starttag(self, tag, attrs):
            if len(dict(attrs)) != len(attrs):
                self.valid = False
            attrs = dict(attrs)
            node = (tag, attrs)
            classes = (attrs.get('class') or '').split()
            ancestors = tuple(self.stack)
            if 'Embed' in classes:
                self.roots.append(node)
            if tag == 'a':
                if any(t == 'a' for t, _ in self.stack):
                    self.valid = False
                if 'EmbeddedMedia' in classes:
                    self.anchors.append((node, ancestors))
            if tag == 'img' and 'EmbeddedMediaImage' in classes:
                self.images.append((node, ancestors))
            if tag not in void:
                self.stack.append(node)

        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs)
            if tag not in void:
                self.handle_endtag(tag)

        def handle_endtag(self, tag):
            if not self.stack or self.stack[-1][0] != tag:
                self.valid = False
            else:
                self.stack.pop()

    parser = Inventory()
    try:
        parser.feed(text)
        # close() turns incomplete tags/comments into ordinary text. Do not
        # let that tolerant recovery erase evidence of a truncated document.
        if parser.rawdata:
            parser.valid = False
        parser.close()
    except Exception:
        return False
    expected = canonical_url(expected_url)
    # HTML permits omitted body/html end tags (both real captures do this).
    # No media/container/anchor or other unclosed element is permissible.
    unclosed = tuple(node[0] for node in parser.stack)
    if (not expected or not parser.valid
            or unclosed not in ((), ('html',), ('body',), ('html', 'body'))
            or len(parser.roots) != 1 or len(parser.anchors) != 1
            or len(parser.images) != 1):
        return False
    root = parser.roots[0]
    anchor, anchor_parents = parser.anchors[0]
    image, image_parents = parser.images[0]
    return (root[0] == 'div' and root[1].get('data-media-type') == 'GraphImage'
            and canonical_url(root[1].get('data-permalink', '')) == expected
            and canonical_url(anchor[1].get('href', '')) == expected
            and any(node is root for node in anchor_parents)
            and any(node is root for node in image_parents)
            and next((node for node in reversed(image_parents) if node[0] == 'a'), None) is anchor
            and image[1].get('src') == image_url)


def embedded_photo_urls(text, expected_url=None, signal_video=False):
    class Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.urls = []
            self.post_anchor = False
            self.video_embed = False

        def handle_starttag(self, tag, attrs):
            # A missing video format is not proof that its cover is a photo.
            # Inspect all occurrences before dict conversion: duplicate type
            # attributes must not hide an explicit GraphVideo contradiction.
            if (any(k == 'class' and 'Embed' in (v or '').split() for k, v in attrs)
                    and any(k == 'data-media-type' and v == 'GraphVideo' for k, v in attrs)):
                self.video_embed = True
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
    if parser.video_embed and signal_video:
        # Positive video evidence contradicts the extractor's no_video. Reuse
        # the parent's existing bounded empty-metadata retry, never its cover.
        raise DownloadError('Instagram sent an empty media response')
    # More than one explicit main image is ambiguous rather than a proven album.
    return parser.urls if not parser.video_embed and len(parser.urls) == 1 else []
