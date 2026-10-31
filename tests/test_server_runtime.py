import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.hosting import bind_socket, publish_address, clear_address, data_identity
from app.version import VERSION


class FakeSocket:
    def __init__(self, errors):
        self.errors = errors
        self.closed = self.listening = False

    def setsockopt(self, *args):
        pass

    def bind(self, address):
        if address[1] in self.errors:
            raise self.errors[address[1]]
        self.address = (address[0], address[1] or 30001)

    def getsockname(self):
        return self.address

    def listen(self, backlog):
        self.listening = True

    def setblocking(self, value):
        pass

    def close(self):
        self.closed = True


class ServerRuntimeTests(unittest.TestCase):
    def make_factory(self, errors):
        instances = []
        def factory(family, kind):
            instance = FakeSocket(errors)
            instances.append(instance)
            return instance
        return factory, instances

    def test_reserved_and_occupied_ports_fall_back_to_os_assigned_port(self):
        denied = PermissionError(errno.EACCES, 'reserved')
        denied.winerror = 10013
        factory, instances = self.make_factory({4173: denied, 8765: OSError(errno.EADDRINUSE, 'occupied')})
        sock, failures = bind_socket('127.0.0.1', 4173, True, factory)
        self.assertEqual(sock.getsockname(), ('127.0.0.1', 30001))
        self.assertTrue(sock.listening)
        self.assertEqual([x['port'] for x in failures], [4173, 8765])
        self.assertTrue(all(x.closed for x in instances[:2]))
        self.assertFalse(sock.closed)

    def test_healthy_preferred_port_is_used_without_fallback(self):
        factory, instances = self.make_factory({})
        sock, failures = bind_socket('127.0.0.1', 4173, True, factory)
        self.assertEqual(sock.getsockname()[1], 4173)
        self.assertEqual(failures, [])
        self.assertEqual(len(instances), 1)

    def test_fixed_port_reports_actionable_error_and_closes_socket(self):
        factory, instances = self.make_factory({4173: PermissionError(errno.EACCES, 'reserved')})
        with self.assertRaisesRegex(RuntimeError, 'start_mathlens.bat'):
            bind_socket('127.0.0.1', 4173, False, factory)
        self.assertEqual(len(instances), 1)
        self.assertTrue(instances[0].closed)

    def test_other_errors_are_not_hidden_by_port_fallback(self):
        factory, instances = self.make_factory({4173: OSError(errno.ENETDOWN, 'network down')})
        with self.assertRaises(OSError):
            bind_socket('127.0.0.1', 4173, True, factory)
        self.assertEqual(len(instances), 1)
        self.assertTrue(instances[0].closed)

    def test_launcher_address_contains_actual_port_and_data_identity(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp', prefix='runtime-test-') as folder:
            data = Path(folder)
            sock, _ = bind_socket('127.0.0.1', 8765, factory=self.make_factory({})[0])
            result = publish_address(data, sock)
            self.assertEqual(result['url'], 'http://127.0.0.1:8765/')
            self.assertEqual(result['data_id'], data_identity(data))
            self.assertEqual(json.loads((data / 'server.json').read_text()), result)
            clear_address(data, result['pid'] + 1)
            self.assertTrue((data / 'server.json').is_file())
            clear_address(data, result['pid'])
            self.assertFalse((data / 'server.json').exists())

    def test_package_entry_starts_isolated_http_service_without_connecting_codex(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp', prefix='package-entry-') as folder:
            data = Path(folder)
            dist = data / 'dist'
            dist.mkdir()
            (dist / 'index.html').write_text('<html>package entry</html>')
            env = {**os.environ, 'MATHLENS_DATA_DIR': str(data), 'MATHLENS_DIST_DIR': str(dist)}
            with (data / 'stderr.log').open('w', encoding='utf-8') as error_log:
                process = subprocess.Popen(
                    [sys.executable, '-X', 'utf8', '-m', 'app', '--port', '0'],
                    cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=error_log,
                )
                try:
                    deadline = time.monotonic() + 20
                    address_file = data / 'server.json'
                    while not address_file.exists() and process.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.1)
                    self.assertTrue(address_file.exists(), (data / 'stderr.log').read_text(encoding='utf-8'))
                    address = json.loads(address_file.read_text(encoding='utf-8'))
                    opener = build_opener(ProxyHandler({}))
                    with opener.open(address['url'] + 'api/health', timeout=5) as response:
                        health = json.load(response)
                    self.assertEqual(health['version'], VERSION)
                    self.assertEqual(health['data_id'], data_identity(data))
                    with opener.open(address['url'], timeout=5) as response:
                        self.assertIn(b'package entry', response.read())
                    with opener.open(address['url'] + 'api/agent/state', timeout=5) as response:
                        state = json.load(response)
                    self.assertFalse(state['connected'])
                    self.assertEqual(state['turns'], [])
                finally:
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=10)


if __name__ == '__main__':
    unittest.main()
