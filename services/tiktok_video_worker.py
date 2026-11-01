"""Public logged-out TikTok worker with ephemeral anonymous site cookies only."""
import sys
sys.dont_write_bytecode = True
import io
import json
import math
from pathlib import Path
import resource
import signal
import urllib.request
import urllib.response
from urllib.parse import urlsplit

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from services.tiktok_video import canonical_url
from services import instagram_network as guard
from services.youtube_video_worker import (WorkerError, Quiet, build_options, probe_file,
                                          tool_limits, check_metadata)
MAX_FILE = 20_000_000
# Reserve control bytes: deliberately skip videos above 19,991,808 bytes.
CONTROL_RESERVE = 8192
METADATA_HOSTS = ('vm.tiktok.com', 'vt.tiktok.com', 'www.tiktok.com', 'tiktok.com')
# Observed public webpage MP4 origins; not arbitrary tiktok subdomains or app APIs.
MEDIA_HOSTS = ('v16-webapp-prime.tiktok.com', 'v19-webapp-prime.tiktok.com')


def allowed_host(host):
    return host in METADATA_HOSTS + MEDIA_HOSTS


def metadata_url(value):
    try:
        p = urlsplit(value)
        return (p.scheme == 'https' and p.netloc in METADATA_HOSTS
                and canonical_url(value) is not None and not p.fragment)
    except (ValueError, TypeError):
        return False


def media_url(value):
    try:
        if not isinstance(value, str) or any(ord(c) < 33 for c in value) or '\\' in value:
            return False
        p = urlsplit(value)
        return (p.scheme == 'https' and p.hostname in MEDIA_HOSTS and not p.username
                and not p.password and p.port in (None, 443) and not p.fragment
                and p.path.startswith('/video/'))
    except (ValueError, TypeError):
        return False


class Redirect(urllib.request.HTTPRedirectHandler):
    def http_error_302(self, req, fp, code, msg, headers):
        fp.close()  # Never drain an untrusted intermediate body.
        if not headers.get('Location') and not headers.get('URI'):
            raise WorkerError('network_denied')
        with io.BytesIO() as empty:
            return super().http_error_302(req, empty, code, msg, headers)
    http_error_301 = http_error_302
    http_error_303 = http_error_302
    http_error_307 = http_error_302
    http_error_308 = http_error_302

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        policy = media_url if media_url(req.full_url) else metadata_url
        count = getattr(req, 'count', 0) + 1
        if count > 3 or not policy(newurl):
            raise WorkerError('network_denied')
        result = super().redirect_request(req, fp, 307 if code == 308 else code, msg, headers, newurl)
        if result is not None:
            result.count = count
            if req.get_method() == 'HEAD': result.method = 'HEAD'
        return result


class Bounded(urllib.response.addinfourl):
    def __init__(self, response, budget=None):
        super().__init__(response, getattr(response, 'headers', {}),
                         response.geturl() if hasattr(response, 'geturl') else '',
                         response.getcode() if hasattr(response, 'getcode') else 200)
        self.response = response
        self.budget = budget if budget is not None else [2_000_000]

    def read(self, n=-1):
        if n is None: n = -1
        if n == 0: return b''
        chunks = []
        while True:
            if self.budget[0] <= 0: raise WorkerError('metadata_limit')
            chunk = self.response.read(min(self.budget[0], 65536 if n < 0 else n))
            self.budget[0] -= len(chunk)
            chunks.append(chunk)
            if n >= 0 or not chunk: return b''.join(chunks)

    def __getattr__(self, key):
        return getattr(self.response, key)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()



def resolve_url(url, session, opener=None):
    canonical = canonical_url(url)
    if not canonical: raise WorkerError('network_denied')
    if urlsplit(canonical).hostname not in ('vm.tiktok.com', 'vt.tiktok.com'):
        return canonical
    with (opener or session.opener()).open(urllib.request.Request(canonical), timeout=8) as response:
        resolved = canonical_url(response.geturl())
        if not resolved or urlsplit(resolved).hostname != 'www.tiktok.com':
            raise WorkerError('network_denied')
        # Close, never drain the final resolution page; extractor fetches it once.
        return resolved


def bind_identity(info, resolved):
    expected = urlsplit(resolved).path.rsplit('/', 1)[-1]
    actual = canonical_url(info.get('webpage_url')) if isinstance(info, dict) else None
    if (not expected.isdigit() or not isinstance(info, dict) or info.get('id') != expected
            or not actual or urlsplit(actual).path.rsplit('/', 1)[-1] != expected):
        raise WorkerError('invalid_file')


def extract_metadata(url, session=None):
    from services.tiktok_session import Session
    session = session or Session()
    from yt_dlp import YoutubeDL
    from yt_dlp.extractor.tiktok import TikTokIE
    from yt_dlp.networking._urllib import UrllibRH

    resolved = resolve_url(url, session)
    opener = session.opener()

    class PublicTikTok(TikTokIE):
        _KNOWN_APP_INFO = None
        @staticmethod
        def _generate_blockbuster_headers(**kw): return {}
        def _extract_aweme_app(self, *a, **kw):
            raise WorkerError('network_denied')
        def _solve_challenge_and_set_cookies(self, *a, **kw):
            raise WorkerError('challenge_required')
        def _set_cookie(self, *a, **kw):
            raise WorkerError('network_denied')

    class RH(UrllibRH):
        _SUPPORTED_URL_SCHEMES = ('https',)
        def _create_instance(self, *a, **kw):
            return opener


    class DL(YoutubeDL):
        def build_request_director(self, handlers, preferences=None):
            return super().build_request_director([RH], preferences)
    with DL(build_options(), auto_init=False) as dl:
        dl.__dict__['cookiejar'] = session.jar
        dl.add_info_extractor(PublicTikTok())
        info = dl.extract_info(resolved, download=False)
        bind_identity(info, resolved)
        return info


def choose(info):
    if not isinstance(info, dict): raise WorkerError('no_video')
    check_metadata(info)
    if 'imagePost' in info: raise WorkerError('no_video')
    candidates = []
    for f in info.get('formats') or []:
        size = f.get('filesize')
        if (type(size) is int and 0 < size <= MAX_FILE - CONTROL_RESERVE and media_url(f.get('url'))
                and f.get('vcodec') in ('h264', 'avc1') and f.get('acodec') in ('aac', 'mp4a')
                and f.get('ext') == 'mp4' and not f.get('has_drm')):
            candidates.append(f)
    if not candidates: raise WorkerError('no_video')
    def rank(f):
        return tuple(f.get(key) if type(f.get(key)) is int else 0 for key in ('height', 'width', 'filesize'))
    return max(candidates, key=rank)


def download(fmt, target, session=None):
    if not media_url(fmt.get('url')): raise WorkerError('network_denied')
    from services.tiktok_session import Session
    session = session or Session()
    session.phase = 'media'
    opener = session.opener()
    headers = {k: v for k, v in (fmt.get('http_headers') or {}).items()
               if k.lower() in ('user-agent', 'referer', 'accept', 'accept-language')}
    headers['Accept-Encoding'] = 'identity'
    created = False
    try:
        with opener.open(urllib.request.Request(fmt['url'], headers=headers), timeout=8) as response:
            if not media_url(response.geturl()): raise WorkerError('network_denied')
            length = response.headers.get('Content-Length')
            if (length is None or not length.isdigit() or not 0 < int(length)
                    <= MAX_FILE - CONTROL_RESERVE - disk_usage(target.parent)):
                raise WorkerError('too_large')
            length = int(length)
            if response.headers.get('Content-Encoding', 'identity').lower() not in ('identity', ''):
                raise WorkerError('invalid_file')
            with target.open('xb') as sink:
                created = True
                while sink.tell() < length:
                    chunk = response.read(min(65536, length - sink.tell()))
                    if not chunk: raise WorkerError('invalid_file')
                    sink.write(chunk)
            if target.stat().st_size != length: raise WorkerError('invalid_file')
    except BaseException:
        if created and target.exists() and not target.is_symlink(): target.unlink()
        raise


def disk_usage(directory):
    import stat
    total = 0
    for path in directory.iterdir():
        entry = path.lstat()
        if not stat.S_ISREG(entry.st_mode): raise WorkerError('invalid_file')
        total += entry.st_size
    if total > MAX_FILE: raise WorkerError('too_large')
    return total


def write_control(directory, name, data, cap):
    payload = json.dumps(data, separators=(',', ':')).encode('ascii')
    if len(payload) > cap or disk_usage(directory) + len(payload) > MAX_FILE:
        raise WorkerError('too_large')
    with (directory / name).open('xb') as sink: sink.write(payload)
    disk_usage(directory)


def write_diagnostic(directory, code, session=None):
    data = {'code': code}
    if session is not None:
        data['http_counts'] = dict(session.counts)
        data['status_counts'] = dict(session.status_counts)
    write_control(directory, 'diagnostic.json', data, 1024)


def process_info(info, directory, session=None):
    fmt = dict(choose(info))
    if disk_usage(directory) + fmt['filesize'] + CONTROL_RESERVE > MAX_FILE:
        raise WorkerError('too_large')
    headers = {}
    for source in (info.get('http_headers'), fmt.get('http_headers')):
        for key, value in (source or {}).items():
            if (isinstance(key, str) and key.lower() in ('user-agent', 'referer', 'accept')
                    and isinstance(value, str) and not any(ord(c) < 32 or ord(c) == 127 for c in value)):
                headers[key.lower()] = value
    fmt['http_headers'] = headers
    target = directory / 'video.mp4'
    if session is None: download(fmt, target)
    else: download(fmt, target, session)
    width, height = probe_file(target)  # actual local H264/AAC, duration, size
    if disk_usage(directory) + CONTROL_RESERVE > MAX_FILE: raise WorkerError('too_large')
    write_control(directory, 'manifest.json', {'version': 1, 'coverage': 'complete',
        'items': [{'type': 'video', 'file': 'video.mp4', 'width': width, 'height': height}]}, CONTROL_RESERVE - 1024)
    from services.tiktok_video import validate_files
    return validate_files(directory)


def main():
    if len(sys.argv) != 3: return 2
    url = canonical_url(sys.argv[1]); directory = Path(sys.argv[2]).resolve()
    if not url or not directory.is_dir(): return 2
    code = 'tiktok_unavailable'
    session = None
    try:
        def deadline(*a): raise WorkerError('timeout')
        signal.signal(signal.SIGALRM, deadline)
        signal.alarm(65)
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE, MAX_FILE))
        resource.setrlimit(resource.RLIMIT_AS, (1_200_000_000, 1_200_000_000))
        resource.setrlimit(resource.RLIMIT_CPU, (45, 45))
        guard.allowed_host = allowed_host
        guard.install_network_guard()
        from services.tiktok_session import Session
        session = Session()
        process_info(extract_metadata(url, session), directory, session)
        code = 'ok'
    except Exception as exc:
        if isinstance(exc, WorkerError) and str(exc) in ('timeout','network_denied','no_video','too_large','invalid_file','duration_denied','metadata_limit','challenge_required'):
            code = str(exc)
    finally:
        signal.alarm(0)
        try:
            write_diagnostic(directory, code, session)
        except (OSError, WorkerError):
            code = 'too_large'
    return 0 if code == 'ok' else 2

if __name__ == '__main__': raise SystemExit(main())
