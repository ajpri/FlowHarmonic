import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from flowharmonic.hardware import playback_outputs
from flowharmonic.local_audio import local_inventory
from flowharmonic.provision import MARKER, SOURCES, Provisioner, server_configuration
from flowharmonic.state import initialize, identity


class Commands:
    def __init__(self):
        self.calls = []
        self.active = set()
    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if args[1] == 'is-active':
            return subprocess.CompletedProcess(args, 0 if args[-1] in self.active else 3, '', '')
        if args[1] in ('start', 'restart'):
            self.active.add(args[-1])
        if args[1] == 'disable':
            self.active.discard(args[-1])
        return subprocess.CompletedProcess(args, 0, '', '')


class Audio:
    def __init__(self):
        self.clients = []
    def status(self):
        return {'streams': [{'id': name} for _, name, _ in SOURCES], 'groups': []}


class ProvisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.etc = self.root / 'etc/flowharmonic'
        self.etc.mkdir(parents=True)
        self.ledger = self.etc / 'infrastructure.json'
        self.ledger.write_text(json.dumps({'server': 'flowharmonic', 'client': 'flowharmonic'}))
        self.db = initialize(self.root / 'var/lib/flowharmonic')
        self.node = identity(self.db)
        self.bin = self.root / 'usr/bin'
        self.bin.mkdir(parents=True)
        for name in ('snapserver', 'snapclient'):
            binary = self.bin / name
            binary.write_text('test executable')
            binary.chmod(0o755)
        self.base = self.root / 'etc/snapserver.conf'
        self.base.write_text('[server]\n# user setting\n[stream]\nsource = pipe:///tmp/user?name=Existing\n')
        self.commands = Commands()
        self.output = {'key': 'a' * 20, 'name': 'Analog output', 'device': 'plughw:CARD=PCH,DEV=0', 'connected': True}
        self.outputs = [self.output]
        self.config = {'snapcast_url': 'tcp://127.0.0.1:1705'}

    def tearDown(self):
        self.temp.cleanup()

    def provision(self, probe=lambda device: ''):
        p = Provisioner(self.root, runner=self.commands, detector=lambda: self.outputs, probe=probe)
        with patch('flowharmonic.provision.time.sleep'):
            return p.provision(self.config, audio=Audio())

    def test_progress_saves_ownership_without_publishing_partial_device_inventory(self):
        status = self.etc / 'local-audio.json'
        complete = {'owner':self.node, 'destinations':[{'id':'speaker','name':'Office'}],
                    'sources':[{'id':'microphone'}], 'owned_units':[]}
        status.write_text(json.dumps(complete))
        provisioner = Provisioner(self.root)
        provisioner.status['owner'] = self.node
        provisioner.status['sources'] = []
        provisioner.status['owned_units'].append('flowharmonic-playback-12345678901234567890.service')
        provisioner.save(progress=True)
        observed = json.loads(status.read_text())
        self.assertEqual(observed['destinations'], complete['destinations'])
        self.assertEqual(observed['sources'], complete['sources'])
        self.assertIn('flowharmonic-playback-12345678901234567890.service', observed['owned_units'])
        provisioner.save()
        self.assertEqual(json.loads(status.read_text())['destinations'], [])

    def test_configured_sources_have_owned_workers_and_leave_external_services_alone(self):
        from flowharmonic.sources import Sources
        store=Sources(self.root/'var/lib/flowharmonic')
        identifier=str(uuid.uuid4())
        store.save({'id':identifier,'name':'Microphone','kind':'input','device':'alsa:known','channels':[1],'state':'stopped'})
        before=self.base.read_bytes()
        result=self.provision()
        self.assertEqual(self.base.read_bytes(),before)
        unit=self.root/'etc/systemd/system'/('flowharmonic-source-'+identifier+'.service')
        self.assertTrue(unit.read_text().startswith(MARKER))
        self.assertIn('User=flowharmonic',unit.read_text())
        self.assertEqual(result['sources'][0]['id'],'fh-source-'+identifier)
        self.assertIn('name=fh-source-'+identifier,(self.etc/'local-snapserver.conf').read_text())
        store.remove(identifier);self.provision();self.assertFalse(unit.exists())
        self.assertEqual(self.base.read_bytes(),before)
        store.save({'id':identifier,'name':'Microphone','kind':'input','device':'alsa:known','channels':[1],'state':'playing'})
        self.ledger.write_text(json.dumps({'server':'existing','client':'existing'}))
        self.provision();self.assertFalse(unit.exists())

    def test_fresh_provisioning_preserves_configuration_and_identity(self):
        before = self.base.read_bytes()
        result = self.provision()
        self.assertEqual(self.base.read_bytes(), before)
        self.assertEqual(identity(self.db), self.node)
        generated = (self.etc / 'local-snapserver.conf').read_text()
        self.assertIn('name=Silence', generated)
        self.assertIn('name=Test%20tone%20440%20Hz', generated)
        self.assertIn('pipe:///tmp/user?name=Existing', generated)
        self.assertLess(generated.index('name=Silence'), generated.index('name=Existing'))
        self.assertTrue((self.root / 'var/lib/flowharmonic-audio/tones/tone-440.pcm').exists())
        unit = result['destinations'][0]['unit']
        content = (self.root / 'etc/systemd/system' / unit).read_text()
        self.assertIn('--player alsa', content)
        self.assertIn('plughw:CARD=PCH,DEV=0', content)
        self.assertIn('User=flowharmonic-audio', content)
        self.assertIn(['systemctl', 'enable', unit], self.commands.calls)
        self.assertIn(['alsactl', 'init', 'PCH'], self.commands.calls)
        first_id = result['destinations'][0]['id']
        self.commands.calls.clear()
        self.assertEqual(self.provision()['destinations'][0]['id'], first_id)
        self.assertFalse(any(args[1] == 'restart' for args in self.commands.calls))
        self.assertFalse(any(args[0] == 'alsactl' for args in self.commands.calls))

    def test_alsa_generic_initialization_exit_is_accepted(self):
        original = self.commands.__call__
        def runner(args, **kwargs):
            if args[0] == 'alsactl':
                return subprocess.CompletedProcess(args, 99, '', 'Hardware is initialized using a generic method')
            return original(args, **kwargs)
        p = Provisioner(self.root, runner=runner, detector=lambda: self.outputs, probe=lambda device: '')
        with patch('flowharmonic.provision.time.sleep'):
            result = p.provision(self.config, audio=Audio())
        self.assertIn(result['destinations'][0]['unit'], result['owned_units'])

    def test_missing_inventory_recovers_marked_running_player_without_busy_probe(self):
        first=self.provision()
        (self.etc/'local-audio.json').unlink()
        self.commands.calls.clear()
        with patch('flowharmonic.provision.uuid.uuid5',return_value=uuid.UUID('12345678-1234-1234-1234-123456789abc')):
            result=self.provision(probe=lambda device:self.fail('An owned running player must not be probed as a foreign busy device'))
        row=result['destinations'][0]
        self.assertEqual(row['id'],'fh-12345678123412341234123456789abc')
        self.assertIn(row['unit'],result['owned_units'])
        self.assertEqual(row['message'],'')
        self.assertIn('--hostID '+row['id'],(self.root/'etc/systemd/system'/row['unit']).read_text())
        self.assertIn(['systemctl','restart',row['unit']],self.commands.calls)
        self.assertFalse(any(args[0]=='alsactl' for args in self.commands.calls))

    def test_saved_hardware_mixer_state_is_not_reset(self):
        state = self.root / 'var/lib/alsa/asound.state'
        state.parent.mkdir(parents=True)
        state.write_text('existing user mixer settings')
        self.provision()
        self.assertFalse(any(args[0] == 'alsactl' for args in self.commands.calls))
        self.assertEqual(state.read_text(), 'existing user mixer settings')

    def test_distribution_server_account_is_retained(self):
        (self.root / 'etc/passwd').write_text('_snapserver:x:112:120::/var/lib/snapserver:/usr/sbin/nologin\n')
        self.provision()
        unit = (self.root / 'etc/systemd/system/flowharmonic-snapserver.service').read_text()
        self.assertIn('User=_snapserver\nGroup=_snapserver', unit)
        self.assertIn('StateDirectory=snapserver', unit)

    def test_preexisting_components_and_remote_endpoint_are_untouched(self):
        for ownership in ({'server': 'existing', 'client': 'flowharmonic'}, {'server': 'flowharmonic', 'client': 'existing'}):
            self.ledger.write_text(json.dumps(ownership))
            self.provision()
            self.assertEqual(self.commands.calls, [])
            self.assertFalse((self.root / 'var/lib/flowharmonic-audio/tones').exists())
        self.ledger.write_text(json.dumps({'server': 'flowharmonic', 'client': 'flowharmonic'}))
        self.config['snapcast_url'] = 'tcp://192.0.2.15:1705'
        self.provision()
        self.assertEqual(self.commands.calls, [])

    def test_busy_output_is_visible_and_retried(self):
        result = self.provision(probe=lambda device: 'This output is in use.')
        self.assertEqual(result['destinations'][0]['message'], 'This output is in use.')
        self.assertFalse(any('playback-' in args[-1] for args in self.commands.calls))
        self.commands.calls.clear()
        result = self.provision()
        self.assertEqual(result['destinations'][0]['message'], '')
        self.assertTrue(any('playback-' in args[-1] for args in self.commands.calls))

    def test_absent_and_disconnected_outputs_do_not_create_fake_players(self):
        self.outputs = [{**self.output, 'connected': False}]
        result = self.provision()
        self.assertEqual(result['destinations'], [])
        self.assertIn('No connected', result['message'])
        self.assertFalse(any('playback-' in args[-1] for args in self.commands.calls))

    def test_removed_hardware_stops_only_owned_players(self):
        result = self.provision()
        unit = result['destinations'][0]['unit']
        unrelated = self.root / 'etc/systemd/system/snapclient-custom.service'
        unrelated.write_text('unrelated service')
        self.outputs = []
        self.commands.calls.clear()
        self.provision()
        self.assertIn(['systemctl', 'disable', '--now', unit], self.commands.calls)
        self.assertFalse((self.root / 'etc/systemd/system' / unit).exists())
        self.assertEqual(unrelated.read_text(), 'unrelated service')
        self.assertFalse(any(args[-1] == 'snapclient-custom.service' for args in self.commands.calls))

    def test_foreign_unit_and_source_name_collision_are_not_overwritten(self):
        unit = self.root / 'etc/systemd/system/flowharmonic-snapserver.service'
        unit.parent.mkdir(parents=True)
        unit.write_text('unrelated service')
        with self.assertRaisesRegex(RuntimeError, 'unrelated'):
            self.provision()
        self.assertEqual(unit.read_text(), 'unrelated service')
        with self.assertRaisesRegex(RuntimeError, 'reserved'):
            server_configuration('[stream]\nsource = pipe:///foreign?name=Silence\n', Path('/assets'))
        self.assertEqual(self.commands.calls, [])

    def test_status_never_merges_other_nodes_or_endpoints(self):
        result = self.provision(probe=lambda device: 'In use.')
        with patch.dict(os.environ, {'FLOWHARMONIC_CONFIG': str(self.etc / 'config.toml')}):
            snapshot = local_inventory({'sources': [], 'destinations': []}, self.node, self.config['snapcast_url'])
            self.assertFalse(snapshot['destinations'][0]['available'])
            self.assertEqual(snapshot['destinations'][0]['message'], 'In use.')
            self.assertEqual(local_inventory({'destinations': []}, str(uuid.uuid4()), self.config['snapcast_url']), {'destinations': []})
            self.assertEqual(local_inventory({'destinations': []}, self.node, 'tcp://elsewhere:1705'), {'destinations': []})


class DiscoveryTests(unittest.TestCase):
    def test_stable_physical_id_across_card_number_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hardware = root / 'pci-device'
            hardware.mkdir()
            for card_number in (0, 2):
                card = root / 'proc' / f'card{card_number}'
                (card / 'pcm0p').mkdir(parents=True)
                (card / 'id').write_text('PCH\n')
                (card / 'pcm0p/info').write_text('name: Analog output\n')
                sys = root / 'sys' / f'card{card_number}'
                sys.mkdir(parents=True)
                (sys / 'device').symlink_to(hardware)
            outputs = playback_outputs(root / 'proc', root / 'sys')
            self.assertEqual(outputs[0]['key'], outputs[1]['key'])
            self.assertEqual(outputs[0]['device'], 'plughw:CARD=PCH,DEV=0')
            self.assertEqual(outputs[0]['name'], 'Analog output')

    def test_disconnected_hdmi_and_capture_only_card(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            card = root / 'card0'
            (card / 'pcm3p').mkdir(parents=True)
            (card / 'pcm0c').mkdir()
            (card / 'id').write_text('PCH\n')
            (card / 'pcm3p/info').write_text('name: HDMI 0\n')
            (card / 'eld#0').write_text('monitor_present 0\neld_valid 0\n')
            outputs = playback_outputs(root, root / 'sys')
            self.assertEqual(len(outputs), 1)
            self.assertFalse(outputs[0]['connected'])


if __name__ == '__main__':
    unittest.main()
