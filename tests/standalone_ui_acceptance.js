// Installed-VM test only. Execute real dashboard event handlers against the
// running HTTP service, with an administrator-issued disposable test session.
// This is a DOM/API test, not a visual browser automation claim.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');
const {Element} = require('./dom_fixture');
const stateFile = '/var/lib/flowharmonic/backups/m5-acceptance-state.json';
const session = JSON.parse(fs.readFileSync('/var/lib/flowharmonic/backups/m5-test-session.json', 'utf8'));
const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
const mode = process.argv[2];
const assets = '/opt/flowharmonic/current/flowharmonic/static';
const ids = {};
for (const match of fs.readFileSync(path.join(assets, 'index.html'), 'utf8').matchAll(/<([\w-]+)[^>]*\bid="([^"]+)"[^>]*>/g)) {
  ids[match[2]] = new Element(match[1]);
  ids[match[2]].hidden = /\bhidden\b/.test(match[0]);
}
const document = {getElementById: id => ids[id], createElement: tag => new Element(tag), activeElement: null};
const redirects = [];
async function fetchLocal(url, options = {}) {
  assert(url.startsWith('/') && !url.startsWith('//'));
  return fetch('http://127.0.0.1:8080' + url, {...options, headers: {...options.headers, Cookie: session.cookie}});
}
const context = vm.createContext({document, location: {replace: url => redirects.push(url)}, fetch: fetchLocal, AbortSignal, setInterval() {}});
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function wait(predicate, timeout = 30000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { if (await predicate()) return; await delay(100); }
  throw new Error('Timed out waiting for ' + mode);
}
async function refresh() { await vm.runInContext('refresh()', context); }
function control(tag, label) {
  return ids.destinations.querySelectorAll(tag).find(node => node['aria-label'] === label);
}
function chooseDestination() {
  const data = vm.runInContext('inventory', context);
  return data.destinations.find(d => d.id === state.destination);
}
async function route(source) {
  const d = chooseDestination();
  const select = control('select', `Source for ${d.name}`);
  assert(select && !select.disabled && !select.children.find(o => o.value === source)?.disabled);
  select.value = source;
  await select.event('change');
  assert.equal(chooseDestination().source_id, source);
}
async function volume(percent) {
  const d = chooseDestination();
  const slider = control('input', `Volume for ${d.name}`);
  slider.value = String(percent);
  await slider.event('change');
  assert.equal(chooseDestination().volume, percent);
}
async function mute(wanted) {
  const d = chooseDestination();
  if (d.muted === wanted) return;
  await control('button', `${d.muted ? 'Unmute' : 'Mute'} ${d.name}`).event('click');
  assert.equal(chooseDestination().muted, wanted);
}
(async () => {
  vm.runInContext(fs.readFileSync(path.join(assets, 'app.js'), 'utf8'), context);
  await wait(() => ids.version.textContent === 'M5' && chooseDestination()?.available);
  assert.deepEqual(redirects, []);
  if (mode === 'tone440' || mode === 'tone880') {
    await volume(37); await mute(false);
    await route(mode === 'tone440' ? 'Test tone 440 Hz' : 'Test tone 880 Hz');
  } else if (mode === 'mute') {
    await mute(true);
  } else if (mode === 'persist') {
    ids['node-name-input'].value = 'M5 standalone test';
    await ids['node-name-input'].event('input');
    await ids['node-settings-form'].event('submit');
    assert.equal(ids['node-name'].textContent, 'M5 standalone test');
    const d = chooseDestination();
    const name = control('input', `Name for ${d.name}`);
    name.value = 'M5 local speakers';
    await name.event('input');
    const form = ids.destinations.querySelectorAll('form').find(form => form.contains(name));
    await form.event('submit');
    assert.equal(chooseDestination().name, 'M5 local speakers');
    await ids['refresh-diagnostics'].event('click');
    assert(ids['diagnostics-content'].querySelectorAll('p').some(p => p.textContent.includes('Local configuration')));
  } else if (mode === 'verify') {
    const d = chooseDestination();
    assert.equal(ids['node-name'].textContent, 'M5 standalone test');
    assert.equal(d.name, 'M5 local speakers');
    assert.equal(d.source_id, 'Test tone 880 Hz');
    assert.equal(d.volume, 37);
    assert.equal(d.muted, true);
  } else if (mode === 'server-recovery' || mode === 'app-recovery' || mode === 'client-recovery') {
    const unit = mode === 'server-recovery' ? 'flowharmonic-snapserver.service' :
      mode === 'app-recovery' ? 'flowharmonic.service' : state.client_unit;
    assert(/^flowharmonic(?:-snapserver|-desktop-\d+|-playback-[a-f0-9]{20})?\.service$/.test(unit));
    const oldPid = execFileSync('systemctl', ['show', unit, '-p', 'MainPID', '--value'], {encoding: 'utf8'}).trim();
    execFileSync('systemctl', ['kill', '--kill-who=main', '--signal=SIGKILL', unit]);
    if (mode === 'client-recovery') {
      await wait(async () => { await refresh(); return !chooseDestination()?.available; }, 10000);
    } else {
      await refresh();
      assert.equal(ids.connection.textContent, 'Audio unavailable');
      assert.equal(ids.error.hidden, false);
      if (mode === 'server-recovery') {
        await ids['refresh-diagnostics'].event('click');
        assert(ids['diagnostics-content'].querySelectorAll('p').some(p => p.textContent.includes('Cannot reach')));
      }
    }
    await wait(async () => { await refresh(); return ids.connection.textContent === 'Audio connected' && chooseDestination()?.available; });
    const newPid = execFileSync('systemctl', ['show', unit, '-p', 'MainPID', '--value'], {encoding: 'utf8'}).trim();
    assert.notEqual(newPid, oldPid);
    assert.notEqual(newPid, '0');
    const d = chooseDestination();
    assert.equal(d.source_id, 'Test tone 880 Hz');
    assert.equal(d.volume, 37); assert.equal(d.muted, true);
    assert.equal(d.name, 'M5 local speakers');
    assert.equal(ids['node-name'].textContent, 'M5 standalone test');
  } else { throw new Error('Unknown test mode'); }
  console.log(JSON.stringify({mode, passed: true}));
})().catch(error => { console.error(error); process.exitCode = 1; });
