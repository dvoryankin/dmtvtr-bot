"""Bounded allowlisted diagnostics: never persist provider strings or URLs."""
import json
import re
from contextvars import ContextVar

context = ContextVar('instagram_context', default='message_id=none')
MESSAGES = {
    'csrf_missing': 'Instagram API did not set a CSRF token',
    'api_denied': 'Instagram API is not granting access',
    'empty_media': 'Instagram returned empty media metadata',
    'http_error': 'HTTP request failed',
    'dns_denied': 'Non-public DNS answer denied',
    'host_denied': 'Outbound host or port denied',
    'connect_denied': 'Non-public connection denied',
    'login_or_rate_limit': 'Provider reports login requirement or rate limit',
    'timeout': 'Network or operation timeout',
    'no_video': 'No supported video found',
    'too_large': 'Media exceeds download size limit',
    'invalid_file': 'Downloaded media failed validation',
    'unknown': 'Unclassified failure',
    'ok': 'Download validated',
}

def classify(text):
    text = str(text)[:16384]
    if text in ('too_large', 'invalid_file'):
        return {'code': text, 'message': MESSAGES[text], 'http_status': None}
    match = re.search(r'HTTP (?:Error |error |status )?(\d{3})\b', text)
    status = int(match.group(1)) if match else None
    code = 'unknown'
    for marker, candidate in [
        ('No CSRF token set', 'csrf_missing'),
        ('Instagram API is not granting access', 'api_denied'),
        ('Instagram sent an empty media response', 'empty_media'),
        ('Non-public DNS answer denied', 'dns_denied'),
        ('Outbound host/port denied', 'host_denied'),
        ('Non-public connection denied', 'connect_denied'),
        ('login required', 'login_or_rate_limit'),
        ('rate-limit', 'login_or_rate_limit'),
        ('There is no video in this post', 'no_video'),
        ('timed out', 'timeout'), ('no_video', 'no_video')]:
        if marker in text:
            code = candidate
            break
    if status is not None and code == 'unknown':
        code = 'http_error'
    return {'code': code, 'message': MESSAGES[code], 'http_status': status}

def safe_record(value):
    if not isinstance(value, dict):
        value = {}
    code = value.get('code')
    if code not in MESSAGES:
        code = 'unknown'
    phase = value.get('phase')
    if phase not in ('startup', 'metadata', 'media', 'validation', 'complete'):
        phase = 'startup'
    status = value.get('http_status')
    if type(status) is not int or not 100 <= status <= 599:
        status = None
    exc = value.get('exception')
    if exc not in ('DownloadError', 'ExtractorError', 'HTTPError', 'ValueError', 'TimeoutError', 'OSError', 'none'):
        exc = 'other'
    return dict(code=code, message=MESSAGES[code], phase=phase, http_status=status, exception=exc)

def read_diagnostic(directory):
    try:
        with (directory / 'diagnostic.json').open('rb') as stream:
            value = json.loads(stream.read(8193))
        result = safe_record(value)
        events = value.get('events', [])
        result['events'] = [safe_record(e) for e in events[:8]] if isinstance(events, list) else []
        return json.dumps(result, ensure_ascii=True, separators=(',', ':'))
    except (OSError, ValueError, TypeError, AttributeError):
        return json.dumps(safe_record({}))

class Diagnostic:
    def __init__(self, directory):
        self.directory = directory
        self.phase = 'startup'
        self.events = []
        self.write()

    def write(self, exc=None, ok=False):
        result = classify(exc or '')
        # yt-dlp wraps extractor/HTTP failures in DownloadError.exc_info.
        info = getattr(exc, 'exc_info', None)
        cause = info[1] if isinstance(info, tuple) and len(info) > 1 else None
        for error in (cause, getattr(cause, 'cause', None), getattr(exc, '__cause__', None)):
            if error is not None:
                detail = classify(error)
                if detail['code'] != 'unknown':
                    result = detail
        if ok:
            result = {'code': 'ok', 'http_status': None}
        result.update(phase=self.phase, exception=type(exc).__name__ if exc else 'none')
        result = safe_record(result)
        result['events'] = self.events[-8:]
        try:
            (self.directory / 'diagnostic.json').write_text(json.dumps(result))
        except OSError:
            pass

    def set_phase(self, phase):
        self.phase = phase
        self.write()

    def debug(self, message):
        pass

    def warning(self, message):
        self.events.append(safe_record(dict(classify(message), phase=self.phase, exception='none')))
        self.events = self.events[-8:]
        self.write()

    error = warning
