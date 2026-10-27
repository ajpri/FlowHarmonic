"""M7 ownership, visibility, authorization, routing, and disconnection behavior."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flowharmonic.coordination import Coordination
from flowharmonic.network import Membership, NetworkError
from flowharmonic.playback_target import target
from flowharmonic.provision import server_configuration
from flowharmonic.snapcast import AudioError
from flowharmonic.state import initialize


class Audio:
    def __init__(self, client):
        self.data={'sources':[{'id':'Desktop Audio','name':'Desktop Audio','status':'playing'},{'id':'Silence','name':'Silence','status':'playing'}],
                   'destinations':[{'id':client,'name':client,'source_id':'Silence','volume':30,'muted':False,'available':True}]}
        self.calls=[]
    def snapshot(self): return copy.deepcopy(self.data)
    def change(self,destination,**change):
        row=next((d for d in self.data['destinations'] if d['id']==destination and d['available']),None)
        if row is None: raise AudioError('Destination is reconnecting.',409)
        self.calls.append((destination,change))
        for key,value in change.items():
            if value is not None: row['volume' if key=='percent' else key]=value
        return self.snapshot()
    def rename(self,destination,name):
        row=next((d for d in self.data['destinations'] if d['id']==destination),None)
        if row is None: raise AudioError('Destination is reconnecting.',409)
        row['name']=name
        return self.snapshot()


class CoordinationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.nodes=[];self.engines=[];self.audio=[];self.urls={}
        for index in range(2):
            directory=Path(self.temp.name)/str(index); path=initialize(directory)
            config={'name':['Office','Living Room'][index],'host':'0.0.0.0','port':8080+index,'snapcast_url':'tcp://127.0.0.1:1705'}
            node=Membership(directory,config,path);audio=Audio('speaker-'+str(index))
            metadata=directory/'local-audio.json'
            metadata.write_text(json.dumps({'owner':node.node_id,'endpoint':config['snapcast_url'],'destinations':[{'id':'speaker-'+str(index)}]}))
            (directory/'infrastructure.json').write_text(json.dumps({'server':'flowharmonic','client':'flowharmonic'}))
            engine=Coordination(node,audio.snapshot,audio,metadata)
            node.coordinator_handler=engine.receive
            self.nodes.append(node);self.engines.append(engine);self.audio.append(audio)
            self.urls['http://127.0.0.'+str(index+1)+':'+str(8080+index)]=node
        self.host,self.member=self.nodes;self.coordinator,self.client=self.engines
        def exchange(url,path,body=None):
            node=self.urls[url]
            if path=='/peer/info': return node.info()
            source='127.0.0.'+str(self.nodes.index(next(n for n in self.nodes if n.node_id==body['sender']))+1)
            return node.receive(body,source)
        self.transport=patch('flowharmonic.network.exchange',side_effect=exchange);self.transport.start();self.addCleanup(self.transport.stop)
        self.host.create('Home');self.host.allow(True)
        request=self.member.request_join('http://127.0.0.1:8080')['pending'][0]['id']
        self.host.approve(request,True);self.member.sync(confirm=True);self.client.tick()
        self.source=self.host.node_id+'/Desktop Audio';self.destination=self.member.node_id+'/speaker-1'

    def test_inventory_is_actual_and_destination_only_node_has_no_source_entry(self):
        self.audio[1].data['sources']=[];self.client.tick()
        view=self.coordinator.dashboard()
        self.assertEqual(len(view['destinations']),2)
        self.assertTrue(all(s['node_id']!=self.member.node_id for s in view['sources']))
        self.assertTrue(any(d['node_id']==self.member.node_id for d in view['destinations']))
        self.assertTrue(all(n['available'] for n in view['nodes']))

    def route(self):
        self.coordinator.change(self.destination,{'source_id':self.source})
        intent=self.client.records('playback')['speaker-1']
        self.assertEqual(intent['owner'],self.member.node_id)
        self.assertEqual(intent['source_id'],self.source)
        # Model the root-owned player's reconnect; native acceptance measures PCM.
        self.audio[1].data['destinations'][0]['available']=False
        self.audio[0].data['destinations'].append({'id':'speaker-1','name':'Living Room','source_id':'Silence','volume':100,'muted':False,'available':True})
        self.coordinator.tick();self.client.tick()
        self.assertTrue(self.coordinator.records('route')[self.destination]['applied'])

    def test_cross_node_routing_volume_mute_and_deduplication(self):
        self.route()
        self.coordinator.change(self.destination,{'percent':37,'muted':True})
        view=self.coordinator.dashboard()
        dest=next(d for d in view['destinations'] if d['id']==self.destination)
        self.assertEqual((dest['source_id'],dest['volume'],dest['muted']),(self.source,37,True))
        self.assertEqual(len(view['destinations']),2)
        self.client.change(self.destination,{'muted':False})
        self.assertFalse(next(d for d in self.audio[0].data['destinations'] if d['id']=='speaker-1')['muted'])

    def test_hiding_preserves_routes_and_source_processes_and_survives_restart(self):
        self.route();before=copy.deepcopy(self.audio[0].data)
        self.coordinator.set_visibility(self.source,False)
        self.assertEqual(before,self.audio[0].data)
        view=self.coordinator.dashboard()
        self.assertNotIn(self.source,[s['id'] for s in view['sources']])
        self.assertEqual(next(d for d in view['destinations'] if d['id']==self.destination)['source_id'],self.source)
        with self.assertRaises(AudioError):self.coordinator.change(self.destination,{'source_id':self.source})
        restored=Coordination(self.host,self.audio[0].snapshot,self.audio[0],self.coordinator.metadata)
        self.assertNotIn(self.source,[s['id'] for s in restored.dashboard()['sources']])
        self.coordinator.change(self.destination,{'percent':42})
        self.coordinator.set_visibility(self.source,True)
        self.assertIn(self.source,[s['id'] for s in self.coordinator.dashboard()['sources']])

    def test_disconnect_keeps_last_settings_and_reconnects_without_rerouting(self):
        self.route();before=copy.deepcopy(self.audio[0].data)
        self.client.last_contact=0
        view=self.client.dashboard()
        self.assertIn('Coordinator unavailable',view['system_message'])
        self.assertFalse(view['destinations'][0]['available'])
        self.assertEqual(before,self.audio[0].data)
        self.client.tick()
        self.assertIn('Coordinator connected',self.client.dashboard()['system_message'])
        self.assertEqual(before,self.audio[0].data)

    def test_member_cannot_control_other_nodes_or_impersonate_coordinator(self):
        with self.assertRaises(NetworkError):self.client.change(self.host.node_id+'/speaker-0',{'muted':True})
        m=self.client.current()
        message=self.member.sign(self.host.node_id,m['id'],'coord.control',{'enrollment':m['enrollment'],'action':'apply','change':{}})
        with self.assertRaises(NetworkError):self.host.receive(message)
        self.host.remove(self.member.node_id)
        with self.assertRaises(NetworkError):self.client.tick()

    def test_failed_source_keeps_ready_destination_selectable(self):
        self.route()
        self.audio[0].data['destinations'][-1]['available']=False
        destination=next(d for d in self.coordinator.dashboard()['destinations'] if d['id']==self.destination)
        self.assertTrue(destination['available'])
        self.assertFalse(destination['playback_available'])
        self.assertIn('Choose another source',destination['message'])

    def test_new_volume_invalidates_old_pending_generation(self):
        self.route()
        intent=self.coordinator.records('route')[self.destination]
        intent['applied']=False
        self.coordinator.put('route',self.destination,intent)
        self.coordinator.change(self.destination,{'percent':61,'muted':True})
        updated=self.coordinator.records('route')[self.destination]
        self.assertNotEqual(intent['generation'],updated['generation'])
        self.coordinator.tick()
        actual=self.audio[0].data['destinations'][-1]
        self.assertEqual((actual['volume'],actual['muted']),(61,True))

    def test_external_infrastructure_is_not_retargeted(self):
        self.client.metadata.unlink();self.client.tick()
        with self.assertRaises(AudioError):self.coordinator.change(self.destination,{'source_id':self.source})
        self.assertFalse(self.client.records('playback'))
        self.coordinator.change(self.destination,{'source_id':self.member.node_id+'/Silence'})

    def test_root_reader_rejects_bad_targets_and_newer_schema_is_preserved(self):
        self.coordinator.change(self.destination,{'source_id':self.source})
        root=Path(self.temp.name)/'root';directory=root/'var/lib/flowharmonic';directory.mkdir(parents=True)
        import shutil,sqlite3
        shutil.copy(self.member.path,directory/'network.db');shutil.copy(self.client.path,directory/'coordination.db')
        self.assertEqual(target(root,self.member.node_id,'speaker-1',1704),('127.0.0.1',1704))
        with sqlite3.connect(directory/'coordination.db') as db:
            data=json.loads(db.execute('SELECT data FROM playback').fetchone()[0]);data['host']='8.8.8.8'
            db.execute('UPDATE playback SET data=?',(json.dumps(data),))
        self.assertEqual(target(root,self.member.node_id,'speaker-1',1704),('127.0.0.1',1704))
        with sqlite3.connect(self.client.path) as db:db.execute('PRAGMA user_version=9')
        before=self.client.path.read_bytes()
        with self.assertRaises(RuntimeError):Coordination(self.member,self.audio[1].snapshot,self.audio[1],self.client.metadata)
        self.assertEqual(before,self.client.path.read_bytes())
        base='[tcp]\nbind_to_address = 127.0.0.1\n[stream]\nbind_to_address = 127.0.0.1\n'
        generated=server_configuration(base,Path('/assets'),expose=True)
        self.assertIn('[tcp]\nbind_to_address = 127.0.0.1',generated)
        self.assertIn('bind_to_address = 0.0.0.0',generated.split('[stream]',1)[1])


if __name__=='__main__':unittest.main()
