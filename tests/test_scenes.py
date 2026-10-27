"""M9 scenes, disconnected-device reporting and saved routing recovery."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flowharmonic.coordination import Coordination
from flowharmonic.network import Membership
from flowharmonic.snapcast import AudioError
from flowharmonic.state import initialize
import test_coordination as coordination_tests
from test_coordination import Audio


class SceneTests(unittest.TestCase):
    setUp = coordination_tests.CoordinationTests.setUp
    route = coordination_tests.CoordinationTests.route

    def test_multizone_scene_restores_assignments_volume_and_mute(self):
        self.route()
        self.coordinator.change(self.destination, {'percent': 37, 'muted': True})
        local = self.host.node_id + '/speaker-0'
        self.coordinator.change(local, {'source_id': self.host.node_id + '/Silence'})
        self.coordinator.tick()
        scene = self.coordinator.scenes.save('Evening', [local, self.destination])['id']
        self.coordinator.change(self.destination, {'percent': 89, 'muted': False})
        result = self.coordinator.scenes.apply(scene)
        self.assertTrue(all(row['applied'] for row in result['results']))
        self.coordinator.tick()
        actual = self.audio[0].data['destinations'][-1]
        self.assertEqual((actual['source_id'], actual['volume'], actual['muted']), ('Desktop Audio', 37, True))
        self.assertEqual(len(self.coordinator.scenes.view()['scenes']), 1)
        self.coordinator.scenes.remove(scene)
        self.assertFalse(self.coordinator.scenes.view()['scenes'])

    def test_scene_survives_restart_and_missing_destination_reports_partial_result(self):
        self.route()
        scene = self.coordinator.scenes.save('Evening', [self.destination])['id']
        other = Coordination(self.host, self.audio[0].snapshot, self.audio[0], self.coordinator.metadata)
        self.assertEqual(other.scenes.view()['scenes'][0]['id'], scene)
        with patch.object(other, 'change', side_effect=AudioError('Speaker is disconnected.', 409)):
            result = other.scenes.apply(scene)
        self.assertFalse(result['results'][0]['applied'])
        self.assertIn('disconnected', result['results'][0]['message'])
        self.assertFalse(self.client.scenes.view()['manageable'])
        with self.assertRaises(AudioError): self.client.scenes.apply(scene)

    def test_save_rejects_disconnected_and_duplicate_destinations(self):
        self.audio[1].data['destinations'][0]['available'] = False
        self.client.tick()
        with self.assertRaises(AudioError): self.coordinator.scenes.save('Missing', [self.destination])
        with self.assertRaises(AudioError): self.coordinator.scenes.save('Duplicate', [self.destination] * 2)
        self.assertFalse(self.coordinator.scenes.view()['scenes'])

    def test_confirmed_coordinator_route_recovers_after_server_loses_audio_settings(self):
        self.route()
        self.coordinator.change(self.destination, {'percent': 43, 'muted': True})
        actual = self.audio[0].data['destinations'][-1]
        actual.update(source_id='Silence', volume=100, muted=False)
        self.coordinator.tick()
        self.assertEqual((actual['source_id'], actual['volume'], actual['muted']), ('Desktop Audio', 43, True))


class StandaloneRecoveryTests(unittest.TestCase):
    def test_saved_local_settings_recover_and_unavailable_hardware_retains_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config = {'name':'Local', 'port':8080, 'snapcast_url':'tcp://127.0.0.1:1705'}
            member = Membership(directory, config, initialize(directory))
            audio = Audio('speaker')
            engine = Coordination(member, audio.snapshot, audio, directory / 'metadata.json')
            engine.change('speaker', {'source_id':'Desktop Audio'})
            engine.change('speaker', {'percent':41, 'muted':True})
            audio.data['destinations'][0].update(source_id='Silence', volume=100, muted=False, available=False)
            engine = Coordination(member, audio.snapshot, audio, directory / 'metadata.json')
            view = engine.dashboard()['destinations'][0]
            self.assertEqual((view['source_id'],view['volume'],view['muted']), ('Desktop Audio',41,True))
            self.assertIn('disconnected', view['message'])
            engine.tick()
            self.assertEqual(audio.data['destinations'][0]['volume'],100)
            audio.data['destinations'][0]['available'] = True
            engine.tick()
            self.assertEqual(audio.data['destinations'][0]['source_id'],'Desktop Audio')
            self.assertEqual(audio.data['destinations'][0]['volume'],41)
            self.assertTrue(audio.data['destinations'][0]['muted'])
            with patch.object(engine, 'snapshot', side_effect=AudioError('Audio server is reconnecting.')):
                view = engine.dashboard()
                self.assertFalse(view['destinations'][0]['available'])
                self.assertIn('reconnecting',view['local_message'])
