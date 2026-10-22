"""Public Instagram media; no credentials or third-party APIs."""
from __future__ import annotations

import re
import json
import asyncio
from collections import OrderedDict, namedtuple
from pathlib import Path
import tempfile
import time
import logging
try:
    from .instagram_diagnostics import context, read_diagnostic
except ImportError:
    from instagram_diagnostics import context, read_diagnostic
from urllib.parse import urlsplit


class DownloadError(Exception):
    """A bounded, expected failure; never surface raw downloader errors to chat."""


class DownloadService:
    def __init__(self, base_dir, allowed_chats, runner=None, clock=time.monotonic):
        self.base_dir = Path(base_dir)
        self.allowed_chats = frozenset(allowed_chats)
        self.runner = runner or self.run_worker
        self.clock = clock
        self.active = set()
        self.inflight = set()
        self.cache = OrderedDict()
        self.pending = {}
        self.chat_locks = {}
        self.network_slots = None
        self.queue_timeout = 900

    async def handle(self, chat_id, url, send, message_id=None):
        url = canonical_url(url)
        if chat_id not in self.allowed_chats or not url:
            raise DownloadError('scope')
        if (url in self.inflight or self.pending.get(chat_id, 0) >= 10
                or sum(self.pending.values()) >= 20):
            raise DownloadError('busy')
        # Python 3.8 binds semaphores to the construction loop: initialize only
        # inside the running bot loop, not at module import.
        if self.network_slots is None:
            self.network_slots = asyncio.Semaphore(2)
        # Admission is atomic until the first await. Counts include active jobs.
        self.pending[chat_id] = self.pending.get(chat_id, 0) + 1
        lock = self.chat_locks.setdefault(chat_id, asyncio.Lock())
        self.inflight.add(url)
        acquired_chat = acquired_slot = False
        deadline = self.clock() + self.queue_timeout
        try:
            await asyncio.wait_for(lock.acquire(), max(0, deadline - self.clock()))
            acquired_chat = True
            await asyncio.wait_for(self.network_slots.acquire(), max(0, deadline - self.clock()))
            acquired_slot = True
            self.active.add(chat_id)
            await self._execute(chat_id, url, send, message_id)
        except asyncio.TimeoutError:
            raise DownloadError('timeout') from None
        finally:
            if acquired_slot:
                self.active.discard(chat_id)
                self.network_slots.release()
            if acquired_chat:
                lock.release()
            self.inflight.discard(url)
            self.pending[chat_id] -= 1
            if not self.pending[chat_id]:
                del self.pending[chat_id]
                del self.chat_locks[chat_id]

    async def _execute(self, chat_id, url, send, message_id):
        now = self.clock()
        token = context.set('message_id=%s chat=%s' % (message_id, chat_id))
        try:
            cached = self.cache.get(url)
            if cached and now - cached[0] < 3600:
                try:
                    await asyncio.wait_for(send(cached[1]), timeout=60)
                except Exception:
                    self.cache.pop(url, None)
                    raise
                return
            self.cache.pop(url, None)
            deadline = self.clock() + 90
            for attempt in range(3):
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise DownloadError('timeout')
                with tempfile.TemporaryDirectory(prefix='dmtvtr-instagram-') as raw:
                    directory = Path(raw)
                    try:
                        await asyncio.wait_for(self.runner(url, directory), timeout=min(28, remaining))
                        files = validate_files(directory)
                    except (DownloadError, asyncio.TimeoutError) as exc:
                        code = 'timeout' if isinstance(exc, asyncio.TimeoutError) else str(exc)
                        if code not in {'unavailable', 'timeout', 'empty_media', 'api_denied', 'login_or_rate_limit'} or attempt == 2:
                            raise DownloadError(code) from None
                        logging.info('Instagram retry %s attempt=%s reason=%s', context.get(), attempt + 1, code)
                    else:
                        # Sending is deliberately outside the download retry boundary.
                        remaining = deadline - self.clock()
                        if remaining <= 0:
                            raise DownloadError('timeout')
                        ids = await asyncio.wait_for(send(files), timeout=min(60, remaining))
                        if ids and len(ids) == len(files):
                            self.cache[url] = (self.clock(), [
                                MediaItem(media_type(item), file_id,
                                          getattr(item, 'width', None), getattr(item, 'height', None),
                                          getattr(item, 'coverage', None))
                                for item, file_id in zip(files, ids)])
                            while len(self.cache) > 128:
                                self.cache.popitem(last=False)
                        return
                # Failed attempt's files are removed before backoff/retry.
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise DownloadError('timeout')
                await asyncio.sleep(min(attempt + 1, remaining))
        finally:
            context.reset(token)

    async def run_worker(self, url, directory):
        started = time.monotonic()
        python = self.base_dir / '.instagram-venv/bin/python'
        worker = self.base_dir / 'services/instagram_worker.py'
        process = await asyncio.create_subprocess_exec(
            str(python), '-I', str(worker), url, str(directory),
            cwd=str(directory),
            env={'PATH': '/usr/bin:/bin', 'HOME': str(directory),
                 'TMPDIR': str(directory), 'LANG': 'C.UTF-8'},
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            code = await process.wait()
            if code:
                diagnostic = json.loads(read_diagnostic(directory))
                reason = diagnostic['code']
                if reason == 'http_error' and diagnostic['http_status'] in {408, 425, 429, 500, 502, 503, 504}:
                    reason = 'unavailable'
                elif reason in {'unknown', 'csrf_missing'}:
                    reason = 'unavailable'
                raise DownloadError(reason)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
            normalized = canonical_url(url)
            shortcode = normalized.rstrip('/').rsplit('/', 1)[-1] if normalized else 'invalid'
            logging.info('Instagram worker shortcode=%s %s elapsed=%.3f returncode=%s diagnostic=%s',
                         shortcode, context.get(), time.monotonic() - started,
                         process.returncode, read_diagnostic(directory))


MediaItem = namedtuple('MediaItem', 'type value width height coverage', defaults=(None, None, None))


def media_complete(item):
    coverage = getattr(item, 'coverage', None)
    # Legacy video runners/IDs retain their established delivery contract.
    # Photos need positive evidence: an embed or missing marker is not inventory.
    return (coverage == 'complete'
            or (media_type(item) == 'photo' and coverage == 'embed_single_image')
            or (media_type(item) == 'video' and coverage in (None, 'extracted_videos')))


def media_type(item):
    return item.type if isinstance(item, MediaItem) else 'video'


def media_value(item):
    return item.value if isinstance(item, MediaItem) else item


def prepare_photo(path):
    # Pillow already belongs to the main bot's Python 3.8 environment. The
    # credential-free 3.12 worker only fetches bytes; no new dependency there.
    from PIL import Image
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(path) as image:
                width, height = image.size
                if (image.format not in {'JPEG', 'PNG', 'WEBP'}
                        or min(width, height) < 161 or width * height > 20000000
                        or width + height > 10000 or max(width, height) / min(width, height) > 20
                        or getattr(image, 'n_frames', 1) != 1):
                    raise DownloadError('invalid_file')
                image.verify()
            target = path.with_name('prepared_' + path.stem + '.jpg')
            if target.is_symlink():
                raise DownloadError('invalid_file')
            with Image.open(path) as image:
                image.convert('RGB').save(target, format='JPEG', quality=92)
            if target.stat().st_size > 10 * 1024 * 1024:
                raise DownloadError('too_large')
            return target
    except DownloadError:
        raise
    except Exception:
        raise DownloadError('invalid_file') from None


def validate_files(directory, decode_photos=True):
    manifest = directory / 'manifest.json'
    typed = manifest.exists() or manifest.is_symlink()
    if typed:
        try:
            if manifest.is_symlink() or manifest.stat().st_size > 8192:
                raise ValueError()
            data = json.loads(manifest.read_text())
            if not isinstance(data, dict) or data.get('version') != 1:
                raise ValueError()
            entries = data.get('items')
            if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ITEMS:
                raise ValueError()
            files = []
            seen = set()
            for entry in entries:
                kind, name = entry['type'], entry['file']
                if (kind not in {'photo', 'video'} or not isinstance(name, str)
                        or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}\.(mp4|jpg|jpeg|png|webp)', name)
                        or name in seen or (kind == 'video') != name.endswith('.mp4')):
                    raise ValueError()
                seen.add(name)
                coverage = data.get('coverage', 'complete' if kind == 'video' else 'unknown')
                if not isinstance(coverage, str):
                    coverage = 'unknown'
                files.append(MediaItem(kind, directory / name, coverage=coverage))
        except (OSError, ValueError, TypeError, KeyError):
            raise DownloadError('invalid_file') from None
    else:
        # Keep compatibility for existing video runners and in-flight workers.
        files = sorted(directory.glob('*.mp4'))
    if not 1 <= len(files) <= MAX_ITEMS:
        raise DownloadError('no_video')
    total = 0
    result = []
    for item in files:
        p = media_value(item)
        if p.is_symlink() or not p.is_file() or p.parent != directory:
            raise DownloadError('invalid_file')
        size = p.stat().st_size
        with p.open('rb') as f:
            signature = f.read(12)
        if not 12 <= size <= MAX_FILE:
            raise DownloadError('invalid_file')
        if media_type(item) == 'video':
            if signature[4:8] != b'ftyp':
                raise DownloadError('invalid_file')
        else:
            if (size > 10 * 1024 * 1024 or not (
                    signature.startswith(b'\xff\xd8\xff') or signature.startswith(b'\x89PNG\r\n\x1a\n')
                    or signature[:4] == b'RIFF' and signature[8:12] == b'WEBP')):
                raise DownloadError('invalid_file')
            if decode_photos:
                p = prepare_photo(p)
                size = p.stat().st_size
                item = item._replace(value=p)
        total += size
        result.append(item)
    if total > MAX_TOTAL or sum(p.stat().st_size for p in directory.iterdir()
                                if p.is_file() and not p.is_symlink()) > MAX_TOTAL:
        raise DownloadError('too_large')
    return result

MAX_FILE = 50_000_000  # Telegram Bot API sendVideo: <=50 MB; other providers unchanged.
MAX_TOTAL = 90 * 1024 * 1024
MAX_ITEMS = 10


def canonical_url(value: str):
    try:
        p = urlsplit(value)
        if (p.scheme != 'https' or p.hostname not in {'instagram.com', 'www.instagram.com', 'm.instagram.com'}
                or p.username is not None or p.password is not None or p.port not in (None, 443)
                or any(ord(c) < 33 for c in value)):
            return None
        if not re.fullmatch(r'/(reel|p|tv)/[A-Za-z0-9_-]{1,64}/?', p.path):
            return None
        return 'https://www.instagram.com' + p.path.rstrip('/') + '/'
    except (ValueError, TypeError):
        return None


def extract_urls(text: str):
    result = []
    for raw in re.findall(r'https://[^\s<>]+', text or ''):
        url = canonical_url(raw.rstrip(".,!?:;)]}\"'"))
        if url and url not in result:
            result.append(url)
    return result
