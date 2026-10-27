"use strict";
let sourceSetup = {sources: [], inputs: [], bluetooth: {devices: []}};
let sourceEdit = null;
let sourceSetupBusy = false;
const sourcePanel = document.getElementById('source-setup');
const sourceForm = document.getElementById('source-setup-form');
const sourceKind = document.getElementById('source-kind');
const sourceDevice = document.getElementById('source-device');
const sourceChannels = document.getElementById('source-channels');
const sourceName = document.getElementById('source-name');
const sourceFolder = document.getElementById('source-folder');
const sourceTrack = document.getElementById('source-track');
const sourceMessage = document.getElementById('source-setup-message');

function sourceOptions() {
  document.getElementById('input-settings').hidden = sourceKind.value === 'music';
  document.getElementById('music-settings').hidden = sourceKind.value !== 'music';
  sourceChannels.hidden = sourceKind.value === 'bluetooth';
  document.getElementById('source-channels-label').hidden = sourceKind.value === 'bluetooth';
  const selected = sourceDevice.value || sourceEdit?.device;
  sourceDevice.replaceChildren();
  const devices = sourceKind.value === 'bluetooth' ? (sourceSetup.bluetooth.devices || []).map(d => ({key: d.address, name: d.name})) : sourceSetup.inputs.filter(d => !d.bluetooth);
  for (const device of devices) {
    const option = element('option', device.name + (device.channels ? ` (${device.channels} channels)` : ''));
    option.value = device.key; sourceDevice.append(option);
  }
  if (selected && !devices.some(d => d.key === selected)) {
    const option = element('option', 'Configured device — unavailable');option.value = selected;sourceDevice.append(option);
  }
  if (selected) sourceDevice.value = selected;
}
async function sourceAction(url, body) {
  if (sourceSetupBusy) return;
  sourceSetupBusy = true;
  sourcePanel.querySelectorAll('button').forEach(button => {button.disabled = true;});
  try {
    await request(url, body);
    sourceMessage.textContent = 'Saved. Source setup applies automatically; allow up to 20 seconds.';
    await refreshSourceSetup();await refresh();
    return true;
  } catch (problem) {sourceMessage.textContent = problem.message;}
  finally {sourceSetupBusy = false;sourcePanel.querySelectorAll('button').forEach(button => {button.disabled = false;});}
}
function sourceValue(row) {
  const {observed, ...value} = row;
  return value;
}
function sourceButton(text, action) {
  const button=element('button',text);button.type='button';button.addEventListener('click',action);return button;
}
function renderSourceSetup() {
  const list=document.getElementById('configured-sources');
  {
    const focused=document.activeElement?.dataset;
    const focusedSource=focused?.sourceId, focusedAction=focused?.sourceAction;
    list.replaceChildren();
    for (const row of sourceSetup.sources) {
      const item=element('div',undefined,'source');
      item.append(element('h3',row.name),element('p',row.observed.message || 'Starting…'));
      if (row.observed.track) item.append(element('p',row.observed.track));
      for (const [label,state] of (row.kind==='music' ? [['Play','playing'],['Pause','paused'],['Stop','stopped']] : [['Start','playing'],['Stop','stopped']])) {
        const button=sourceButton(label,()=>sourceAction('/api/source-setup/save',{...sourceValue(row),state}));
        button.disabled=row.state===state;item.append(button);
      }
      item.append(sourceButton('Edit',async()=>{
        sourceEdit=sourceValue(row);sourceKind.value=row.kind;sourceKind.disabled=true;sourceName.value=row.name;
        sourceFolder.value=row.folder || '';sourceChannels.value=(row.channels || [1,2]).join(',');
        sourceOptions();sourceDevice.value=row.device || '';
        if (row.kind==='music') {
          await loadSourceTracks();
          if(row.track && !Array.from(sourceTrack.querySelectorAll('option')).some(option=>option.value===row.track)){
            const option=element('option',row.track+' — unavailable');option.value=row.track;sourceTrack.append(option);
          }
          sourceTrack.value=row.track || '';
        }
        document.getElementById('save-source').textContent='Save source';document.getElementById('cancel-source-edit').hidden=false;
        sourceName.focus();
      }));
      item.append(sourceButton('Remove',()=>{
        if (confirm(`Remove ${row.name}? Any route using this source will lose its audio.`)) sourceAction('/api/source-setup/remove',{id:row.id});
      }));
      item.querySelectorAll('button').forEach(button=>{button.dataset.sourceId=row.id;button.dataset.sourceAction=button.textContent;});
      list.append(item);
    }
    if (!sourceSetup.sources.length) list.append(element('p','No additional sources configured.'));
    if(focusedSource)list.querySelectorAll('button').find(button=>button.dataset.sourceId===focusedSource && button.dataset.sourceAction===focusedAction)?.focus();
  }
  if (!sourceForm.contains(document.activeElement)) sourceOptions();
  const bluetooth=sourceSetup.bluetooth;
  document.getElementById('bluetooth-message').textContent=bluetooth.message || 'Bluetooth status is unavailable.';
  document.getElementById('bluetooth-pair').disabled=bluetooth.available===false;
  const confirmation=document.getElementById('bluetooth-confirmation');confirmation.replaceChildren();
  if (bluetooth.confirmation) {
    confirmation.append(element('p',bluetooth.confirmation.message));
    for (const accept of [true,false]) confirmation.append(sourceButton(accept ? (bluetooth.confirmation.message.includes('passkey') ? 'Approve matching code' : 'Approve device request') : 'Reject',()=>sourceAction('/api/source-setup/bluetooth',{action:'confirm',accept,confirmation:bluetooth.confirmation.id})));
  }
  const devices=document.getElementById('bluetooth-devices');devices.replaceChildren();
  for (const device of bluetooth.devices || []) {
    const line=element('div');line.append(element('p',`${device.name} (${device.address}) — ${device.connected ? 'Connected' : 'Disconnected'}`));
    if (!device.connected || !device.trusted) line.append(sourceButton('Trust and connect',()=>sourceAction('/api/source-setup/bluetooth',{action:'connect',device:device.address})));
    if (device.connected) line.append(sourceButton('Disconnect',()=>sourceAction('/api/source-setup/bluetooth',{action:'disconnect',device:device.address})));
    line.append(sourceButton('Forget',()=>{if(confirm(`Forget the Bluetooth pairing for ${device.name}?`))sourceAction('/api/source-setup/bluetooth',{action:'forget',device:device.address});}));devices.append(line);
  }
}
async function refreshSourceSetup() {
  try {sourceSetup=await request('/api/source-setup');renderSourceSetup();}
  catch (problem) {sourceMessage.textContent=problem.message;}
}
async function loadSourceTracks() {
  try {
    const selected=sourceTrack.value;
    const result=await request('/api/source-setup/tracks',{folder:sourceFolder.value});
    sourceTrack.replaceChildren();const first=element('option','First available track');first.value='';sourceTrack.append(first);
    for (const track of result.tracks) {const option=element('option',track);option.value=track;sourceTrack.append(option);}
    sourceTrack.value=selected || '';
    sourceMessage.textContent=`${result.tracks.length} supported tracks found.`;
  }catch(problem){sourceMessage.textContent=problem.message;}
}
function clearSourceEdit() {
  sourceEdit=null;sourceKind.disabled=false;sourceName.value='';sourceFolder.value='';
  document.getElementById('save-source').textContent='Add source';document.getElementById('cancel-source-edit').hidden=true;sourceOptions();
}
sourceForm.addEventListener('submit',async event=>{
  event.preventDefault();
  const value={...(sourceEdit || {}),name:sourceName.value,kind:sourceKind.value,state:sourceEdit?.state || 'stopped'};
  if (value.kind==='music') {value.folder=sourceFolder.value;value.track=sourceTrack.value;}
  else {value.device=sourceDevice.value;if(value.kind==='input')value.channels=sourceChannels.value.split(',').map(c=>Number(c.trim()));}
  if (await sourceAction('/api/source-setup/save',value)) clearSourceEdit();
});
sourceKind.addEventListener('change',()=>{sourceEdit=null;sourceDevice.value='';sourceOptions();});
document.getElementById('cancel-source-edit').addEventListener('click',clearSourceEdit);
document.getElementById('refresh-source-setup').addEventListener('click',refreshSourceSetup);
document.getElementById('load-tracks').addEventListener('click',loadSourceTracks);
document.getElementById('bluetooth-pair').addEventListener('click',()=>sourceAction('/api/source-setup/bluetooth',{action:'pairing'}));
document.getElementById('bluetooth-close').addEventListener('click',()=>sourceAction('/api/source-setup/bluetooth',{action:'close'}));
sourcePanel.addEventListener('toggle',()=>{if(sourcePanel.open)refreshSourceSetup();});
setInterval(()=>{if(sourcePanel.open && !sourceSetupBusy)refreshSourceSetup();},3000);
