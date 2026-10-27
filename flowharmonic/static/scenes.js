"use strict";
let sceneBusy = false;
let sceneAvailability = "";
async function refreshScenes() {
  if (sceneBusy) return;
  sceneBusy = true;
  const message = document.getElementById('scene-message');
  const form = document.getElementById('scene-form');
  try {
    const data = await request('/api/scenes');
    form.hidden = !data.manageable;
    message.textContent = data.message;
    const list = document.getElementById('scene-list');
    list.replaceChildren();
    if (data.manageable && !data.scenes.length) list.append(element('p', 'No scenes saved.'));
    for (const scene of data.scenes) {
      const row = element('div', undefined, 'audio-row');
      row.append(element('strong', scene.name), element('p', scene.destinations.map(d => d.name).join(', ')));
      const apply = element('button', 'Apply');
      apply.type = 'button';
      apply.setAttribute('aria-label', `Apply scene ${scene.name}`);
      apply.addEventListener('click', () => sceneAction(`/api/scenes/${scene.id}/apply`));
      const remove = element('button', 'Remove');
      remove.type = 'button';
      remove.setAttribute('aria-label', `Remove scene ${scene.name}`);
      remove.addEventListener('click', () => {
        if (confirm(`Remove scene “${scene.name}”?`)) sceneAction(`/api/scenes/${scene.id}/remove`);
      });
      row.append(apply, remove);
      list.append(row);
    }
    updateSceneDestinations(await request('/api/audio'));
  } catch (problem) { message.textContent = problem.message; }
  finally { sceneBusy = false; }
}
function updateSceneDestinations(audio, preserve = false) {
  const signature = JSON.stringify(audio.destinations.map(d => [d.id, d.name, d.available, d.pending, d.playback_available, Boolean(d.source_id)]));
  if (preserve && signature === sceneAvailability) return;
  sceneAvailability = signature;
  const choices = document.getElementById('scene-destinations');
  const previous = new Map(Array.from(choices.querySelectorAll('input')).map(input => [input.value, input]));
  choices.replaceChildren();
  for (const destination of audio.destinations) {
    const available = Boolean(destination.available && !destination.pending && destination.playback_available !== false && destination.source_id);
    const old = previous.get(destination.id);
    const label = element('label');
    const input = element('input');
    input.type = 'checkbox';
    input.value = destination.id;
    input.checked = available && (preserve && old && !old.disabled ? old.checked : true);
    input.disabled = !available;
    label.append(input, element('span', destination.name + (available ? '' : ' (unavailable)')));
    choices.append(label);
  }
}
async function sceneAction(url, body = {}) {
  if (sceneBusy || busy) return;
  sceneBusy = true;
  busy = true;
  changeRevision += 1;
  updateDisabled();
  document.getElementById('scenes').querySelectorAll('button').forEach(button => { button.disabled = true; });
  let resultMessage;
  try {
    const data = await request(url, body);
    resultMessage = data.results ? data.results.map(row => `${row.name}: ${row.applied ? 'Settings requested.' : row.message}`).join(' ') : 'Scene saved.';
    if (url.endsWith('/remove')) resultMessage = 'Scene removed.';
  } catch (problem) { resultMessage = problem.message; }
  finally {
    sceneBusy = false;
    busy = false;
    document.getElementById('scenes').querySelectorAll('button').forEach(button => { button.disabled = false; });
    await refresh();
    await refreshScenes();
    document.getElementById('scene-message').textContent = resultMessage;
  }
}
document.getElementById('scenes').addEventListener('toggle', () => {
  if (document.getElementById('scenes').open) refreshScenes();
});
document.getElementById('refresh-scenes').addEventListener('click', refreshScenes);
document.getElementById('scene-form').addEventListener('submit', event => {
  event.preventDefault();
  const selected = Array.from(document.getElementById('scene-destinations').querySelectorAll('input')).filter(input => input.checked).map(input => input.value);
  if (!selected.length) { document.getElementById('scene-message').textContent = 'Select at least one connected destination.'; return; }
  sceneAction('/api/scenes', {name: document.getElementById('scene-name').value, destinations: selected});
});
