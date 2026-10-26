"""Untrusted IPv4 mDNS hints. Enrollment always verifies and pins node keys."""
import ipaddress
import logging
import socket
import threading
import time
import uuid

import ifaddr
from zeroconf import IPVersion, ServiceBrowser, ServiceInfo, Zeroconf

TYPE = '_flowharmonic._tcp.local.'


class Discovery:
    def __init__(self, membership, config, advertise=True):
        self.membership = membership
        self.config = config
        self.advertise = advertise
        self.lock = threading.Lock()
        self.nodes = {}
        self.message = 'Looking for nearby FlowHarmonic nodes…'
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.run, name='fh-discovery', daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=8)

    def snapshot(self):
        with self.lock:
            # Zeroconf removes records on goodbye or DNS TTL expiry, including
            # refreshes that leave TXT data unchanged.
            nodes = [dict(node) for node in self.nodes.values()]
            return {'nodes': [{k: v for k, v in node.items() if k != 'seen'} for node in sorted(nodes, key=lambda n: n['name'])],
                    'message': self.message}

    def addresses(self):
        host = self.config['host']
        if host != '0.0.0.0':
            try:
                ip = ipaddress.ip_address(host)
                return [str(ip)] if ip.version == 4 and not ip.is_loopback else []
            except ValueError:
                return []
        addresses = set()
        for adapter in ifaddr.get_adapters():
            for address in adapter.ips:
                if isinstance(address.ip, str):
                    ip = ipaddress.ip_address(address.ip)
                    if ip.version == 4 and not (ip.is_loopback or ip.is_link_local or ip.is_unspecified):
                        addresses.add(str(ip))
        return sorted(addresses)

    def record(self):
        info = self.membership.info()
        system = info['system']
        properties = {'protocol': '1', 'id': info['identity'], 'name': info['name'], 'version': info['version'],
                      'system': system['id'] if system else '', 'system_name': system['name'] if system else '',
                      'host': system['host_id'] if system else '', 'accepting': '1' if info['accepting'] else '0'}
        # DNS-SD TXT strings have a 255-byte limit, including their key.
        properties['name'] = properties['name'].encode()[:200].decode(errors='ignore')
        properties['system_name'] = properties['system_name'].encode()[:200].decode(errors='ignore')
        return ServiceInfo(TYPE, info['identity'] + '.' + TYPE, parsed_addresses=self.addresses(),
                           port=self.config['port'], properties=properties,
                           server='fh-' + info['identity'] + '.local.', host_ttl=30, other_ttl=30)

    def run(self):
        while not self.stop_event.is_set():
            zc = browser = record = None
            try:
                interfaces = self.addresses()
                zc = Zeroconf(ip_version=IPVersion.V4Only)
                browser = ServiceBrowser(zc, TYPE, self)
                while not self.stop_event.is_set():
                    if not self.advertise:
                        with self.lock:
                            self.message = 'Nearby nodes are suggestions only. Joining requires approval on both devices.'
                        self.stop_event.wait(5)
                        continue
                    candidate = self.record()
                    if candidate.parsed_addresses() != interfaces:
                        # Reopen multicast sockets after LAN interfaces change.
                        break
                    if not candidate.parsed_addresses():
                        if record is not None:
                            zc.unregister_service(record)
                            record = None
                        with self.lock:
                            self.message = 'No LAN address is available for discovery. You can connect using an address below.'
                    else:
                        if record is None:
                            zc.register_service(candidate)
                        elif candidate.properties != record.properties or candidate.addresses != record.addresses:
                            zc.update_service(candidate)
                        record = candidate
                        with self.lock:
                            self.message = 'Nearby nodes are suggestions only. Joining requires approval on both devices.'
                    self.stop_event.wait(5)
            except Exception as error:
                # Discovery must never take down standalone audio or the dashboard.
                logging.getLogger(__name__).warning('LAN discovery unavailable (%s); retrying automatically', type(error).__name__)
                with self.lock:
                    self.message = 'Nearby discovery is unavailable. Use a node’s local address below; discovery will retry automatically.'
            finally:
                if browser:
                    browser.cancel()
                if zc:
                    zc.close()
            self.stop_event.wait(20)

    def add_service(self, zc, type_, name):
        self.update_service(zc, type_, name)

    def update_service(self, zc, type_, name):
        try:
            info = zc.get_service_info(type_, name, timeout=1000)
            if not info:
                return
            properties = {k.decode(): v.decode() for k, v in info.properties.items() if isinstance(k, bytes) and isinstance(v, bytes)}
            node_id = properties['id']
            uuid.UUID(node_id)
            if node_id == self.membership.node_id or properties.get('protocol') != '1':
                return
            addresses = info.parsed_addresses(IPVersion.V4Only)
            if not addresses or not info.port:
                return
            address = ipaddress.ip_address(addresses[0])
            if not address.is_private or address.is_link_local or address.is_loopback or address.is_unspecified or address.is_multicast:
                return
            system_id = properties.get('system', '')
            host_id = properties.get('host', '')
            if system_id:
                uuid.UUID(system_id)
                uuid.UUID(host_id)
            entry = {'identity': node_id, 'name': properties.get('name', 'Nearby node')[:80],
                     'version': properties.get('version', '')[:16], 'url': f'http://{address}:{info.port}',
                     'system_id': system_id, 'system_name': properties.get('system_name', '')[:80],
                     'is_host': bool(system_id and host_id == node_id), 'accepting': properties.get('accepting') == '1',
                     'seen': time.monotonic()}
            with self.lock:
                if len(self.nodes) < 100 or name in self.nodes:
                    self.nodes[name] = entry
        except (OSError, ValueError, KeyError, UnicodeError, TypeError):
            return

    def remove_service(self, zc, type_, name):
        with self.lock:
            self.nodes.pop(name, None)
