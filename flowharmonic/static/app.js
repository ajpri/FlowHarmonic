"use strict";
const connection = document.getElementById("connection");
const error = document.getElementById("error");
const retry = document.getElementById("retry");
const notice = document.getElementById("notice");
const destinations = document.getElementById("destinations");
let authentication = {configured: false, authenticated: false};
let busy = false;
let polling = false;
let diagnosticsBusy = false;
let nodeNameDirty = false;
const renameDrafts = new Map();
let changeRevision = 0;
let online = false;
let inventory = {sources: [], destinations: []};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
async function request(url, body) {
  const options = {cache: "no-store", credentials: "same-origin", signal: AbortSignal.timeout(30000)};
  if (body !== undefined) {
    options.method = "POST";
    options.headers = {"Content-Type": "application/json", "X-FlowHarmonic-Request": "1"};
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(url, options);
  } catch (problem) {
    const message = problem.name === "TimeoutError" || problem.name === "AbortError" ?
      "This device took too long to respond." : "Cannot reach this device. Check its connection.";
    throw new Error(message + (body !== undefined ? " The change may have applied; refresh before trying again." : " Try again shortly."));
  }
  let data;
  try { data = await response.json(); }
  catch (_) { throw new Error("This device returned an unreadable response. Refresh and try again."); }
  if (!response.ok) {
    if (response.status === 401) { authentication.authenticated = false; location.replace("/sign-in"); updateDisabled(); }
    throw new Error(typeof data.detail === "string" ? data.detail : "Check the selected audio setting and try again.");
  }
  return data;
}
function showError(message) {
  error.textContent = message;
  error.hidden = false;
  retry.hidden = false;
}
function updateDisabled() {
  document.getElementById("sign-out").disabled = busy;
  document.getElementById("save-node").disabled = busy;
  const canEdit = authentication.authenticated && online;
  destinations.querySelectorAll(".destination-controls").forEach(group => {
    group.hidden = !canEdit || group.dataset.offline === "true";
  });
  destinations.querySelectorAll(".playback-summary").forEach(summary => {
    const stale = !online || summary.dataset.offline === "true";
    summary.hidden = canEdit && !stale;
    summary.textContent = (stale ? "Last known: " : "") + summary.dataset.settings;
  });
  destinations.querySelectorAll(".destination-reason").forEach(reason => {
    reason.hidden = online && reason.dataset.offline !== "true";
    reason.textContent = online ? reason.dataset.message :
      "The audio connection is unavailable. Playback controls will return when it reconnects.";
  });
  destinations.querySelectorAll("input, select, button").forEach(control => {
    control.disabled = !authentication.authenticated || !online || busy || control.dataset.offline === "true";
    control.title = control.dataset.offline === "true" ? "This destination or its sources are unavailable." :
      !authentication.authenticated ? "Sign in to change audio settings." :
      !online ? "Audio is unavailable. Controls will return when it reconnects." :
      busy ? "Saving your change…" : "";
  });
}
function render() {
  const sources = document.getElementById("sources");
  document.getElementById("local-status").textContent = inventory.local_message || "";
  document.getElementById("system-status").textContent = inventory.system_message || "";
  const nodes = document.getElementById("system-nodes");
  nodes.replaceChildren();
  for (const node of inventory.nodes || []) nodes.append(element("p", `${node.name}: ${node.available ? "Connected" : "Disconnected"}`));
  const visibility = document.getElementById("source-visibility");
  if (!visibility.contains(document.activeElement)) {
    visibility.replaceChildren();
    for (const source of inventory.all_sources || inventory.sources) {
      const label = element("label");
      const check = element("input");
      check.type = "checkbox";
      check.checked = source.visible !== false;
      check.setAttribute("aria-label", `Show ${source.node_name ? source.node_name + " / " : ""}${source.name}`);
      check.addEventListener("change", async () => {
        check.disabled = true;
        try {
          await request("/api/source-visibility", {source_id: source.id, visible: check.checked});
          notice.textContent = "Source visibility saved. Existing playback continues.";
          await refresh();
        } catch (problem) { check.checked = !check.checked; showError(problem.message); }
        finally { check.disabled = false; }
      });
      label.append(check, element("span", ` ${source.node_name ? source.node_name + " / " : ""}${source.name}`));
      visibility.append(label);
    }
  }
  sources.replaceChildren();
  destinations.replaceChildren();
  document.getElementById("source-count").textContent = String(inventory.sources.length);
  document.getElementById("destination-count").textContent = String(inventory.destinations.length);
  if (!inventory.sources.length) sources.append(element("p", "No sources available.", "empty"));
  for (const source of inventory.sources) {
    const row = element("div", undefined, "audio-row");
    row.append(element("strong", source.node_name ? `${source.node_name} / ${source.name}` : source.name), element("span", source.status === "playing" ? "Playing" : source.status === "idle" ? "Idle" : "Unavailable", "availability"));
    if (source.message) row.append(element("p", source.message, "availability-note"));
    sources.append(row);
  }
  if (!inventory.destinations.length) destinations.append(element("p", "No destinations available.", "empty"));
  for (const destination of inventory.destinations) {
    const row = element("div", undefined, "audio-row");
    row.append(element("strong", destination.name), element("span", destination.available ? "Online" : "Offline", "availability"));
    if (destination.pending || destination.playback_available === false) row.append(element("p", destination.message || "Connecting to the selected source…", "availability-note"));
    const sourceLabel = element("label", "Source");
    sourceLabel.hidden = !inventory.sources.some(source => source.status !== "disabled");
    const select = element("select");
    select.setAttribute("aria-label", `Source for ${destination.name}`);
    if (!inventory.sources.some(source => source.id === destination.source_id)) {
      const current = (inventory.all_sources || []).find(source => source.id === destination.source_id);
      const option = element("option", current ? `${current.name} (hidden)` : "No source available");
      option.value = destination.source_id || "";
      option.disabled = true;
      select.append(option);
    }
    for (const source of inventory.sources) {
      const option = element("option", source.node_name ? `${source.node_name} / ${source.name}` : source.name);
      option.value = source.id;
      option.disabled = source.status === "disabled";
      select.append(option);
    }
    select.value = destination.source_id || "";
    select.addEventListener("change", () => change(destination, "source", {source_id: select.value}));
    sourceLabel.append(select);
    const volumeLabel = element("label", "Volume");
    const volume = element("input");
    volume.type = "range";
    volume.min = "0";
    volume.max = "100";
    volume.value = String(destination.volume);
    volume.setAttribute("aria-label", `Volume for ${destination.name}`);
    const output = element("output", `${destination.volume}%`);
    volume.addEventListener("input", () => { output.textContent = `${volume.value}%`; });
    volume.addEventListener("change", () => change(destination, "volume", {percent: Number(volume.value)}));
    volumeLabel.append(volume, output);
    const mute = element("button", destination.muted ? "Unmute" : "Mute");
    mute.type = "button";
    mute.setAttribute("aria-label", `${destination.muted ? "Unmute" : "Mute"} ${destination.name}`);
    mute.setAttribute("aria-pressed", String(destination.muted));
    mute.addEventListener("click", () => change(destination, "volume", {muted: !destination.muted}));
    for (const control of [select, volume, mute]) control.dataset.offline = String(!destination.available);
    select.dataset.offline = String(!destination.available || !inventory.sources.some(source => source.status !== "disabled"));
    const controls = element("div", undefined, "destination-controls");
    controls.dataset.offline = String(!destination.available);
    controls.append(sourceLabel, volumeLabel, mute);
    if (sourceLabel.hidden) controls.append(element("p", "No sources available.", "availability-note"));
    const summary = element("p", undefined, "playback-summary");
    const sourceName = (inventory.all_sources || inventory.sources).find(source => source.id === destination.source_id)?.name || "No source available";
    summary.dataset.settings = `${sourceName} · Volume ${destination.volume}% · ${destination.muted ? "Muted" : "Unmuted"}`;
    summary.dataset.offline = String(!destination.available);
    const reason = element("p", undefined, "destination-reason");
    reason.dataset.offline = String(!destination.available);
    reason.dataset.message = destination.message || "This device is disconnected. Playback controls will return when it reconnects.";
    const renameDetails = element("details", undefined, "destination-rename");
    const draft = renameDrafts.get(destination.id);
    renameDetails.open = Boolean(draft?.open);
    const renameSummary = element("summary", "Rename");
    const renameForm = element("form");
    const nameLabel = element("label", "Destination name");
    const nameInput = element("input");
    nameInput.type = "text";
    nameInput.maxLength = 80;
    nameInput.required = true;
    nameInput.value = draft?.name ?? destination.name;
    nameInput.setAttribute("aria-label", `Name for ${destination.name}`);
    nameLabel.append(nameInput);
    nameInput.addEventListener("input", () => renameDrafts.set(destination.id, {name: nameInput.value, open: true}));
    renameDetails.addEventListener("toggle", () => {
      if (renameDetails.open) renameDrafts.set(destination.id, {name: nameInput.value, open: true});
      else if (renameDrafts.has(destination.id)) renameDrafts.get(destination.id).open = false;
    });
    const saveName = element("button", "Save name");
    saveName.type = "submit";
    const cancelName = element("button", "Cancel");
    cancelName.type = "button";
    cancelName.addEventListener("click", () => { renameDrafts.delete(destination.id); render(); });
    renameForm.addEventListener("submit", async event => {
      event.preventDefault();
      if (busy) return;
      busy = true;
      changeRevision += 1;
      updateDisabled();
      try {
        inventory = await request(`/api/destinations/${encodeURIComponent(destination.id)}/name`, {name: nameInput.value});
        renameDrafts.delete(destination.id);
        notice.textContent = "Name saved.";
      } catch (problem) { showError(problem.message); }
      finally { busy = false; render(); }
    });
    renameForm.append(nameLabel, saveName, cancelName);
    renameDetails.append(renameSummary, renameForm);
    row.append(controls, summary, reason, renameDetails);
    destinations.append(row);
  }
  updateDisabled();
}
async function change(destination, action, body) {
  if (busy) return;
  busy = true;
  changeRevision += 1;
  notice.textContent = "Saving…";
  updateDisabled();
  try {
    inventory = await request(`/api/destinations/${encodeURIComponent(destination.id)}/${action}`, body);
    error.hidden = true;
    retry.hidden = true;
    notice.textContent = inventory.destinations.some(row => row.pending) ? "Connecting to the selected source…" : "Saved.";
  } catch (problem) {
    notice.textContent = "";
    showError(problem.message || "The change could not be confirmed. Refresh before trying again.");
    // Observe the server again, including partial changes or concurrent edits.
    try { inventory = await request("/api/audio"); }
    catch (_) { online = false; connection.textContent = "Audio unavailable"; connection.className = "offline"; }
  } finally {
    busy = false;
    render();
  }
}
async function refresh() {
  if (busy || polling) return;
  polling = true;
  const revision = changeRevision;
  try {
    const observedAuth = await request("/api/auth");
    if (busy || revision !== changeRevision) return;
    authentication = observedAuth;
    if (!authentication.authenticated) { location.replace("/sign-in"); return; }
    const node = await request("/api/node");
    document.getElementById("node-name").textContent = node.name;
    if (!nodeNameDirty) document.getElementById("node-name-input").value = node.name;
    document.getElementById("version").textContent = node.version;
    const observed = await request("/api/audio");
    if (busy || revision !== changeRevision) return;
    const sourceAvailabilityChanged = JSON.stringify(observed.sources) !== JSON.stringify(inventory.sources);
    const availabilityChanged = sourceAvailabilityChanged || observed.destinations.length !== inventory.destinations.length ||
      observed.destinations.some(destination => inventory.destinations.find(old => old.id === destination.id)?.available !== destination.available);
    inventory = observed;
    if (typeof updateSceneDestinations === 'function' && document.getElementById('scenes').open && !sceneBusy) updateSceneDestinations(observed, true);
    online = observed.audio_available !== false;
    connection.textContent = online ? "Audio connected" : "Audio unavailable";
    connection.className = online ? "online" : "offline";
    error.hidden = true;
    retry.hidden = true;
    if (availabilityChanged || !destinations.contains(document.activeElement)) render();
  } catch (problem) {
    if (busy || revision !== changeRevision) return;
    online = false;
    connection.textContent = "Audio unavailable";
    connection.className = "offline";
    document.getElementById("source-count").textContent = "—";
    document.getElementById("destination-count").textContent = "—";
    const message = problem.message === "Failed to fetch" ? "Cannot reach this device. Check its connection and try again." : problem.message;
    showError(message + (inventory.destinations.length ? " Displayed settings may be out of date." : ""));
  } finally {
    polling = false;
    updateDisabled();
  }
}
document.getElementById("node-name-input").addEventListener("input", () => { nodeNameDirty = true; });
document.getElementById("node-settings-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (busy) return;
  busy = true;
  changeRevision += 1;
  updateDisabled();
  try {
    const saved = await request("/api/settings", {name: document.getElementById("node-name-input").value});
    document.getElementById("node-name").textContent = saved.name;
    document.getElementById("node-name-input").value = saved.name;
    nodeNameDirty = false;
    notice.textContent = "Node name saved.";
  } catch (problem) { showError(problem.message); }
  finally { busy = false; updateDisabled(); }
});
async function refreshDiagnostics() {
  if (diagnosticsBusy) return;
  diagnosticsBusy = true;
  const button = document.getElementById("refresh-diagnostics");
  const content = document.getElementById("diagnostics-content");
  button.disabled = true;
  content.replaceChildren(element("p", "Checking this node…"));
  try {
    const report = await request("/api/diagnostics");
    content.replaceChildren(element("p", `${report.node.name} · ${report.node.version} · ${report.node.build}`));
    if (report.node.identity) content.append(element("p", `Identity: ${report.node.identity}`));
    content.append(element("p", `Audio endpoint: ${report.audio_endpoint}`));
    for (const check of report.checks) content.append(element("p", `${check.name}: ${check.detail}`));
    for (const service of report.services) {
      const state = service.unit === "flowharmonic-audio.service" && service.state === "inactive" && service.result === "success" ?
        "Waiting for the next check" : service.state;
      content.append(element("p", `${service.name}: ${state}. ${service.detail || ""}`));
    }
  } catch (problem) { content.replaceChildren(element("p", problem.message)); }
  finally { diagnosticsBusy = false; button.disabled = false; }
}
document.getElementById("diagnostics").addEventListener("toggle", () => {
  if (document.getElementById("diagnostics").open) refreshDiagnostics();
});
document.getElementById("refresh-diagnostics").addEventListener("click", refreshDiagnostics);
document.getElementById("sign-out").addEventListener("click", async () => {
  if (busy) return;
  busy = true;
  changeRevision += 1;
  updateDisabled();
  try {
    authentication = await request("/api/auth/sign-out", {});
    location.replace("/sign-in");
    notice.textContent = "";
  } catch (problem) { showError(problem.message); }
  finally { busy = false; updateDisabled(); }
});
retry.addEventListener("click", refresh);
refresh();
setInterval(refresh, 5000);
