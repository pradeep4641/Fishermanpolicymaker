/* ═══════════════════════════════════════════════════════════
   OCEANIX — script.js
   Vanilla JS — no framework, no build step.
   fetch() → DOM updates → Leaflet/Chart.js rendering.
═══════════════════════════════════════════════════════════ */

const API = '';   // same origin — FastAPI serves this file

/* ══════════════════════════════════════════════════
   UTILITIES
══════════════════════════════════════════════════ */
const $ = id => document.getElementById(id);

function region() { return $('globalRegion').value; }
function lang()   { return $('langSelect').value; }

function fmt(v, decimals = 1) {
  if (v === null || v === undefined) return 'N/A';
  if (typeof v === 'number') return v.toFixed(decimals);
  return v;
}

function deltaCls(v) {
  if (v === null || v === undefined) return '';
  return v >= 0 ? 'positive' : 'negative';
}

function showSpinner(el) {
  el.innerHTML = '<div class="spinner"></div>';
}

async function apiFetch(path, opts = {}) {
  try {
    const r = await fetch(API + path, opts);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } catch (e) {
    console.error('API error', path, e);
    return null;
  }
}

/* ══════════════════════════════════════════════════
   HEALTH CHECK & STATUS DOT
══════════════════════════════════════════════════ */
async function checkHealth() {
  const d = await apiFetch('/api/health');
  const dot = $('statusDot');
  dot.classList.toggle('ok',  !!d);
  dot.classList.toggle('err', !d);
  dot.title = d ? 'API online ✓' : 'API offline ✗';
}

/* ══════════════════════════════════════════════════
   TAB NAVIGATION
══════════════════════════════════════════════════ */
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    $(`tab-${btn.dataset.tab}`).classList.add('active');
    // Lazy-load tab content on first visit
    if (btn.dataset.tab === 'policy' && !policyLoaded)   loadPolicy();
    if (btn.dataset.tab === 'species' && !speciesLoaded) loadSpecies();
    if (btn.dataset.tab === 'compare')                   initCompareDates();
  });
});

/* ══════════════════════════════════════════════════
   LEAFLET MAP
══════════════════════════════════════════════════ */
const regionCenters = {
  bay_of_bengal:   [13.0, 87.5],
  arabian_sea:     [15.0, 66.0],
  andaman_sea:     [11.0, 96.0],
  lakshadweep_sea: [11.0, 73.0],
};

const map = L.map('map').setView([13.0, 87.5], 5);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap contributors',
  maxZoom: 18,
}).addTo(map);

let sightingLayer = L.layerGroup().addTo(map);
let annotateLayer = L.layerGroup().addTo(map);
let annotateMode  = false;
let pendingLatLng = null;

// Colourful circle marker for sightings
function sightingMarker(lat, lon, species, date_) {
  const hue = Math.abs((species.charCodeAt(0) * 37 + species.charCodeAt(1) * 13) % 360);
  const m = L.circleMarker([lat, lon], {
    radius: 6,
    fillColor: `hsl(${hue},65%,50%)`,
    color: '#fff',
    weight: 1.5,
    fillOpacity: 0.85,
  });
  m.bindPopup(`<b>${species}</b><br/><small>${date_ || 'date unknown'}</small>`);
  return m;
}

async function loadSightings() {
  sightingLayer.clearLayers();
  const reg = region();
  const center = regionCenters[reg] || [13, 87.5];
  map.setView(center, 5);

  const data = await apiFetch(`/api/sightings?region=${reg}`);
  if (!data || !data.results) return;

  data.results.forEach(s => {
    sightingLayer.addLayer(sightingMarker(s.lat, s.lon, s.scientificName, s.date));
  });
}

// ── Map Annotations (localStorage) ──────────────────
const ANN_KEY = 'oceanix_annotations';

function loadAnnotations() {
  annotateLayer.clearLayers();
  const stored = JSON.parse(localStorage.getItem(ANN_KEY) || '[]');
  stored.forEach(a => addAnnotationMarker(a.lat, a.lng, a.note));
}

function saveAnnotation(lat, lng, note) {
  const stored = JSON.parse(localStorage.getItem(ANN_KEY) || '[]');
  stored.push({ lat, lng, note, ts: new Date().toISOString() });
  localStorage.setItem(ANN_KEY, JSON.stringify(stored));
}

function addAnnotationMarker(lat, lng, note) {
  const pin = L.marker([lat, lng], {
    icon: L.divIcon({ className: '', html: '📍', iconSize: [24, 24] }),
  });
  pin.bindPopup(`<b>📍 Note</b><br/>${note}<br/><small class="device-note">Saved on this device only</small>`,
    { className: 'annotation-popup' });
  annotateLayer.addLayer(pin);
}

map.on('click', e => {
  if (!annotateMode) return;
  pendingLatLng = e.latlng;
  $('annotateText').value = '';
  $('annotateModal').classList.remove('hidden');
  $('modalOverlay').classList.remove('hidden');
});

$('btnAnnotate').addEventListener('click', () => {
  annotateMode = !annotateMode;
  $('btnAnnotate').textContent = annotateMode ? '✅ Click map' : '📍 Annotate';
  $('btnAnnotate').style.background = annotateMode ? '#e3f2fd' : '';
  map.getContainer().style.cursor = annotateMode ? 'crosshair' : '';
});

$('btnClearAnnotations').addEventListener('click', () => {
  if (!confirm('Clear all saved map notes?')) return;
  localStorage.removeItem(ANN_KEY);
  annotateLayer.clearLayers();
});

$('btnSaveAnnotation').addEventListener('click', () => {
  const note = $('annotateText').value.trim();
  if (!note || !pendingLatLng) return;
  saveAnnotation(pendingLatLng.lat, pendingLatLng.lng, note);
  addAnnotationMarker(pendingLatLng.lat, pendingLatLng.lng, note);
  closeModal();
  annotateMode = false;
  $('btnAnnotate').textContent = '📍 Annotate';
  map.getContainer().style.cursor = '';
});

$('btnCancelAnnotation').addEventListener('click', closeModal);
$('modalOverlay').addEventListener('click', closeModal);

function closeModal() {
  $('annotateModal').classList.add('hidden');
  $('modalOverlay').classList.add('hidden');
}

/* ══════════════════════════════════════════════════
   KPI CARDS
══════════════════════════════════════════════════ */
async function loadKPIs() {
  const reg = region();

  // Health index
  const hi = await apiFetch(`/api/health-index?region=${reg}`);
  if (hi) {
    $('kpiHealth').textContent      = hi.score ?? '—';
    $('kpiGrade').textContent       = hi.grade ?? '';
    $('kpiSpecies').textContent     = hi.recent_summary?.species_count ?? '—';
    $('kpiOccurrences').textContent = hi.recent_summary?.occurrence_count ?? '—';
    if (hi.env_avg_sst !== undefined) $('kpiSST').textContent = hi.env_avg_sst + '°C';
  }

  // Anomaly count
  const anom = await apiFetch(`/api/anomalies?region=${reg}`);
  if (anom) {
    $('kpiAnomalies').textContent = anom.flagged_count ?? 0;
  }
}

/* ══════════════════════════════════════════════════
   TREND CHART (Chart.js)
══════════════════════════════════════════════════ */
let trendChart = null;

async function loadTrendChart() {
  const reg    = region();
  const metric = $('metricSelect').value;
  const data   = await apiFetch(`/api/timeseries?region=${reg}&metric=${metric}`);
  if (!data || !data.data) return;

  const labels = data.data.map(d => d.year);
  const values = data.data.map(d => d.value);

  const metricLabels = {
    species_count:    'Species Count',
    occurrence_count: 'Occurrences',
    avg_sst:          'Avg SST (°C)',
  };

  const ctx = $('trendChart').getContext('2d');
  if (trendChart) trendChart.destroy();

  trendChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: metricLabels[metric] || metric,
        data: values,
        borderColor: '#1565C0',
        backgroundColor: 'rgba(21,101,192,0.10)',
        borderWidth: 2.5,
        pointRadius: 4,
        pointHoverRadius: 6,
        fill: true,
        tension: 0.3,
      }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: { mode: 'index', intersect: false },
      },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: false, grid: { color: '#E3F2FD' } },
      },
    },
  });
}

$('metricSelect').addEventListener('change', loadTrendChart);

/* ══════════════════════════════════════════════════
   ENVIRONMENTAL CARDS
══════════════════════════════════════════════════ */
async function loadEnvData() {
  const reg = region();
  const end   = new Date().toISOString().slice(0,10);
  const start = new Date(Date.now() - 30*24*3600*1000).toISOString().slice(0,10);

  const data = await apiFetch(`/api/environmental?region=${reg}&start_date=${start}&end_date=${end}`);
  const container = $('envCards');

  if (!data || !data.data || data.data.length === 0) {
    container.innerHTML = '<p style="color:var(--text-muted)">No environmental data available.</p>';
    return;
  }

  // Show last available day's snapshot
  const recent = data.data.filter(d => Object.values(d).some(v => v !== null)).slice(-1)[0];
  if (!recent) { container.innerHTML = '<p>No recent data.</p>'; return; }

  const fields = [
    { key: 'sst',                    label: 'Sea Surface Temp', unit: '°C' },
    { key: 'wave_height',            label: 'Wave Height',      unit: 'm'  },
    { key: 'wave_period',            label: 'Wave Period',      unit: 's'  },
    { key: 'swell_wave_height',      label: 'Swell Height',     unit: 'm'  },
    { key: 'ocean_current_velocity', label: 'Current Speed',    unit: 'm/s'},
  ];

  container.innerHTML = fields.map(f => {
    const val = recent[f.key];
    const display = val !== null && val !== undefined ? `${Number(val).toFixed(1)} ${f.unit}` : 'N/A';
    return `<div class="env-card">
      <div class="env-val">${display}</div>
      <div class="env-lbl">${f.label}</div>
      <div class="env-date">${recent.date || ''}</div>
    </div>`;
  }).join('');
}

/* ══════════════════════════════════════════════════
   SPECIES EXPLORER
══════════════════════════════════════════════════ */
let speciesLoaded = false;

async function loadSpecies(q = '') {
  speciesLoaded = true;
  const grid = $('speciesGrid');
  showSpinner(grid);
  const reg  = region();
  const url  = `/api/species?region=${reg}${q ? `&q=${encodeURIComponent(q)}` : ''}`;
  const data = await apiFetch(url);

  if (!data || !data.results || data.results.length === 0) {
    grid.innerHTML = '<p style="color:var(--text-muted);padding:20px">No species found.</p>';
    return;
  }

  function iucnClass(cat) {
    const map = { CR:'CR', EN:'EN', VU:'VU', NT:'NT', LC:'LC', DD:'DD' };
    return map[cat] || 'Unknown';
  }

  grid.innerHTML = data.results.map(s => `
    <div class="species-card">
      <div class="sp-sci">${s.scientificName || '—'}</div>
      <div class="sp-vern">${s.vernacularName || 'No common name'}</div>
      <div class="sp-tax">${[s.class, s.phylum].filter(Boolean).join(' · ')}</div>
      <span class="iucn-badge iucn-${iucnClass(s.iucnCategory)}">
        IUCN: ${s.iucnCategory || 'Unknown'}
      </span>
    </div>`).join('');
}

$('btnSpeciesSearch').addEventListener('click', () => {
  loadSpecies($('speciesSearch').value.trim());
});
$('speciesSearch').addEventListener('keydown', e => {
  if (e.key === 'Enter') loadSpecies($('speciesSearch').value.trim());
});

/* ══════════════════════════════════════════════════
   COMPARE TAB
══════════════════════════════════════════════════ */
function initCompareDates() {
  const today  = new Date();
  const y6 = new Date(today); y6.setFullYear(today.getFullYear() - 6);
  const y3 = new Date(today); y3.setFullYear(today.getFullYear() - 3);
  const iso = d => d.toISOString().slice(0, 10);
  $('periodAStart').value = iso(y6);
  $('periodAEnd').value   = iso(y3);
  $('periodBStart').value = iso(y3);
  $('periodBEnd').value   = iso(today);
}

$('compareMode').addEventListener('change', () => {
  const mode = $('compareMode').value;
  $('periodControls').style.display = mode === 'period' ? '' : 'none';
  $('regionControls').style.display = mode === 'region' ? '' : 'none';
});

$('btnCompare').addEventListener('click', async () => {
  const reg   = region();
  const mode  = $('compareMode').value;
  const box   = $('compareResults');
  showSpinner(box);
  box.style.display = 'block';

  let url = `/api/compare?region_a=${reg}`;
  if (mode === 'period') {
    const pA = `${$('periodAStart').value}:${$('periodAEnd').value}`;
    const pB = `${$('periodBStart').value}:${$('periodBEnd').value}`;
    url += `&period_a=${pA}&period_b=${pB}`;
  } else {
    const regB = $('regionB').value;
    url += `&region_b=${regB}`;
  }

  const data = await apiFetch(url);
  if (!data) { box.innerHTML = '<p>Failed to load comparison.</p>'; return; }

  const label = mode === 'period'
    ? `Period A: ${data.label_a} vs Period B: ${data.label_b}`
    : `${data.label_a} vs ${data.label_b}`;

  const rows = [
    ['Species Count',    data.period_a?.species_count,    data.period_b?.species_count,    data.delta?.species_count,    data.pct_change?.species_count],
    ['Occurrences',      data.period_a?.occurrence_count, data.period_b?.occurrence_count, data.delta?.occurrence_count, data.pct_change?.occurrence_count],
    ['Avg SST (°C)',     data.period_a?.avg_sst,          data.period_b?.avg_sst,          data.delta?.avg_sst,          data.pct_change?.avg_sst],
  ];

  box.innerHTML = `
    <h3 style="margin-bottom:12px;color:var(--text)">${label}</h3>
    <table class="compare-table">
      <thead><tr><th>Metric</th><th>${data.label_a}</th><th>${data.label_b}</th><th>Delta</th><th>% Change</th></tr></thead>
      <tbody>
        ${rows.map(([metric, va, vb, d, pct]) => `
          <tr>
            <td>${metric}</td>
            <td>${fmt(va, 1)}</td>
            <td>${fmt(vb, 1)}</td>
            <td class="${deltaCls(d)}">${d !== null && d !== undefined ? (d >= 0 ? '+' : '') + fmt(d, 1) : 'N/A'}</td>
            <td class="${deltaCls(pct)}">${pct !== null && pct !== undefined ? (pct >= 0 ? '+' : '') + fmt(pct, 1) + '%' : 'N/A'}</td>
          </tr>`).join('')}
      </tbody>
    </table>`;
});

/* ── What-If Projection ─────────────────────────── */
$('severity').addEventListener('input', () => {
  $('severityLabel').textContent = $('severity').value + '%';
});

$('btnWhatIf').addEventListener('click', async () => {
  const body = {
    region:        region(),
    stressor_type: $('stressorType').value,
    severity:      parseInt($('severity').value) / 100,
    target_year:   parseInt($('targetYear').value),
  };
  const result = $('whatIfResult');
  result.style.display = 'block';
  result.innerHTML = '<div class="spinner"></div>';

  const data = await apiFetch('/api/what-if', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!data || data.error) {
    result.innerHTML = `<p style="color:var(--danger)">${data?.error || 'Projection failed.'}</p>`;
    return;
  }

  result.innerHTML = `
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:12px">
      <div><b>Current Species</b><br/>${data.current_species_count}</div>
      <div><b>Baseline 2040 Proj.</b><br/>${data.baseline_projected_species}</div>
      <div><b>Adjusted Proj.</b><br/><span class="negative">${data.adjusted_projected_species}</span></div>
      <div><b>Target Year</b><br/>${data.target_year}</div>
      <div><b>Trend Slope</b><br/>${data.trend_slope} sp/yr</div>
      <div><b>Proj. Health Index</b><br/>${data.projected_health_index}/100</div>
    </div>
    <p><i>${data.interpretation}</i></p>`;
});

/* ══════════════════════════════════════════════════
   POLICY TAB
══════════════════════════════════════════════════ */
let policyLoaded  = false;
let gaugeChart    = null;
let componentsChart = null;

async function loadPolicy() {
  policyLoaded = true;
  const reg = region();

  // Health index
  const hi = await apiFetch(`/api/health-index?region=${reg}`);
  if (hi) {
    $('gaugeScore').textContent    = hi.score ?? '—';
    $('gaugeGrade').textContent    = hi.grade ?? '';
    $('healthInterp').textContent  = hi.interpretation ?? '';
    drawGauge(hi.score ?? 0);
    drawComponents(hi.components ?? {});
    buildRecommendation(hi.score, hi.grade, hi.interpretation);
  }

  // Anomalies
  const anom = await apiFetch(`/api/anomalies?region=${reg}`);
  if (anom) renderAnomalies(anom.flagged ?? []);
}

function drawGauge(score) {
  const ctx = $('gaugeChart').getContext('2d');
  if (gaugeChart) gaugeChart.destroy();

  const color =
    score >= 80 ? '#2E7D32' :
    score >= 60 ? '#1565C0' :
    score >= 40 ? '#E65100' : '#C62828';

  gaugeChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      datasets: [{
        data: [score, 100 - score],
        backgroundColor: [color, '#E3F2FD'],
        borderWidth: 0,
        circumference: 180,
        rotation: 270,
      }],
    },
    options: {
      responsive: false,
      cutout: '72%',
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
    },
  });
}

function drawComponents(comps) {
  const ctx = $('componentsChart').getContext('2d');
  if (componentsChart) componentsChart.destroy();

  componentsChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: ['Biodiversity', 'Trend', 'Stability', 'Confidence'],
      datasets: [{
        data: [comps.biodiversity, comps.trend, comps.stability, comps.confidence],
        backgroundColor: ['#1565C0', '#00838F', '#1E88E5', '#42A5F5'],
        borderRadius: 6,
      }],
    },
    options: {
      responsive: true,
      scales: {
        y: { min: 0, max: 100, grid: { color: '#E3F2FD' } },
        x: { grid: { display: false } },
      },
      plugins: { legend: { display: false } },
    },
  });
}

function renderAnomalies(flagged) {
  const list = $('anomalyList');
  if (!flagged.length) {
    list.innerHTML = '<p style="color:var(--success)">✓ No significant anomalies detected.</p>';
    return;
  }
  list.innerHTML = flagged.slice(0, 8).map(f => `
    <div class="anomaly-item">
      <span class="anomaly-badge anom-${f.type === 'SST' ? 'SST' : 'Occ'}">${f.type}</span>
      <span class="anomaly-reason">${f.reason} <small>(${f.date || ''})</small></span>
    </div>`).join('');
}

function buildRecommendation(score, grade, interp) {
  const recs = {
    Excellent: 'Continue current conservation measures and expand marine protected area coverage. Species richness is strong — focus on habitat integrity and reducing coastal pollution to sustain these gains.',
    Good:      'Targeted interventions for vulnerable species and enhanced SST monitoring are recommended. Engage local fishing communities in sustainable practices to prevent regression.',
    Fair:      'Strengthen fishing regulations, establish new no-take zones, and accelerate coral/seagrass restoration. Immediate pollution remediation along coastal hotspots is advised.',
    Poor:      '⚠️ Emergency conservation action required: moratorium on high-impact fishing, urgent pollution remediation, and international coordination for habitat restoration. Engage CMLRE and state fisheries departments immediately.',
  };
  $('recommendationText').textContent = recs[grade] || interp || '—';
}

/* ── Report Download ─────────────────────────────── */
$('btnReport').addEventListener('click', () => {
  const reg  = region();
  const pA   = $('rptPeriodA').value.trim() || '';
  const pB   = $('rptPeriodB').value.trim() || '';
  let url = `/api/report?region=${reg}`;
  if (pA) url += `&period_a=${encodeURIComponent(pA)}`;
  if (pB) url += `&period_b=${encodeURIComponent(pB)}`;
  window.open(url, '_blank');
});

/* ── CSV Upload ──────────────────────────────────── */
$('btnUpload').addEventListener('click', async () => {
  const file = $('csvUpload').files[0];
  if (!file) { alert('Please select a CSV file.'); return; }

  const form = new FormData();
  form.append('file', file);

  const box = $('uploadResult');
  box.style.display = 'block';
  box.innerHTML = '<div class="spinner"></div>';

  const data = await apiFetch('/api/upload', { method: 'POST', body: form });
  if (!data) { box.innerHTML = '<p>Upload failed.</p>'; box.className = 'upload-result errors'; return; }

  const hasErrors = data.error_count > 0 || data.missing_columns?.length > 0;
  box.className = `upload-result ${hasErrors ? 'errors' : 'valid'}`;

  box.innerHTML = `
    <b>${data.filename}</b><br/>
    ✅ Valid rows: ${data.valid_rows} / ${data.total_rows}<br/>
    ❌ Row errors: ${data.error_count}<br/>
    ${data.missing_columns?.length ? `⚠️ Missing columns: ${data.missing_columns.join(', ')}<br/>` : ''}
    ${data.extra_columns?.length   ? `ℹ️ Extra columns: ${data.extra_columns.join(', ')}<br/>` : ''}
    ${data.errors?.length          ? `<br/><b>Row errors (first 20):</b><ul>${data.errors.map(e => `<li>${e}</li>`).join('')}</ul>` : ''}
    <br/><i>📝 ${data.note}</i>`;
});

/* ══════════════════════════════════════════════════
   ASSISTANT — CHAT + VOICE
══════════════════════════════════════════════════ */
const chatWindow = $('chatWindow');

function appendBubble(text, role, sources = [], translatedText = '', langLabel = '') {
  const div = document.createElement('div');
  div.className = `chat-bubble ${role === 'user' ? 'user-bubble' : 'assistant-bubble'}`;

  if (role === 'user') {
    div.textContent = text;
  } else {
    div.innerHTML = `<strong>Oceanix Kural:</strong> ${escapeHtml(text)}`;
    if (sources?.length) {
      const src = document.createElement('div');
      src.className = 'source-line';
      src.textContent = 'Sources: ' + sources.join(' · ');
      div.appendChild(src);
    }
    if (translatedText && langLabel) {
      const tr = document.createElement('div');
      tr.className = 'translated-line';
      tr.innerHTML = `<b>${langLabel}:</b> ${escapeHtml(translatedText)}`;
      div.appendChild(tr);
      // Speak translated text
      speakText(translatedText);
    } else {
      speakText(text);
    }
  }
  chatWindow.appendChild(div);
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

function escapeHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br/>');
}

async function sendQuestion(question) {
  if (!question.trim()) return;
  appendBubble(question, 'user');
  $('chatInput').value = '';

  // Typing indicator
  const typing = document.createElement('div');
  typing.className = 'chat-bubble assistant-bubble';
  typing.innerHTML = '<i>Oceanix Kural is thinking…</i>';
  chatWindow.appendChild(typing);
  chatWindow.scrollTop = chatWindow.scrollHeight;

  const data = await apiFetch('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, region: region() }),
  });

  chatWindow.removeChild(typing);

  if (!data) {
    appendBubble('Sorry, I could not reach the server. Please try again.', 'assistant');
    return;
  }

  const targetLang = lang();
  let translatedText = '';

  if (targetLang && data.answer) {
    const tr = await apiFetch('/api/translate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: data.answer, target_lang: targetLang }),
    });
    if (tr?.translated) translatedText = tr.translated;
  }

  appendBubble(data.answer || '—', 'assistant', data.sources, translatedText, targetLang);
}

$('btnAsk').addEventListener('click', () => sendQuestion($('chatInput').value));
$('chatInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') sendQuestion($('chatInput').value);
});

/* ── Voice Input (Web Speech API) ───────────────── */
let recognition = null;

if ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SR();
  recognition.continuous    = false;
  recognition.interimResults = false;
  recognition.lang          = 'en-IN';

  recognition.onresult = e => {
    const transcript = e.results[0][0].transcript;
    $('chatInput').value = transcript;
    $('voiceStatus').textContent = '';
    $('btnMic').classList.remove('listening');
    sendQuestion(transcript);
  };

  recognition.onerror = e => {
    $('voiceStatus').textContent = `Voice error: ${e.error}`;
    $('btnMic').classList.remove('listening');
  };

  recognition.onend = () => {
    $('btnMic').classList.remove('listening');
    $('voiceStatus').textContent = '';
  };

  $('btnMic').addEventListener('click', () => {
    if ($('btnMic').classList.contains('listening')) {
      recognition.stop();
    } else {
      $('btnMic').classList.add('listening');
      $('voiceStatus').textContent = '🎤 Listening… speak now';
      recognition.start();
    }
  });
} else {
  $('btnMic').title = 'Voice input not supported in this browser';
  $('btnMic').style.opacity = '.4';
  $('btnMic').style.cursor = 'not-allowed';
}

/* ── Voice Output (Web Speech Synthesis) ────────── */
function speakText(text) {
  if (!window.speechSynthesis) return;
  speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang   = lang() ? `${lang()}-IN` : 'en-IN';
  utter.rate   = 0.95;
  utter.pitch  = 1.0;
  speechSynthesis.speak(utter);
}

/* ══════════════════════════════════════════════════
   REGION CHANGE → RELOAD ALL
══════════════════════════════════════════════════ */
$('globalRegion').addEventListener('change', () => {
  // Reset lazy-load flags so tabs reload on next visit
  speciesLoaded = false;
  policyLoaded  = false;

  // Reload research tab data
  loadSightings();
  loadKPIs();
  loadTrendChart();
  loadEnvData();

  // Reload whichever tab is currently active
  const activeTab = document.querySelector('.tab-btn.active')?.dataset.tab;
  if (activeTab === 'policy')  loadPolicy();
  if (activeTab === 'species') loadSpecies();
});

/* ══════════════════════════════════════════════════
   INITIAL LOAD
══════════════════════════════════════════════════ */
(async function init() {
  await checkHealth();
  initCompareDates();
  await Promise.all([
    loadSightings(),
    loadKPIs(),
    loadTrendChart(),
    loadEnvData(),
  ]);
  loadAnnotations();
})();
