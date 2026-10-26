import json
import os
import subprocess
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flowharmonic.diagnostics import report, service_status
from flowharmonic.state import initialize, identity


class DiagnosticsTests(unittest.TestCase):
    def test_only_fixed_or_valid_owned_units_are_queried(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = initialize(root / 'state')
            (root / 'infrastructure.json').write_text(json.dumps({'server': 'existing', 'client': 'existing'}))
            (root / 'local-audio.json').write_text(json.dumps({'owner': identity(db), 'endpoint': 'tcp://localhost:1705',
                'owned_units': ['unrelated.service', '--root=/secret', 'flowharmonic-playback-'+'a'*20+'.service']}))
            fake_audio = type('Audio', (), {'snapshot': lambda _: {'sources': [], 'destinations': []}})()
            with patch.dict(os.environ, {'FLOWHARMONIC_CONFIG': str(root / 'config.toml')}), patch('flowharmonic.diagnostics.service_status', return_value=[]) as status:
                data = report({'name': 'Local', 'snapcast_url': 'tcp://localhost:1705'}, db, fake_audio)
            units = status.call_args.args[0]
            self.assertNotIn('unrelated.service', units)
            self.assertNotIn('--root=/secret', units)
            self.assertTrue(any('Existing infrastructure' in c['detail'] for c in data['checks']))

    def test_newer_local_settings_are_diagnosed_without_modification(self):
        with tempfile.TemporaryDirectory() as folder:
            path = initialize(Path(folder))
            with sqlite3.connect(path) as db:
                db.execute('UPDATE local_settings SET version=999')
            audio = type('Audio', (), {'snapshot': lambda _: {'sources': [], 'destinations': []}})()
            with patch('flowharmonic.diagnostics.service_status', return_value=[]):
                data = report({'name': 'Local', 'snapcast_url': 'tcp://localhost:1705'}, path, audio)
            self.assertEqual(data['checks'][0]['state'], 'unavailable')
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('SELECT version FROM local_settings').fetchone()[0], 999)

    def test_service_status_timeout_and_inactive_success_are_observable(self):
        units = {'flowharmonic-audio.service': 'Local audio setup'}
        text = 'Id=flowharmonic-audio.service\nActiveState=inactive\nSubState=dead\nResult=success\n'
        with patch('flowharmonic.diagnostics.subprocess.run', return_value=subprocess.CompletedProcess([], 0, text, '')) as run:
            rows = service_status(units)
        self.assertEqual(rows[0]['state'], 'inactive')
        self.assertEqual(rows[0]['result'], 'success')
        self.assertNotIn('shell', run.call_args.kwargs)
        with patch('flowharmonic.diagnostics.subprocess.run', side_effect=subprocess.TimeoutExpired('systemctl', 3)):
            self.assertEqual(service_status(units)[0]['state'], 'unknown')
