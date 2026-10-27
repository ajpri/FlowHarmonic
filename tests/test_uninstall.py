"""Removal is explicit, preserves external infrastructure, and never follows links."""
import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from flowharmonic import uninstall, cli
from flowharmonic.state import initialize, identity

REPO=Path(__file__).resolve().parents[1]


class UninstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.etc=self.root/'etc/flowharmonic';self.etc.mkdir(parents=True)
        self.data=self.root/'var/lib/flowharmonic';self.db=initialize(self.data)
        self.units=self.root/'etc/systemd/system';self.units.mkdir(parents=True)
        for name in uninstall.FIXED:
            (self.units/name).write_bytes((REPO/'packaging'/name).read_bytes())
        self.worker='flowharmonic-playback-'+'a'*20+'.service'
        (self.units/self.worker).write_text('# Managed by FlowHarmonic local audio\n[Service]\nExecStart=/usr/bin/snapclient\n')
        (self.units/'flowharmonic-snapserver.service').write_text('# Managed by FlowHarmonic local audio\nDescription=FlowHarmonic local audio server\n')
        (self.etc/'infrastructure.json').write_text('{"server":"flowharmonic","client":"flowharmonic"}')
        (self.etc/'config.toml').write_text('name="Kitchen"\n')
        self.release=self.root/'opt/flowharmonic/releases/M10-20261027T000000Z-test'
        self.release.mkdir(parents=True);(self.release/'BUILD').write_text(self.release.name)
        (self.release/'application').write_text('replaceable application')
        (self.release.parent.parent/'current').symlink_to(self.release)
        self.launcher=self.root/'usr/local/bin/flowharmonic';self.launcher.parent.mkdir(parents=True)
        self.launcher.write_bytes((REPO/'packaging/flowharmonic').read_bytes())
        self.external=self.root/'etc/snapserver.conf';self.external.write_text('existing unrelated config')
        self.other=self.root/'var/lib/snapserver/server.json';self.other.parent.mkdir(parents=True);self.other.write_text('existing audio history')
        (self.root/'usr/bin').mkdir(parents=True);(self.root/'usr/bin/snapserver').write_text('shared package')
        self.backups=self.data/'backups';self.backups.mkdir();(self.backups/'backup.zip').write_text('private backup')
        self.calls=[]

    def runner(self,args,**options):
        self.calls.append(args)
        return subprocess.CompletedProcess(args,0)

    def files(self):
        return {str(p.relative_to(self.root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file() and not p.is_symlink()}

    def test_dry_run_including_purge_does_not_write_notify_or_stop(self):
        before=self.files();original=uninstall.plan
        for purge in (False,True):
            with patch.object(uninstall,'plan',side_effect=lambda **kwargs:original(self.root,**kwargs)), \
                 patch.object(uninstall,'execute') as execute, patch('builtins.input') as prompt, redirect_stdout(io.StringIO()) as output:
                uninstall.run(argparse.Namespace(purge=purge,dry_run=True))
                self.assertIn('Dry run: no files, services or memberships changed.',output.getvalue())
                execute.assert_not_called();prompt.assert_not_called()
            self.assertEqual(self.files(),before)

    def test_default_removes_owned_services_code_and_launcher_keeps_configuration(self):
        original_id=identity(self.db)
        with redirect_stdout(io.StringIO()): uninstall.execute(uninstall.plan(self.root),self.root,self.runner)
        self.assertEqual(identity(self.db),original_id)
        self.assertTrue((self.etc/'config.toml').exists());self.assertTrue((self.backups/'backup.zip').exists())
        self.assertFalse(self.release.exists());self.assertFalse(self.launcher.exists())
        self.assertTrue(self.external.exists());self.assertTrue((self.root/'usr/bin/snapserver').exists())
        self.assertTrue(self.other.exists())
        self.assertTrue(all(call[3].startswith('flowharmonic') for call in self.calls if call[:2]==['systemctl','disable']))
        self.assertFalse(list(self.units.glob('flowharmonic*.service')))

    def test_purge_removes_identity_backups_but_retains_unknown_files_and_external_services(self):
        (self.data/'unrelated.txt').write_text('user file')
        (self.etc/'unrelated.txt').write_text('user config')
        (self.etc/'infrastructure.json').write_text('{"server":"existing","client":"existing"}')
        (self.units/'flowharmonic-snapserver.service').write_text('Description=Unrelated custom audio server\n')
        with redirect_stdout(io.StringIO()): uninstall.execute(uninstall.plan(self.root,True),self.root,self.runner)
        self.assertFalse(self.db.exists());self.assertFalse(self.backups.exists())
        self.assertEqual((self.data/'unrelated.txt').read_text(),'user file')
        self.assertTrue((self.etc/'unrelated.txt').exists());self.assertTrue(self.external.exists());self.assertTrue(self.other.exists())
        self.assertEqual((self.units/'flowharmonic-snapserver.service').read_text(),'Description=Unrelated custom audio server\n')
        self.assertFalse(any('flowharmonic-snapserver.service' in call for call in self.calls))

    def test_foreign_units_releases_and_maintenance_command_are_retained(self):
        (self.units/self.worker).write_text('Description=Unrelated speaker service\n')
        foreign=self.release.parent/'unrelated';foreign.mkdir();(foreign/'data').write_text('user application')
        self.launcher.write_text('#!/bin/sh\necho unrelated\n')
        with redirect_stdout(io.StringIO()): uninstall.execute(uninstall.plan(self.root),self.root,self.runner)
        self.assertTrue((self.units/self.worker).exists());self.assertTrue((foreign/'data').exists());self.assertTrue(self.launcher.exists())
        self.assertFalse(any(self.worker in call for call in self.calls))

    def test_symbolic_link_roots_are_rejected_before_any_mutation(self):
        self.etc.rename(self.root/'real-config')
        self.etc.symlink_to(self.root/'real-config',target_is_directory=True)
        before=self.files()
        with self.assertRaisesRegex(RuntimeError,'symbolic'):uninstall.plan(self.root,True)
        self.assertEqual(before,self.files())

    def test_cancel_and_purge_second_confirmation_leave_everything_untouched(self):
        original=uninstall.plan;before=self.files()
        for replies in (['NO'],['UNINSTALL','NO']):
            with patch.object(uninstall,'plan',side_effect=lambda **kwargs:original(self.root,**kwargs)), \
                 patch('builtins.open',return_value=io.StringIO()),patch.object(uninstall.fcntl,'flock'), \
                 patch.object(uninstall.sys,'stdin',type('Terminal',(),{'isatty':lambda self:True})()), \
                 patch('builtins.input',side_effect=replies),patch.object(uninstall,'execute') as execute,redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError,'cancelled|Cancelled'):
                    uninstall.run(argparse.Namespace(purge=True,dry_run=False))
                execute.assert_not_called()
            self.assertEqual(before,self.files())

    def test_cli_requires_admin_even_for_plan(self):
        with patch.object(cli.os,'geteuid',return_value=1000),patch.object(uninstall,'run') as run:
            with self.assertRaises(SystemExit) as error:cli.main(['uninstall','--dry-run'])
            self.assertEqual(error.exception.code,1);run.assert_not_called()

    def test_date_and_legacy_releases_are_both_removed(self):
        dated=self.release.parent/'26.10.27-20261027T010000Z-preview'
        dated.mkdir();(dated/'BUILD').write_text(dated.name)
        proposed=uninstall.plan(self.root)
        self.assertIn(str(self.release),proposed['releases'])
        self.assertIn(str(dated),proposed['releases'])
        with redirect_stdout(io.StringIO()):uninstall.execute(proposed,self.root,self.runner)
        self.assertFalse(dated.exists());self.assertFalse(self.release.exists())


import test_network as enrollment_fixture
from flowharmonic.state import database


class DepartureTests(unittest.TestCase):
    setUp=enrollment_fixture.MembershipTests.setUp
    exchange=enrollment_fixture.MembershipTests.exchange
    request=enrollment_fixture.MembershipTests.request
    joined=enrollment_fixture.MembershipTests.joined

    def test_successful_notification_revokes_host_access_but_preserves_local_membership_and_key(self):
        self.joined()
        with database(self.member.path) as db: before=db.execute('SELECT private_key,membership FROM settings').fetchone()
        with patch('flowharmonic.config.load_config',return_value=self.member.config),redirect_stdout(io.StringIO()):
            uninstall.notify_departure(self.member.path.parent)
        with database(self.member.path) as db: after=db.execute('SELECT private_key,membership FROM settings').fetchone()
        self.assertEqual(before,after);self.assertEqual(self.host.view()['peers'],[])
        self.assertIn('explicit approval',self.member.view()['message'])
        message=self.member.sign(self.host.node_id,self.host.info()['system']['id'],'coord.report',{'enrollment':self.member.view()['membership']['enrollment'],'inventory':{}})
        from flowharmonic.network import NetworkError
        with self.assertRaises(NetworkError):self.host.receive(message)
        with self.assertRaisesRegex(NetworkError, 'explicit approval'):self.member.sync()
        with database(self.member.path) as db:
            self.assertEqual(before, db.execute('SELECT private_key,membership FROM settings').fetchone())

    def test_unreachable_host_preserves_all_local_trust_and_explains_stale_membership(self):
        self.joined()
        with database(self.member.path) as db: before=db.execute('SELECT private_key,membership FROM settings').fetchone()
        from flowharmonic.network import Membership,NetworkError
        with patch('flowharmonic.config.load_config',return_value=self.member.config),patch.object(Membership,'send',side_effect=NetworkError('offline')),redirect_stdout(io.StringIO()) as output:
            uninstall.notify_departure(self.member.path.parent)
            self.assertIn('stale member entry',output.getvalue())
        with database(self.member.path) as db: after=db.execute('SELECT private_key,membership FROM settings').fetchone()
        self.assertEqual(before,after);self.assertEqual(len(self.host.view()['peers']),1)
