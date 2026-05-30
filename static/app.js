// ---------- Editor state ----------
let speakerCount = PROMPT_DATA.speakers || 3;
let speakerImages = {};
let originalImages = {};
let bgRemoving = {};
let logoBase64 = null;

// ---------- Quick‑fill sample data ----------
window.fillSampleData = function() {
  document.getElementById('f-church-name').value = 'Living Chapel Manchester';
  document.getElementById('f-social').value = '@livingchapel';
  document.getElementById('f-theme').value = 'FAITHFUL GOD';
  document.getElementById('f-title').value = PROMPT_DATA.name || 'Sunday Worship Experience';
  document.getElementById('f-date').value = 'Sunday 25th October 2025';
  document.getElementById('f-time').value = '10:00 AM – 1:00 PM';
  document.getElementById('f-venue').value = '123 Church Street, Manchester';
  const host = document.getElementById('f-host');
  if (host) host.value = 'Pst. Ejembi Pius';
  // Fill speaker names if present
  for (let i = 0; i < speakerCount; i++) {
    const nameInput = document.getElementById(`speaker-name-${i}`);
    if (nameInput) nameInput.value = `Speaker ${i+1}`;
  }
};

// ---------- People Grid ----------
function renderPeopleGrid() {
  const grid = document.getElementById('people-grid');
  grid.innerHTML = '';
  for (let i = 0; i < speakerCount; i++) {
    const slot = document.createElement('div');
    slot.className = 'person-slot';
    slot.innerHTML = `
      <input type="file" id="person-file-${i}" accept="image/*" onchange="handlePersonUpload(${i}, this)">
      <div class="slot-icon">👤</div>
      <div class="slot-label">Speaker ${i+1}<br><span style="font-size:0.65rem">Click to upload</span></div>
      <div class="slot-overlay">Change photo</div>
    `;
    if (speakerImages[i]) {
      const img = document.createElement('img');
      img.src = speakerImages[i];
      img.onerror = () => { img.style.opacity = '0.2'; img.style.filter = 'grayscale(100%)'; };
      slot.insertBefore(img, slot.firstChild);
      const btn = document.createElement('div');
      btn.className = 'remove-bg-btn';
      btn.title = 'Remove background';
      btn.innerHTML = '✂️';
      btn.onclick = e => { e.stopPropagation(); handleRemoveBackground(i); };
      if (bgRemoving[i]) { btn.classList.add('working'); btn.innerHTML = '⏳'; }
      else if (originalImages[i] && speakerImages[i] !== originalImages[i]) {
        btn.classList.add('done'); btn.innerHTML = '✅';
      }
      slot.appendChild(btn);
    }
    slot.addEventListener('click', () => {
      if (!bgRemoving[i]) document.getElementById(`person-file-${i}`).click();
    });
    grid.appendChild(slot);
  }
}

// ---------- Speaker upload ----------
function handlePersonUpload(index, input) {
  if (!input.files[0]) return;
  const reader = new FileReader();
  reader.onload = e => {
    speakerImages[index] = e.target.result;
    originalImages[index] = e.target.result;
    bgRemoving[index] = false;
    renderPeopleGrid();
  };
  reader.readAsDataURL(input.files[0]);
}

function handleLogoUpload(input) {
  if (!input.files[0]) return;
  document.getElementById('logo-filename').textContent = input.files[0].name;
  const reader = new FileReader();
  reader.onload = e => { logoBase64 = e.target.result; };
  reader.readAsDataURL(input.files[0]);
}

// ---------- Background removal (via Flask proxy) ----------
async function handleRemoveBackground(index) {
  if (bgRemoving[index]) return;
  if (!speakerImages[index]) return;
  bgRemoving[index] = true;
  renderPeopleGrid();
  try {
    const res = await fetch('/api/remove-bg', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image: speakerImages[index] })
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    if (data.image) {
      speakerImages[index] = data.image;
      bgRemoving[index] = false;
      renderPeopleGrid();
    } else {
      throw new Error(data.error || 'Unknown error');
    }
  } catch (err) {
    alert('Background removal failed: ' + err.message);
    bgRemoving[index] = false;
    renderPeopleGrid();
  }
}

// ---------- Speaker names ----------
function renderSpeakerNames() {
  const area = document.getElementById('speaker-names-area');
  area.innerHTML = '';
  for (let i = 0; i < speakerCount; i++) {
    const row = document.createElement('div');
    row.className = 'field';
    row.innerHTML = `<label>Speaker ${i+1} Name & Title</label>
      <input type="text" id="speaker-name-${i}" placeholder="e.g. Pst. Emmanuel Okafor">`;
    area.appendChild(row);
  }
}

// ---------- Change speaker count ----------
function changeCount(delta) {
  speakerCount = Math.max(1, Math.min(5, speakerCount + delta));
  document.getElementById('count-display').textContent = speakerCount;
  renderPeopleGrid();
  renderSpeakerNames();
}

// ---------- Build prompt (using template from PROMPT_DATA) ----------
function buildPrompt() {
  const church = document.getElementById('f-church-name').value || 'Your Church';
  const eventTitle = document.getElementById('f-title').value || PROMPT_DATA.name;
  const date = document.getElementById('f-date').value || 'Date TBD';
  const time = document.getElementById('f-time').value || 'Time TBD';
  const venue = document.getElementById('f-venue').value || 'Your Venue';
  const theme = document.getElementById('f-theme').value || '';
  const host = document.getElementById('f-host')?.value || '';
  const social = document.getElementById('f-social').value || '';

  // Build speaker section with URLs
  let speakerSection = 'Use placeholder silhouettes.';
  const speakerUrls = [];
  for (let i = 0; i < speakerCount; i++) {
    if (speakerImages[i] && speakerImages[i].startsWith('http')) {
      speakerUrls.push(speakerImages[i]);
    }
  }
  if (speakerUrls.length > 0) {
    speakerSection = speakerUrls.map((url, i) => `Speaker ${i+1}: ${url}`).join('\n');
  }

  // Replace placeholders in prompt template
  let prompt = PROMPT_DATA.prompt_template
    .replace(/{church_name}/g, church)
    .replace(/{event_title}/g, eventTitle)
    .replace(/{date}/g, date)
    .replace(/{time}/g, time)
    .replace(/{venue}/g, venue)
    .replace(/{theme}/g, theme)
    .replace(/{host}/g, host)
    .replace(/{social}/g, social)
    .replace(/{speakers_section}/g, speakerSection);

  return prompt;
}

// ---------- Generate (via Flask proxy) ----------
async function handleGenerate() {
  const promptText = buildPrompt();
  const ratio = document.getElementById('f-ratio').value;
  const res = document.getElementById('f-res').value;

  document.getElementById('editor-panel').style.display = 'none';
  document.getElementById('result-area').style.display = 'block';
  const statusBar = document.getElementById('status-bar');
  const statusText = document.getElementById('status-text');
  const resultImg = document.getElementById('result-img');
  const downloadActions = document.getElementById('download-actions');
  statusBar.className = 'status-bar';
  statusText.textContent = 'Generating...';
  resultImg.style.display = 'none';
  downloadActions.style.display = 'none';

  try {
    const resp = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: promptText, ratio, resolution: res })
    });
    const data = await resp.json();
    if (data.image) {
      resultImg.src = data.image;
      resultImg.style.display = 'block';
      document.getElementById('download-link').href = data.image;
      downloadActions.style.display = 'flex';
      statusBar.className = 'status-bar done';
      statusText.textContent = 'Flyer generated!';
    } else {
      throw new Error(data.error || 'Unknown error');
    }
  } catch (err) {
    statusBar.className = 'status-bar error';
    statusText.textContent = err.message;
  }
}

// ---------- Reset views ----------
function resetToEditor() {
  document.getElementById('result-area').style.display = 'none';
  document.getElementById('editor-panel').style.display = 'block';
}

// ---------- Init ----------
document.addEventListener('DOMContentLoaded', () => {
  renderPeopleGrid();
  renderSpeakerNames();
});
