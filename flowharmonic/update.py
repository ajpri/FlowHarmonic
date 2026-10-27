"""Explicit, checksum-pinned local/HTTPS updates using the normal staged installer."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile
import urllib.request
from urllib.parse import urlsplit

from . import VERSION
from .snapcast import NoRedirect
from .versioning import version_key

LIMIT=64*1024*1024
ROOTS={'flowharmonic','packaging','scripts','installLinux.sh','requirements.txt','requirements.in','README.md','SPEC.md'}


def fetch(source, destination):
    parsed=urlsplit(source)
    if parsed.scheme:
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError('Use a local archive or HTTPS URL without embedded credentials.')
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        reader=opener.open(source,timeout=30)
    else:
        reader=Path(source).open('rb')
    total=0;digest=hashlib.sha256()
    with reader, destination.open('wb') as output:
        while chunk:=reader.read(128*1024):
            total+=len(chunk)
            if total>LIMIT:raise ValueError('Update archive exceeds 64 MiB.')
            digest.update(chunk);output.write(chunk)
    return digest.hexdigest()


def inspect(archive_path, expected):
    if not re.fullmatch(r'[a-fA-F0-9]{64}',expected):raise ValueError('Provide the trusted artifact’s 64-character SHA256 checksum.')
    if hashlib.sha256(archive_path.read_bytes()).hexdigest()!=expected.lower():
        raise ValueError('Update checksum does not match. The active installation was not changed.')
    with tarfile.open(archive_path,'r:gz') as archive:
        members=archive.getmembers()
        if len(members)>2000 or sum(m.size for m in members)>LIMIT:raise ValueError('Update contents exceed the size limit.')
        seen=set()
        for member in members:
            name=PurePosixPath(member.name)
            if (member.name in seen or name.is_absolute() or '..' in name.parts or
                    not name.parts or name.parts[0]!='FlowHarmonic' or
                    (len(name.parts)>1 and name.parts[1] not in ROOTS) or
                    not (member.isfile() or member.isdir())):
                raise ValueError('Update archive has unsafe or unexpected files. Nothing was installed.')
            seen.add(member.name)
        required={'FlowHarmonic/installLinux.sh','FlowHarmonic/requirements.txt','FlowHarmonic/flowharmonic/__init__.py'}
        if not required<=seen:raise ValueError('Update is missing required application files.')
        stream=archive.extractfile('FlowHarmonic/flowharmonic/__init__.py')
        match=re.search(rb'^VERSION = "([M0-9.]+)"$',stream.read(4096),re.M)
        if not match:raise ValueError('Update does not declare a supported version.')
        version=match[1].decode()
        version_key(version)
        return version


def extract(archive_path,destination):
    # Never tar.extractall: permit only verified ordinary files/directories.
    with tarfile.open(archive_path,'r:gz') as archive:
        for member in archive.getmembers():
            path=destination/member.name
            if member.isdir():path.mkdir(parents=True,exist_ok=True);continue
            path.parent.mkdir(parents=True,exist_ok=True)
            with archive.extractfile(member) as source, path.open('xb') as output:
                while chunk:=source.read(128*1024):output.write(chunk)
            path.chmod(0o755 if member.mode&0o111 else 0o644)


def run(args):
    if not re.fullmatch(r'[a-fA-F0-9]{64}',args.sha256):raise ValueError('Provide the trusted artifact’s 64-character SHA256 checksum.')
    with tempfile.TemporaryDirectory(prefix='flowharmonic-update-') as temporary:
        directory=Path(temporary);archive=directory/'release.tar.gz'
        digest=fetch(args.source,archive)
        try: version=inspect(archive,args.sha256)
        except tarfile.TarError as error: raise ValueError('The verified file is not a readable FlowHarmonic update archive.') from error
        print(f'Installed: {VERSION}; verified available artifact: {version}; SHA256: {digest}')
        if args.check:return
        if version_key(version)<version_key(VERSION):raise ValueError('Refusing a version downgrade. Use an administrator-reviewed rollback procedure with compatible data.')
        extract(archive,directory)
        subprocess.run(['bash',str(directory/'FlowHarmonic/installLinux.sh')],cwd=directory/'FlowHarmonic',check=True)
        # Store only artifact identity, never private download URLs or credentials.
        active=Path('/opt/flowharmonic/current').resolve()
        if active.parent!=Path('/opt/flowharmonic/releases'):raise RuntimeError('The active release path is invalid.')
        (active/'UPDATE.json').write_text(json.dumps({'version':version,'sha256':digest})+'\n')
        (active/'UPDATE.json').chmod(0o644)
        print('Verified update installed; identity and configuration retained.')
