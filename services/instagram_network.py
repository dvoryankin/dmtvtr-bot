"""Fail-closed outbound socket policy, installed ONLY in the disposable worker.

stdlib urllib resolves through getaddrinfo then connects to the returned numeric
address. Validate the complete DNS answer, and validate the actual connect address
again (no second name resolution / DNS rebinding). Redirects use the same policy.
No proxies, curl, ffmpeg, external downloaders, or alternative HTTP handlers.
"""
import ipaddress
import socket


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
