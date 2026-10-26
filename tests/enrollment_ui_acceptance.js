// Installed-VM DOM/event-handler + real HTTP test. No visual browser claim.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');
const {Element} = require('./dom_fixture');
const root = '/var/tmp/fh-m6-testing';
const assets = '/opt/flowharmonic/current/flowharmonic/static';
const sessions = JSON.parse(fs.readFileSync(root + '/sessions.json'));
const bases = {host: 'http://127.0.0.1:8080', member: 'http://10.206.0.2:8080'};
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function wait(predicate, message, timeout = 40000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await predicate()) return; await delay(100); }
  throw new Error('Timed out: ' + message);
}
async function api(role, path) {
  const response = await fetch(bases[role] + path, {headers: {Cookie: sessions[role].cookie}});
  assert(response.ok, `${role} ${path}: ${response.status}`);
  return response.json();
}
function open(role) {
  const ids = {};
  for (const match of fs.readFileSync(assets + '/index.html', 'utf8').matchAll(/<([\w-]+)[^>]*\bid="([^"]+)"[^>]*>/g)) ids[match[2]] = new Element(match[1]);
  const context = vm.createContext({document: {getElementById: id => ids[id], createElement: tag => new Element(tag), activeElement: null},
    fetch: (url, options = {}) => fetch(bases[role] + url, {...options, headers: {...options.headers, Cookie: sessions[role].cookie}}),
    location: {replace: url => { throw new Error('Unexpected sign out: ' + role + ' ' + url); }},
    AbortSignal, setInterval() {}, window: {confirm: () => true}});
  vm.runInContext(fs.readFileSync(assets + '/app.js', 'utf8'), context);
  vm.runInContext(fs.readFileSync(assets + '/network.js', 'utf8'), context);
  return {ids, context, state: () => vm.runInContext('networkState', context)};
}
async function settled(page) {
  try { await wait(() => vm.runInContext('networkState !== null && !networkBusy && !networkPolling', page.context), 'UI request finished'); }
  catch (error) { throw new Error(error.message + ': ' + page.ids['network-message'].textContent); }
}
async function refresh(page) { await settled(page); await vm.runInContext('refreshNetwork(true)', page.context); await settled(page); }
async function click(page, label, container = 'network-content') {
  await settled(page);
  const button = page.ids[container].querySelectorAll('button').find(button => button.textContent === label);
  assert(button, 'Missing button ' + label);
  assert(!button.disabled, 'Disabled button ' + label);
  await button.event('click');
  await settled(page);
}
async function verifyCode(page) {
  const check = page.ids['network-content'].querySelectorAll('input').find(input => input.type === 'checkbox');
  assert(check);
  check.checked = true;
  await check.event('change');
}
async function main() {
  await wait(async () => {
    try { await api('host', '/health'); await api('member', '/health'); return true; } catch { return false; }
  }, 'both HTTP services ready');
  const host = open('host'), member = open('member');
  await settled(host); await settled(member);
  if (process.argv[2] === 'exercise') {
    const hostInfo = await api('host', '/peer/info'), memberInfo = await api('member', '/peer/info');
    assert.notEqual(hostInfo.identity, memberInfo.identity);
    assert.notEqual(hostInfo.public_key, memberInfo.public_key);
    await wait(async () => { await refresh(host); await refresh(member); return host.state().discovery.nodes.some(n => n.identity === memberInfo.identity) && member.state().discovery.nodes.some(n => n.identity === hostInfo.identity); }, 'mutual mDNS discovery');
    assert.equal(host.state().membership, null); assert.equal(member.state().membership, null);
    host.ids['system-name-input'].value = 'M6 acceptance house';
    await host.ids['create-system-form'].event('submit'); await settled(host);
    await click(host, 'Allow join requests');
    await wait(async () => { await refresh(member); return member.state().discovery.nodes.some(n => n.identity === hostInfo.identity && n.is_host && n.accepting); }, 'existing managed system announcement');
    await click(member, 'Request to join', 'nearby-nodes');
    assert.equal(member.state().membership, null);
    await refresh(host);
    assert.equal(host.state().peers.length, 0);
    const hostCode = host.state().pending[0].code, memberCode = member.state().pending[0].code;
    assert.equal(hostCode, memberCode);
    await verifyCode(host); await click(host, 'Approve request');
    assert.equal(host.state().peers.length, 0);
    await refresh(member);
    assert.equal(member.state().pending[0].status, 'approved');
    assert.equal(member.state().membership, null);
    await verifyCode(member); await click(member, 'Confirm and join');
    await refresh(host); await refresh(member);
    assert.equal(host.state().membership.id, member.state().membership.id);
    assert.equal(host.state().peers[0].identity, memberInfo.identity);
    assert.match(member.ids['network-message'].textContent, /authenticated/);
    const evidence = {host: hostInfo.identity, member: memberInfo.identity, host_key: hostInfo.public_key, member_key: memberInfo.public_key,
      system: host.state().membership.id, mutual_mdns: true, managed_system_discovery: true, codes_match: hostCode === memberCode,
      no_automatic_enrollment: true, both_dashboard_approvals: true, signed_ping: true};
    fs.writeFileSync(root + '/exercise-result.json', JSON.stringify(evidence, null, 2));
    console.log(JSON.stringify(evidence));
  } else if (process.argv[2] === 'verify') {
    const before = JSON.parse(fs.readFileSync(root + '/exercise-result.json'));
    await refresh(host); await refresh(member);
    assert.equal((await api('host', '/health')).identity, before.host);
    assert.equal((await api('member', '/health')).identity, before.member);
    assert.equal((await api('host', '/peer/info')).public_key, before.host_key);
    assert.equal((await api('member', '/peer/info')).public_key, before.member_key);
    assert.equal(host.state().membership.id, before.system);
    assert.equal(member.state().membership.id, before.system);
    await wait(async () => { await refresh(host); await refresh(member); return host.state().discovery.nodes.some(n => n.identity === before.member) && member.state().discovery.nodes.some(n => n.identity === before.host); }, 'discovery after recovery');
    assert.match(member.ids['network-message'].textContent, /authenticated/);
    console.log(JSON.stringify({identity_keys_membership_and_browser_sessions_retained: true, signed_ping_after_recovery: true}));
  } else if (process.argv[2] === 'finish') {
    execFileSync('systemctl', ['stop', 'flowharmonic.service']);
    await refresh(member);
    assert.match(member.ids['network-message'].textContent, /Cannot reach/);
    assert(member.state().membership);
    execFileSync('systemctl', ['start', 'flowharmonic.service']);
    await wait(async () => { try { await api('host', '/health'); return true; } catch { return false; } }, 'primary restart');
    await refresh(member);
    assert.match(member.ids['network-message'].textContent, /authenticated/);
    await click(member, 'Leave system');
    await refresh(host);
    assert.equal(member.state().membership, null); assert.equal(host.state().peers.length, 0);
    // Manual fallback is a UI action, without any discovery dependency.
    if (!host.state().accepting) await click(host, 'Allow join requests');
    member.ids['system-address-input'].value = 'http://10.206.0.1:8080';
    await member.ids['join-system-form'].event('submit'); await settled(member);
    assert.equal(member.state().pending.length, 1);
    await click(member, 'Cancel request');
    await click(host, 'Dissolve system');
    assert.equal(host.state().membership, null);
    const evidence = {host_outage_understandable: true, membership_survives_outage: true, recovery_authenticated: true,
      leave_updates_both_nodes: true, manual_address_join_request: true, cancellation_and_dissolution: true};
    fs.writeFileSync(root + '/finish-result.json', JSON.stringify(evidence, null, 2));
    console.log(JSON.stringify(evidence));
  } else throw new Error('Unknown test phase');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
