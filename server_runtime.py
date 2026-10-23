"""Bind local HTTP safely and publish the actual address to the launcher."""
import errno
import hashlib
from http.server import ThreadingHTTPServer
import json
import os
import socket

VERSION = '0.5.2'


def data_identity(data):
    return hashlib.sha256(str(data.resolve()).casefold().encode('utf-8')).hexdigest()


def bind_server(handler, host, port, auto_port=False, factory=ThreadingHTTPServer):
    candidates = [port]
    if auto_port and port:
        candidates.extend(p for p in (8765, 0) if p != port)
    failures = []
    for candidate in candidates:
        http = factory((host, candidate), handler, bind_and_activate=False)
        try:
            if os.name == 'nt':
                http.allow_reuse_address = False
                http.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            http.server_bind()
            http.server_activate()
            return http, failures
        except OSError as exc:
            http.server_close()
            if getattr(exc, 'winerror', None) not in (10013, 10048) and exc.errno not in (errno.EACCES, errno.EADDRINUSE):
                raise
            failures.append({'port': candidate, 'code': getattr(exc, 'winerror', None) or exc.errno})
    raise RuntimeError(
        f'Cannot bind local port {port}. Windows may reserve it or another app may use it. '
        'Run start_mathlens.bat to choose an available port automatically.'
    )


def publish_address(data, http):
    host, port = http.server_address[:2]
    address = {'url': f'http://{host}:{port}/', 'pid': os.getpid(),
               'version': VERSION, 'data_id': data_identity(data)}
    temporary = data / f'server-{os.getpid()}.tmp'
    temporary.write_text(json.dumps(address), encoding='utf-8')
    temporary.replace(data / 'server.json')
    return address


def clear_address(data, pid):
    path = data / 'server.json'
    try:
        if json.loads(path.read_text(encoding='utf-8')).get('pid') == pid:
            path.unlink()
    except (OSError, ValueError):
        pass
