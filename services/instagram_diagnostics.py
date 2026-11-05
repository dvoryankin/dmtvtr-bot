"""Bounded allowlisted diagnostics: never persist provider strings or URLs."""
import json
import re
from contextvars import ContextVar

context = ContextVar('instagram_context', default='message_id=none')
MESSAGES = {
    'login_required': 'Provider explicitly requires login or age verification',
    'rate_limited': 'Provider rate limit reached',
    'session_invalid': 'Optional session rejected',
    'challenge_required': 'Provider requires human verification',
    'inventory_incomplete': 'Complete media inventory not established',
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

# Exact upstream yt-dlp 2026.08.19 text, including its static login/help suffix.
# Do not accept arbitrary trailing text or reduce safety errors to this prefix.
YTDLP_EMPTY_MEDIA_MESSAGE = (
    'Instagram sent an empty media response. Check if this post is accessible in your '
    'browser without being logged-in. If it is not, then use --cookies-from-browser or '
    '--cookies for the authentication. See  https://github.com/yt-dlp/yt-dlp/wiki/'
    'FAQ#how-do-i-pass-cookies-to-yt-dlp  for how to manually pass cookies. '
    'Otherwise, if the post is accessible in browser without being logged-in, '
    'please report this issue on  https://github.com/yt-dlp/yt-dlp/issues?q= , '
    'filling out the appropriate issue template. Confirm you are on the latest '
    'version using  yt-dlp -U'
)

def classify(text):
    text = str(text)
    if len(text) > 16384:
        return {'code': 'unknown', 'message': MESSAGES['unknown'], 'http_status': None}
    if text in ('too_large', 'invalid_file', 'session_invalid', 'challenge_required', 'inventory_incomplete'):
        return {'code': text, 'message': MESSAGES[text], 'http_status': None}
    match = re.search(r'HTTP (?:Error |error |status )?(\d{3})\b', text)
    status = int(match.group(1)) if match else None
    code = 'unknown'
    lower = text.lower()
    if status == 429 or any(m in lower for m in ('rate-limit', 'rate limit', 'too many requests')):
        return {'code': 'rate_limited', 'message': MESSAGES['rate_limited'], 'http_status': status}
    if any(m in lower for m in ('challenge_required', 'checkpoint_required', 'challenge required')):
        return {'code': 'challenge_required', 'message': MESSAGES['challenge_required'], 'http_status': status}
    if status is not None:
        return {'code': 'http_error', 'message': MESSAGES['http_error'], 'http_status': status}
    for marker, candidate in [
        ('Non-public DNS answer denied', 'dns_denied'),
        ('Outbound host/port denied', 'host_denied'),
        ('Non-public connection denied', 'connect_denied'),
        ('timed out', 'timeout'), ('timeout', 'timeout'),
        ('Instagram API is not granting access', 'api_denied'),
        ('There is no video in this post', 'no_video'), ('no_video', 'no_video')]:
        if marker.lower() in lower:
            code = candidate
            break
    if code == 'unknown':
        # Positive auth evidence is an entire known message, never a substring
        # of foreign/ambiguous failure text. Accept only yt-dlp's static prefix.
        clean = re.sub(r'^(?:ERROR: )?(?:\[Instagram\] [A-Za-z0-9_-]+: )?', '', text).strip()
        code = {'Instagram sent an empty media response': 'empty_media',
                YTDLP_EMPTY_MEDIA_MESSAGE: 'empty_media',
                'No CSRF token set by Instagram API': 'csrf_missing',
                'login required': 'login_required',
                'age-restricted': 'login_required'}.get(clean, 'unknown')
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

def auth_verification_eligible(value):
    """Positive metadata evidence only; any ambiguous history vetoes auth."""
    if not isinstance(value, dict) or value.get('code') not in {'empty_media', 'login_required'}:
        return False
    events = value.get('events')
    if value.get('events_truncated', False) is not False:
        return False
    if not isinstance(events, list) or len(events) > 8:
        return False
    allowed = {'csrf_missing', 'empty_media', 'login_required'}
    return all(isinstance(record, dict)
               and record.get('code') in allowed
               and record.get('phase') == 'metadata'
               and 'http_status' in record and record['http_status'] is None
               and record.get('exception') in {'none', 'DownloadError', 'ExtractorError'}
               for record in [value] + events)


def read_diagnostic(directory):
    try:
        with (directory / 'diagnostic.json').open('rb') as stream:
            value = json.loads(stream.read(8193))
        result = safe_record(value)
        result['auth_eligible'] = auth_verification_eligible(value)
        events = value.get('events', [])
        result['events'] = [safe_record(e) for e in events[:8]] if isinstance(events, list) else []
        return json.dumps(result, ensure_ascii=True, separators=(',', ':'))
    except (OSError, ValueError, TypeError, AttributeError):
        return json.dumps(safe_record({}))

def _exception_evidence(error):
    """Bounded cycle-aware walk; aliases are not cycles, uncertainty vetoes auth."""
    if error is None:
        return [], False
    pending, visited, records, uncertain = [(error, ())], set(), [], False
    while pending:
        node, ancestors = pending.pop()
        if not isinstance(node, BaseException) or id(node) in ancestors:
            uncertain = True
            continue
        if id(node) in visited:
            continue
        if len(visited) >= 16:
            uncertain = True
            break
        visited.add(id(node)); records.append(classify(node))
        children = []
        try:
            children = [getattr(node, name, None) for name in ('cause', '__cause__', '__context__')]
            info = getattr(node, 'exc_info', None)
            if info is not None:
                if not isinstance(info, tuple) or len(info) != 3:
                    uncertain = True
                elif info[1] is not None:
                    children.append(info[1])
                elif info[0] is not None:
                    uncertain = True
        except Exception:
            uncertain = True
        for child in children:
            if child is not None:
                pending.append((child, ancestors + (id(node),)))
    return records, uncertain


class Diagnostic:
    def __init__(self, directory):
        self.directory = directory
        self.phase = 'startup'
        self.events = []
        self.events_truncated = False
        self.write()

    def write(self, exc=None, ok=False):
        evidence, uncertain = _exception_evidence(exc)
        result = evidence[0] if evidence else classify('')
        allowed = {'empty_media', 'login_required', 'csrf_missing'}
        for detail in evidence[1:]:
            if (result['code'] in allowed
                    or detail['code'] not in allowed and detail['code'] != 'unknown'):
                result = detail
        if uncertain and result['code'] in allowed:
            result = classify('')
        if ok:
            result = {'code': 'ok', 'http_status': None}
        result.update(phase=self.phase, exception=type(exc).__name__ if exc else 'none')
        result = safe_record(result)
        result['events'] = self.events[-8:]
        result['events_truncated'] = self.events_truncated
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
        self.events_truncated = self.events_truncated or len(self.events) > 8
        self.events = self.events[-8:]
        self.write()

    error = warning
