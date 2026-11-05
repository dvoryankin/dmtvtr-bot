"""Fail-closed outbound socket policy, installed ONLY in the disposable worker.

stdlib urllib resolves through getaddrinfo then connects to the returned numeric
address. Validate the complete DNS answer, and validate the actual connect address
again (no second name resolution / DNS rebinding). Redirects use the same policy.
No proxies, curl, ffmpeg, external downloaders, or alternative HTTP handlers.
"""
import ipaddress
import socket
import urllib.request
from urllib.parse import urlsplit, urljoin


class CredentialBoundary(urllib.request.BaseHandler):
    """Runs after HTTPCookieProcessor, on every request including redirects.

    Never trust extractor Cookie/Authorization headers or cookiejar extensions.
    Only our immutable session jar can supply cookies at exact approved origins.
    """
    handler_order = 999

    def __init__(self, jar):
        self.jar = jar

    def https_request(self, request):
        from instagram_session import AUTH_HOSTS
        p = urlsplit(request.full_url)
        if (p.scheme != 'https' or not allowed_host(p.hostname)
                or p.port not in (None, 443) or p.username is not None
                or p.password is not None):
            raise ValueError('Outbound host/port denied')
        for mapping in (request.headers, request.unredirected_hdrs):
            for name in list(mapping):
                if name.lower() in ('cookie', 'cookie2', 'authorization', 'proxy-authorization', 'host',
                                    'x-csrftoken', 'x-ig-www-claim'):
                    del mapping[name]
        if p.hostname in AUTH_HOSTS:
            self.jar.add_cookie_header(request)
        return request

    http_request = https_request


class NoDrainRedirect(urllib.request.HTTPRedirectHandler):
    """Do not inherit urllib's unbounded intermediate fp.read()."""
    def http_error_302(self, req, fp, code, msg, headers):
        try:
            target = headers.get('Location')
            if not target or getattr(req, '_auth_redirects', 0) >= 3:
                raise ValueError('Outbound host/port denied')
            redirect = self.redirect_request(req, fp, code, msg, headers,
                                             urljoin(req.full_url, target))
            if redirect is None:
                raise ValueError('Outbound host/port denied')
            redirect._auth_redirects = getattr(req, '_auth_redirects', 0) + 1
        finally:
            fp.close()  # close without draining, on both success and rejection
        return self.parent.open(redirect, timeout=req.timeout)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def authenticated_handler(jar):
    """Only UrllibRH; add a final HTTP credential gate after cookie injection."""
    from yt_dlp.networking._urllib import UrllibRH

    class AuthUrllibRH(UrllibRH):
        def _create_instance(self, proxies, cookiejar, **kwargs):
            # Build afresh: never retain an inherited redirect handler dispatch.
            original = super()._create_instance(proxies={}, cookiejar=jar, **kwargs)
            opener = urllib.request.OpenerDirector()
            for handler in original.handlers:
                if not isinstance(handler, urllib.request.HTTPRedirectHandler):
                    opener.add_handler(handler)
            opener.add_handler(NoDrainRedirect())
            opener.add_handler(CredentialBoundary(jar))
            opener.addheaders = []
            return opener

    return AuthUrllibRH


def allowed_host(host):
    if not isinstance(host, str):
        return False
    host = host.lower()
    return any(host == suffix or host.endswith('.' + suffix)
               for suffix in ('instagram.com', 'cdninstagram.com', 'fbcdn.net'))


def public_ip(value):
    try:
        ip = ipaddress.ip_address(value)
        return (ip.is_global and not ip.is_multicast and not ip.is_reserved
                and not getattr(ip, 'ipv4_mapped', None))
    except ValueError:
        return False


def resolve_public(resolver, host, port, *args, **kwargs):
    if not allowed_host(host) or str(port) != '443':
        raise ValueError('Outbound host/port denied')
    records = resolver(host, port, *args, **kwargs)
    if not records or any(not public_ip(row[4][0]) for row in records):
        raise ValueError('Non-public DNS answer denied')
    return records


def install_network_guard():
    original_resolve = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def resolve(host, port, *args, **kwargs):
        return resolve_public(original_resolve, host, port, *args, **kwargs)

    def validate(address):
        if (not isinstance(address, tuple) or len(address) < 2
                or address[1] != 443 or not public_ip(address[0])):
            raise ValueError('Non-public connection denied')

    def connect(sock, address):
        validate(address)
        return original_connect(sock, address)

    def connect_ex(sock, address):
        validate(address)
        return original_connect_ex(sock, address)

    socket.getaddrinfo = resolve
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
