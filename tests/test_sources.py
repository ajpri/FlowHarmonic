import copy
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

from flowharmonic.sources import Sources,tracks,validate
from flowharmonic.source_worker import commands,input_links
from flowharmonic.provision import server_configuration


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.store=Sources(self.root)
        self.source={'id':str(uuid.uuid4()),'name':'USB piano','kind':'input','device':'alsa:stable','channels':[2],'state':'stopped'}

    def test_preferences_persist_and_unknown_schema_is_not_reset(self):
        self.store.save(self.source)
        self.assertEqual(Sources(self.root).rows(),[self.source])
        with sqlite3.connect(self.store.path) as db:db.execute('PRAGMA user_version=8')
        before=self.store.path.read_bytes()
        with self.assertRaises(RuntimeError):Sources(self.root)
        self.assertEqual(self.store.path.read_bytes(),before)

    def test_input_and_channel_validation_and_no_implicit_monitoring(self):
        self.store.save(self.source)
        self.assertEqual(self.store.rows()[0]['state'],'stopped')
        for channels in ([],[0],[33],[True],[1,1],[1,2,3],'1,2'):
            with self.assertRaises(ValueError):validate({**self.source,'channels':channels})
        for identifier in ('../../root','{'+self.source['id']+'}'):
            with self.assertRaises(ValueError):validate({**self.source,'id':identifier})
        pipeline=commands(self.source,{'channels':2,'backend':'alsa','device':'plughw:CARD=USB,DEV=0'})
        self.assertIn('plughw:CARD=USB,DEV=0',pipeline[0]);self.assertIn('pan=stereo|c0=c1|c1=c1',pipeline[1])
        self.assertFalse(any('aplay' in c or 'snapclient' in c for cmd in pipeline for c in cmd))
        with self.assertRaises(ValueError):commands(self.source)
        with self.assertRaises(ValueError):commands({**self.source,'channels':[3]}, {'channels':2,'backend':'alsa','device':'hw:USB'})

    def test_alsa_retry_revalidates_identity_before_reusing_card_alias(self):
        from flowharmonic.source_worker import revalidate_input
        old={'key':'alsa:stable','device':'plughw:CARD=USB,DEV=0','backend':'alsa','channels':2}
        replacement={**old,'key':'alsa:different'}
        with patch('flowharmonic.source_worker.capture_inputs',return_value=[replacement]):
            with self.assertRaises(ValueError):revalidate_input(self.source,old)
        moved={**old,'device':'plughw:CARD=USB_1,DEV=0'}
        with patch('flowharmonic.source_worker.capture_inputs',return_value=[moved]):
            self.assertEqual(revalidate_input(self.source,old)['device'],moved['device'])

    def test_music_scan_and_path_boundary(self):
        folder=self.root/'music';folder.mkdir();(folder/'a.wav').touch();(folder/'b.mp3').touch()
        outside=self.root/'outside.wav';outside.touch();(folder/'link.wav').symlink_to(outside)
        (folder/'escape').symlink_to(self.root,target_is_directory=True)
        self.assertEqual(tracks(folder),['a.wav','b.mp3'])
        source={'id':self.source['id'],'kind':'music','name':'Music','folder':str(folder),'track':'a.wav','state':'playing'}
        self.assertEqual(commands(source,track='a.wav')[0][-1],'pipe:1')
        with self.assertRaises(ValueError):commands(source,track='../outside.wav')
        with self.assertRaises(ValueError):validate({**source,'track':'../outside.wav'})

    def test_pairing_terminal_redraw_does_not_create_another_approval(self):
        from flowharmonic.bluetooth import PairingPrompts
        parser=PairingPrompts()
        prompt=parser.feed('Request confirmation\r\n[agent] Confirm passkey 123456 (yes/no): ')
        self.assertEqual(prompt['message'],'Confirm passkey 123456 (yes/no):')
        parser.reply()
        self.assertIsNone(parser.feed('[agent] Confirm passkey 123456 (yes/no): yes\r\n'))
        self.assertIsNone(parser.feed('Request canceled\n[agent] Confirm passkey 123456 (yes/no): '))
        new=parser.feed('Request authorization\n[agent] Accept pairing (yes/no): ')
        self.assertNotEqual(prompt['id'],new['id'])
        self.assertEqual(new['message'],'Accept pairing (yes/no):')

    def test_bluetooth_commands_bounded_and_confirmation_bound(self):
        for command in ({'action':'shell'},{'action':'connect','device':'AA; reboot'},{'action':'confirm','accept':True},{'action':'confirm','accept':'yes','confirmation':'a'*64}):
            with self.assertRaises(ValueError):self.store.bluetooth(command)
        result=self.store.bluetooth({'action':'pairing'})
        self.assertLessEqual(result['expires']-time.time(),120)
        self.assertTrue(result['nonce'])
        path=self.root/'bluetooth-request.json'
        self.assertEqual(path.stat().st_mode & 0o777,0o640)
        self.assertEqual(json.loads(path.read_text())['requests'],[result])
        self.assertEqual(self.store.path.stat().st_mode & 0o777,0o600)
        self.store.bluetooth({'action':'confirm','accept':False,'confirmation':'a'*64})
        self.assertFalse(self.store.bluetooth()['accept'])

    def test_bluetooth_actions_are_queued_not_overwritten(self):
        from flowharmonic.bluetooth import command
        first=self.store.bluetooth({'action':'pairing'})
        second=self.store.bluetooth({'action':'close'})
        third=self.store.bluetooth({'action':'forget','device':'00:AA:01:01:00:01'})
        path=self.root/'bluetooth-request.json'
        self.assertEqual(command(path),first)
        self.assertEqual(command(path,{first['nonce']}),second)
        self.assertEqual(command(path,{first['nonce'],second['nonce']}),third)
        self.assertEqual(command(path,{first['nonce'],second['nonce'],third['nonce']}),{})

    def test_physical_monitor_microphone_is_not_confused_with_speaker_monitor(self):
        from flowharmonic.source_provision import session_inputs
        from types import SimpleNamespace
        def node(name,kind,device_class='sound'):
            return {'id':1,'type':':Node','info':{'props':{'node.name':name,'media.class':kind,'device.api':'alsa','device.class':device_class,'audio.channels':1}}}
        objects=[node('alsa_input.usb_Monitor_Microphone','Audio/Source'),node('speakers.monitor','Audio/Source','monitor'),node('speakers','Audio/Sink')]
        fake=SimpleNamespace(root=Path('/test'),command=lambda *a,**k:subprocess.CompletedProcess(a,0,json.dumps(objects),''))
        inputs=session_inputs(fake,('1',1000))
        self.assertEqual(len(inputs),1)
        self.assertEqual(inputs[0]['key'],'pw:alsa_input.usb_Monitor_Microphone')

    def test_only_exact_pipewire_source_links_to_owned_capture(self):
        def node(i,name,kind):return {'id':i,'type':':Node','info':{'props':{'node.name':name,'media.class':kind}}}
        def port(i,node,direction,index):return {'id':i,'type':':Port','info':{'props':{'node.id':node,'port.direction':direction,'port.id':index}}}
        objects=[node(1,'chosen','Audio/Source'),node(2,'default','Audio/Source'),node(3,'owned','Stream/Input/Audio'),node(4,'speakers','Audio/Sink'),port(10,1,'out',0),port(11,1,'out',1),port(20,2,'out',0),port(30,3,'in',0),port(31,3,'in',1),port(40,4,'in',0)]
        desired,existing,available=input_links(objects,'chosen','owned')
        self.assertEqual(desired,{(10,30),(11,31)});self.assertTrue(available)
        self.assertEqual(input_links(objects,'missing','owned')[0],set())
        self.assertEqual(input_links(objects,'speakers','owned')[0],set())
        pipeline=commands(self.source,{'channels':2,'backend':'pipewire','device':'chosen'})
        self.assertTrue(any('node.autoconnect=(boolean)false' in arg for arg in pipeline[0]))

    def test_generated_stream_does_not_replace_existing_streams(self):
        base='[stream]\nsource = pipe:///existing?name=Existing\n'
        result=server_configuration(base,Path('/tones'),extra_sources=[(Path('/run/own/audio.pcm'),'fh-source-'+self.source['id'])])
        self.assertIn('source = pipe:///existing?name=Existing',result)
        self.assertIn('name=fh-source-'+self.source['id'],result)

    @unittest.skipUnless(shutil.which('ffmpeg'),'Native ffmpeg decoder required')
    def test_real_music_pause_resume_stop(self):
        import wave,math,struct
        source_dir=self.root/'source';source_dir.mkdir();status_dir=self.root/'status';status_dir.mkdir()
        fifo=source_dir/'audio.pcm';os.mkfifo(fifo);reader=os.open(fifo,os.O_RDONLY|os.O_NONBLOCK)
        self.addCleanup(os.close,reader)
        music=self.root/'music';music.mkdir()
        with wave.open(str(music/'test.wav'),'wb') as writer:
            writer.setparams((2,2,48000,0,'NONE','not compressed'))
            writer.writeframes(b''.join(struct.pack('<hh',int(500*math.sin(i*2*math.pi*440/48000)),int(700*math.sin(i*2*math.pi*880/48000))) for i in range(48000*4)))
        source={'id':self.source['id'],'kind':'music','name':'Music','folder':str(music),'track':'test.wav','state':'playing'}
        config=source_dir/'config.json';status=status_dir/'status.json'
        def save():
            temporary=config.with_suffix('.next');temporary.write_text(json.dumps({'source':source,'device':None}));temporary.replace(config)
        save();process=subprocess.Popen([os.sys.executable,'-m','flowharmonic.source_worker','--config',str(config),'--status',str(status)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        def finish():
            process.terminate()
            try:process.communicate(timeout=6)
            except subprocess.TimeoutExpired:process.kill();process.communicate()
        self.addCleanup(finish)
        def wait(state):
            end=time.time()+10;audio=bytearray()
            while time.time()<end:
                try:audio.extend(os.read(reader,65536))
                except BlockingIOError:pass
                try:
                    value=json.loads(status.read_text())
                    if value.get('state')==state and (value.get('available') or state=='stopped'):return value,audio
                except (OSError,ValueError):pass
                time.sleep(.05)
            self.fail('Worker did not reach '+state+'; '+status.read_text() if status.exists() else 'No status')
        _,audio=wait('playing');self.assertTrue(any(audio))
        source['state']='paused';save();wait('paused')
        source['state']='playing';save();wait('playing')
        source['state']='stopped';save();wait('stopped')
