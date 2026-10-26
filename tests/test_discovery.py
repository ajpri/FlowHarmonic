"""Discovery hints stay untrusted and failures leave the local app usable."""
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flowharmonic.discovery import Discovery, TYPE


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.own = str(uuid.uuid4())
        self.other = str(uuid.uuid4())
        self.membership = SimpleNamespace(node_id=self.own, info=lambda: {'identity': self.own, 'name': 'Office',
            'version': 'M6', 'system': None, 'accepting': False})
        self.discovery = Discovery(self.membership, {'host': '0.0.0.0', 'port': 8080})

    def record(self, properties=None, address='192.168.10.2'):
        return SimpleNamespace(properties=properties or {b'id': self.other.encode(), b'name': b'Living Room', b'protocol': b'1'},
            parsed_addresses=lambda version: [address], port=8080)

    def test_nodes_are_hints_only_and_goodbye_removes_them(self):
        zc = Mock(get_service_info=Mock(return_value=self.record()))
        self.discovery.add_service(zc, TYPE, 'living-room')
        result = self.discovery.snapshot()['nodes']
        self.assertEqual(result[0]['identity'], self.other)
        self.assertFalse(result[0]['is_host'])
        self.assertNotIn('public_key', result[0])
        self.discovery.remove_service(zc, TYPE, 'living-room')
        self.assertFalse(self.discovery.snapshot()['nodes'])
        for record in (self.record(address='8.8.8.8'), self.record(address='169.254.169.254'),
                       self.record({b'id': b'bad', b'protocol': b'1'}),
                       self.record({b'id': self.own.encode(), b'protocol': b'1'})):
            zc.get_service_info.return_value = record
            self.discovery.add_service(zc, TYPE, 'untrusted')
        self.assertFalse(self.discovery.snapshot()['nodes'])

    def test_unavailable_mdns_has_manual_fallback_and_closes_promptly(self):
        with patch.object(self.discovery, 'addresses', return_value=['192.168.10.1']), \
             patch('flowharmonic.discovery.Zeroconf', side_effect=OSError('Restricted sockets')):
            self.discovery.start()
            deadline = time.monotonic() + 2
            while 'unavailable' not in self.discovery.snapshot()['message'] and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertIn('unavailable', self.discovery.snapshot()['message'])
            self.discovery.close()
            self.assertFalse(self.discovery.thread.is_alive())

    def test_unicode_names_fit_dns_sd_and_loopback_is_not_advertised(self):
        self.membership.info = lambda: {'identity': self.own, 'name': '🎵'*80, 'version': 'M6',
            'system': {'id': self.other, 'name': '🎵'*80, 'host_id': self.own}, 'accepting': True}
        with patch.object(self.discovery, 'addresses', return_value=['192.168.10.1']):
            record = self.discovery.record()
        for key, value in record.properties.items():
            self.assertLessEqual(len(key) + 1 + len(value), 255)
        self.discovery.config['host'] = '127.0.0.1'
        self.assertFalse(self.discovery.addresses())


if __name__ == '__main__':
    unittest.main()
