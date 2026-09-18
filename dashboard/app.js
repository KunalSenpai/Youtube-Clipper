let state = {videos: [], accounts: [], jobs: [], stats: {}};
let selected = new Set();
let currentSection = 'dashboard';
let technicalJobId = null;
let technicalTimer = null;
let technicalRequestInFlight = false;

const $ = id => document.getElementById(id);

async function loadState() {
  try {
    const r = await fetch('/api/state?_=' + Date.now(), {cache: 'no-store'});
    if (!r.ok) throw new Error('State request failed: ' + r.status);
    state = await r.json();
    render();
  } catch (e) {
    console.error(e);
    toast('Could not load dashboard state. Check the dashboard server.');
  }
}

function youtubeAccounts() {
  return state.accounts.filter(a => a.platform === 'youtube');
}

function platformAccounts(platform) {
  return state.accounts.filter(a => a.platform === platform);
}

function accountName(id) {
  const a = state.accounts.find(x => x.id === id);
  return a ? a.name : id || 'Unassigned';
}

function uploadedFor(video, accountId) {
  return (video.uploaded_accounts || []).includes(accountId);
}

function videosForAccount(accountId) {
  if (!accountId || accountId === '__all__') return state.videos;
  return state.videos.filter(v => !v.content_account_id || v.content_account_id === accountId);
}

function render() {
  $('statVideos').textContent = state.stats.videos ?? 0;
  $('statPending').textContent = state.stats.pending ?? 0;
  $('statUploaded').textContent = state.stats.uploaded ?? 0;
  $('statRunning').textContent = state.stats.running ?? 0;
  renderAccountSelects();
  renderUploadAccounts();
  renderVideos();
  renderTable();
  renderJobs();
  renderAccountsPage();
  updateCount();
}

function setOptions(select, accounts, placeholder) {
  const previous = select.value;
  select.innerHTML = accounts.length
    ? accounts.map(a => `<option value="${esc(a.id)}">${esc(a.name)}</option>`).join('')
    : `<option value="">${esc(placeholder)}</option>`;
  if (accounts.some(a => a.id === previous)) select.value = previous;
}

function renderAccountSelects() {
  const yt = youtubeAccounts();
  setOptions($('generateAccount'), yt, 'No YouTube account configured');
  setOptions($('generateAccountFull'), yt, 'No YouTube account configured');

  const platform = $('platform').value;
  const accounts = platformAccounts(platform);
  setOptions($('account'), accounts, platform === 'instagram' ? 'No Instagram account configured' : 'No YouTube account configured');

  const filter = $('videoAccountFilter');
  const old = filter.value;
  filter.innerHTML = `<option value="__all__">All accounts + legacy</option>` +
    yt.map(a => `<option value="${esc(a.id)}">${esc(a.name)}</option>`).join('');
  if ([...filter.options].some(o => o.value === old)) filter.value = old;
}

function renderUploadAccounts() {
  const platform = $('platform').value;
  const accounts = platformAccounts(platform);
  const account = $('account').value;
  $('uploadHint').textContent = platform === 'youtube'
    ? (accounts.length ? `Publishing to ${accountName(account)}. Existing OAuth, duplicate protection and scheduling are preserved.` : 'Configure a YouTube account first.')
    : 'Instagram is visible as a destination, but publishing is not configured yet.';
}

function renderVideos() {
  const account = $('account').value;
  const videos = videosForAccount(account);
  const grid = $('videoGrid');
  grid.innerHTML = videos.map(v => {
    const uploaded = uploadedFor(v, account);
    const checked = selected.has(v.path);
    return `<article class="video-card ${checked ? 'selected' : ''}" data-path="${esc(v.path)}">
      <div class="thumb"><video muted preload="metadata" src="/media?path=${encodeURIComponent(v.path)}"></video></div>
      <div class="video-meta">
        <div class="video-title-row"><label class="check-wrap"><input type="checkbox" class="video-check" data-path="${esc(v.path)}" ${checked ? 'checked' : ''}><span></span></label><b title="${esc(v.name)}">${esc(v.name)}</b></div>
        <small>${esc(v.folder)} · ${v.size_mb} MB</small>
        <div class="badge-row"><span class="badge ${uploaded ? 'done' : ''}">${uploaded ? 'Uploaded' : 'Pending'}</span>${v.legacy ? '<span class="badge legacy">Legacy</span>' : ''}</div>
      </div>
    </article>`;
  }).join('') || '<div class="empty">No rendered Shorts for this account yet. Generate some from the Generate Shorts page.</div>';
}

function renderTable() {
  const filter = $('videoAccountFilter').value || '__all__';
  const videos = videosForAccount(filter);
  $('videoTable').innerHTML = videos.map(v => {
    const owner = v.content_account_id ? accountName(v.content_account_id) : 'Unassigned / legacy';
    return `<div class="row video-row">
      <div><b>${esc(v.name)}</b><span>${esc(v.folder)}</span></div>
      <div>${esc(owner)}</div>
      <div>${esc(v.modified)}</div>
      <div>${v.size_mb} MB</div>
    </div>`;
  }).join('') || '<div class="empty">No Shorts found.</div>';
}

function renderJobs() {
  const jobs = state.jobs || [];
  renderTechnicalJobOptions(jobs);
  $('jobs').innerHTML = jobs.map(j => {
    const type = j.job_type === 'generate' ? 'Generate' : 'Upload';
    const detail = j.job_type === 'generate' ? (j.source_url || 'YouTube source') : `${(JSON.parseSafe(j.selected_files) || []).length} video(s)`;
    const action = (j.status === 'running' || j.status === 'queued') ? `<button type="button" class="danger small-stop" data-stop-job="${esc(j.id)}">Stop</button>` : '';
    return `<div class="row job-row" data-job-id="${esc(j.id)}">
      <div><b>${esc(type)}</b><span>${esc(accountName(j.account_id))} · ${esc(j.platform)}</span></div>
      <div class="status ${esc(j.status)}">${esc(j.status.toUpperCase())}</div>
      <div title="${esc(detail)}">${esc(detail)}</div>
      <div>${esc(formatDate(j.created_at))} ${action}</div>
    </div>`;
  }).join('') || '<div class="empty">No jobs yet.</div>';
}

function renderTechnicalJobOptions(jobs) {
  const select = $('techJobSelect');
  if (!select) return;
  const ordered = [...jobs].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
  if (!technicalJobId || !ordered.some(j => j.id === technicalJobId)) {
    const active = ordered.find(j => j.status === 'running' || j.status === 'queued');
    technicalJobId = active ? active.id : (ordered[0]?.id || null);
  }
  select.innerHTML = ordered.length
    ? ordered.map(j => {
        const type = j.job_type === 'generate' ? 'Generate' : 'Upload';
        return `<option value="${esc(j.id)}">${esc(type)} · ${esc(j.status.toUpperCase())} · ${esc(j.id)}</option>`;
      }).join('')
    : '<option value="">No jobs yet</option>';
  if (technicalJobId && ordered.some(j => j.id === technicalJobId)) select.value = technicalJobId;
  updateTechnicalProgress();
}

function jobStage(log, job) {
  const text = String(log || '');
  const lower = text.toLowerCase();
  const lines = text.split(/\r?\n/).filter(Boolean);
  const last = lines.length ? lines[lines.length - 1].trim() : '';
  let stage = job?.job_type === 'upload' ? 'Preparing upload' : 'Starting';
  if (/youtube download|trying youtube download|downloaded:|downloading/i.test(text)) stage = 'Downloading source';
  if (/loading whisper|whisper loaded/i.test(text)) stage = 'Loading Whisper';
  if (/transcribing|whisper progress/i.test(text)) stage = 'Transcribing audio';
  if (/identifying real-world video source|source type:|detected source:/i.test(text)) stage = 'Detecting source context';
  if (/finding content-driven moments|semantic candidates|selected .* high-quality moments/i.test(text)) stage = 'Selecting best moments';
  if (/rendering selected shorts|short \d+|detecting stable speaker shots|optimizing pacing|creating word-synchronized|adding captions/i.test(text)) stage = 'Rendering Shorts';
  if (/final youtube metadata|generating metadata|seo|tags|validation passed/i.test(text)) stage = 'Generating / validating SEO';
  if (/uploading:|uploading short|privacy:|scheduled public time/i.test(text)) stage = 'Uploading to YouTube';
  if (/youtube caption|caption track/i.test(text)) stage = 'Uploading captions';
  if (/bot complete|created \d+ shorts/i.test(text)) stage = 'Completed';
  if (job?.status === 'failed') stage = 'Failed';
  if (job?.status === 'cancelled') stage = 'Stopped';
  if (job?.status === 'success') stage = 'Completed';
  return {stage, last};
}

function technicalProgress(log, job) {
  const text = String(log || '');
  const lower = text.toLowerCase();
  if (job?.status === 'success') return 100;
  if (job?.status === 'failed' || job?.status === 'cancelled') return 100;

  // Use only progress that can be derived from actual backend output.
  const whisper = text.match(/whisper progress:\s*processed about\s*([0-9.]+)\s*minutes/i);
  const duration = text.match(/whisper (?:will analyze|finished audio at) about\s*([0-9.]+)\s*minutes/i);
  if (whisper && duration && Number(duration[1]) > 0) {
    return Math.max(1, Math.min(65, Number(whisper[1]) / Number(duration[1]) * 45));
  }
  if (/transcription complete/i.test(text)) return 48;
  if (/source type:|detected source:/i.test(text)) return 55;
  if (/finding content-driven moments/i.test(text)) return 60;
  if (/selected .* high-quality moments/i.test(text)) return 66;
  if (/rendering selected shorts/i.test(text)) return 70;
  if (/short \d+/i.test(text)) return 75;
  if (/final youtube metadata|generating metadata/i.test(text)) return 84;
  if (/validation passed/i.test(text)) return 88;
  if (/uploading:/i.test(text)) return 92;
  if (/caption track uploaded/i.test(text)) return 97;
  return job?.status === 'running' ? 5 : 0;
}

async function updateTechnicalProgress() {
  const select = $('techJobSelect');
  if (!select || technicalRequestInFlight) return;
  const id = select.value || technicalJobId;
  if (!id) {
    $('techStage').textContent = 'Waiting';
    $('techStatus').textContent = '—';
    $('techElapsed').textContent = '—';
    $('techProgressText').textContent = '—';
    $('techProgressBar').style.width = '0%';
    $('techCurrent').textContent = 'No job selected.';
    $('techConsole').textContent = 'Select a job to view its live technical output.';
    return;
  }
  technicalJobId = id;
  technicalRequestInFlight = true;
  try {
    const r = await fetch('/api/log?id=' + encodeURIComponent(id) + '&_=' + Date.now(), {cache: 'no-store'});
    if (!r.ok) throw new Error('Log request failed: ' + r.status);
    const data = await r.json();
    const job = data.job || state.jobs.find(j => j.id === id) || {};
    const log = data.log || '';
    const meta = jobStage(log, job);
    const pct = technicalProgress(log, job);
    $('techStage').textContent = meta.stage;
    $('techStatus').textContent = String(job.status || '—').toUpperCase();
    $('techElapsed').textContent = elapsedForJob(job);
    $('techProgressText').textContent = pct ? `${Math.round(pct)}%` : 'Waiting';
    $('techProgressBar').style.width = `${Math.max(0, Math.min(100, pct))}%`;
    $('techCurrent').textContent = meta.last || 'Waiting for backend output…';
    const lines = log.split(/\r?\n/).filter(Boolean);
    $('techConsole').textContent = lines.slice(-80).join('\n') || 'Waiting for backend output…';
    $('techConsole').scrollTop = $('techConsole').scrollHeight;
  } catch (e) {
    $('techCurrent').textContent = 'Technical log temporarily unavailable.';
  } finally {
    technicalRequestInFlight = false;
  }
}

function elapsedForJob(job) {
  if (!job || !job.created_at) return '—';
  const start = new Date(job.started_at || job.created_at).getTime();
  if (!Number.isFinite(start)) return '—';
  const end = job.finished_at ? new Date(job.finished_at).getTime() : Date.now();
  const seconds = Math.max(0, Math.floor((end - start) / 1000));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h ? `${h}h ${m}m ${s}s` : (m ? `${m}m ${s}s` : `${s}s`);
}


function renderAccountsPage() {
  $('accounts').innerHTML = state.accounts.map(a => {
    const configured = a.status !== 'not_configured' && (a.platform !== 'youtube' || !!a.token_file);
    return `<div class="account"><div><b>${esc(a.name)}</b><span>${esc(a.platform)}</span></div><strong class="account-status ${configured ? 'connected' : ''}">${configured ? 'Connected' : 'Not configured'}</strong></div>`;
  }).join('') || '<div class="empty">No accounts configured.</div>';
}

function togglePath(path) {
  if (selected.has(path)) selected.delete(path); else selected.add(path);
  renderVideos();
  updateCount();
}

function selectPending() {
  const account = $('account').value;
  videosForAccount(account).filter(v => !uploadedFor(v, account)).forEach(v => selected.add(v.path));
  renderVideos(); updateCount();
}

function selectAll() {
  videosForAccount($('account').value).forEach(v => selected.add(v.path));
  renderVideos(); updateCount();
}

function clearSelection() {
  selected.clear();
  renderVideos(); updateCount();
}

function updateCount() {
  $('selectionCount').textContent = `${selected.size} selected`;
  $('uploadBtn').disabled = selected.size === 0 || !$('account').value;
  if ($('deleteBtn')) $('deleteBtn').disabled = selected.size === 0;
}

async function startUpload() {
  const platform = $('platform').value;
  const account = $('account').value;
  if (!selected.size) return toast('Select at least one Short.');
  if (!account) return toast('Configure an account first.');

  const already = [...selected].filter(path => {
    const v = state.videos.find(x => x.path === path);
    return v && uploadedFor(v, account);
  });
  if (already.length) {
    const ok = window.confirm(`${already.length} selected Short(s) are already uploaded to ${accountName(account)}.\n\nUpload them again?`);
    if (!ok) return;
  }

  const ok = window.confirm(`Upload ${selected.size} Short(s) to ${accountName(account)}?\n\nThe existing uploader will handle metadata and scheduling.`);
  if (!ok) return;

  setBusy($('uploadBtn'), true, 'Starting...');
  try {
    const data = await postJson('/api/upload', {platform, account_id: account, files: [...selected]});
    if (!data.ok) throw new Error(data.error || 'Could not start upload.');
    toast(`Upload job ${data.job_id} started.`);
    selected.clear();
    await loadState();
  } catch (e) {
    toast(e.message);
  } finally {
    setBusy($('uploadBtn'), false, 'Upload selected');
  }
}

async function deleteSelectedShorts() {
  if (!selected.size) return toast('Select at least one generated Short.');
  const count = selected.size;
  const ok = window.confirm(`Delete ${count} generated Short(s) from this PC?\n\nThis removes the MP4s, local caption files, manifests, and duplicate-upload log references. Source downloads and transcripts are kept.`);
  if (!ok) return;
  try {
    const data = await postJson('/api/delete', {files: [...selected]});
    if (!data.ok) throw new Error(data.error || 'Delete failed.');
    selected.clear();
    toast(`Deleted ${data.deleted.length} Short(s).`);
    await loadState();
  } catch (e) { toast(e.message); }
}

async function stopJob(jobId) {
  if (!window.confirm('Stop this running job? Any active download/render/upload child processes will also be terminated.')) return;
  try {
    const data = await postJson('/api/stop', {job_id: jobId});
    toast(data.message || 'Job stopped.');
    await loadState();
  } catch (e) { toast(e.message); }
}

async function generateFrom(urlInput, accountInput, button, statusEl) {
  const url = $(urlInput).value.trim();
  const account = $(accountInput).value;
  if (!url) return toast('Paste a YouTube URL first.');
  if (!account) return toast('Configure a YouTube account first.');

  setBusy(button, true, 'Starting...');
  $(statusEl).textContent = 'Starting main.py…';
  try {
    const data = await postJson('/api/generate', {account_id: account, url});
    if (!data.ok) throw new Error(data.error || 'Could not start generation.');
    toast(`Generation job ${data.job_id} started.`);
    $(statusEl).textContent = `Generating for ${accountName(account)}. You can keep using the dashboard.`;
    $('generateUrl').value = '';
    $('generateUrlFull').value = '';
    nav('activity');
    await loadState();
  } catch (e) {
    $(statusEl).textContent = '';
    toast(e.message);
  } finally {
    setBusy(button, false, 'Generate Shorts');
  }
}

function setBusy(button, busy, label) {
  button.disabled = busy;
  if (busy) button.dataset.originalText = button.textContent;
  button.textContent = busy ? label : (button.dataset.originalText || label);
}

async function postJson(url, body) {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  let data;
  try { data = await r.json(); } catch { throw new Error(`Server returned ${r.status}.`); }
  if (!r.ok) throw new Error(data.error || `Request failed (${r.status}).`);
  return data;
}

function nav(section) {
  currentSection = section;
  document.querySelectorAll('.section').forEach(x => x.classList.toggle('active', x.id === section));
  document.querySelectorAll('.nav').forEach(x => x.classList.toggle('active', x.dataset.section === section));
  const titles = {settings: 'Accounts & Settings', generate: 'Generate Shorts', activity: 'Activity & History', videos: 'Videos', dashboard: 'Dashboard'};
  $('pageTitle').textContent = titles[section] || 'Dashboard';
}

function toast(message) {
  const t = $('toast'); t.textContent = message; t.classList.add('show');
  clearTimeout(window.__toastTimer); window.__toastTimer = setTimeout(() => t.classList.remove('show'), 3200);
}

function esc(s) { return String(s ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m])); }
function formatDate(s) { if (!s) return '—'; const d = new Date(s); return Number.isNaN(d.getTime()) ? s : d.toLocaleString(); }
function JSONSafe(v) { try { return JSON.parse(v); } catch { return null; } }
JSON.parseSafe = JSONSafe;

function bindEvents() {
  document.querySelectorAll('.nav').forEach(btn => btn.addEventListener('click', () => nav(btn.dataset.section)));
  $('refreshBtn').addEventListener('click', loadState);
  $('platform').addEventListener('change', () => { selected.clear(); renderAccountSelects(); renderUploadAccounts(); renderVideos(); updateCount(); });
  $('account').addEventListener('change', () => { selected.clear(); renderVideos(); updateCount(); });
  $('videoAccountFilter').addEventListener('change', renderTable);
  $('selectPendingBtn').addEventListener('click', selectPending);
  $('selectAllBtn').addEventListener('click', selectAll);
  $('clearBtn').addEventListener('click', clearSelection);
  $('uploadBtn').addEventListener('click', startUpload);
  $('deleteBtn').addEventListener('click', deleteSelectedShorts);
  $('jobs').addEventListener('click', e => { const btn = e.target.closest('[data-stop-job]'); if (btn) stopJob(btn.dataset.stopJob); });
  $('techJobSelect').addEventListener('change', () => { technicalJobId = $('techJobSelect').value; updateTechnicalProgress(); });
  $('generateBtn').addEventListener('click', () => generateFrom('generateUrl', 'generateAccount', $('generateBtn'), 'generateStatus'));
  $('generateFullBtn').addEventListener('click', () => generateFrom('generateUrlFull', 'generateAccountFull', $('generateFullBtn'), 'generateStatus'));
  $('videoGrid').addEventListener('click', e => {
    const card = e.target.closest('.video-card');
    if (!card) return;
    const check = e.target.closest('.video-check');
    const path = card.dataset.path;
    if (check) {
      if (check.checked) selected.add(path); else selected.delete(path);
      renderVideos(); updateCount();
      return;
    }
    togglePath(path);
  });
}

bindEvents();
loadState();
technicalTimer = setInterval(updateTechnicalProgress, 1200);
setInterval(loadState, 3000);
