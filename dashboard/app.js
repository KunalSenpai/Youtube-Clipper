let state = {videos: [], accounts: [], jobs: [], stats: {}};
let selected = new Set();
let currentSection = 'dashboard';
let technicalJobId = null;
let latestKnownJobId = null;
let technicalTimer = null;
let technicalRequestInFlight = false;
let activeReviewJobId = null;
let activeReviewReport = null;
let activeReviewAccountId = null;
let reviewPollTimer = null;
let activeFramePath = null;
let activePreviewPath = null;
let lastSyncAt = null;
let framePosition = {centerX: 0.5, centerY: 0.5, zoom: 1};
let framePreviewAnimation = null;

const $ = id => document.getElementById(id);

async function loadState() {
  try {
    const r = await fetch('/api/state?_=' + Date.now(), {cache: 'no-store'});
    if (!r.ok) throw new Error('State request failed: ' + r.status);
    state = await r.json();
    lastSyncAt = new Date();
    updateSyncState(true);
    render();
  } catch (e) {
    console.error(e);
    updateSyncState(false);
    toast('Could not load dashboard state. Check the dashboard server.');
  }
}

function updateSyncState(online) {
  const container = $('syncState');
  if (!container) return;
  const connected = online !== false && navigator.onLine;
  container.classList.toggle('offline', !connected);
  $('syncLabel').textContent = connected ? 'Live' : 'Offline';
  $('syncTime').textContent = connected && lastSyncAt
    ? `· ${lastSyncAt.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'})}`
    : '· retrying';
  container.title = connected && lastSyncAt ? `Last updated ${lastSyncAt.toLocaleString()}` : 'Dashboard connection unavailable';
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
  document.body.classList.add('ready');
}

function emptyState(index, title, message) {
  return `<div class="empty"><span>${esc(index)}</span><b>${esc(title)}</b><p>${esc(message)}</p></div>`;
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
        <div class="video-card-actions"><button type="button" class="frame-button" data-preview-path="${esc(v.path)}">Preview</button><button type="button" class="frame-button" data-frame-path="${esc(v.path)}" ${v.frame_editable ? '' : 'disabled'}>${v.frame_editable ? 'Adjust frame' : 'Regenerate to edit'}</button>${v.framing_mode === 'manual' ? '<span class="badge done">Manual frame</span>' : ''}</div>
      </div>
    </article>`;
  }).join('') || emptyState('01', 'No Shorts in this queue', 'Generate a source video to create your first reviewable clips.');
}

function filteredLibraryVideos() {
  const filter = $('videoAccountFilter').value || '__all__';
  const search = $('videoSearch').value.trim().toLowerCase();
  const status = $('videoStatusFilter').value;
  const sort = $('videoSort').value;
  const videos = videosForAccount(filter).filter(v => {
    const uploaded = (v.uploaded_accounts || []).length > 0;
    if (status === 'uploaded' && !uploaded) return false;
    if (status === 'pending' && uploaded) return false;
    if (!search) return true;
    const owner = v.content_account_id ? accountName(v.content_account_id) : 'unassigned legacy';
    return [v.name, v.folder, owner, v.path].some(value => String(value || '').toLowerCase().includes(search));
  });
  return videos.sort((a, b) => {
    if (sort === 'oldest') return String(a.modified || '').localeCompare(String(b.modified || ''));
    if (sort === 'largest') return Number(b.size_mb || 0) - Number(a.size_mb || 0);
    if (sort === 'name') return String(a.name || '').localeCompare(String(b.name || ''), undefined, {sensitivity: 'base'});
    return String(b.modified || '').localeCompare(String(a.modified || ''));
  });
}

function renderTable() {
  const videos = filteredLibraryVideos();
  $('videoResultCount').textContent = `${videos.length} Short${videos.length === 1 ? '' : 's'}`;
  $('videoTable').innerHTML = videos.map(v => {
    const owner = v.content_account_id ? accountName(v.content_account_id) : 'Unassigned / legacy';
    const uploaded = (v.uploaded_accounts || []).length > 0;
    return `<div class="row video-row">
      <div><b>${esc(v.name)}</b><span>${esc(v.folder)}</span></div>
      <div>${esc(owner)}</div>
      <div><span class="badge ${uploaded ? 'done' : ''}">${uploaded ? 'Uploaded' : 'Pending'}</span><span>${esc(v.modified)}</span></div>
      <div>${v.size_mb} MB</div>
      <div class="row-actions"><button type="button" class="frame-button" data-preview-path="${esc(v.path)}">Preview</button><button type="button" class="frame-button" data-frame-path="${esc(v.path)}" ${v.frame_editable ? '' : 'disabled'}>${v.frame_editable ? 'Adjust' : 'No master'}</button></div>
    </div>`;
  }).join('') || emptyState('03', 'No matching Shorts', 'Try another search, account, or upload status filter.');
}

function renderJobs() {
  const jobs = state.jobs || [];
  renderTechnicalJobOptions(jobs);
  const jobMarkup = job => {
    const type = job.job_type === 'generate' ? 'Generate' : (job.job_type === 'prepare' ? 'Prepare review' : 'Upload');
    const detail = job.job_type === 'generate' ? (job.source_url || 'YouTube source') : `${(JSON.parseSafe(job.selected_files) || []).length} video(s)`;
    const action = (job.status === 'running' || job.status === 'queued') ? `<button type="button" class="danger small-stop" data-stop-job="${esc(job.id)}">Stop</button>` : '';
    return `<article class="row job-row" data-job-id="${esc(job.id)}" tabindex="0" role="button" aria-label="Inspect ${esc(type)} job ${esc(job.id)}">
      <div><b>${esc(type)}</b><span>${esc(accountName(job.account_id))} · ${esc(job.platform)}</span></div>
      <div class="status ${esc(job.status)}">${esc(job.status.toUpperCase())}</div>
      <div title="${esc(detail)}">${esc(detail)}</div>
      <div>${esc(formatDate(job.created_at))} ${action}</div>
    </article>`;
  };
  const typeFilter = $('jobTypeFilter').value;
  const statusFilter = $('jobStatusFilter').value;
  const search = $('jobSearch').value.trim().toLowerCase();
  const filtered = jobs.filter(job => {
    if (typeFilter !== 'all' && job.job_type !== typeFilter) return false;
    if (statusFilter !== 'all' && job.status !== statusFilter) return false;
    if (!search) return true;
    return [job.id, job.source_url, job.platform, accountName(job.account_id)].some(value => String(value || '').toLowerCase().includes(search));
  });
  $('jobResultCount').textContent = `${filtered.length} job${filtered.length === 1 ? '' : 's'}`;
  $('jobs').innerHTML = filtered.map(jobMarkup).join('') || emptyState('04', 'No matching activity', 'Try another job type, status, or search term.');
  const generations = jobs.filter(j => j.job_type === 'generate').slice(0, 6);
  $('generationJobs').innerHTML = generations.map(jobMarkup).join('') || emptyState('02', 'No generation history', 'Start a job above and its progress will appear here.');
}

function renderTechnicalJobOptions(jobs) {
  const select = $('techJobSelect');
  if (!select) return;
  const ordered = [...jobs].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
  const newestJobId = ordered[0]?.id || null;

  // Automatically follow a job that arrived after the last state refresh.
  // If the user deliberately selects an older job, preserve that selection
  // until another new job is created.
  if (newestJobId !== latestKnownJobId) technicalJobId = newestJobId;
  if (technicalJobId && !ordered.some(j => j.id === technicalJobId)) {
    technicalJobId = newestJobId;
  }
  latestKnownJobId = newestJobId;
  select.innerHTML = ordered.length
    ? ordered.map(j => {
        const type = j.job_type === 'generate' ? 'Generate' : (j.job_type === 'prepare' ? 'Prepare review' : 'Upload');
        return `<option value="${esc(j.id)}">${esc(type)} / ${esc(j.status.toUpperCase())} / ${esc(j.id)}</option>`;
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
  let stage = job?.job_type === 'upload' ? 'Preparing upload' : (job?.job_type === 'prepare' ? 'Preparing review' : 'Starting');
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
    $('techStatus').textContent = '-';
    $('techElapsed').textContent = '-';
    $('techProgressText').textContent = '-';
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
    $('techStatus').textContent = String(job.status || '-').toUpperCase();
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
  if (!job || !job.created_at) return '-';
  const start = new Date(job.started_at || job.created_at).getTime();
  if (!Number.isFinite(start)) return '-';
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
    const initial = String(a.platform || '?').slice(0, 1).toUpperCase();
    return `<article class="account"><span class="account-mark">${esc(initial)}</span><div><b>${esc(a.name)}</b><span>${esc(a.platform)} destination</span></div><strong class="account-status ${configured ? 'connected' : ''}"><i></i>${configured ? 'Connected' : 'Not configured'}</strong></article>`;
  }).join('') || emptyState('05', 'No accounts configured', 'Add an account definition on the server to enable publishing.');
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

async function prepareUpload() {
  const platform = $('platform').value;
  const account = $('account').value;
  if (!selected.size) return toast('Select at least one Short.');
  if (!account) return toast('Configure an account first.');

  const already = [...selected].filter(path => {
    const v = state.videos.find(x => x.path === path);
    return v && uploadedFor(v, account);
  });
  if (already.length) {
    return toast(`${already.length} selected Short(s) are already in this account's upload log. Select pending Shorts only.`);
  }

  openReviewDialog();
  showReviewState('Preparing metadata, captions, validation, and schedule. Nothing is being uploaded.');
  setBusy($('uploadBtn'), true, 'Preparing...');
  try {
    const data = await postJson('/api/prepare', {platform, account_id: account, files: [...selected]});
    if (!data.ok) throw new Error(data.error || 'Could not prepare upload.');
    activeReviewJobId = data.job_id;
    activeReviewAccountId = account;
    activeReviewReport = null;
    pollReview();
    await loadState();
  } catch (e) {
    showReviewState(e.message, true);
  } finally {
    setBusy($('uploadBtn'), false, 'Prepare upload');
  }
}

function openPreview(path) {
  const video = state.videos.find(item => item.path === path);
  if (!video) return toast('That Short is no longer available.');
  activePreviewPath = path;
  const uploaded = (video.uploaded_accounts || []).length > 0;
  $('previewTitle').textContent = video.name || 'Preview Short';
  $('previewSubtitle').textContent = video.folder || 'Upload-ready render';
  $('previewStatus').textContent = uploaded ? 'Uploaded' : 'Pending review';
  $('previewAccount').textContent = video.content_account_id ? accountName(video.content_account_id) : 'Unassigned / legacy';
  $('previewSize').textContent = `${video.size_mb || 0} MB`;
  $('previewModified').textContent = video.modified || '—';
  $('previewFraming').textContent = video.framing_mode === 'manual' ? 'Manual crop' : (video.frame_editable ? 'Automatic face tracking' : 'Legacy render');
  $('previewSelectBtn').textContent = selected.has(path) ? 'Remove from selection' : 'Select for upload';
  $('previewFrameBtn').disabled = !video.frame_editable;
  $('previewFrameBtn').textContent = video.frame_editable ? 'Adjust frame' : 'No retained edit master';
  $('previewVideo').src = '/media?path=' + encodeURIComponent(path) + '&_=' + Date.now();
  if (!$('previewDialog').open) $('previewDialog').showModal();
}

function closePreview() {
  const video = $('previewVideo');
  video.pause();
  video.removeAttribute('src');
  video.load();
  activePreviewPath = null;
  if ($('previewDialog').open) $('previewDialog').close();
}

function togglePreviewSelection() {
  if (!activePreviewPath) return;
  const path = activePreviewPath;
  if (selected.has(path)) selected.delete(path); else selected.add(path);
  $('previewSelectBtn').textContent = selected.has(path) ? 'Remove from selection' : 'Select for upload';
  renderVideos();
  updateCount();
}

function inspectJob(jobId) {
  if (!jobId) return;
  technicalJobId = jobId;
  nav('activity');
  if ([...$('techJobSelect').options].some(option => option.value === jobId)) $('techJobSelect').value = jobId;
  updateTechnicalProgress();
  $('technicalProgress').scrollIntoView({behavior: 'smooth', block: 'start'});
}

function handleJobInteraction(event) {
  const stopButton = event.target.closest?.('[data-stop-job]');
  if (stopButton) {
    event.stopPropagation();
    stopJob(stopButton.dataset.stopJob);
    return;
  }
  const row = event.target.closest?.('[data-job-id]');
  if (row) inspectJob(row.dataset.jobId);
}

function showFrameState(message, error = false) {
  const el = $('frameState');
  el.textContent = message;
  el.classList.toggle('show', Boolean(message));
  el.classList.toggle('error', error);
}

async function openFrameEditor(path) {
  const dialog = $('frameDialog');
  activeFramePath = path;
  showFrameState('Loading the retained full-frame clip…');
  if (!dialog.open) dialog.showModal();
  try {
    const r = await fetch('/api/frame-info?path=' + encodeURIComponent(path) + '&_=' + Date.now(), {cache: 'no-store'});
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || 'Could not open the framing editor.');
    const framing = data.framing || {};
    framePosition = {
      centerX: framing.mode === 'manual' ? Number(framing.center_x ?? 0.5) : 0.5,
      centerY: framing.mode === 'manual' ? Number(framing.center_y ?? 0.5) : 0.5,
      zoom: framing.mode === 'manual' ? Number(framing.zoom ?? 1) : 1,
    };
    $('frameZoom').value = String(framePosition.zoom);
    $('frameZoomValue').textContent = `${framePosition.zoom.toFixed(2)}×`;
    $('frameSourceVideo').src = '/media?path=' + encodeURIComponent(data.source_master_path) + '&_=' + Date.now();
    $('frameResultVideo').src = '/media?path=' + encodeURIComponent(data.video_path) + '&_=' + Date.now();
    showFrameState(framing.mode === 'auto_face_tracking' ? 'The saved Short currently uses automatic face tracking. Saving here changes it to your fixed manual crop.' : 'Manual framing loaded.');
  } catch (e) {
    showFrameState(e.message, true);
    $('saveFrameBtn').disabled = true;
  }
}

function closeFrameEditor() {
  const source = $('frameSourceVideo');
  source.pause();
  source.removeAttribute('src');
  source.load();
  $('frameResultVideo').removeAttribute('src');
  $('frameResultVideo').load();
  activeFramePath = null;
  $('saveFrameBtn').disabled = false;
  if (framePreviewAnimation) cancelAnimationFrame(framePreviewAnimation);
  framePreviewAnimation = null;
  $('frameDialog').close();
}

function frameCropFractions() {
  const video = $('frameSourceVideo');
  if (!video.videoWidth || !video.videoHeight) return {width: 0.3, height: 1};
  let height = Math.min(1, (video.videoWidth / video.videoHeight) * (16 / 9));
  let width = height * (video.videoHeight / video.videoWidth) * (9 / 16);
  height /= framePosition.zoom;
  width /= framePosition.zoom;
  return {width, height};
}

function clampFramePosition() {
  const crop = frameCropFractions();
  framePosition.centerX = Math.max(crop.width / 2, Math.min(1 - crop.width / 2, framePosition.centerX));
  framePosition.centerY = Math.max(crop.height / 2, Math.min(1 - crop.height / 2, framePosition.centerY));
}

function updateFrameOverlay() {
  const video = $('frameSourceVideo');
  const overlay = $('cropOverlay');
  if (!video.videoWidth || !video.clientWidth) return;
  clampFramePosition();
  const crop = frameCropFractions();
  overlay.style.left = `${video.offsetLeft + (framePosition.centerX - crop.width / 2) * video.clientWidth}px`;
  overlay.style.top = `${video.offsetTop + (framePosition.centerY - crop.height / 2) * video.clientHeight}px`;
  overlay.style.width = `${crop.width * video.clientWidth}px`;
  overlay.style.height = `${crop.height * video.clientHeight}px`;
  $('frameZoomValue').textContent = `${framePosition.zoom.toFixed(2)}×`;
  drawFramePreview();
}

function drawFramePreview() {
  const video = $('frameSourceVideo');
  const canvas = $('frameCanvas');
  if (!video.videoWidth || video.readyState < 2) return;
  const crop = frameCropFractions();
  const sw = crop.width * video.videoWidth;
  const sh = crop.height * video.videoHeight;
  const sx = framePosition.centerX * video.videoWidth - sw / 2;
  const sy = framePosition.centerY * video.videoHeight - sh / 2;
  const context = canvas.getContext('2d');
  context.drawImage(video, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
}

function runFramePreview() {
  drawFramePreview();
  if ($('frameDialog').open) framePreviewAnimation = requestAnimationFrame(runFramePreview);
}

async function saveManualFrame() {
  if (!activeFramePath) return;
  setBusy($('saveFrameBtn'), true, 'Rendering…');
  showFrameState('Re-rendering the Short with this frame. The full-frame master will be kept.');
  try {
    const data = await postJson('/api/reframe', {
      video_path: activeFramePath,
      center_x: framePosition.centerX,
      center_y: framePosition.centerY,
      zoom: framePosition.zoom,
    });
    if (!data.ok) throw new Error(data.error || 'Could not save the new frame.');
    $('frameResultVideo').src = '/media?path=' + encodeURIComponent(activeFramePath) + '&_=' + Date.now();
    showFrameState('Saved. The upload-ready Short now uses this manual frame.');
    toast('Short re-rendered with the new frame.');
    await loadState();
  } catch (e) {
    showFrameState(e.message, true);
  } finally {
    setBusy($('saveFrameBtn'), false, 'Save and re-render');
  }
}

function openReviewDialog() {
  const dialog = $('reviewDialog');
  $('reviewItems').innerHTML = '';
  $('approveReviewBtn').disabled = true;
  if (!dialog.open) dialog.showModal();
}

function closeReviewDialog() {
  clearTimeout(reviewPollTimer);
  reviewPollTimer = null;
  $('reviewDialog').close();
}

function showReviewState(message, error = false) {
  const el = $('reviewState');
  el.textContent = message;
  el.classList.add('show');
  el.classList.toggle('error', error);
}

async function pollReview() {
  clearTimeout(reviewPollTimer);
  if (!activeReviewJobId) return;
  try {
    const r = await fetch('/api/review?id=' + encodeURIComponent(activeReviewJobId) + '&_=' + Date.now(), {cache: 'no-store'});
    const data = await r.json();
    if (r.status === 202) {
      showReviewState('Preparing the review. Video files stay local and YouTube is not contacted.');
      reviewPollTimer = setTimeout(pollReview, 1200);
      return;
    }
    if (!r.ok) throw new Error(data.error || `Review failed (${r.status}).`);
    activeReviewReport = data.report;
    renderReview(data.report);
    await loadState();
  } catch (e) {
    showReviewState(e.message, true);
    $('approveReviewBtn').disabled = true;
  }
}

function renderReview(report) {
  const items = report.items || [];
  const valid = items.filter(item => item.validation?.passed);
  $('reviewSummary').textContent = `${valid.length} validated Short(s) prepared for ${accountName(activeReviewAccountId)}.`;
  $('reviewState').classList.remove('show', 'error');
  $('reviewItems').innerHTML = items.map((item, index) => {
    const request = item.planned_api_requests?.['videos.insert'];
    const body = request?.body || {};
    const snippet = body.snippet || item.metadata || {};
    const status = body.status || {};
    const visibility = status.publishAt ? 'scheduled' : (status.privacyStatus || 'private');
    const problems = item.validation?.problems || [];
    return `<article class="review-item" data-review-index="${index}" data-video-path="${esc(item.video_path)}">
      <div class="review-preview">
        <video controls preload="metadata" src="/media?path=${encodeURIComponent(item.video_path)}"></video>
        <div class="review-file" title="${esc(item.video_path)}">${esc(item.video_path.split(/[\\/]/).pop())}</div>
        <div class="review-source">${esc(item.source?.title || 'Unknown source')} / confidence ${esc(item.source?.confidence ?? 'unknown')}</div>
      </div>
      <div class="review-form">
        <label class="wide">Title<input data-field="title" maxlength="100" value="${esc(snippet.title || '')}" ${item.validation?.passed ? '' : 'disabled'}></label>
        <label class="wide">Description<textarea data-field="description" maxlength="5000" ${item.validation?.passed ? '' : 'disabled'}>${esc(snippet.description || '')}</textarea></label>
        <label class="wide">Tags, separated by commas<input data-field="tags" value="${esc((snippet.tags || []).join(', '))}" ${item.validation?.passed ? '' : 'disabled'}></label>
        <label>Visibility<select data-field="visibility" ${item.validation?.passed ? '' : 'disabled'}>
          ${status.publishAt ? `<option value="scheduled" ${visibility === 'scheduled' ? 'selected' : ''}>Scheduled: ${esc(formatDate(status.publishAt))}</option>` : ''}
          <option value="private" ${visibility === 'private' ? 'selected' : ''}>Private</option>
          <option value="public" ${visibility === 'public' ? 'selected' : ''}>Public now</option>
        </select></label>
        <div class="review-validation ${item.validation?.passed ? '' : 'invalid'}">${item.validation?.passed ? 'Validation passed' : esc(problems.join(' '))}</div>
      </div>
    </article>`;
  }).join('') || '<div class="empty">No reviewable Shorts were produced.</div>';
  $('approveReviewBtn').disabled = valid.length === 0;
}

async function approveReview() {
  if (!activeReviewJobId || !activeReviewReport) return;
  const account = activeReviewAccountId;
  const items = [...document.querySelectorAll('.review-item')]
    .filter(el => !el.querySelector('[data-field="title"]').disabled)
    .map(el => ({
      video_path: el.dataset.videoPath,
      title: el.querySelector('[data-field="title"]').value.trim(),
      description: el.querySelector('[data-field="description"]').value.trim(),
      tags: el.querySelector('[data-field="tags"]').value.split(',').map(x => x.trim()).filter(Boolean),
      visibility: el.querySelector('[data-field="visibility"]').value,
    }));
  if (!items.length) return showReviewState('No validated Shorts are available to approve.', true);
  setBusy($('approveReviewBtn'), true, 'Starting upload...');
  try {
    const data = await postJson('/api/approve', {
      account_id: account,
      review_job_id: activeReviewJobId,
      items,
    });
    if (!data.ok) throw new Error(data.error || 'Could not start approved upload.');
    selected.clear();
    closeReviewDialog();
    toast(`Approved upload job ${data.job_id} started.`);
    nav('activity');
    await loadState();
  } catch (e) {
    showReviewState(e.message, true);
  } finally {
    setBusy($('approveReviewBtn'), false, 'Approve and upload');
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
  button.classList.toggle('is-busy', busy);
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
  document.querySelectorAll('.nav').forEach(x => {
    const active = x.dataset.section === section;
    x.classList.toggle('active', active);
    x.setAttribute('aria-current', active ? 'page' : 'false');
  });
  const pages = {
    settings: ['Accounts', 'Manage publishing destinations and connection status.'],
    generate: ['Generate', 'Create a new batch of Shorts from a YouTube source.'],
    activity: ['Activity', 'Follow live processing output and inspect earlier jobs.'],
    videos: ['Library', 'Review rendered clips, framing state, and account ownership.'],
    dashboard: ['Overview', 'Generate, review, and publish from one private workspace.'],
  };
  const page = pages[section] || pages.dashboard;
  $('pageTitle').textContent = page[0];
  $('pageSubtitle').textContent = page[1];
}

function toast(message) {
  const t = $('toast'); t.textContent = message; t.classList.add('show');
  clearTimeout(window.__toastTimer); window.__toastTimer = setTimeout(() => t.classList.remove('show'), 3200);
}

function esc(s) { return String(s ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m])); }
function formatDate(s) { if (!s) return '-'; const d = new Date(s); return Number.isNaN(d.getTime()) ? s : d.toLocaleString(); }
function JSONSafe(v) { try { return JSON.parse(v); } catch { return null; } }
JSON.parseSafe = JSONSafe;

function bindEvents() {
  document.querySelectorAll('.nav').forEach(btn => btn.addEventListener('click', () => nav(btn.dataset.section)));
  $('refreshBtn').addEventListener('click', async () => {
    setBusy($('refreshBtn'), true, 'Refreshing…');
    await loadState();
    setBusy($('refreshBtn'), false, 'Refresh');
  });
  $('platform').addEventListener('change', () => { selected.clear(); renderAccountSelects(); renderUploadAccounts(); renderVideos(); updateCount(); });
  $('account').addEventListener('change', () => { selected.clear(); renderVideos(); updateCount(); });
  $('videoAccountFilter').addEventListener('change', renderTable);
  $('videoStatusFilter').addEventListener('change', renderTable);
  $('videoSort').addEventListener('change', renderTable);
  $('videoSearch').addEventListener('input', renderTable);
  $('jobTypeFilter').addEventListener('change', renderJobs);
  $('jobStatusFilter').addEventListener('change', renderJobs);
  $('jobSearch').addEventListener('input', renderJobs);
  $('selectPendingBtn').addEventListener('click', selectPending);
  $('selectAllBtn').addEventListener('click', selectAll);
  $('clearBtn').addEventListener('click', clearSelection);
  $('uploadBtn').addEventListener('click', prepareUpload);
  $('approveReviewBtn').addEventListener('click', approveReview);
  $('closeReviewBtn').addEventListener('click', closeReviewDialog);
  $('cancelReviewBtn').addEventListener('click', closeReviewDialog);
  $('reviewDialog').addEventListener('cancel', e => { e.preventDefault(); closeReviewDialog(); });
  $('closePreviewBtn').addEventListener('click', closePreview);
  $('previewSelectBtn').addEventListener('click', togglePreviewSelection);
  $('previewFrameBtn').addEventListener('click', () => {
    const path = activePreviewPath;
    if (!path) return;
    closePreview();
    openFrameEditor(path);
  });
  $('previewDialog').addEventListener('cancel', e => { e.preventDefault(); closePreview(); });
  $('closeFrameBtn').addEventListener('click', closeFrameEditor);
  $('cancelFrameBtn').addEventListener('click', closeFrameEditor);
  $('saveFrameBtn').addEventListener('click', saveManualFrame);
  $('frameDialog').addEventListener('cancel', e => { e.preventDefault(); closeFrameEditor(); });
  $('frameSourceVideo').addEventListener('loadedmetadata', () => {
    updateFrameOverlay();
    if (framePreviewAnimation) cancelAnimationFrame(framePreviewAnimation);
    runFramePreview();
  });
  $('frameZoom').addEventListener('input', e => {
    framePosition.zoom = Number(e.target.value);
    updateFrameOverlay();
  });
  $('centerFrameBtn').addEventListener('click', () => {
    framePosition.centerX = 0.5;
    framePosition.centerY = 0.5;
    framePosition.zoom = 1;
    $('frameZoom').value = '1';
    updateFrameOverlay();
  });
  let dragOffset = null;
  $('cropOverlay').addEventListener('pointerdown', e => {
    const box = $('cropOverlay').getBoundingClientRect();
    dragOffset = {x: e.clientX - (box.left + box.width / 2), y: e.clientY - (box.top + box.height / 2)};
    e.currentTarget.setPointerCapture(e.pointerId);
  });
  $('cropOverlay').addEventListener('pointermove', e => {
    if (!dragOffset || !e.currentTarget.hasPointerCapture(e.pointerId)) return;
    const video = $('frameSourceVideo').getBoundingClientRect();
    framePosition.centerX = (e.clientX - dragOffset.x - video.left) / video.width;
    framePosition.centerY = (e.clientY - dragOffset.y - video.top) / video.height;
    updateFrameOverlay();
  });
  $('cropOverlay').addEventListener('pointerup', e => {
    dragOffset = null;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
  });
  $('cropOverlay').addEventListener('keydown', e => {
    const step = e.shiftKey ? 0.03 : 0.01;
    if (e.key === 'ArrowLeft') framePosition.centerX -= step;
    else if (e.key === 'ArrowRight') framePosition.centerX += step;
    else if (e.key === 'ArrowUp') framePosition.centerY -= step;
    else if (e.key === 'ArrowDown') framePosition.centerY += step;
    else return;
    e.preventDefault();
    updateFrameOverlay();
  });
  window.addEventListener('resize', updateFrameOverlay);
  window.addEventListener('offline', () => updateSyncState(false));
  window.addEventListener('online', loadState);
  $('deleteBtn').addEventListener('click', deleteSelectedShorts);
  $('jobs').addEventListener('click', handleJobInteraction);
  $('generationJobs').addEventListener('click', handleJobInteraction);
  [$('jobs'), $('generationJobs')].forEach(container => container.addEventListener('keydown', e => {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('[data-job-id]')) {
      e.preventDefault();
      inspectJob(e.target.dataset.jobId);
    }
  }));
  $('techJobSelect').addEventListener('change', () => { technicalJobId = $('techJobSelect').value; updateTechnicalProgress(); });
  $('generateBtn').addEventListener('click', () => generateFrom('generateUrl', 'generateAccount', $('generateBtn'), 'generateStatus'));
  $('generateFullBtn').addEventListener('click', () => generateFrom('generateUrlFull', 'generateAccountFull', $('generateFullBtn'), 'generateStatus'));
  $('videoGrid').addEventListener('click', e => {
    const previewButton = e.target.closest('[data-preview-path]');
    if (previewButton) {
      e.stopPropagation();
      openPreview(previewButton.dataset.previewPath);
      return;
    }
    const frameButton = e.target.closest('[data-frame-path]');
    if (frameButton && !frameButton.disabled) {
      e.stopPropagation();
      openFrameEditor(frameButton.dataset.framePath);
      return;
    }
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
  $('videoTable').addEventListener('click', e => {
    const previewButton = e.target.closest('[data-preview-path]');
    if (previewButton) {
      openPreview(previewButton.dataset.previewPath);
      return;
    }
    const frameButton = e.target.closest('[data-frame-path]');
    if (frameButton && !frameButton.disabled) openFrameEditor(frameButton.dataset.framePath);
  });
}

bindEvents();
loadState();
technicalTimer = setInterval(updateTechnicalProgress, 1200);
setInterval(loadState, 3000);
