"""Only public, direct HTTPS MP4 files on the exact idiod.video host."""
import re
from urllib.parse import urlsplit

URL_RE = re.compile(r'https?://[^\s<>]+')


def canonical_url(value):
    if not isinstance(value, str) or re.search(r'[\s\\\x00-\x1f\x7f]', value):
        return None
    try:
        p = urlsplit(value)
        if (p.scheme != 'https' or p.hostname != 'idiod.video'
                or p.username is not None or p.password is not None
                or p.port not in (None, 443) or p.query or p.fragment
                or '?' in value or '#' in value
                or not re.fullmatch(r'/[A-Za-z0-9_-]{1,128}\.mp4', p.path)):
            return None
        return 'https://idiod.video' + p.path
    except ValueError:
        return None


import asyncio
import socket
import aiohttp
from services.instagram_network import public_ip


class GuardResolver(aiohttp.abc.AbstractResolver):
    async def resolve(self, host, port=443, family=socket.AF_UNSPEC):
        if host != 'idiod.video' or port != 443:
            raise ValueError('network_guard')
        # Deliberately request ALL families even if connector asks for IPv4.
        rows = await asyncio.get_running_loop().run_in_executor(
            None, lambda: socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM))
        if not rows or any(not public_ip(row[4][0]) for row in rows):
            raise ValueError('network_guard')
        return [dict(hostname=host, host=row[4][0], port=443, family=row[0],
                     proto=row[2], flags=socket.AI_NUMERICHOST) for row in rows]

    async def close(self):
        pass


MAX_FILE = 45 * 1024 * 1024


async def fetch(session, url, path, limit=MAX_FILE):
    if not canonical_url(url):
        raise ValueError('network_guard')
    async with session.get(url, allow_redirects=False) as response:
        if response.status != 200:
            raise ValueError('http_error')
        if (response.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'video/mp4'
                or response.headers.get('Content-Encoding', 'identity') != 'identity'):
            raise ValueError('invalid_file')
        expected = response.content_length
        limit = min(limit, MAX_FILE)
        if expected is not None and expected > limit:
            raise ValueError('too_large')
        size = 0
        with path.open('wb') as output:
            async for chunk in response.content.iter_chunked(65536):
                size += len(chunk)
                if size > limit:
                    raise ValueError('too_large')
                output.write(chunk)
        if not size or expected is not None and size != expected:
            raise ValueError('invalid_file')
        return size


import tempfile
from pathlib import Path
from collections import namedtuple
from services.instagram_video_metadata import probe_video_dimensions

Item = namedtuple('Item', 'value width height')


class IdiodService:
    def __init__(self, allowed_chats):
        self.allowed_chats = set(allowed_chats)
        self.pending = 0
        self.chats = {}
        self.locks = {}
        self.active = None  # Python 3.8: construct only in the runtime loop.
        self.inflight = set()
        self.receipts = {}  # Bounded incoming-update receipts, not a media cache.

    async def handle(self, chat, url, send, message_id=None):
        url = canonical_url(url)
        if chat not in self.allowed_chats or not url:
            raise ValueError('scope')
        key = (chat, url)
        receipt = (chat, message_id, url)
        if key in self.inflight or message_id is not None and receipt in self.receipts:
            return False
        if self.pending >= 20 or self.chats.get(chat, 0) >= 10:
            raise ValueError('busy')
        if message_id is not None:
            self.receipts[receipt] = True
            if len(self.receipts) > 2048:
                self.receipts.pop(next(iter(self.receipts)))
        self.inflight.add(key)
        self.pending += 1
        self.chats[chat] = self.chats.get(chat, 0) + 1
        if self.active is None:
            self.active = asyncio.Semaphore(2)
        lock = self.locks.setdefault(chat, asyncio.Lock())
        locked = active = False
        async def acquire():
            nonlocal locked, active
            await lock.acquire()
            locked = True
            await self.active.acquire()
            active = True
        try:
            await asyncio.wait_for(acquire(), 900)
            return await asyncio.wait_for(self._download_send(url, send), 90)
        finally:
            if active:
                self.active.release()
            if locked:
                lock.release()
            self.inflight.discard(key)
            self.pending -= 1
            self.chats[chat] -= 1
            if not self.chats[chat]:
                self.chats.pop(chat)
                self.locks.pop(chat, None)

    async def _download_send(self, url, send):
        with tempfile.TemporaryDirectory(prefix='idiod-video-') as tmp:
            path = Path(tmp) / 'video.mp4'
            connector = aiohttp.TCPConnector(resolver=GuardResolver(), use_dns_cache=False)
            async with aiohttp.ClientSession(
                    connector=connector, trust_env=False, auto_decompress=False,
                    cookie_jar=aiohttp.DummyCookieJar(),
                    headers={'Accept-Encoding': 'identity'},
                    timeout=aiohttp.ClientTimeout(total=90)) as session:
                await fetch(session, url, path)
            with path.open('rb') as stream:
                header = stream.read(32)
            if header[4:8] != b'ftyp':
                raise ValueError('invalid_file')
            dims = await probe_video_dimensions(path)
            if not dims:
                raise ValueError('invalid_file')
            return bool(await send([Item(path, *dims)]))
