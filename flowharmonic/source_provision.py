"""Fixed root boundary for additional sources, invoked by the owned audio timer."""
import json
import os
import re
import stat
import uuid

from .hardware import capture_inputs
from .sources import validate
from .state import database


def read_sources(p):
    path=p.path('/var/lib/flowharmonic/sources.db')
    if not path.exists():return []
    with database(path) as db:
        if db.execute('PRAGMA user_version').fetchone()[0]!=1:raise RuntimeError('Unsupported source schema; existing services retained.')
        return [validate(json.loads(row[0])) for row in db.execute('SELECT data FROM source LIMIT 33')]


def session_inputs(p,session):
    if not session:return []
    uid=session[1]
    import pwd
    username=pwd.getpwuid(uid).pw_name if p.root==p.root.__class__('/') else str(uid)
    result=p.command('runuser','-u',username,'--','env',f'XDG_RUNTIME_DIR=/run/user/{uid}','pw-dump',check=False)
    if result.returncode:return []
    inputs=[]
    try:
        objects=json.loads(result.stdout)
        devices={o['id']:o.get('info',{}).get('props',{}) for o in objects if o['type'].endswith(':Device')}
        for obj in objects:
            if not obj['type'].endswith(':Node'):continue
            props=obj.get('info',{}).get('props',{})
            props={**devices.get(int(props.get('device.id',-1)),{}),**props}
            if props.get('media.class')!='Audio/Source' or props.get('device.api') not in ('alsa','bluez5'):continue
            name=props.get('node.name','')
            if not name or name.endswith('.monitor') or props.get('device.class')=='monitor':continue
            channels=int(props.get('audio.channels',2))
            if not 1<=channels<=32:continue
            bluetooth=props.get('device.api')=='bluez5'
            # Bluetooth identity is the remote MAC, never a changing PipeWire ID.
            match=re.search(r'([0-9A-Fa-f]{2}(?:[._:][0-9A-Fa-f]{2}){5})',name)
            key=match[1].replace('_',':').replace('.',':').upper() if bluetooth and match else 'pw:'+name
            inputs.append({'key':key,'name':props.get('node.description',name),'device':name,'backend':'pipewire','channels':channels,'bluetooth':bluetooth})
    except (ValueError,KeyError,TypeError):return []
    return inputs


def prepare(p,session,server_user):
    from .provision import write_file,MARKER,unit_quote
    import grp,pwd
    rows=read_sources(p)
    if len(rows)>32:raise RuntimeError('Too many configured sources; existing services retained.')
    inputs=session_inputs(p,session) if session else capture_inputs(p.path('/proc/asound'),p.path('/sys/class/sound'))
    previous={d['key']:d for d in p.previous.get('inputs',[])}
    for device in inputs:
        if not device['channels'] and device['key'] in previous:device['channels']=previous[device['key']]['channels']
    p.status['inputs']=inputs;p.status['sources']=[]
    runtime=p.path('/run/flowharmonic-sources')
    if runtime.is_symlink():raise RuntimeError('An unrelated source runtime path was retained.')
    runtime.mkdir(parents=True,exist_ok=True)
    keep=set();uris=[];actions=[]
    for source in rows:
        identifier=source['id'];uuid.UUID(identifier)
        if str(uuid.UUID(identifier))!=identifier:raise RuntimeError('Invalid source identity.')
        directory=runtime/identifier
        if directory.is_symlink():raise RuntimeError('An unrelated source path was retained.')
        marker=directory/'.flowharmonic'
        if directory.exists() and (not marker.is_file() or marker.read_text()!=identifier):raise RuntimeError('An unrelated source directory was retained.')
        directory.mkdir(exist_ok=True)
        write_file(marker,identifier)
        fifo=directory/'audio.pcm'
        if fifo.is_symlink() or (fifo.exists() and not stat.S_ISFIFO(fifo.stat().st_mode)):raise RuntimeError('An unrelated source pipe was retained.')
        if not fifo.exists():os.mkfifo(fifo,0o640)
        device=next((d for d in inputs if d['key']==source.get('device')),None)
        session_capture=source['kind']=='bluetooth' or bool(device and device['backend']=='pipewire') or (source['kind']=='input' and source.get('device','').startswith('pw:'))
        user=str(session[1]) if session_capture and session else 'flowharmonic'
        if p.root==p.root.__class__('/'):
            os.chown(fifo,int(user) if user.isdigit() else pwd.getpwnam(user).pw_uid,grp.getgrnam(server_user).gr_gid);fifo.chmod(0o640)
        write_file(directory/'config.json',json.dumps({'source':source,'device':device}))
        unit='flowharmonic-source-'+identifier+'.service';keep.add(unit)
        status='/run/flowharmonic-source-'+identifier+'/status.json'
        p.status['sources'].append({'id':'fh-source-'+identifier,'name':source['name'],'kind':source['kind'],'state':source['state'],'status':status})
        uris.append((fifo,'fh-source-'+identifier))
        release=p.path('/opt/flowharmonic/current').resolve()
        environment=f'Environment=XDG_RUNTIME_DIR=/run/user/{session[1]}\nEnvironment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{session[1]}/bus\n' if session_capture and session else ''
        binding=f'BindsTo=session-{session[0]}.scope\n' if session_capture and session else ''
        unit_text=f'''[Unit]
{binding}Description=FlowHarmonic configured audio source
After=flowharmonic-snapserver.service
StartLimitIntervalSec=0
[Service]
User={user}
SupplementaryGroups=audio
WorkingDirectory=/opt/flowharmonic/current
{environment}ExecStart={unit_quote(release/'.venv/bin/python')} -m flowharmonic.source_worker --config {unit_quote(directory/'config.json')} --status {status}
RuntimeDirectory=flowharmonic-source-{identifier}
RuntimeDirectoryMode=0755
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths={unit_quote(fifo)}
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX
UMask=0022
'''
        path=p.units/unit
        if path.exists() and not path.read_text().startswith(MARKER):raise RuntimeError('An unrelated source service was retained.')
        modified=write_file(path,MARKER+unit_text)
        actions.append(('restart' if modified else 'start',unit))
    for path in p.units.glob('flowharmonic-source-*.service'):
        if path.name in keep:continue
        if re.fullmatch(r'flowharmonic-source-[a-f0-9-]{36}\.service',path.name) and path.read_text().startswith(MARKER):
            p.command('systemctl','stop',path.name);path.unlink()
            identifier=path.name.removeprefix('flowharmonic-source-').removesuffix('.service')
            directory=runtime/identifier
            marker=directory/'.flowharmonic'
            if not directory.is_symlink() and marker.is_file() and marker.read_text()==identifier:
                for name in ('audio.pcm','config.json','.flowharmonic'):
                    owned=directory/name
                    if owned.exists() or owned.is_symlink():owned.unlink()
                if not any(directory.iterdir()):directory.rmdir()
    if actions:
        p.command('systemctl','daemon-reload')
        for action,unit in actions:p.command('systemctl',action,unit)
    return uris


def pause(p):
    from .provision import MARKER
    for path in p.units.glob('flowharmonic-source-*.service'):
        if re.fullmatch(r'flowharmonic-source-[a-f0-9-]{36}\.service',path.name) and path.read_text().startswith(MARKER):p.command('systemctl','stop',path.name)
