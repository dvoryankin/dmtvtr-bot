"""Disposable public YouTube worker. No player JS, credentials or network muxing."""
import sys
sys.dont_write_bytecode = True

import io
import json
import math
from pathlib import Path
import resource
import signal
import subprocess
import tempfile
import urllib.request
from urllib.parse import urlsplit

# Explicit sibling provenance under python -I, never production module paths.
if __package__:
    from .youtube_video import canonical_url, validate_files, MAX_FILE, MAX_TOTAL, DIAGNOSTIC_CODES
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from youtube_video import canonical_url, validate_files, MAX_FILE, MAX_TOTAL, DIAGNOSTIC_CODES

SELECTION_LIMIT = MAX_FILE


class WorkerError(Exception):
    pass


def cdn_url(value):
    try:
        if not isinstance(value, str) or any(ord(c) < 33 for c in value) or '\\' in value:
            return False
        p = urlsplit(value)
        return (p.scheme == 'https' and p.hostname is not None
                and p.hostname.endswith('.googlevideo.com')
                and p.username is None and p.password is None
                and p.port in (None, 443) and p.path == '/videoplayback'
                and not p.fragment)
    except ValueError:
        return False


def allowed_host(host):
    return (isinstance(host, str) and (host.lower() in
            ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtubei.googleapis.com')
            or host.lower().endswith('.googlevideo.com')))


def metadata_url(value):
    try:
        if not isinstance(value, str) or any(ord(c) < 33 for c in value) or '\\' in value:
            return False
        p = urlsplit(value)
        return (p.scheme == 'https' and allowed_host(p.hostname)
                and p.username is None and p.password is None
                and p.port in (None, 443) and not p.fragment)
    except ValueError:
        return False


class CDNRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 3
    max_repeats = 3

    def http_error_302(self, req, fp, code, msg, headers):
        # urllib drains fp unbounded before following a redirect, outside the
        # media-byte budget. Close the real response before *any* processing
        # (including rejected/malformed Locations), and give urllib only an
        # empty local body. Keep its URL resolution, method and loop checks.
        fp.close()
        with io.BytesIO() as empty_body:
            return super().http_error_302(req, empty_body, code, msg, headers)

    # Base-class aliases bind its original function, not this override.
    http_error_301 = http_error_302
    http_error_303 = http_error_302
    http_error_307 = http_error_302
    http_error_308 = http_error_302

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        count = getattr(req, '_youtube_redirects', 0) + 1
        if count > 3 or not cdn_url(newurl):
            raise WorkerError('network_denied')
        # 308 has the same method policy as 307; urllib on Python 3.8
        # does not recognize 308 in redirect_request despite our error alias.
        policy_code = 307 if code == 308 else code
        redirected = super().redirect_request(req, fp, policy_code, msg, headers, newurl)
        if redirected is not None:
            redirected._youtube_redirects = count
        return redirected


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def check_metadata(info):
    duration = info.get('duration')
    if (not number(duration) or not 0 < duration <= 90 or info.get('is_live')
            or info.get('live_status') not in (None, 'not_live', 'was_live')
            or info.get('_type') in ('playlist', 'multi_video', 'url', 'url_transparent')
            or info.get('entries') is not None):
        raise WorkerError('duration_denied')


def ranked_candidates(formats):
    def known(f):
        size = f.get('filesize')
        return (number(size) and 0 < size <= SELECTION_LIMIT
                and f.get('protocol') == 'https' and cdn_url(f.get('url'))
                and not f.get('has_drm'))
    def aac(f):
        return str(f.get('acodec', '')).startswith(('mp4a.', 'aac'))
    def rank(f):
        def val(key):
            v = f.get(key)
            return v if number(v) else 0
        return (min(val('width'), val('height')), val('width') * val('height'),
                val('fps'), val('quality'), val('tbr'))
    videos = [f for f in formats if isinstance(f, dict) and known(f)
              and f.get('ext') == 'mp4'
              and str(f.get('vcodec', '')).startswith(('avc1', 'h264'))]
    audios = [f for f in formats if isinstance(f, dict) and known(f)
              and f.get('ext') == 'm4a' and f.get('vcodec') == 'none' and aac(f)]
    candidates = []
    for v in videos:
        if aac(v):
            candidates.append((v,))
        elif v.get('acodec') == 'none':
            candidates.extend((v, a) for a in audios
                              if v['filesize'] + a['filesize'] <= SELECTION_LIMIT)
    if not candidates:
        raise WorkerError('no_video')
    def score(pair):
        a = pair[-1]
        abr = a.get('abr')
        return rank(pair[0]) + (abr if number(abr) else 0, -sum(f['filesize'] for f in pair))
    plans, seen = [], set()
    for pair in sorted(candidates, key=score, reverse=True):
        urls = tuple(f['url'] for f in pair)
        if urls in seen:
            continue
        seen.add(urls)
        # Do not spend the bounded fallback budget on the same video quality
        # with alternate audio, or on aliases of the same signed stream tuple.
        if plans and rank(pair[0]) >= rank(plans[-1][0]):
            continue
        plans.append(pair)
        if len(plans) == 3:
            break
    return plans


def choose_formats(formats):
    return ranked_candidates(formats)[0]


def check_disk(directory):
    if sum(p.stat().st_size for p in directory.rglob('*') if p.is_file()) > MAX_TOTAL:
        raise WorkerError('too_large')


def download_stream(fmt, target, used, opener=None):
    if not cdn_url(fmt.get('url')):
        raise WorkerError('network_denied')
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), CDNRedirect())
    headers = {k: v for k, v in (fmt.get('http_headers') or {}).items()
               if k.lower() in ('user-agent', 'accept', 'accept-language', 'origin', 'referer')}
    headers['Accept-Encoding'] = 'identity'
    try:
        request = urllib.request.Request(fmt['url'], headers=headers)
        with opener.open(request, timeout=8) as response:
            if not cdn_url(response.geturl()):
                raise WorkerError('network_denied')
            length = response.headers.get('Content-Length')
            if length is not None and (not length.isdigit() or int(length) > MAX_FILE - used[0]):
                raise WorkerError('too_large')
            encoding = response.headers.get('Content-Encoding', 'identity')
            if encoding.lower() not in ('identity', ''):
                raise WorkerError('invalid_file')
            with target.open('xb') as sink:
                while True:
                    if used[0] >= MAX_FILE:
                        # No sentinel byte: only an explicit length proves EOF at cap.
                        if length is not None and sink.tell() == int(length):
                            break
                        raise WorkerError('too_large')
                    chunk = response.read(min(65536, MAX_FILE - used[0]))
                    if not chunk:
                        break
                    used[0] += len(chunk)
                    if used[0] > MAX_FILE:
                        raise WorkerError('too_large')
                    sink.write(chunk)
            if not target.stat().st_size:
                raise WorkerError('invalid_file')
    except BaseException:
        if target.exists() and not target.is_symlink():
            target.unlink()
        raise


def tool_limits(file_size=MAX_FILE):
    resource.setrlimit(resource.RLIMIT_CPU, (12, 12))
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_size, file_size))


TOOL_ENV = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LANG': 'C'}


def mux(inputs, output):
    command = ['/usr/bin/ffmpeg', '-nostdin', '-v', 'fatal', '-y', '-threads', '1']
    for path in inputs:
        command.extend(['-protocol_whitelist', 'file,pipe', '-i', str(path)])
    command.extend(['-map', '0:v:0', '-map', '1:a:0' if len(inputs) == 2 else '0:a:0',
                    '-c', 'copy', '-map_metadata', '-1', '-map_chapters', '-1',
                    '-movflags', '+faststart', str(output)])
    try:
        subprocess.run(command, env=TOOL_ENV, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=10, check=True, preexec_fn=tool_limits)
    except subprocess.CalledProcessError as exc:
        # RLIMIT_FSIZE may stop ffmpeg before a >MAX_FILE file can exist.
        # No stderr parsing (signed URLs), no generic mux-error fallback.
        if (exc.returncode == -signal.SIGXFSZ
                or (exc.returncode == 1 and not output.is_symlink() and output.is_file()
                    and output.stat().st_size > MAX_FILE)):
            raise WorkerError('too_large') from None
        raise
    if output.is_symlink() or not output.is_file() or output.stat().st_size < 12:
        raise WorkerError('invalid_file')
    if output.stat().st_size > MAX_FILE:
        raise WorkerError('too_large')


def probe_file(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size < 12:
        raise WorkerError('invalid_file')
    if path.stat().st_size > MAX_FILE:
        raise WorkerError('too_large')
    command = ['/usr/bin/ffprobe', '-v', 'fatal', '-protocol_whitelist', 'file,pipe',
               '-show_entries', 'format=duration:stream=codec_name,codec_type,width,height,duration',
               '-of', 'json', str(path)]
    # Bounded on-disk stdout, never stderr/provider error strings in memory/logs.
    with tempfile.TemporaryFile(dir=str(path.parent)) as output:
        subprocess.run(command, env=TOOL_ENV, stdin=subprocess.DEVNULL,
                       stdout=output, stderr=subprocess.DEVNULL, timeout=5, check=True,
                       preexec_fn=lambda: tool_limits(8192))
        output.seek(0)
        raw = output.read(8193)
    try:
        if len(raw) > 8192:
            raise ValueError()
        data = json.loads(raw)
        duration = float(data['format']['duration'])
        streams = data['streams']
        videos = [s for s in streams if s.get('codec_type') == 'video']
        audios = [s for s in streams if s.get('codec_type') == 'audio']
        if (not math.isfinite(duration) or not 0 < duration <= 90 or len(streams) != 2
                or len(videos) != 1 or len(audios) != 1
                or videos[0].get('codec_name') != 'h264' or audios[0].get('codec_name') != 'aac'):
            raise ValueError()
        width, height = videos[0]['width'], videos[0]['height']
        if (type(width) is not int or type(height) is not int or not 16 <= min(width, height)
                or max(width, height) > 4096 or width * height > 16_000_000
                or max(width, height) / min(width, height) > 20):
            raise ValueError()
        for stream in streams:
            if stream.get('duration') is not None:
                d = float(stream['duration'])
                if not math.isfinite(d) or not 0 < d <= 90:
                    raise ValueError()
        return width, height
    except (ValueError, TypeError, KeyError):
        raise WorkerError('invalid_file') from None


def process_info(info, directory):
    check_metadata(info)  # Absolutely no media bytes before metadata admission.
    candidates = ranked_candidates(info.get('formats') or [])
    output = directory / 'video.mp4'
    manifest = directory / 'manifest.json'
    for attempt, formats in enumerate(candidates):
        overflow = False
        try:
            with tempfile.TemporaryDirectory(prefix='youtube-input-', dir=str(directory)) as raw:
                inputs = []
                used = [0]
                for index, fmt in enumerate(formats):
                    path = Path(raw) / ('input%d.%s' % (index, 'mp4' if index == 0 else 'm4a'))
                    download_stream(fmt, path, used)
                    inputs.append(path)
                    check_disk(directory)
                try:
                    mux(tuple(inputs), output)
                except WorkerError as exc:
                    overflow = str(exc) == 'too_large'
                    raise
                check_disk(directory)
            try:
                dimensions = probe_file(output)
            except WorkerError as exc:
                overflow = str(exc) == 'too_large'
                raise
            manifest.write_text(json.dumps({'version':1, 'coverage':'complete',
                                            'items':[{'type':'video','file':'video.mp4',
                                                      'width':dimensions[0], 'height':dimensions[1]}]}))
            check_disk(directory)
            validate_files(directory)
            return dimensions
        except BaseException as exc:
            # The input TemporaryDirectory has already exited before any next
            # download. Never accumulate attempts or restart the worker alarm.
            for path in (output, manifest):
                if path.exists() and not path.is_symlink():
                    path.unlink()
            if (not overflow or not isinstance(exc, WorkerError) or str(exc) != 'too_large'
                    or attempt + 1 == len(candidates)):
                raise


class Quiet:
    def debug(self, *args, **kwargs): pass
    def info(self, *args, **kwargs): pass
    def warning(self, *args, **kwargs): pass
    def error(self, *args, **kwargs): pass


def build_options():
    return dict(quiet=True, no_warnings=True, logger=Quiet(), skip_download=True,
                noplaylist=True, cachedir=False, proxy='', cookiefile=None,
                socket_timeout=8, retries=0, extractor_retries=0, fragment_retries=0,
                file_access_retries=0, js_runtimes={}, remote_components=[],
                fixup='never', postprocessors=[], writethumbnail=False,
                writeinfojson=False, writesubtitles=False, writeautomaticsub=False)


def write_diagnostic(directory, code):
    if code not in DIAGNOSTIC_CODES:
        code = 'youtube_unavailable'
    try:
        (directory / 'diagnostic.json').write_text(json.dumps({'code':code}))
    except OSError:
        pass


def install_guard():
    if __package__:
        from . import instagram_network as guard
    else:
        import instagram_network as guard
    # Process-local change only. The parent and Instagram module on disk are untouched.
    guard.allowed_host = allowed_host
    guard.install_network_guard()


class MetadataPolicy(urllib.request.BaseHandler):
    def https_request(self, request):
        if not metadata_url(request.full_url):
            raise WorkerError('network_denied')
        # Metadata cannot download player code, manifests or stream bytes.
        path = urlsplit(request.full_url).path.lower()
        if (path.startswith('/s/player/') or path.startswith('/api/manifest/')
                or path.endswith(('.js', '.m3u8', '.mpd'))
                or urlsplit(request.full_url).hostname.endswith('.googlevideo.com')):
            raise WorkerError('network_denied')
        return request
    http_request = https_request


def extract_metadata(url):
    from yt_dlp import YoutubeDL
    from yt_dlp.networking._urllib import UrllibRH
    from yt_dlp.extractor.youtube import YoutubeIE

    class GuardedUrllibRH(UrllibRH):
        _SUPPORTED_URL_SCHEMES = ('https',)

        def _create_instance(self, *args, **kwargs):
            opener = super()._create_instance(*args, **kwargs)
            opener.add_handler(MetadataPolicy())
            for handler in opener.handlers:
                if isinstance(handler, urllib.request.HTTPRedirectHandler):
                    handler.max_redirections = 3
                    handler.max_repeats = 1
            return opener

    class GuardedDL(YoutubeDL):
        def build_request_director(self, handlers, preferences=None):
            return super().build_request_director([GuardedUrllibRH], preferences)

    options = build_options()
    options['extractor_args'] = {'youtube': {'player_skip':['js'], 'skip':['hls', 'dash']}}
    # Only the single-video extractor, never playlist/search/redirect extractors.
    with GuardedDL(options, auto_init=False) as dl:
        dl.add_info_extractor(YoutubeIE())
        return dl.extract_info(url, download=False)


def apply_limits():
    def deadline(signum, frame):
        raise WorkerError('timeout')
    signal.signal(signal.SIGALRM, deadline)
    signal.signal(signal.SIGTERM, deadline)
    signal.alarm(65)
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE, MAX_FILE))
    resource.setrlimit(resource.RLIMIT_AS, (1200 * 1024 * 1024, 1200 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (45, 45))


def main():
    if len(sys.argv) != 3:
        return 2
    url = canonical_url(sys.argv[1])
    directory = Path(sys.argv[2]).resolve()
    if not url or not directory.is_dir():
        return 2
    try:
        apply_limits()
        install_guard()
        info = extract_metadata(url)
        if not isinstance(info, dict):
            raise WorkerError('youtube_unavailable')
        process_info(info, directory)
        write_diagnostic(directory, 'ok')
        return 0
    except Exception as exc:
        # Never serialize downloader exception text (may contain signed CDN URLs).
        code = str(exc) if isinstance(exc, WorkerError) else 'youtube_unavailable'
        write_diagnostic(directory, code)
        return 2
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    raise SystemExit(main())
