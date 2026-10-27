"""Only bounded, checksum-verified source artifacts may reach the installer."""
import argparse
import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

from flowharmonic import update, cli
from flowharmonic.versioning import version_key

spec=importlib.util.spec_from_file_location('package_release',Path(__file__).resolve().parents[1]/'scripts/package-release.py')
package=importlib.util.module_from_spec(spec);spec.loader.exec_module(package)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=Path(__file__).resolve().parents[1]
        self.archive=self.root/'26.10.27.tar.gz'
        with redirect_stdout(io.StringIO()):self.digest=package.build(self.source,self.archive)

    def test_packaging_is_reproducible_and_excludes_runtime_secrets(self):
        other=self.root/'26.10.27-copy.tar.gz'
        with redirect_stdout(io.StringIO()):digest=package.build(self.source,other)
        self.assertEqual(digest,self.digest)
        self.assertEqual(update.inspect(self.archive,self.digest),'26.10.27')
        with tarfile.open(self.archive) as archive:
            self.assertTrue(all('.venv' not in m.name and not m.name.endswith('.db') and '__pycache__' not in m.name for m in archive))
        destination=self.root/'extracted';destination.mkdir();update.extract(self.archive,destination)
        self.assertTrue((destination/'FlowHarmonic/installLinux.sh').is_file())

    def test_check_verifies_available_version_without_running_installer(self):
        with patch.object(update.subprocess,'run') as run,redirect_stdout(io.StringIO()) as output:
            update.run(argparse.Namespace(source=str(self.archive),sha256=self.digest,check=True))
            self.assertIn('verified available artifact: 26.10.27',output.getvalue());run.assert_not_called()

    def test_date_versions_validate_calendar_and_sort_after_legacy_milestones(self):
        self.assertLess(version_key('M10'),version_key('26.10.27'))
        self.assertLess(version_key('26.10.27'),version_key('26.11.01'))
        self.assertLess(version_key('26.12.31'),version_key('27.01.01'))
        for value in ('1.0.0','26.02.29','26.13.01','26.1.01','26.10.27-preview'):
            with self.assertRaises(ValueError):version_key(value)

    def test_legacy_and_older_date_artifacts_are_inspectable_but_not_installed_as_downgrades(self):
        for version in ('M10','26.10.26'):
            old=self.root/(version+'.tar.gz')
            with tarfile.open(self.archive) as source,tarfile.open(old,'w:gz') as target:
                for member in source.getmembers():
                    data=source.extractfile(member).read()
                    if member.name=='FlowHarmonic/flowharmonic/__init__.py':
                        data=('VERSION = "'+version+'"\n').encode();member.size=len(data)
                    target.addfile(member,io.BytesIO(data))
            digest=hashlib.sha256(old.read_bytes()).hexdigest()
            self.assertEqual(update.inspect(old,digest),version)
            with patch.object(update.subprocess,'run') as run,redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError,'downgrade'):
                    update.run(argparse.Namespace(source=str(old),sha256=digest,check=False))
                run.assert_not_called()

    def test_tampered_archive_is_rejected_before_install_or_service_actions(self):
        self.archive.write_bytes(self.archive.read_bytes()+b'tampered')
        with patch.object(update.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'checksum'):update.run(argparse.Namespace(source=str(self.archive),sha256=self.digest,check=False))
            run.assert_not_called()

    def test_verified_but_unsafe_archive_paths_and_links_are_refused(self):
        for name,kind in (('../escape',tarfile.REGTYPE),('FlowHarmonic/scripts/escape',tarfile.SYMTYPE),('/etc/cron.d/job',tarfile.REGTYPE)):
            bad=self.root/'bad.tar.gz'
            with tarfile.open(bad,'w:gz') as archive:
                entry=tarfile.TarInfo(name);entry.type=kind;entry.linkname='/etc/passwd';archive.addfile(entry)
            with self.assertRaisesRegex(ValueError,'unsafe'):update.inspect(bad,hashlib.sha256(bad.read_bytes()).hexdigest())
            self.assertFalse((self.root/'escape').exists())

    def test_insecure_remote_url_and_unprivileged_update_are_refused(self):
        with self.assertRaisesRegex(ValueError,'HTTPS'):update.fetch('http://example.com/code.tar.gz',self.root/'download')
        with patch.object(cli.os,'geteuid',return_value=1000),patch.object(update,'run') as run:
            with self.assertRaises(SystemExit):cli.main(['update',str(self.archive),'--sha256',self.digest])
            run.assert_not_called()
