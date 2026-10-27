// Test-only DOM/event-handler acceptance against real installed HTTP services.
'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const {Element}=require('./dom_fixture');
const assets=process.env.FH_M7_ASSETS || require('node:path').join(__dirname,'../flowharmonic/static');
const session=JSON.parse(fs.readFileSync(process.env.FH_M7_SESSION));
const base=process.env.FH_M7_URL || 'http://127.0.0.1:18080';
const ids={};
for(const match of fs.readFileSync(assets+'/index.html','utf8').matchAll(/<([\w-]+)[^>]*\bid="([^"]+)"[^>]*>/g))ids[match[2]]=new Element(match[1]);
const context=vm.createContext({document:{getElementById:id=>ids[id],createElement:tag=>new Element(tag),activeElement:null},
 fetch:(url,options={})=>fetch(base+url,{...options,headers:{...options.headers,Cookie:session.cookie}}),AbortSignal,setInterval(){},
 location:{replace:url=>{throw Error('Unexpected sign-out: '+url);}}});
vm.runInContext(fs.readFileSync(assets+'/app.js','utf8'),context);
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const inventory=()=>vm.runInContext('inventory',context);
async function wait(check,timeout=60000){const end=Date.now()+timeout;while(Date.now()<end){if(await check())return;await delay(250);}throw Error('Timed out; UI error: '+ids.error.textContent);}
async function refresh(){await vm.runInContext('refresh()',context);}
function destination(){return inventory().destinations.find(d=>d.node_id===process.env.FH_M7_DEST && d.owned);}
async function main(){
 await wait(async()=>{await refresh();return destination()?.available;});
 const mode=process.argv[2];
 if(mode==='route'){
  const source=inventory().sources.find(s=>s.node_id===process.env.FH_M7_SOURCE && s.id.endsWith('/Desktop Audio'));
  assert(source && source.status!=='disabled');
  const d=destination();
  const select=ids.destinations.querySelectorAll('select').find(s=>s['aria-label']==='Source for '+d.name);
  select.value=source.id;await select.event('change');
  await wait(async()=>{await refresh();const row=destination();return row.available && row.source_id===source.id && !row.pending;});
  console.log(JSON.stringify({desktop_routed_through_dashboard:true,destination:destination().id,source:source.id}));
 }else if(mode==='volume'||mode==='mute'||mode==='unmute'){
  const d=destination();
  const control=mode==='volume'?ids.destinations.querySelectorAll('input').find(c=>c['aria-label']==='Volume for '+d.name):
   ids.destinations.querySelectorAll('button').find(c=>c['aria-label']===(mode==='mute'?'Mute ':'Unmute ')+d.name);
  assert(control);
  if(mode==='volume'){control.value='37';await control.event('change');}else await control.event('click');
  await wait(async()=>{await refresh();return mode==='volume'?destination().volume===37:destination().muted===(mode==='mute');});
  console.log(JSON.stringify({[mode]:true}));
 }else if(mode==='hide'||mode==='show'||mode==='destination-only'){
  const all=inventory().all_sources;
  const selected=all.filter(s=>mode==='destination-only'?s.node_id===process.env.FH_M7_DEST:s.node_id===process.env.FH_M7_SOURCE && s.id.endsWith('/Desktop Audio'));
  for(const source of selected){
   const label='Show '+source.node_name+' / '+source.name;
   const check=ids['source-visibility'].querySelectorAll('input').find(c=>c['aria-label']===label);
   assert(check);check.checked=mode==='show';await check.event('change');
  }
  await wait(async()=>{await refresh();return selected.every(source=>mode==='show'?inventory().sources.some(s=>s.id===source.id):!inventory().sources.some(s=>s.id===source.id));});
  assert(destination().available);
  console.log(JSON.stringify({[mode]:true,existing_destination_available:true}));
 }else if(mode==='verify-hidden'){
  assert(!inventory().sources.some(s=>s.node_id===process.env.FH_M7_SOURCE && s.id.endsWith('/Desktop Audio')));
  assert(destination().source_id.endsWith('/Desktop Audio'));
  console.log(JSON.stringify({hidden_source_persisted_and_current_route_retained:true}));
 }else throw Error('Unknown test mode');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
