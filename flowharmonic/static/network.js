"use strict";
const networkPanel = document.getElementById("network-settings");
const networkContent = document.getElementById("network-content");
const networkMessage = document.getElementById("network-message");
let networkBusy = false;
let networkPolling = false;
let networkState = null;
let networkSignature = "";

function networkButton(parent, label, action) {
  const button = element("button", label);
  button.type = "button";
  button.addEventListener("click", action);
  parent.append(button);
  return button;
}
function verifiedButton(parent, label, action) {
  const checkLabel = element("label");
  const check = element("input");
  check.type = "checkbox";
  checkLabel.append(check, element("span", "I checked that this code matches the other device’s dashboard."));
  parent.append(checkLabel);
  const button = networkButton(parent, label, action);
  button.disabled = true;
  check.addEventListener("change", () => { button.disabled = !check.checked || networkBusy; });
}
function renderNetwork(state) {
  if (state.message) networkMessage.textContent = state.message;
  networkState = state;
  const signature = JSON.stringify(state);
  if (signature === networkSignature) return;
  networkSignature = signature;
  networkContent.replaceChildren();
  const member = state.membership;
  const outbound = state.pending.some(pending => pending.direction === "out");
  document.getElementById("create-system-form").hidden = Boolean(member) || outbound;
  document.getElementById("join-system-form").hidden = Boolean(member) || outbound;
  if (member) {
    networkContent.append(element("p", `${member.name} · ${state.is_host ? "System host" : "Joined"}`));
    networkContent.append(element("p", state.is_host ? "This node coordinates system audio. Sources and destinations from joined nodes appear above." : "Audio changes on this node go through the coordinator. Existing playback continues if its web service is unavailable."));
    if (state.is_host) {
      networkContent.append(element("p", state.accepting ? "Join requests are allowed for up to 10 minutes. Each request still needs approval." : "Join requests are closed."));
      networkButton(networkContent, state.accepting ? "Close join requests" : "Allow join requests", () => networkChange("allow", {enabled: !state.accepting}));
      for (const peer of state.peers) {
        const row = element("div", undefined, "audio-row");
        row.append(element("strong", peer.name), element("p", `Node: ${peer.identity}`));
        networkButton(row, "Remove member", () => {
          if (window.confirm(`Remove ${peer.name} from this system? Its local audio will continue.`)) networkChange(`remove/${encodeURIComponent(peer.identity)}`, {});
        });
        networkContent.append(row);
      }
      if (!state.peers.length) networkContent.append(element("p", "No other nodes have joined yet."));
    }
    networkButton(networkContent, state.is_host ? "Dissolve system" : "Leave system", () => {
      if (window.confirm(state.is_host ? "Dissolve this system and revoke all memberships? Coordinated routes end; standalone audio settings are retained." : "Leave this system? Coordinated routes end; standalone audio settings are retained.")) networkChange("leave", {});
    });
  } else networkContent.append(element("p", "This node is independent. Create a system here, or request to join a nearby system."));
  for (const pending of state.pending) {
    const row = element("div", undefined, "audio-row");
    const incoming = pending.direction === "in";
    row.append(element("strong", incoming ? `${pending.name} wants to join` : `Join ${pending.system_name}`));
    row.append(element("p", `Verification code: ${pending.code}`));
    row.append(element("p", "Compare this code on both devices. Approve only if every group matches. Requests expire after 10 minutes."));
    if (incoming) {
      if (pending.status === "pending") verifiedButton(row, "Approve request", () => networkChange(`requests/${encodeURIComponent(pending.id)}`, {approve: true}));
      else row.append(element("p", pending.status === "approved" ? "Approved here. Confirm the matching code on the joining device to finish." : "Request rejected."));
      if (pending.status !== "rejected") networkButton(row, "Reject request", () => networkChange(`requests/${encodeURIComponent(pending.id)}`, {approve: false}));
    } else {
      if (pending.status === "approved") verifiedButton(row, "Confirm and join", () => networkChange("confirm", {}));
      else row.append(element("p", pending.status === "rejected" ? "The system host rejected this request." : "Open the system host’s dashboard and approve the matching request, then refresh here."));
      networkButton(row, "Cancel request", () => networkChange("cancel", {}));
    }
    networkContent.append(row);
  }
  const nearby = document.getElementById("nearby-nodes");
  nearby.replaceChildren(element("p", state.discovery?.message || ""));
  const nodes = state.discovery?.nodes || [];
  const suggestions = nodes.filter(node => node.is_host && (!member || node.system_id !== member.id));
  document.getElementById("network-summary").textContent = !member && suggestions.length ? "Connections · Nearby system available" : "Connections";
  if (!nodes.length) nearby.append(element("p", "No nearby nodes found. Both devices must be on the same LAN, with discovery allowed by the network. You can also connect using an address."));
  for (const node of nodes) {
    const row = element("div", undefined, "audio-row");
    row.append(element("strong", node.name), element("p", node.system_name ? `${node.system_name} · ${node.is_host ? "System host" : "Member"}` : "Independent node"));
    if (node.is_host && !member && !outbound) {
      row.append(element("p", node.accepting ? "Available to request joining. Approval is required on both devices." : "On that device, allow join requests before requesting to join."));
      networkButton(row, "Request to join", () => networkChange("join", {url: node.url, identity: node.identity}));
    }
    nearby.append(row);
  }
}
async function refreshNetwork(sync = false) {
  if (networkBusy || networkPolling) return;
  networkPolling = true;
  try {
    if (sync && networkState && (networkState.pending.some(item => item.direction === "out") || networkState.membership && !networkState.is_host)) {
      const result = await request("/api/network/sync", {});
      if (result.message) networkMessage.textContent = result.message;
    }
    renderNetwork(await request("/api/network"));
  } catch (problem) { networkMessage.textContent = problem.message; }
  finally { networkPolling = false; }
}
async function networkChange(action, body) {
  if (networkBusy || networkPolling) return;
  networkBusy = true;
  networkPanel.querySelectorAll("button").forEach(button => { button.disabled = true; });
  try {
    const result = await request(`/api/network/${action}`, body);
    networkMessage.textContent = result.message || "Saved.";
  } catch (problem) { networkMessage.textContent = problem.message; }
  finally {
    networkBusy = false;
    networkSignature = "";
    networkPanel.querySelectorAll("button").forEach(button => { button.disabled = false; });
    await refreshNetwork();
  }
}
document.getElementById("create-system-form").addEventListener("submit", event => {
  event.preventDefault();
  networkChange("create", {name: document.getElementById("system-name-input").value});
});
document.getElementById("join-system-form").addEventListener("submit", event => {
  event.preventDefault();
  networkChange("join", {url: document.getElementById("system-address-input").value});
});
networkPanel.addEventListener("toggle", () => { if (networkPanel.open) refreshNetwork(true); });
document.getElementById("refresh-network").addEventListener("click", () => refreshNetwork(true));
refreshNetwork();
setInterval(() => { refreshNetwork(networkPanel.open); }, 5000);
