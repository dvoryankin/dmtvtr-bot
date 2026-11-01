"""Public single TikTok videos. Parent-compatible Python 3.8 URL policy."""
import re
from urllib.parse import urlsplit


def canonical_url(value):
    try:
        if not isinstance(value, str) or any(ord(c) < 33 for c in value) or '\\' in value:
            return None
        p = urlsplit(value)
        if p.scheme not in ('http', 'https') or p.netloc.lower() not in (
                'vm.tiktok.com', 'vt.tiktok.com', 'www.tiktok.com', 'tiktok.com'):
            return None
        host = p.hostname
        if host in ('vm.tiktok.com', 'vt.tiktok.com'):
            match = re.fullmatch(r'/([A-Za-z0-9]{1,64})/?', p.path)
            return 'https://' + host + '/' + match.group(1) + '/' if match else None
        match = re.fullmatch(r'/@([A-Za-z0-9_.]{1,64})/video/([0-9]{1,24})/?', p.path)
        return 'https://www.tiktok.com/@%s/video/%s' % match.groups() if match else None
    except (ValueError, TypeError):
        return None


# Reuse the established bounded queue/cache, confirmed-send adapter and worker
# runner. Only provider policy and the disposable executable differ.
import time
from .instagram_download import DownloadService, DownloadError
from .youtube_video import YouTubeService, validate_files as video_validate_files


def validate_files(directory):
    if not (directory / 'manifest.json').is_file():
        raise DownloadError('invalid_file')
    return video_validate_files(directory)


class TikTokService(YouTubeService):
    worker_filename = 'tiktok_video_worker.py'
    worker_python_flags = ('-I', '-B')
    unavailable_code = 'tiktok_unavailable'
    diagnostic_codes = frozenset(('ok', 'tiktok_unavailable', 'timeout', 'network_denied',
        'no_video', 'too_large', 'invalid_file', 'duration_denied', 'metadata_limit', 'challenge_required'))

    def __init__(self, base_dir, allowed_chats, runner=None, clock=time.monotonic):
        DownloadService.__init__(self, base_dir, allowed_chats, runner=runner, clock=clock,
                                 canonicalizer=canonical_url, validator=validate_files)
