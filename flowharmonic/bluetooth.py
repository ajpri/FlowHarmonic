"""Owned, bounded BlueZ pairing agent. Never accept an incoming prompt silently."""
import hashlib
import json
import os
import pty
import re
import select
import signal
import sqlite3
import subprocess
import time
from pathlib import Path

from .desktop import save_status

MAC=r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}'
ANSI=re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


class PairingPrompts:
    """BlueZ callback announcements distinguish requests from terminal redraws."""
    def __init__(self):
        self.buffer='';self.waiting=False;self.current=None

    def reply(self):
        self.buffer='';self.waiting=False;self.current=None

    def feed(self,text):
        text=ANSI.sub('',text)
        text=''.join(c for c in text if ord(c)>=32 or c in '\n\t')
        self.buffer=(self.buffer+text)[-8192:]
        events=list(re.finditer(r'(Request confirmation|Request authorization|Authorize service|Request canceled)\n',self.buffer))
        if events:
            event=events[-1];self.waiting=event[1]!='Request canceled';self.current=None;self.buffer=self.buffer[event.end():]
        if self.waiting:
            match=re.search(r'\[agent\]\s*((?:Confirm passkey \d{6}|Accept pairing|Authorize service [0-9a-fA-F-]+) \(yes/no\):)',self.buffer)
            if match:
                self.current={'id':hashlib.sha256((str(time.time_ns())+match[1]).encode()).hexdigest(),'message':match[1]}
                self.waiting=False;self.buffer=''
        return self.current


def call(*args):
    return subprocess.run(['bluetoothctl',*args],capture_output=True,text=True,timeout=7).stdout


def devices():
    result=[]
    for mac,name in re.findall(r'^Device ('+MAC+r') (.*)$',call('devices'),re.M):
        info=call('info',mac)
        if re.search(r'Paired: yes',info):result.append({'address':mac,'name':name,'connected':bool(re.search(r'Connected: yes',info)),'trusted':bool(re.search(r'Trusted: yes',info))})
        if len(result)>=32:break
    return result


def command(path,seen=None):
    if not path.exists():return {}
    if path.stat().st_size>4096:raise ValueError('Unsupported Bluetooth request.')
    value=json.loads(path.read_text())
    queue=value.get('requests',[value]) if isinstance(value,dict) else []
    if not isinstance(queue,list) or len(queue)>8:raise ValueError('Unsupported Bluetooth request.')
    for value in queue:
        if (not isinstance(value,dict) or set(value)-{'action','device','accept','confirmation','nonce','expires'} or
                value.get('action') not in ('pairing','close','confirm','connect','disconnect','forget') or
                type(value.get('expires')) not in (int,float) or not isinstance(value.get('nonce'),str)):
            raise ValueError('Unsupported Bluetooth request.')
        if value['nonce'] not in (seen or {}) and value['expires']>time.time():return value
    return {}


def agent(database,status):
    running=True;process=None;master=None;deadline=0;original={};seen={};buffer='';prompt=None;initialized=False;message='Pairing is closed.';last_devices=[];refresh=0;prompts=PairingPrompts()
    def end(*_):
        nonlocal running
        running=False
    def send(text):os.write(master,(text+'\n').encode())
    def close():
        nonlocal process,master,deadline,prompt
        if process:
            process.terminate()
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:process.kill();process.wait()
            os.close(master);process=None;master=None
            for key,value in original.items():call(key,'on' if value else 'off')
        deadline=0;prompt=None
    signal.signal(signal.SIGTERM,end);signal.signal(signal.SIGINT,end)
    try:
        while running:
            try:
                now=time.time();seen={nonce:expires for nonce,expires in seen.items() if expires>now}
                request=command(database,seen)
                if now>=refresh:
                    adapter=call('show');last_devices=devices() if 'Controller ' in adapter else [];refresh=now+5
                available='Controller ' in adapter
                if request.get('nonce') not in seen and request.get('expires',0)>now:
                    seen[request['nonce']]=request['expires'];action=request.get('action')
                    if action=='pairing':
                        close()
                        adapter=call('show');available='Controller ' in adapter
                        if not available:message='No Bluetooth adapter is available. Other sources remain usable.'
                        else:
                            original={key:bool(re.search(label+r': yes',adapter)) for key,label in [('pairable','Pairable'),('discoverable','Discoverable')]}
                            master,slave=pty.openpty()
                            process=subprocess.Popen(['bluetoothctl','--agent','DisplayYesNo'],stdin=slave,stdout=slave,stderr=slave,close_fds=True);os.close(slave)
                            deadline=time.monotonic()+max(0,min(120,request['expires']-time.time()));buffer='';prompt=None;initialized=False;prompts=PairingPrompts()
                            message='Pair from your phone now. Compare and approve the code here. Pairing closes after two minutes.'
                    elif action=='close':close();message='Pairing is closed.'
                    elif action=='confirm' and process and prompt and request.get('confirmation')==prompt['id'] and type(request.get('accept')) is bool:
                        send('yes' if request['accept'] else 'no');prompt=None;prompts.reply();buffer='';message='Pairing response sent. Waiting for the device.'
                    elif action in ('connect','disconnect','forget') and re.fullmatch(MAC,request.get('device','')):
                        # Only an authenticated explicit request can touch this device.
                        paired=bool(re.search(r'Paired: yes',call('info',request['device'])))
                        if action=='connect' and not paired:
                            message='Pair this device and approve its code before connecting.'
                        else:
                            if action=='connect':call('trust',request['device'])
                            result=call('remove' if action=='forget' else action,request['device'])
                            message='Device request completed.' if 'Failed' not in result else 'The device did not accept the request. Check that it is on and nearby.'
                        refresh=0
                if process:
                    if time.monotonic()>=deadline or process.poll() is not None:close();message='Pairing is closed.'
                    elif select.select([master],[],[],.1)[0]:
                        text=ANSI.sub('',os.read(master,8192).decode(errors='replace'))
                        text=''.join(c for c in text if ord(c)>=32 or c in '\n\t')
                        buffer=(buffer+text)[-8192:]
                        if not initialized and 'Agent registered' in buffer:
                            for instruction in ('power on','default-agent','pairable on','discoverable on'):send(instruction)
                            initialized=True
                        prompt=prompts.feed(text)
                        if prompt:message='Compare the device and pairing details before approving.'
                        if '[agent]' in buffer and re.search(r'(Enter PIN|Enter passkey)',buffer,re.I):
                            close();message='This device requires legacy PIN entry, which is not supported. Use a device with code confirmation.'
                save_status(status,available,message,pairing=bool(process),confirmation=prompt,devices=last_devices,handled=list(seen)[-32:])
            except (OSError,ValueError,TypeError,KeyError,sqlite3.Error,subprocess.SubprocessError):
                close();message='Bluetooth is unavailable. Other sources remain usable.'
                save_status(status,False,message,pairing=False,devices=[],handled=list(seen)[-32:])
            time.sleep(.5)
    finally:close()


if __name__=='__main__':agent(Path('/var/lib/flowharmonic/bluetooth-request.json'),Path('/run/flowharmonic-bluetooth/status.json'))
