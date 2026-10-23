import errno
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server_runtime import bind_server, publish_address, clear_address, data_identity


class FakeSocket:
    def setsockopt(self, *args):
        pass


class FakeHTTP:
    def __init__(self, address, error=None):
        self.server_address = address
        self.socket = FakeSocket()
        self.error = error
        self.closed = self.activated = False

    def server_bind(self):
        if self.error:
            raise self.error
        if self.server_address[1] == 0:
            self.server_address = (self.server_address[0], 30001)

    def server_activate(self):
        self.activated = True

    def server_close(self):
        self.closed = True


class ServerRuntimeTests(unittest.TestCase):
    def make_factory(self, errors):
        instances = []
        def factory(address, handler, bind_and_activate):
            self.assertFalse(bind_and_activate)
            instance = FakeHTTP(address, errors.get(address[1]))
            instances.append(instance)
            return instance
        return factory, instances

    def test_reserved_and_occupied_ports_fall_back_to_os_assigned_port(self):
        denied = PermissionError(errno.EACCES, 'reserved')
        denied.winerror = 10013
        factory, instances = self.make_factory({4173: denied, 8765: OSError(errno.EADDRINUSE, 'occupied')})
        http, failures = bind_server(None, '127.0.0.1', 4173, True, factory)
        self.assertEqual(http.server_address, ('127.0.0.1', 30001))
        self.assertTrue(http.activated)
        self.assertEqual([x['port'] for x in failures], [4173, 8765])
        self.assertTrue(all(x.closed for x in instances[:2]))
        self.assertFalse(http.closed)

    def test_healthy_preferred_port_is_used_without_fallback(self):
        factory, instances = self.make_factory({})
        http, failures = bind_server(None, '127.0.0.1', 4173, True, factory)
        self.assertEqual(http.server_address[1], 4173)
        self.assertEqual(failures, [])
        self.assertEqual(len(instances), 1)

    def test_fixed_port_reports_actionable_error_and_closes_socket(self):
        factory, instances = self.make_factory({4173: PermissionError(errno.EACCES, 'reserved')})
        with self.assertRaisesRegex(RuntimeError, 'start_mathlens.bat'):
            bind_server(None, '127.0.0.1', 4173, False, factory)
        self.assertEqual(len(instances), 1)
        self.assertTrue(instances[0].closed)

    def test_other_errors_are_not_hidden_by_port_fallback(self):
        factory, instances = self.make_factory({4173: OSError(errno.ENETDOWN, 'network down')})
        with self.assertRaises(OSError):
            bind_server(None, '127.0.0.1', 4173, True, factory)
        self.assertEqual(len(instances), 1)
        self.assertTrue(instances[0].closed)

    def test_launcher_address_contains_actual_port_and_data_identity(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp', prefix='runtime-test-') as folder:
            data = Path(folder)
            result = publish_address(data, FakeHTTP(('127.0.0.1', 8765)))
            self.assertEqual(result['url'], 'http://127.0.0.1:8765/')
            self.assertEqual(result['data_id'], data_identity(data))
            self.assertEqual(json.loads((data / 'server.json').read_text()), result)
            clear_address(data, result['pid'] + 1)
            self.assertTrue((data / 'server.json').is_file())
            clear_address(data, result['pid'])
            self.assertFalse((data / 'server.json').exists())


if __name__ == '__main__':
    unittest.main()
