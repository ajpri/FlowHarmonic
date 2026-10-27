// Exercise the shipped scene controls, selection, partial errors and member view.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {Element}=require('./dom_fixture');
const ids={};
for(const match of fs.readFileSync('flowharmonic/static/index.html','utf8').matchAll(/<([\w-]+)[^>]*\bid="([^"]+)"[^>]*>/g))ids[match[2]]=new Element(match[1]);
let scenes=[],manageable=true,writes=[];
const context=vm.createContext({document:{getElementById:id=>ids[id],createElement:tag=>new Element(tag)},
 element:(tag,text,cls)=>{const e=new Element(tag);e.textContent=text;e.className=cls;return e;},
 busy:false,changeRevision:0,updateDisabled(){},refresh:async()=>{},confirm:()=>true,
 request:async(url,body)=>{
  if(body!==undefined){writes.push({url,body});
   if(url==='/api/scenes'){scenes=[{id:'scene-1',name:body.name,destinations:[{name:'Office'},{name:'Kitchen'}]}];}
   if(url.endsWith('/apply'))return {results:[{name:'Office',applied:true},{name:'Kitchen',applied:false,message:'Speaker disconnected.'}]};
   if(url.endsWith('/remove'))scenes=[];
  }
  if(url==='/api/audio')return {destinations:[{id:'a',name:'Office',available:true,source_id:'Tone'},{id:'b',name:'Kitchen',available:false,source_id:'Tone'}]};
  return {scenes,manageable,message:manageable?'':'Manage scenes on the coordinator.'};
 }});
vm.runInContext(fs.readFileSync('flowharmonic/static/scenes.js','utf8'),context);
(async()=>{
 await vm.runInContext('refreshScenes()',context);
 const checks=ids['scene-destinations'].querySelectorAll('input');assert.equal(checks.length,2);assert.equal(checks[0].checked,true);assert.equal(checks[1].disabled,true);
 ids['scene-name'].value='Evening';await ids['scene-form'].event('submit');await new Promise(setImmediate);
 assert.deepEqual(JSON.parse(JSON.stringify(writes[0])),{url:'/api/scenes',body:{name:'Evening',destinations:['a']}});
 await vm.runInContext('sceneAction("/api/scenes/scene-1/apply")',context);
 assert.match(ids['scene-message'].textContent,/Office: Settings requested/);assert.match(ids['scene-message'].textContent,/Kitchen: Speaker disconnected/);
 await vm.runInContext('sceneAction("/api/scenes/scene-1/remove")',context);assert.equal(scenes.length,0);
 ids['scene-destinations'].querySelectorAll('input')[0].checked=false;
 await vm.runInContext("updateSceneDestinations({destinations:[{id:'a',name:'Office',available:true,source_id:'Tone'},{id:'b',name:'Kitchen',available:true,source_id:'Tone'}]},true)",context);
 const resumed=ids['scene-destinations'].querySelectorAll('input');assert.equal(resumed[0].checked,false);assert.equal(resumed[1].disabled,false);assert.equal(resumed[1].checked,true);
 manageable=false;await vm.runInContext('refreshScenes()',context);assert.equal(ids['scene-form'].hidden,true);assert.match(ids['scene-message'].textContent,/coordinator/);
 console.log('Scene destination selection, save/apply/remove, partial failure, and member guidance passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
