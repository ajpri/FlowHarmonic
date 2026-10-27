// Controlled in-memory DOM tests; no user browser, network, or credentials.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assets = path.join(__dirname, '../flowharmonic/static');
const {Element} = require('./dom_fixture');
const password = 'a remembered test passphrase';
const server = {configured: false, session: false, outputOnline: true, audioOnline: true};
const writes = [];
async function fetch(url, options) {
  assert.equal(options.credentials, 'same-origin');
  let status = 200, data;
  if (options.method === 'POST') {
    assert.equal(options.headers['X-FlowHarmonic-Request'], '1');
    assert.equal(options.headers.Authorization, undefined);
    const body = JSON.parse(options.body);
    writes.push(url);
    if (url === '/api/auth/sign-in') {
      if (body.password === password) server.session = true;
      else { status = 401; data = {detail: 'That password is incorrect. Try again.'}; }
    } else if (url === '/api/auth/sign-out') server.session = false;
    else assert.fail(`Unexpected mutation ${url}`);
  }
  if (!data && url.startsWith('/api/auth')) data = {configured: server.configured, authenticated: server.session};
  else if (url === '/api/node') data = {name: 'Test device', version: '26.10.27'};
  else if (url === '/api/audio') {
    if (!server.audioOnline) { status = 503; data = {detail: 'Audio unavailable'}; }
    else data = {sources: [{id: 'Silence', name: 'Silence', status: 'playing'}], destinations: [{id: 'test', name: 'Test output', source_id: 'Silence', volume: 70, muted: false, available: server.outputOnline}]};
  }
  if (url === '/api/audio' && status === 200 && server.desktop !== undefined) {
    data.sources.push({id: 'Desktop Audio', name: 'Desktop Audio', status: server.desktop ? 'playing' : 'disabled', message: server.desktop ? 'Desktop audio is ready.' : 'Log in to a local PipeWire desktop.'});
  }
  return {ok: status === 200, status, json: async () => structuredClone(data)};
}
async function openPage(signIn = false) {
  const html = fs.readFileSync(path.join(assets, signIn ? 'sign-in.html' : 'index.html'), 'utf8');
  const script = fs.readFileSync(path.join(assets, signIn ? 'sign-in.js' : 'app.js'), 'utf8');
  const ids = {};
  for (const match of html.matchAll(/<([\w-]+)[^>]*\bid="([^"]+)"[^>]*>/g)) {
    ids[match[2]] = new Element(match[1]);
    ids[match[2]].hidden = /\bhidden\b/.test(match[0]);
  }
  const document = {getElementById: id => ids[id], createElement: tag => new Element(tag), activeElement: null};
  const redirects = [];
  const context = vm.createContext({document, location: {replace: target => redirects.push(target)}, fetch, AbortSignal, setInterval() {}});
  vm.runInContext(script, context);
  await new Promise(setImmediate);
  return {ids, document, context, redirects, controls: () => ids.destinations.querySelectorAll('input, select, button'), groups: selector => ids.destinations.querySelectorAll(selector)};
}
(async () => {
  const unconfigured = await openPage(true);
  assert.equal(unconfigured.ids['sign-in-form'].hidden, true);
  assert.match(unconfigured.ids['sign-in-status'].textContent, /sudo flowharmonic password/);
  const signedOut = await openPage();
  assert.deepEqual(signedOut.redirects, ['/sign-in']);
  server.configured = true;
  const signIn = await openPage(true);
  assert.equal(signIn.ids['sign-in-form'].hidden, false);
  signIn.ids.password.value = 'wrong password';
  await signIn.ids['sign-in-form'].event('submit');
  assert.equal(signIn.ids['sign-in-error'].hidden, false);
  assert.match(signIn.ids['sign-in-error'].textContent, /incorrect/);
  signIn.ids.password.value = password;
  await signIn.ids['sign-in-form'].event('submit');
  assert.deepEqual(signIn.redirects, ['/']);
  assert.equal(signIn.ids.password.value, '');
  const dashboard = await openPage();
  assert(dashboard.controls().every(control => !control.disabled));
  assert(dashboard.groups('.destination-controls').every(group => !group.hidden));
  assert(dashboard.groups('.playback-summary').every(summary => summary.hidden));
  assert.equal(dashboard.ids['sign-out'].hidden, false);
  assert((await openPage()).controls().every(control => !control.disabled));
  assert((await openPage(true)).redirects.includes('/'));
  // A focused control must not prevent a disconnected output being updated.
  dashboard.document.activeElement = dashboard.controls().at(-1);
  server.desktop = false;
  await vm.runInContext('refresh()', dashboard.context);
  assert(dashboard.ids.destinations.querySelectorAll('option').some(option => option.value === 'Desktop Audio' && option.disabled));
  assert(dashboard.ids.sources.querySelectorAll('p').some(note => note.textContent.includes('Log in')));
  server.desktop = true;
  await vm.runInContext('refresh()', dashboard.context);
  assert(dashboard.ids.destinations.querySelectorAll('option').some(option => option.value === 'Desktop Audio' && !option.disabled));
  server.outputOnline = false;
  await vm.runInContext('refresh()', dashboard.context);
  assert(dashboard.groups('.destination-controls').every(group => group.hidden));
  assert(dashboard.groups('.playback-summary').every(summary => !summary.hidden && summary.textContent.startsWith('Last known:')));
  assert(dashboard.groups('.destination-reason').every(reason => !reason.hidden && reason.textContent.includes('disconnected')));
  server.outputOnline = true;
  await vm.runInContext('refresh()', dashboard.context);
  assert(dashboard.groups('.destination-controls').every(group => !group.hidden));
  assert(dashboard.controls().every(control => !control.disabled));
  server.audioOnline = false;
  await vm.runInContext('refresh()', dashboard.context);
  assert(dashboard.groups('.destination-controls').every(group => group.hidden));
  assert(dashboard.groups('.destination-reason').every(reason => !reason.hidden && reason.textContent.includes('connection')));
  server.audioOnline = true;
  await vm.runInContext('refresh()', dashboard.context);
  assert(dashboard.controls().every(control => !control.disabled));
  const anotherTab = await openPage();
  await dashboard.ids['sign-out'].event('click');
  assert(dashboard.redirects.includes('/sign-in'));
  await vm.runInContext('refresh()', anotherTab.context);
  assert(anotherTab.redirects.includes('/sign-in'));
  assert.deepEqual(writes, ['/api/auth/sign-in', '/api/auth/sign-in', '/api/auth/sign-out']);
  console.log('Sign-in page, remembered session, offline/reconnect, focused controls, outage recovery, and sign-out checks passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
