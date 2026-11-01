"""Bounded public YouTube single-video downloads; main process supports Python 3.8."""
import re
import asyncio
import json
import os
import signal
import time
try:
    from .instagram_download import DownloadService, DownloadError, MediaItem, validate_files as base_validate_files, media_value, media_type
except ImportError:
    from instagram_download import DownloadService, DownloadError, MediaItem, validate_files as base_validate_files, media_value, media_type

MAX_FILE = 20_000_000
MAX_TOTAL = 45_000_000
# Deliberately not in the shared service's retry set (auth/bot checks never retry).
DIAGNOSTIC_CODES = frozenset(('ok', 'youtube_unavailable', 'duration_denied', 'no_video',
                              'too_large', 'invalid_file', 'network_denied', 'timeout'))


def validate_files(directory):
    files = base_validate_files(directory, decode_photos=False)
    if (len(files) != 1 or media_type(files[0]) != 'video'
            or media_value(files[0]).stat().st_size > MAX_FILE
            or sum(p.stat().st_size for p in directory.rglob('*') if p.is_file()) > MAX_TOTAL):
        raise DownloadError('invalid_file')
    item = files[0]
    item = item if isinstance(item, MediaItem) else MediaItem('video', item)
    manifest = directory / 'manifest.json'
    if manifest.exists():
        # The shared validator already bounds and checks the manifest and file.
        # Geometry is YouTube-specific and must match the worker's probe bounds.
        try:
            entry = json.loads(manifest.read_text())['items'][0]
            width, height = entry['width'], entry['height']
            if (type(width) is not int or type(height) is not int or min(width, height) < 16
                    or max(width, height) > 4096 or width * height > 16_000_000
                    or max(width, height) / min(width, height) > 20):
                raise ValueError()
        except (OSError, ValueError, TypeError, KeyError):
            raise DownloadError('invalid_file') from None
        item = item._replace(width=width, height=height)
    return [item]


class YouTubeService(DownloadService):
    worker_filename = 'youtube_video_worker.py'
    worker_python_flags = ('-I',)
    unavailable_code = 'youtube_unavailable'
    diagnostic_codes = DIAGNOSTIC_CODES
    worker_timeout = 70
    retry_attempts = 1

    def __init__(self, base_dir, allowed_chats, runner=None, clock=time.monotonic):
        super().__init__(base_dir, allowed_chats, runner=runner, clock=clock,
                         canonicalizer=canonical_url, validator=validate_files)

    async def handle(self, chat_id, url, send, message_id=None):
        async def confirmed_send(items):
            confirmations = await send(items)
            if not confirmations or len(confirmations) != len(items):
                return None
            ids = []
            for entry in confirmations:
                if (not isinstance(entry, (tuple, list)) or len(entry) not in (2, 3)
                        or type(entry[0]) is not int or entry[0] <= 0
                        or not isinstance(entry[1], str) or not entry[1]
                        or len(entry) == 3 and entry[2] != 'video'):
                    return None
                ids.append(entry[1])
            return ids
        return await super().handle(chat_id, url, confirmed_send, message_id=message_id)

    async def run_worker(self, url, directory):
        try:
            process = await asyncio.create_subprocess_exec(
                str(self.base_dir / '.instagram-venv/bin/python'), *self.worker_python_flags,
                str(self.base_dir / 'services' / self.worker_filename), url, str(directory),
                cwd=str(directory), env={'PATH': '/usr/bin:/bin', 'HOME': str(directory),
                                         'TMPDIR': str(directory), 'LANG': 'C.UTF-8'},
                start_new_session=True, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL)
        except OSError:
            raise DownloadError(self.unavailable_code) from None
        try:
            if await process.wait():
                reason = self.unavailable_code
                try:
                    path = directory / 'diagnostic.json'
                    if not path.is_symlink() and path.stat().st_size <= 1024:
                        value = json.loads(path.read_text()).get('code')
                        if value in self.diagnostic_codes and value != 'ok':
                            reason = value
                except (OSError, ValueError, TypeError, AttributeError):
                    pass
                raise DownloadError(reason)
        finally:
            # Kill the complete session even if the worker already exited: a
            # timeout/crash must not leave a muxer holding temporary files open.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()

from urllib.parse import urlsplit

URL_RE = re.compile(r'https?://[^\s<>]+', re.IGNORECASE)
_ID = r'[A-Za-z0-9_-]{11}'


def canonical_url(value):
    try:
        if not isinstance(value, str) or any(ord(c) < 33 for c in value) or '\\' in value:
            return None
        p = urlsplit(value)
        if (p.scheme not in ('http', 'https') or p.netloc.lower() not in
                ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be')):
            return None
        if p.hostname == 'youtu.be':
            match = re.fullmatch('/(' + _ID + ')/?', p.path)
        elif p.path == '/watch':
            # Do not decode escaped IDs or accept ambiguous duplicate v parameters.
            values = [part[2:] for part in p.query.split('&') if part.startswith('v=')]
            match = re.fullmatch('(' + _ID + ')', values[0]) if len(values) == 1 else None
        else:
            match = re.fullmatch('/shorts/(' + _ID + ')/?', p.path)
        return 'https://www.youtube.com/watch?v=' + match.group(1) if match else None
    except (TypeError, ValueError):
        return None
