"""Local socket ownership and the launcher's address file."""

import errno
import hashlib
import json
import os
import socket

from app.version import VERSION


def data_identity(data):
    return hashlib.sha256(str(data.resolve()).casefold().encode('utf-8')).hexdigest()


def bind_socket(host, port, auto_port=False, factory=socket.socket):
    """Bind once, then pass the owned socket to Uvicorn without a port race."""
    candidates = [port]
    if auto_port and port:
        candidates.extend(p for p in (8765, 0) if p != port)
    failures = []
    for candidate in candidates:
        sock = factory(socket.AF_INET6 if ':' in host else socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name == 'nt':
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, candidate))
            sock.listen(128)
            sock.setblocking(False)
            return sock, failures
        except OSError as exc:
            sock.close()
            if getattr(exc, 'winerror', None) not in (10013, 10048) and exc.errno not in (errno.EACCES, errno.EADDRINUSE):
                raise
            failures.append({'port': candidate, 'code': getattr(exc, 'winerror', None) or exc.errno})
    raise RuntimeError(f'Cannot bind local port {port}. Run start_mathlens.bat to choose an available port automatically.')


def publish_address(data, sock):
    host, port = sock.getsockname()[:2]
    host_url = f'[{host}]' if ':' in host else host
    address = {
        'url': f'http://{host_url}:{port}/',
        'pid': os.getpid(),
        'version': VERSION,
        'data_id': data_identity(data),
    }
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
