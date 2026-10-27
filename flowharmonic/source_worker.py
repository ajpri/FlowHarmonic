"""Unprivileged source capture/player. Explicit devices only; never speaker monitoring."""
import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path

from .desktop import save_status
from .sources import tracks, validate
from .hardware import capture_inputs


def revalidate_input(source,device):
    # ALSA card aliases can be reused before the next provisioning poll. Check
    # identity on every recorder restart rather than opening a stale alias.
    if device and device['backend']=='alsa':
        current=next((row for row in capture_inputs() if row['key']==source['device']),None)
        if current is None:raise ValueError('The configured input is disconnected. Capture waits for this exact device to return.')
        return {**current,'channels':current['channels'] or device['channels']}
    return device


def commands(source, device=None, track=None):
    if source['kind']=='music':
        base=Path(source['folder']).resolve(strict=True)
        path=(base/track).resolve(strict=True)
        if not path.is_relative_to(base) or not path.is_file():raise ValueError('The selected track is outside the music folder or unavailable.')
        return [['ffmpeg','-nostdin','-v','error','-re','-i',str(path),'-vn','-f','s16le','-ar','48000','-ac','2','pipe:1']]
    if not device and source['kind']=='bluetooth':raise ValueError('Bluetooth audio is unavailable from this device. Log in to a local PipeWire desktop, connect the paired device and start audio on it.')
    if not device:raise ValueError('The configured input is disconnected or unavailable. It will retry when this device returns.')
    channels=device['channels']
    selected=source.get('channels',[1,2] if channels>=2 else [1])
    if any(c>channels for c in selected):raise ValueError('The selected channels are unavailable on this input. Check its channel selection.')
    left,right=selected[0]-1,selected[-1]-1
    if device['backend']=='alsa':
        capture=['arecord','-q','-D',device['device'],'-f','S16_LE','-r','48000','-c',str(channels),'-t','raw']
    else:
        capture=['gst-launch-1.0','-q','pipewiresrc','always-copy=true',
                 'client-name=FlowHarmonic input capture',
                 'stream-properties=props,node.name=(string)flowharmonic.source.'+source['id']+',node.autoconnect=(boolean)false,node.always-process=(boolean)true,node.want-driver=(boolean)true',
                 '!',f'audio/x-raw,format=S16LE,rate=48000,channels={channels}'+(',channel-mask=(bitmask)0' if channels>2 else ''),
                 '!','fdsink','fd=1','sync=false']
    return [capture,['ffmpeg','-nostdin','-v','error','-f','s16le','-ar','48000','-ac',str(channels),'-i','pipe:0',
                     '-af',f'pan=stereo|c0=c{left}|c1=c{right}','-f','s16le','-ar','48000','-ac','2','pipe:1']]


def input_links(objects, source_name, capture_name):
    nodes={o['id']:o.get('info',{}).get('props',{}) for o in objects if o['type'].endswith(':Node')}
    capture={i for i,p in nodes.items() if p.get('node.name')==capture_name}
    source={i for i,p in nodes.items() if p.get('node.name')==source_name and p.get('media.class')=='Audio/Source'}
    ports={o['id']:o.get('info',{}).get('props',{}) for o in objects if o['type'].endswith(':Port')}
    incoming=sorted((i for i,p in ports.items() if int(p.get('node.id',-1)) in capture and p.get('port.direction')=='in'),key=lambda i:int(ports[i].get('port.id',i)))
    outgoing=sorted((i for i,p in ports.items() if int(p.get('node.id',-1)) in source and p.get('port.direction')=='out'),key=lambda i:int(ports[i].get('port.id',i)))
    existing={(int(o['info']['output-port-id']),int(o['info']['input-port-id'])) for o in objects if o['type'].endswith(':Link') and int(o.get('info',{}).get('input-node-id',-1)) in capture}
    return set(zip(outgoing,incoming)),existing,bool(source and incoming and len(outgoing)==len(incoming))


def link_input(device,identifier):
    objects=json.loads(subprocess.run(['pw-dump'],capture_output=True,text=True,check=True,timeout=5).stdout)
    desired,existing,available=input_links(objects,device['device'],'flowharmonic.source.'+identifier)
    for left,right in existing-desired:subprocess.run(['pw-link','-d',str(left),str(right)],capture_output=True,timeout=3)
    for left,right in desired-existing:subprocess.run(['pw-link',str(left),str(right)],capture_output=True,check=True,timeout=3)
    return available


def stop(processes):
    for process in processes:
        if process.poll() is None:
            process.send_signal(signal.SIGCONT);process.terminate()
    for process in processes:
        try:process.wait(timeout=2)
        except subprocess.TimeoutExpired:process.kill();process.wait()


def worker(config_path,status):
    running=True;processes=[];signature=None;paused=False;current='';playlist=[];last_written=-1;progress=time.monotonic();retry=0
    def end(*_):
        nonlocal running
        running=False
    signal.signal(signal.SIGTERM,end);signal.signal(signal.SIGINT,end)
    status.parent.mkdir(parents=True,exist_ok=True)
    try:
        while running:
            try:
                configuration=json.loads(config_path.read_text());source=validate(configuration['source'])
                if source['state']=='stopped':
                    stop(processes);processes=[];signature=None;paused=False
                    save_status(status,False,'Stopped.',state='stopped');time.sleep(.5);continue
                device=configuration.get('device')
                new_signature=json.dumps({k:v for k,v in source.items() if k not in ('name','state')},sort_keys=True)+json.dumps(device,sort_keys=True)
                if signature!=new_signature:
                    stop(processes);processes=[];signature=new_signature;current=source.get('track','');playlist=[];paused=False;retry=0
                if source['kind']=='music' and not playlist:
                    playlist=tracks(source['folder'])
                    if not playlist:raise ValueError('No supported audio tracks were found in this music folder.')
                    if current and current not in playlist:raise ValueError('The selected track is unavailable in this folder.')
                    current=current or playlist[0]
                if processes and any(p.poll() is not None for p in processes):
                    success=all(p.poll()==0 for p in processes)
                    stop(processes);processes=[];paused=False
                    if source['kind']=='music' and success:
                        current=playlist[(playlist.index(current)+1)%len(playlist)]
                    else:
                        retry=time.monotonic()+3
                        raise ValueError('The audio input or decoder stopped. Check the device, file permissions and supported format; playback will retry.')
                if not processes and time.monotonic()>=retry:
                    device=revalidate_input(source,device)
                    pipeline=commands(source,device,current)
                    fifo=config_path.parent/'audio.pcm'
                    # Retain our own pipe read end so older Snapcast readers can
                    # rendezvous without an open/EOF retry race. Backpressure
                    # remains bounded by the kernel pipe buffer.
                    fd=os.open(fifo,os.O_RDWR|os.O_NONBLOCK|os.O_NOFOLLOW)
                    os.set_blocking(fd,True)
                    previous=None
                    try:
                        for index,command in enumerate(pipeline):
                            process=subprocess.Popen(command,stdin=previous if previous is not None else subprocess.DEVNULL,
                                stdout=fd if index==len(pipeline)-1 else subprocess.PIPE,stderr=subprocess.DEVNULL)
                            if previous is not None:previous.close()
                            processes.append(process);previous=process.stdout
                    finally:os.close(fd)
                    progress=time.monotonic();last_written=-1
                if processes:
                    linked=True
                    if device and device['backend']=='pipewire':linked=link_input(device,source['id'])
                    requested=source['state']=='paused'
                    if requested!=paused:
                        for process in processes:process.send_signal(signal.SIGSTOP if requested else signal.SIGCONT)
                        paused=requested
                    counters=dict(line.split(':',1) for line in Path(f'/proc/{processes[-1].pid}/io').read_text().splitlines())
                    written=int(counters['wchar'])
                    if written!=last_written:progress=time.monotonic();last_written=written
                    available=linked and (paused or (written>0 and time.monotonic()-progress<5))
                    message='Paused.' if paused else 'Playing.' if available else 'Waiting for audio from the configured device.'
                    save_status(status,available,message,state='paused' if paused else 'playing',track=current)
                time.sleep(.5)
            except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
                stop(processes);processes=[];paused=False
                message=str(error) if isinstance(error,ValueError) else 'The configured device or music folder cannot be opened. Check its availability and access permissions; setup retries automatically.'
                save_status(status,False,message,state='unavailable',track=current);time.sleep(2)
    finally:
        stop(processes);save_status(status,False,'Source stopped.',state='stopped')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',type=Path,required=True);parser.add_argument('--status',type=Path,required=True)
    args=parser.parse_args();worker(args.config,args.status)
