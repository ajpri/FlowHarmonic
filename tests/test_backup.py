"""Configuration restoration preserves identity, credentials and scenes safely."""
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from flowharmonic.backup import export, read_archive, restore_files
from flowharmonic.coordination import Coordination
from flowharmonic.network import Membership
from flowharmonic.security import Authentication
from flowharmonic.sources import Sources
from flowharmonic.state import initialize, identity, node_name, set_node_name
from test_coordination import Audio


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.data = self.root / 'data'
        self.config = self.root / 'config.toml'; self.config.write_text('name = "Office"\n')
        self.ledger = self.root / 'infrastructure.json'; self.ledger.write_text('{"server":"existing","client":"existing"}')
        self.path = initialize(self.data); self.identity = identity(self.path)
        set_node_name(self.path, 'Office speakers')
        self.auth = Authentication(self.data); self.auth.set_password('protected backup test password')
        self.token = self.auth.sign_in('protected backup test password')
        self.sources = Sources(self.data)
        member = Membership(self.data, {'name':'Office', 'port':8080, 'snapcast_url':'tcp://127.0.0.1:1705'}, self.path)
        audio = Audio('speaker'); self.engine = Coordination(member, audio.snapshot, audio, self.root / 'metadata.json')
        self.engine.change('speaker', {'source_id':'Desktop Audio'})
        self.engine.scenes.save('Evening', ['speaker'])
        self.archive = self.root / 'backup.zip'

    def test_roundtrip_keeps_identity_credentials_scenes_names_and_assignment(self):
        export(self.data, self.config, self.archive)
        self.assertEqual(self.archive.stat().st_mode & 0o777, 0o600)
        set_node_name(self.path, 'Changed'); self.config.write_text('name = "Changed"\n')
        self.engine.scenes.remove(self.engine.scenes.view()['scenes'][0]['id'])
        _, files = read_archive(self.archive, self.data, self.config)
        restore_files(files, self.data, self.config, os.getuid(), os.getgid())
        self.assertEqual(identity(self.path), self.identity)
        self.assertEqual(node_name(self.path, ''), 'Office speakers')
        self.assertTrue(self.auth.authenticated(self.token))
        self.assertEqual(self.engine.scenes.view()['scenes'][0]['name'], 'Evening')
        self.assertEqual(self.config.read_text(), 'name = "Office"\n')
        self.assertEqual(self.engine.scenes.path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError): export(self.data, self.config, self.archive)

    def test_archive_corruption_paths_and_ownership_change_are_refused(self):
        export(self.data, self.config, self.archive)
        bad = self.root / 'bad.zip'
        with zipfile.ZipFile(self.archive) as source, zipfile.ZipFile(bad,'w') as target:
            for name in source.namelist(): target.writestr(name, b'broken' if name=='scenes.db' else source.read(name))
        with self.assertRaisesRegex(ValueError, 'integrity'): read_archive(bad,self.data,self.config)
        with zipfile.ZipFile(bad,'w') as target: target.writestr('../escape', b'bad')
        with self.assertRaisesRegex(ValueError, 'unexpected'): read_archive(bad,self.data,self.config)
        with zipfile.ZipFile(bad,'w') as target: target.writestr('manifest.json', '[]')
        with self.assertRaisesRegex(ValueError, 'manifest'): read_archive(bad,self.data,self.config)
        self.ledger.write_text('{"server":"flowharmonic","client":"existing"}')
        with self.assertRaisesRegex(ValueError,'ownership'): read_archive(self.archive,self.data,self.config)
        self.assertEqual(identity(self.path), self.identity)

    def test_failed_replacement_cleans_staging_file_and_retains_original(self):
        from unittest.mock import patch
        from flowharmonic.backup import replace_file
        before = self.config.read_bytes()
        with patch('flowharmonic.backup.os.replace', side_effect=OSError('Disk unavailable')):
            with self.assertRaises(OSError): replace_file(self.config, b'replacement', 0o644)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(list(self.root.glob('.restore-*')), [])

    def test_different_node_and_future_schema_are_refused(self):
        export(self.data,self.config,self.archive)
        other = self.root / 'other'; initialize(other)
        with self.assertRaisesRegex(ValueError,'another node'): read_archive(self.archive,other,self.config)
        import sqlite3
        with sqlite3.connect(self.engine.scenes.path) as db: db.execute('PRAGMA user_version=999')
        with self.assertRaisesRegex(ValueError,'unsupported'): export(self.data,self.config,self.root / 'future.zip')
