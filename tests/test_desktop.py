"""Desktop graph safety and login lifecycle; real PipeWire acceptance is separate."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from flowharmonic.desktop import CAPTURE_NODE, graph_links
from flowharmonic.desktop_provision import active_session, prepare, start
from flowharmonic.local_audio import desktop_inventory
import test_provision


def node(i, name, media_class, binary=''):
    return {'id': i, 'type': 'PipeWire:Interface:Node', 'info': {'props': {
        'node.name': name, 'media.class': media_class, 'application.process.binary': binary}}}


def port(i, n, channel, direction):
    return {'id': i, 'type': 'PipeWire:Interface:Port', 'info': {'props': {
        'node.id': n, 'audio.channel': channel, 'port.direction': direction}}}


def link(i, outnode, outport, innode, inport):
    return {'id': i, 'type': 'PipeWire:Interface:Link', 'info': {
        'output-node-id': outnode, 'output-port-id': outport, 'input-node-id': innode, 'input-port-id': inport}}


class GraphTests(unittest.TestCase):
    def graph(self):
        return [node(1, 'speakers', 'Audio/Sink'), node(2, CAPTURE_NODE, 'Stream/Input/Audio'),
                node(3, 'browser', 'Stream/Output/Audio', 'firefox'),
                node(4, 'ALSA plug-in [snapclient]', 'Stream/Output/Audio', 'snapclient'),
                node(5, 'mic', 'Audio/Source'),
                port(21, 2, 'FL', 'in'), port(22, 2, 'FR', 'in'),
                port(31, 3, 'FL', 'out'), port(32, 3, 'FR', 'out'),
                port(41, 4, 'FL', 'out'), port(51, 5, 'FL', 'out'),
                link(100, 3, 31, 1, 11), link(101, 3, 32, 1, 12), link(102, 4, 41, 1, 11)]

    def test_additive_capture_excludes_feedback_and_mic(self):
        graph = self.graph()
        before = json.dumps(graph)
        desired, existing, ready, _ = graph_links(graph)
        self.assertEqual(desired, {(31, 21), (32, 22)})
        self.assertEqual(existing, set())
        self.assertTrue(ready)
        self.assertEqual(json.dumps(graph), before)
        graph.append(link(103, 4, 41, 2, 21))
        desired, existing, *_ = graph_links(graph)
        self.assertEqual(existing - desired, {(41, 21)})

    def test_media_title_does_not_misidentify_normal_playback(self):
        graph = self.graph()
        graph[2]['info']['props']['media.name'] = '/home/user/FlowHarmonic/song.wav'
        self.assertIn((31, 21), graph_links(graph)[0])

    def test_native_client_identity_also_excludes_snapclient(self):
        graph = self.graph()
        graph[3]['info']['props'].update({'node.name': 'custom speaker', 'application.process.binary': '', 'client.id': 88})
        graph.append({'id': 88, 'type': 'PipeWire:Interface:Client', 'info': {'props': {
            'application.process.binary': 'snapclient'}}})
        # Node properties should not erase useful binary identity from a client;
        # actual older native nodes omit the binary key rather than sending it empty.
        del graph[3]['info']['props']['application.process.binary']
        self.assertNotIn((41, 21), graph_links(graph)[0])

    def test_mono_and_apps_without_speaker_link(self):
        graph = self.graph()
        graph.append(node(6, 'not-playing', 'Stream/Output/Audio'))
        graph.append(port(61, 6, 'FL', 'out'))
        graph.append(node(7, 'mono', 'Stream/Output/Audio'))
        graph.append(port(71, 7, 'MONO', 'out'))
        graph.append(link(104, 7, 71, 1, 11))
        desired, *_ = graph_links(graph)
        self.assertIn((71, 21), desired)
        self.assertIn((71, 22), desired)
        self.assertNotIn((61, 21), desired)

    def test_stale_session_disables_source_and_playback(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'status.json'
            path.write_text(json.dumps({'available': True, 'playback': True, 'updated': time.time() - 60}))
            data = {'sources': [{'id': 'Desktop Audio', 'status': 'playing'}],
                    'destinations': [{'id': 'desk', 'available': True}]}
            with patch('flowharmonic.local_audio.Path', return_value=path):
                desktop_inventory(data, {'source': 'Desktop Audio', 'uid': 1000, 'session': '4', 'destination': 'desk'})
            self.assertEqual(data['sources'][0]['status'], 'disabled')
            self.assertFalse(data['destinations'][0]['available'])
            self.assertIn('stopped responding', data['sources'][0]['message'])


class DesktopProvisionTests(unittest.TestCase):
    setUp = test_provision.ProvisionTests.setUp
    tearDown = test_provision.ProvisionTests.tearDown
    provision = test_provision.ProvisionTests.provision
    def session_runner(self, args, **kwargs):
        import subprocess
        if args[0] == 'loginctl':
            text = '4 1000 test seat0 tty2\n' if args[1] == 'list-sessions' else 'User=1000\nActive=yes\nRemote=no\nType=x11\nSeat=seat0\nClass=user\n'
            return subprocess.CompletedProcess(args, 0, text, '')
        return self.commands(args, **kwargs)

    def test_desktop_replaces_only_owned_hardware_players(self):
        self.provision()
        p = self.make_desktop()
        result = p.provision(self.config, audio=__import__('test_provision').Audio())
        self.assertIn('desktop', result)
        self.assertEqual(result['desktop']['session'], '4')
        self.assertTrue(any(c[:2] == ['systemctl', 'disable'] and 'playback' in c[-1] for c in self.commands.calls))
        unit = self.root / 'etc/systemd/system/flowharmonic-desktop-1000.service'
        self.assertIn('BindsTo=session-4.scope', unit.read_text())
        self.assertIn('User=1000', unit.read_text())
        generated = (self.etc / 'local-snapserver.conf').read_text()
        self.assertIn('name=Desktop%20Audio', generated)
        self.assertNotIn('set-default', '\n'.join(' '.join(c) for c in self.commands.calls))

    def make_desktop(self):
        from flowharmonic.provision import Provisioner
        return Provisioner(self.root, runner=self.session_runner, detector=lambda: self.outputs, probe=lambda _: '')

    def test_no_capture_for_ssh_or_inactive_sessions(self):
        p = self.make_desktop()
        original = p.runner
        def ssh_runner(args, **kw):
            result = original(args, **kw)
            result.stdout = result.stdout.replace('Remote=no', 'Remote=yes')
            return result
        p.runner = ssh_runner
        self.assertIsNone(active_session(p))

    def test_logout_stops_capture_and_preserves_pipe(self):
        self.make_desktop().provision(self.config, audio=__import__('test_provision').Audio())
        self.commands.calls.clear()
        self.provision()
        self.assertIn(['systemctl', 'stop', 'flowharmonic-desktop-1000.service'], self.commands.calls)
        self.assertTrue((self.root / 'run/flowharmonic-desktop/audio.pcm').is_fifo())

    def test_foreign_capture_unit_is_retained(self):
        path = self.root / 'etc/systemd/system/flowharmonic-desktop-1000.service'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('unrelated service')
        with self.assertRaisesRegex(RuntimeError, 'unrelated service'):
            self.make_desktop().provision(self.config, audio=__import__('test_provision').Audio())
        self.assertEqual(path.read_text(), 'unrelated service')
