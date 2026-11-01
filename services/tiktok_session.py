"""Ephemeral public anonymous transport, shared by extraction and media only."""
import http.cookiejar
import time
import urllib.request as u

NAMES = frozenset(('ttwid', 'tt_webid', 'tt_webid_v2', 'msToken', 'odin_tt', 'tt_chain_token'))

class AnonymousPolicy(http.cookiejar.DefaultCookiePolicy):
    def __init__(self):
        super().__init__(strict_ns_domain=self.DomainStrictNonDomain)
    def set_ok(self, c, r):
        from .tiktok_video_worker import metadata_url, media_url, METADATA_HOSTS, MEDIA_HOSTS
        return (bool(metadata_url(r.full_url) or media_url(r.full_url))
                and c.domain.lstrip('.') in ('tiktok.com',) + METADATA_HOSTS + MEDIA_HOSTS
                and c.name in NAMES and len(c.value or '') <= 4096
                and not any(ord(x) < 32 or ord(x) == 127 for x in (c.value or ''))
                and super().set_ok(c, r))
    def return_ok(self, c, r):
        from .tiktok_video_worker import metadata_url, media_url
        return (bool(metadata_url(r.full_url) or media_url(r.full_url))
                and c.name in NAMES and super().return_ok(c, r))

class Jar(http.cookiejar.CookieJar):
    def __init__(self):
        super().__init__(AnonymousPolicy())
    def set_cookie(self, c, *a, **kw):
        from .tiktok_video_worker import WorkerError, METADATA_HOSTS, MEDIA_HOSTS
        if (c.name not in NAMES or c.domain.lstrip('.') not in ('tiktok.com',) + METADATA_HOSTS + MEDIA_HOSTS
                or len(c.value or '') > 4096 or any(ord(x) < 32 or ord(x) == 127 for x in (c.value or ''))):
            return
        others = [x for x in self if (x.domain, x.path, x.name) != (c.domain, c.path, c.name)]
        if (len(others) >= 16 or sum(len(x.name) + len(x.value or '') for x in others)
                + len(c.name) + len(c.value or '') > 16384):
            raise WorkerError('metadata_limit')
        super().set_cookie(c, *a, **kw)
    def get_cookie_header(self, url):
        r = u.Request(url); self.add_cookie_header(r)
        return r.get_header('Cookie')
    def get_cookies_for_url(self, url):
        self._policy._now = self._now = int(time.time())
        return self._cookies_for_request(u.Request(url))

class Clean(u.BaseHandler):
    handler_order = 100
    def https_request(self, r):
        headers = {k: v for k, v in r.header_items()
                   if k.lower() in ('user-agent', 'referer', 'accept', 'accept-language')
                   and isinstance(v, str) and not any(ord(x) < 32 or ord(x) == 127 for x in v)}
        r.headers.clear(); r.unredirected_hdrs.clear()
        for k, v in headers.items(): r.add_unredirected_header(k, v)
        r.add_unredirected_header('Accept-Encoding', 'identity')
        return r
    http_request = https_request

class Session(u.BaseHandler):
    handler_order = 999
    def __init__(self, jar=None):
        self.jar = jar if jar is not None else Jar()
        self.phase = 'metadata'
        self.metadata_budget = [2_000_000]
        self.counts = {'metadata': 0, 'media': 0, 'head': 0}
        self.status_counts = {}
    def https_request(self, r):
        from .tiktok_video_worker import metadata_url, media_url, WorkerError
        media = media_url(r.full_url)
        if (not (media or metadata_url(r.full_url)) or r.get_method() not in ('GET', 'HEAD')
                or media and self.phase != 'media'):
            raise WorkerError('network_denied')
        key = 'head' if r.get_method() == 'HEAD' else 'media' if media else 'metadata'
        self.counts[key] += 1
        if self.counts[key] > {'head': 2, 'media': 4, 'metadata': 8}[key]:
            raise WorkerError('metadata_limit')
        r.remove_header('Cookie'); r.remove_header('Authorization')
        self.jar.add_cookie_header(r)
        return r
    http_request = https_request
    def https_response(self, request, response):
        from .tiktok_video_worker import Bounded, WorkerError, metadata_url
        status = response.getcode()
        if type(status) is int and 100 <= status <= 599:
            key = str(status)
            self.status_counts[key] = self.status_counts.get(key, 0) + 1
        if metadata_url(request.full_url):
            if response.headers.get('Content-Encoding', 'identity').strip().lower() not in ('', 'identity'):
                response.close()
                raise WorkerError('metadata_limit')
            return Bounded(response, self.metadata_budget)
        return response
    http_response = https_response
    def opener(self):
        from .tiktok_video_worker import Redirect
        return u.build_opener(u.ProxyHandler({}), Clean(), u.HTTPCookieProcessor(self.jar), Redirect(), self)
