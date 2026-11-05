import io
import unittest
import urllib.request
from email.message import Message
from urllib.response import addinfourl
from unittest.mock import patch
from instagram_session import parse_session
from test_instagram_session import material
import instagram_network as network


class AuthNetworkTests(unittest.TestCase):
    def test_wire_headers_redirect_and_remote_cookies(self):
        self.assertTrue(hasattr(network, 'CredentialBoundary'), 'missing post-cookie HTTP enforcement')
        jar = parse_session(material())
        wires = []
        class RedirectBody(io.BytesIO):
            def read(self, *args):
                raise AssertionError('redirect body must not be read')
        class Wire(urllib.request.HTTPSHandler):
            def https_open(self, req):
                wires.append((req.full_url, dict(req.header_items())))
                headers = Message()
                if len(wires) == 1:
                    headers['Location'] = 'https://scontent.cdninstagram.com/media'
                    headers['Set-Cookie'] = 'sessionid=evil; Domain=.cdninstagram.com; Secure; Path=/'
                    response = addinfourl(RedirectBody(b'private redirect payload'), headers, req.full_url, 302)
                    response.msg = 'Found'
                else:
                    response = addinfourl(io.BytesIO(b'ok'), headers, req.full_url, 200)
                    response.msg = 'OK'
                return response
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Wire(),
                    urllib.request.HTTPCookieProcessor(jar), network.CredentialBoundary(jar))
        if hasattr(network, 'NoDrainRedirect'):
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Wire(),
                urllib.request.HTTPCookieProcessor(jar), network.CredentialBoundary(jar), network.NoDrainRedirect())
        with patch('socket.socket.connect', side_effect=AssertionError('network forbidden')):
            opener.open(urllib.request.Request('https://www.instagram.com/p/abc/',
                        headers={'Cookie':'injected=secret', 'Authorization':'Bearer secret'})).close()
            opener.open(urllib.request.Request('https://other.instagram.com/x',
                        headers={'Cookie':'injected=secret', 'Authorization':'Bearer secret'})).close()
        first = {k.lower(): v for k,v in wires[0][1].items()}
        self.assertIn('sessionid=fixture-session', first['cookie'])
        self.assertNotIn('injected', first['cookie'])
        self.assertNotIn('authorization', first)
        for _, headers in wires[1:]:
            self.assertFalse({'cookie', 'authorization'} & {k.lower() for k in headers})
        self.assertNotIn('evil', [c.value for c in jar])

    def test_unsafe_redirect_rejected_before_wire(self):
        self.assertTrue(hasattr(network, 'CredentialBoundary'), 'missing HTTP boundary')
        boundary = network.CredentialBoundary(parse_session(material()))
        for url in ['http://www.instagram.com/x', 'https://evil.com/x',
                    'https://user:pw@www.instagram.com/x', 'https://www.instagram.com:444/x']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                boundary.https_request(urllib.request.Request(url))
