'use strict';

if (!WwtsAuth.requireAuth('/login')) { /* redirecting */ }

const authContext = WwtsAuth.getAuthContext();
let currentId = null;
let summaries = [];

function byId(id) { return document.getElementById(id); }

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function showToast(message, variant = '') {
  const root = byId('toast-root');
  const el = document.createElement('div');
  el.className = `toast${variant ? ` ${variant}` : ''}`;
  el.textContent = message;
  root.appendChild(el);
  setTimeout(() => { el.classList.add('leaving'); setTimeout(() => el.remove(), 300); }, 3500);
}

function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString([], {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function fmtDuration(startIso, endIso) {
  const a = new Date(startIso).getTime();
  const b = new Date(endIso).getTime();
  if (Number.isNaN(a) || Number.isNaN(b) || b < a) return '';
  const s = Math.round((b - a) / 1000);
  const mm = Math.floor(s / 60);
  const ss = s % 60;
  return mm > 0 ? `${mm}m ${ss}s` : `${ss}s`;
}

async function loadTranscripts() {
  const all = byId('scope-all').checked;
  const userId = byId('user-id').value || (authContext && authContext.userId) || '';
  const qs = all || !userId ? '' : `?user_id=${encodeURIComponent(userId)}`;
  try {
    const res = await fetch(`/transcripts${qs}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    summaries = await res.json();
  } catch (err) {
    showToast('Could not load transcripts.', 'warn');
    summaries = [];
  }
  renderList();
}

function renderList() {
  const list = byId('transcript-list');
  const empty = byId('list-empty');
  list.innerHTML = '';
  if (!summaries.length) {
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  for (const s of summaries) {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = `dash-card${s.id === currentId ? ' active' : ''}`;
    card.onclick = () => openTranscript(s.id);
    const who = s.user_name || s.user_id || 'Unknown caller';
    card.innerHTML =
      `<div class="dash-card-top">` +
        `<span class="dash-badge dash-badge-${esc(s.mode || 'voice')}">${esc(s.mode || 'voice')}</span>` +
        `<time>${esc(fmtDate(s.started_at || s.created_at))}</time>` +
      `</div>` +
      `<p class="dash-card-preview">${esc(s.preview || '(no content)')}</p>` +
      `<div class="dash-card-foot">` +
        `<span>${esc(who)}</span>` +
        `<span>${esc(s.turn_count)} turn${s.turn_count === 1 ? '' : 's'}</span>` +
      `</div>`;
    list.appendChild(card);
  }
}

async function openTranscript(id) {
  currentId = id;
  renderList();
  try {
    const res = await fetch(`/transcripts/${encodeURIComponent(id)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderDetail(data);
  } catch (err) {
    showToast('Could not open transcript.', 'warn');
  }
}

function renderDetail(data) {
  byId('detail-empty').hidden = true;
  byId('detail').hidden = false;

  const who = data.user_name || data.user_id || 'Unknown caller';
  byId('detail-title').textContent = `${data.mode === 'chat' ? 'Chat' : 'Call'} with ${who}`;

  const metaBits = [
    fmtDate(data.started_at),
    fmtDuration(data.started_at, data.ended_at),
    `${data.turn_count} turn${data.turn_count === 1 ? '' : 's'}`,
    `agent: ${data.agent_id || 'wwts'}`,
  ].filter(Boolean);
  byId('detail-meta').textContent = metaBits.join('  ·  ');

  const thread = byId('detail-thread');
  thread.innerHTML = '';
  for (const turn of (data.turns || [])) {
    const role = turn.role === 'user' ? 'user' : 'agent';
    const row = document.createElement('div');
    row.className = `dash-turn ${role}`;
    row.innerHTML =
      `<span class="dash-turn-label">${role === 'user' ? 'Caller' : 'Agent'}</span>` +
      `<p class="dash-turn-text">${esc(turn.text)}</p>`;
    thread.appendChild(row);
  }
}

async function deleteCurrent() {
  if (!currentId) return;
  if (!window.confirm('Delete this transcript permanently?')) return;
  try {
    const res = await fetch(`/transcripts/${encodeURIComponent(currentId)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    showToast('Transcript deleted.');
    currentId = null;
    byId('detail').hidden = true;
    byId('detail-empty').hidden = false;
    await loadTranscripts();
  } catch (err) {
    showToast('Could not delete transcript.', 'warn');
  }
}

function toggleProfileMenu() {
  byId('profile-menu').classList.toggle('open');
}
byId('profile-btn')?.addEventListener('click', (e) => { e.stopPropagation(); toggleProfileMenu(); });
document.addEventListener('click', () => byId('profile-menu')?.classList.remove('open'));

function logout() {
  WwtsAuth.clearAuthContext();
  window.location.replace('/login');
}
window.logout = logout;
window.loadTranscripts = loadTranscripts;
window.deleteCurrent = deleteCurrent;

function initAuthUI() {
  if (!authContext) return;
  byId('user-id').value = authContext.userId || '';
  const userLabel = authContext.userName || authContext.userId || 'User';
  byId('auth-user').textContent = userLabel;
  byId('profile-initials').textContent = userLabel.slice(0, 2).toUpperCase();
}

byId('scope-all').addEventListener('change', loadTranscripts);

initAuthUI();
loadTranscripts();
