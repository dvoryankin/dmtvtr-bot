import os
import tempfile
import time
import unittest
from pathlib import Path
import instagram_session as session


def material(expiry=None):
    expiry = int(time.time()) + 3600 if expiry is None else expiry
    return ('# Netscape HTTP Cookie File\n' + ''.join(
        '.instagram.com\tTRUE\t/\tTRUE\t%d\t%s\t%s\n' % (expiry, k, v)
        for k, v in [('sessionid', 'fixture-session'), ('csrftoken', 'fixture-csrf'), ('ds_user_id', '123')])).encode()


class SessionTests(unittest.TestCase):
    def test_absent_session_is_disabled_even_in_nonprivate_directory(self):
        with tempfile.TemporaryDirectory() as raw:
            Path(raw).chmod(0o755)
            self.assertIsNone(session.open_session(Path(raw) / 'missing.cookies.txt'))

    def test_optional_safe_file_and_memory_only_exact_hosts(self):
        with tempfile.TemporaryDirectory() as raw:
            p = Path(raw) / 'session.cookies.txt'
            self.assertIsNone(session.open_session(p))
            p.write_bytes(material()); p.chmod(0o600)
            fd = session.open_session(p)
            jar = session.read_session(fd)
            with self.assertRaises(OSError): os.fstat(fd)
            self.assertEqual({c.domain for c in jar}, {'www.instagram.com', 'i.instagram.com'})
            self.assertFalse(hasattr(jar, 'save'))
            self.assertEqual(p.read_bytes(), material())

    def test_reject_file_and_parser_boundaries(self):
        with tempfile.TemporaryDirectory() as raw:
            p = Path(raw) / 'session.cookies.txt'
            p.write_bytes(material()); p.chmod(0o644)
            with self.assertRaisesRegex(ValueError, '^session_invalid$'): session.open_session(p)
            p.chmod(0o600)
            link = Path(raw) / 'link'; link.symlink_to(p)
            with self.assertRaises(ValueError): session.open_session(link)
            p.write_bytes(b'x' * 32769)
            with self.assertRaises(ValueError): session.open_session(p)
            p.write_bytes(material())
            Path(raw).chmod(0o755)
            with self.assertRaises(ValueError): session.open_session(p)
            Path(raw).chmod(0o700)
        for data in [material(1), material(0), material().replace(b'TRUE\t', b'FALSE\t'),
                     material().replace(b'.instagram.com', b'.evil.com'),
                     material().replace(b'\t/\t', b'\t/private\t'), b'invalid',
                     material() + material(), material().replace(b'fixture-session', b'bad;value')]:
            with self.subTest(data=data[:30]):
                with self.assertRaisesRegex(ValueError, '^session_invalid$'): session.parse_session(data)
