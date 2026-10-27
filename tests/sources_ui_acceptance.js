// Test-only DOM/event-handler acceptance against an actual installed M8 service.
'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const {Element}=require('./dom_fixture');
Element.prototype.focus=function(){};
const session=JSON.parse(fs.readFileSync(process.env.FH_M8_SESSION));
const base=process.env.FH_M8_URL || 'http://127.0.0.1:18080';
const ids={};
for(const match of fs.readFileSync('flowharmonic/static/index.html','utf8').matchAll(/<([\w-]+)[^>]*\bid="([^"]+)"[^>]*>/g))ids[match[2]]=new Element(match[1]);
const context=vm.createContext({document:{getElementById:id=>ids[id],createElement:tag=>new Element(tag),activeElement:null},
 fetch:(url,options={})=>fetch(base+url,{...options,headers:{...options.headers,Cookie:session.cookie}}),AbortSignal,setInterval(){},
 confirm:()=>true,location:{replace:url=>{throw Error('Unexpected authentication redirect: '+url);}}});
for(const script of ['app.js','sources.js'])vm.runInContext(fs.readFileSync('flowharmonic/static/'+script,'utf8'),context);
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function wait(check){const end=Date.now()+60000;while(Date.now()<end){if(await check())return;await delay(500);}throw Error('Timeout: '+ids['source-setup-message'].textContent);}
const evaluate=code=>vm.runInContext(code,context);
async function setup(){await evaluate('refreshSourceSetup()');return evaluate('sourceSetup');}
async function main(){
 const mode=process.argv[2];
 await wait(async()=>{await setup();return mode==='add'?evaluate('sourceSetup').inputs.length:evaluate('sourceSetup').sources.length;});
 if(mode==='add'){
  ids['source-kind'].value='music';await ids['source-kind'].event('change');ids['source-name'].value='M8 acceptance music';
  ids['source-folder'].value='/srv/fh-m8-acceptance';await ids['load-tracks'].event('click');ids['source-track'].value='stereo.wav';
  await ids['source-setup-form'].event('submit');
  let view=await setup();assert(view.sources.some(s=>s.name==='M8 acceptance music'));
  ids['source-kind'].value='input';await ids['source-kind'].event('change');ids['source-name'].value='M8 acceptance input channel 2';
  ids['source-device'].value=view.inputs.find(d=>d.device==='plughw:CARD=Loopback,DEV=0').key;ids['source-channels'].value='2';
  await ids['source-setup-form'].event('submit');view=await setup();assert.equal(view.sources.filter(s=>s.name.startsWith('M8 acceptance')).length,2);
  assert(view.sources.filter(s=>s.name.startsWith('M8 acceptance')).every(s=>s.state==='stopped'));
  fs.writeFileSync('/tmp/fh-m8-test-ids.json',JSON.stringify(view.sources.filter(s=>s.name.startsWith('M8 acceptance')).map(s=>({id:s.id,kind:s.kind}))));
  console.log(JSON.stringify({created_using_ui:true,new_sources_stopped:true}));
 }else if(mode==='remove-test-sources'){
  const owned=(await setup()).sources.filter(s=>s.name.startsWith('M8 acceptance'));
  for(const source of owned){
   await setup();
   const row=ids['configured-sources'].children.find(row=>row.children.some(c=>c.tag==='h3' && c.textContent===source.name));assert(row);
   await row.querySelectorAll('button').find(b=>b.textContent==='Remove').event('click');
   await wait(async()=>{const view=await setup();return !view.sources.some(s=>s.id===source.id) && !evaluate('sourceSetupBusy');});
  }
  console.log(JSON.stringify({test_sources_removed_using_ui:owned.length}));
 }else if(mode==='track'){
  const row=ids['configured-sources'].children.find(row=>row.children.some(c=>c.tag==='h3' && c.textContent==='M8 acceptance music'));assert(row);
  await row.querySelectorAll('button').find(b=>b.textContent==='Edit').event('click');
  ids['source-track'].value='second.wav';await ids['source-setup-form'].event('submit');
  await wait(async()=>{const view=await setup();return view.sources.find(s=>s.kind==='music').observed.track==='second.wav';});
  console.log(JSON.stringify({track_selection_using_ui:true}));
 }else if(mode==='add-bluetooth'){
  ids['source-kind'].value='bluetooth';await ids['source-kind'].event('change');ids['source-name'].value='M8 acceptance Bluetooth';ids['source-device'].value='00:AA:01:01:00:01';
  await ids['source-setup-form'].event('submit');
  await setup();const row=ids['configured-sources'].children.find(row=>row.children.some(c=>c.tag==='h3' && c.textContent==='M8 acceptance Bluetooth'));assert(row);
  await row.querySelectorAll('button').find(b=>b.textContent==='Start').event('click');
  console.log(JSON.stringify({bluetooth_configured_and_started_using_ui:true}));
 }else if(mode==='route-music'||mode==='route-input'){
  const name=mode==='route-music'?'M8 acceptance music':'M8 acceptance input channel 2';
  await wait(async()=>{await evaluate('refresh()');return evaluate('inventory').sources.some(s=>s.name===name && s.status!=='disabled');});
  const inventory=evaluate('inventory'),destination=inventory.destinations.find(d=>d.id==='fh-84b6170736e45479838a35653d66c8d2');assert(destination?.available);
  const select=ids.destinations.querySelectorAll('select').find(c=>c['aria-label']==='Source for '+destination.name);assert(select);
  select.value=inventory.sources.find(s=>s.name===name).id;await select.event('change');
  await wait(async()=>{await evaluate('refresh()');return evaluate('inventory').destinations.find(d=>d.id===destination.id).source_id===select.value;});
  console.log(JSON.stringify({[mode]:true}));
 }else if(mode==='configure-input'){
  const view=await setup();
  const row=ids['configured-sources'].children.find(row=>row.children.some(c=>c.tag==='h3' && c.textContent==='M8 acceptance input channel 2'));assert(row);
  await row.querySelectorAll('button').find(b=>b.textContent==='Edit').event('click');
  ids['source-device'].value=view.inputs.find(d=>d.backend==='pipewire' && !d.bluetooth).key;ids['source-channels'].value='2';
  await ids['source-setup-form'].event('submit');console.log(JSON.stringify({input_device_and_channel_selected_using_ui:true}));
 }else if(['play','pause','resume','stop','start-input','remove'].includes(mode)){
  const name=mode==='start-input'?'M8 acceptance input channel 2':'M8 acceptance music';
  const row=ids['configured-sources'].children.find(row=>row.children.some(c=>c.tag==='h3' && c.textContent===name));assert(row);
  const label={play:'Play',pause:'Pause',resume:'Play',stop:'Stop','start-input':'Start',remove:'Remove'}[mode];
  await row.querySelectorAll('button').find(b=>b.textContent===label).event('click');
  const state={play:'playing',pause:'paused',resume:'playing',stop:'stopped','start-input':'playing'}[mode];
  if(state)await wait(async()=>{const view=await setup();const row=view.sources.find(s=>s.name===name);return row.observed.state===state && (state==='stopped'||row.observed.available);});
  console.log(JSON.stringify({[mode]:true}));
 }else throw Error('Unknown test action');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
