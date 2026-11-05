"""Optional owner session: fixed private file -> read-only FD -> volatile cookies.

No browser discovery, login, refresh, serialization or provider response cookies.
"""
import http.cookiejar
import os
from pathlib import Path
import re
import stat
import time

SESSION_PATH = Path('/root/.config/dmtvtr-instagram-auth/session.cookies.txt')
MAX_SESSION = 32768
AUTH_HOSTS = frozenset(('www.instagram.com', 'i.instagram.com'))
COOKIE_NAMES = frozenset(('sessionid', 'csrftoken', 'ds_user_id', 'ig_did', 'mid', 'rur'))


def open_session(path=SESSION_PATH):
    """Walk without following *any* symlink; absent file means disabled."""
    fd = None
    parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        parts = Path(path).parts
        if not Path(path).is_absolute() or '..' in parts:
            raise ValueError('session_invalid')
        for part in parts[1:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = next_fd
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        parent_st = os.fstat(parent)
        if parent_st.st_uid != 0 or stat.S_IMODE(parent_st.st_mode) != 0o700:
            raise ValueError('session_invalid')
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != 0
                or stat.S_IMODE(st.st_mode) != 0o600 or st.st_nlink != 1
                or not 1 <= st.st_size <= MAX_SESSION):
            raise ValueError('session_invalid')
        result, fd = fd, None
        return result
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise ValueError('session_invalid') from None
    finally:
        os.close(parent)
        if fd is not None:
            os.close(fd)


class FrozenPolicy(http.cookiejar.DefaultCookiePolicy):
    def set_ok(self, cookie, request):
        return False  # Ignore all remote Set-Cookie, including domain expansion.

    def return_ok(self, cookie, request):
        from urllib.parse import urlsplit
        p = urlsplit(request.full_url)
        return (p.scheme == 'https' and p.hostname in AUTH_HOSTS
                and p.port in (None, 443) and cookie.domain == p.hostname
                and super().return_ok(cookie, request))


class VolatileJar(http.cookiejar.CookieJar):
    """yt-dlp's read helpers, deliberately without its disk load/save methods."""
    def get_cookie_header(self, url):
        from urllib.request import Request
        request = Request(url)
        self.add_cookie_header(request)
        return request.get_header('Cookie')

    def get_cookies_for_url(self, url):
        from urllib.request import Request
        request = Request(url)
        self.add_cookie_header(request)  # sets cookie policy's current time
        return self._cookies_for_request(request)


def parse_session(data):
    try:
        if not 1 <= len(data) <= MAX_SESSION:
            raise ValueError()
        text = data.decode('ascii')
        if not text.startswith('# Netscape HTTP Cookie File\n'):
            raise ValueError()
        values = {}
        for line in text.splitlines()[1:]:
            if line.startswith('#HttpOnly_'):
                line = line[len('#HttpOnly_'):]
            elif not line or line.startswith('#'):
                continue
            domain, include, path, secure, expiry, name, value = line.split('\t')
            if (domain not in ('.instagram.com', 'instagram.com', *AUTH_HOSTS)
                    or include not in ('TRUE', 'FALSE') or path != '/' or secure != 'TRUE'
                    or not expiry.isdigit() or int(expiry) <= time.time()
                    or name not in COOKIE_NAMES or name in values
                    or not re.fullmatch(r'[A-Za-z0-9%_:.=+/@-]{1,4096}', value)):
                raise ValueError()
            values[name] = (value, int(expiry))
        if not {'sessionid', 'csrftoken', 'ds_user_id'} <= values.keys():
            raise ValueError()
        jar = VolatileJar(FrozenPolicy())
        for host in AUTH_HOSTS:
            for name, (value, expiry) in values.items():
                jar.set_cookie(http.cookiejar.Cookie(
                    0, name, value, None, False, host, False, False, '/', True,
                    True, expiry, False, None, None, {}, False))
        return jar
    except (ValueError, TypeError, UnicodeError):
        raise ValueError('session_invalid') from None


def read_session(fd):
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != 0
                or stat.S_IMODE(st.st_mode) != 0o600 or st.st_nlink != 1
                or not 1 <= st.st_size <= MAX_SESSION):
            raise ValueError('session_invalid')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(MAX_SESSION + 1)
        return parse_session(data)
    except (OSError, ValueError):
        raise ValueError('session_invalid') from None
    finally:
        os.close(fd)
