#!/usr/bin/env python3
"""Build a reproducible, runtime-data-free FH update artifact and SHA256 file."""
import argparse
import hashlib
from pathlib import Path
import re
import tarfile


def build(source,output):
    source,output=Path(source),Path(output)
    version=re.search(r'^VERSION = "([M0-9.]+)"$',(source/'flowharmonic/__init__.py').read_text(),re.M)[1]
    roots=('flowharmonic','packaging','scripts','installLinux.sh','requirements.txt','requirements.in','README.md','SPEC.md')
    paths=[]
    for name in roots:
        path=source/name
        paths.extend(p for p in (path.rglob('*') if path.is_dir() else [path]) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    # Exclusive output avoids replacing a previously distributed artifact.
    with output.open('xb') as raw:
        import gzip
        with gzip.GzipFile(fileobj=raw,mode='wb',mtime=0,filename='') as compressed, tarfile.open(fileobj=compressed,mode='w') as archive:
            for path in sorted(paths):
                if path.is_symlink():raise ValueError('Release sources must not contain symbolic links.')
                info=archive.gettarinfo(str(path),'FlowHarmonic/'+str(path.relative_to(source)))
                info.uid=info.gid=0;info.uname=info.gname='root';info.mtime=0
                with path.open('rb') as content:archive.addfile(info,content)
    checksum=hashlib.sha256(output.read_bytes()).hexdigest()
    checksum_path=output.with_name(output.name+'.sha256')
    with checksum_path.open('x') as writer:writer.write(checksum+'  '+output.name+'\n')
    print(f'FlowHarmonic {version}: {output}\nSHA256: {checksum}')
    return checksum


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    build(Path(__file__).resolve().parents[1],args.output)
