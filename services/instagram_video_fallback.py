"""Select a size-verified progressive MP4 without transcoding or extra providers.

Used only inside the isolated worker, after its public-IP socket guard is installed.
The extractor's best format can exceed the upload cap; yt-dlp otherwise silently
skips it and returns successfully with no file. Probe at most three progressive
variants, retaining yt-dlp's quality order. Never select audio-only/DASH video-only.
"""
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener
from instagram_photos import validate_fetch_url
from instagram_download import MAX_FILE, DownloadError


class HeadNoRedirect(HTTPRedirectHandler):
    """Never let urllib turn a HEAD probe into a redirected GET."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('redirect denied')

    # Python 3.8 lacks the stdlib 308 alias; deny it identically on both runtimes.
    http_error_308 = HTTPRedirectHandler.http_error_302


def head_size(url):
    request = Request(validate_fetch_url(url), method='HEAD',
                      headers={'User-Agent': 'Mozilla/5.0', 'Accept-Encoding': 'identity'})
    with build_opener(ProxyHandler({}), HeadNoRedirect()).open(request, timeout=3) as response:
        validate_fetch_url(response.geturl())
        value = response.headers.get('Content-Length', '')
        if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or len(value) > 15:
            raise DownloadError('invalid_file')
        size = int(value)
        if size < 1:
            raise DownloadError('invalid_file')
        return size


def fitting_mp4(context):
    checked = 0
    for candidate in reversed(context.get('formats', [])):
        if (candidate.get('ext') != 'mp4' or candidate.get('protocol') != 'https'
                or candidate.get('vcodec') == 'none' or candidate.get('acodec') == 'none'):
            continue
        if checked >= 3:
            break
        checked += 1
        size = head_size(candidate['url'])
        if size <= MAX_FILE:
            yield dict(candidate, filesize=size)
            return
    raise DownloadError('too_large')
