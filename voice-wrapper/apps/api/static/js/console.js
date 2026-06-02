'use strict';

if (!WwtsAuth.requireAuth('/login')) { /* redirecting */ }

const authContext = WwtsAuth.getAuthContext();

const AGENT_LABELS = {
  wwts: { name: 'WWTS Support Agent', sub: 'Voice Assistant' },
  agent_one: { name: 'Agent One', sub: 'General assistant' },
  l1_support: { name: 'L1 Support', sub: 'IT support' },
};

const FRIENDLY_ERRORS = [
  [/input_audio_transcription|session\.input_audio/i, 'Live captions are temporarily unavailable. Your call can continue.'],
  [/microphone|getUserMedia/i, 'We need microphone access to start the call.'],
  [/WebRTC|connection failed/i, 'The voice connection dropped. Please try again.'],
  [/OPENAI|client_secret|SDP/i, 'Unable to connect to the voice service. Please try again shortly.'],
];

let pc = null;
let dc = null;
let micStream = null;
let sessionId = null;
let toolCount = 0;
let msgCount = 0;
let currentUserEl = null;
let currentAiEl = null;
let lastTranscript = '';
let isAiResponding = false;
let aiTranscriptFinalized = false;
let toolCallActive = false;
let isMuted = false;
let timerInterval = null;
let timerStart = null;
let audioCtx = null;
let analyser = null;
let vizAnimId = null;
let _holdCtx = null;
let _holdGain = null;
let _holdTimeout = null;
let sessionWorkOrder = '';
let sessionIntent = '';

function friendlyError(raw) {
  const msg = String(raw || '');
  for (const [re, text] of FRIENDLY_ERRORS) {
    if (re.test(msg)) return text;
  }
  if (msg.length > 120) return 'Something went wrong. Please try again.';
  return msg;
}

function showToast(message, variant = '') {
  const root = document.getElementById('toast-root');
  const el = document.createElement('div');
  el.className = `toast${variant ? ` ${variant}` : ''}`;
  el.textContent = message;
  root.appendChild(el);
  setTimeout(() => {
    el.classList.add('leaving');
    setTimeout(() => el.remove(), 300);
  }, 4500);
}

function showError(msg) {
  showToast(friendlyError(msg), 'warn');
}

function clearError() { /* toasts only */ }

function setAvatarState(state) {
  const wrap = document.getElementById('avatar-wrap');
  wrap.className = `avatar-wrap state-${state || 'idle'}`;
  const labels = {
    idle: 'Idle',
    listening: 'Listening',
    speaking: 'Speaking',
    thinking: 'Thinking',
  };
  const status = labels[state] || 'Idle';
  document.getElementById('agent-status').textContent = status;
  document.getElementById('info-agent-state').textContent = status;
}

function setCallUI(inCall) {
  const dock = document.getElementById('call-dock');
  dock.classList.toggle('in-call', inCall);
  document.getElementById('pre-call-settings').style.display = inCall ? 'none' : '';
  const timer = document.getElementById('call-timer');
  timer.classList.toggle('idle', !inCall);
  if (!inCall) timer.textContent = 'Ready to connect';
}

function updateAgentDisplay() {
  const id = document.getElementById('agent-id').value;
  const meta = AGENT_LABELS[id] || { name: id, sub: 'Voice Assistant' };
  document.getElementById('agent-display-name').textContent = meta.name;
  document.querySelector('.agent-sub').textContent = meta.sub;
}

function setStatus(s) {
  const dot = document.getElementById('status-dot');
  dot.className = `conn-dot ${s}`;
  const labels = {
    connected: 'Connected',
    connecting: 'Connecting…',
    disconnected: 'Disconnected',
    error: 'Connection issue',
  };
  document.getElementById('status-label').textContent = labels[s] || s;
}

function toggleInsightPanel() {
  const panel = document.getElementById('insight-panel');
  const open = panel.classList.toggle('open');
  document.getElementById('panel-toggle').setAttribute('aria-expanded', String(open));
  document.getElementById('panel-toggle').classList.toggle('shifted', open);
}

function toggleProfileMenu() {
  document.getElementById('profile-menu').classList.toggle('open');
}

document.getElementById('profile-btn')?.addEventListener('click', (e) => {
  e.stopPropagation();
  toggleProfileMenu();
});
document.addEventListener('click', () => {
  document.getElementById('profile-menu')?.classList.remove('open');
});

function hideCaptionPlaceholder() {
  const ph = document.getElementById('caption-placeholder');
  if (ph) ph.remove();
}

function fadeCaptions() {
  const lines = document.querySelectorAll('#transcript .caption-line');
  const n = lines.length;
  lines.forEach((el, i) => {
    el.classList.remove('faded', 'older');
    const age = n - 1 - i;
    if (age === 1) el.classList.add('faded');
    if (age >= 2) el.classList.add('older');
  });
}

function startHoldSound() {
  stopHoldSound();
  _holdCtx = new (window.AudioContext || window.webkitAudioContext)();
  _holdGain = _holdCtx.createGain();
  _holdGain.gain.value = 0;
  _holdGain.connect(_holdCtx.destination);
  function beep() {
    const osc = _holdCtx.createOscillator();
    osc.type = 'sine';
    osc.frequency.value = 440;
    osc.connect(_holdGain);
    const now = _holdCtx.currentTime;
    _holdGain.gain.setValueAtTime(0, now);
    _holdGain.gain.linearRampToValueAtTime(0.06, now + 0.04);
    _holdGain.gain.linearRampToValueAtTime(0, now + 0.25);
    osc.start(now);
    osc.stop(now + 0.3);
    _holdTimeout = setTimeout(beep, 1500);
  }
  beep();
}

function stopHoldSound() {
  if (_holdTimeout) { clearTimeout(_holdTimeout); _holdTimeout = null; }
  if (_holdCtx) { try { _holdCtx.close(); } catch {} _holdCtx = null; }
  _holdGain = null;
}

function startTimer() {
  timerStart = Date.now();
  const timer = document.getElementById('call-timer');
  timer.classList.remove('idle');
  timerInterval = setInterval(() => {
    const s = Math.floor((Date.now() - timerStart) / 1000);
    const hh = String(Math.floor(s / 3600)).padStart(2, '0');
    const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
    const ss = String(s % 60).padStart(2, '0');
    timer.textContent = hh !== '00' ? `${hh}:${mm}:${ss}` : `${mm}:${ss}`;
  }, 1000);
}

function stopTimer() {
  if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }
  const timer = document.getElementById('call-timer');
  timer.classList.add('idle');
  timer.textContent = 'Ready to connect';
}

function initViz(stream) {
  try {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const src = audioCtx.createMediaStreamSource(stream);
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 32;
    analyser.smoothingTimeConstant = 0.65;
    src.connect(analyser);
  } catch {
    analyser = null;
  }
}

function drawViz() {
  if (!analyser) return;
  const canvas = document.getElementById('viz-canvas');
  const ctx = canvas.getContext('2d');
  const buf = new Uint8Array(analyser.frequencyBinCount);
  analyser.getByteFrequencyData(buf);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const barW = 3;
  const gap = 2;
  for (let i = 0; i < Math.min(12, buf.length); i++) {
    const val = buf[i] / 255;
    const h = Math.max(2, val * canvas.height);
    ctx.fillStyle = `rgba(37, 99, 235, ${0.3 + val * 0.7})`;
    ctx.fillRect(i * (barW + gap), canvas.height - h, barW, h);
  }
  vizAnimId = requestAnimationFrame(drawViz);
}

function startUserViz() {
  setAvatarState('listening');
  if (analyser && !vizAnimId) drawViz();
}

function startAiViz() {
  if (vizAnimId) { cancelAnimationFrame(vizAnimId); vizAnimId = null; }
  setAvatarState('speaking');
}

function hideViz() {
  if (vizAnimId) { cancelAnimationFrame(vizAnimId); vizAnimId = null; }
  if (!sessionId) setAvatarState('idle');
  else if (!isAiResponding && !toolCallActive) setAvatarState('listening');
  const canvas = document.getElementById('viz-canvas');
  canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
}

function destroyViz() {
  hideViz();
  if (audioCtx) { try { audioCtx.close(); } catch {} audioCtx = null; }
  analyser = null;
}

function startProcessingViz() {
  if (vizAnimId) { cancelAnimationFrame(vizAnimId); vizAnimId = null; }
  setAvatarState('thinking');
  document.getElementById('info-active-tool').textContent = 'Running…';
}

function detectWorkOrder(text) {
  const m = String(text).match(/\b[A-Z]{2}\d{6,}\b/i);
  if (m) {
    sessionWorkOrder = m[0].toUpperCase();
    document.getElementById('info-work-order').textContent = sessionWorkOrder;
  }
}

function detectIntent(text) {
  const t = String(text).toLowerCase();
  if (/work order|workorder/.test(t)) {
    sessionIntent = 'Work order inquiry';
    document.getElementById('info-intent').textContent = sessionIntent;
  }
}

async function startCall() {
  setStatus('connecting');
  setBtnEnabled('start', false);
  clearError();
  clearTranscript();
  setAvatarState('thinking');

  try {
    const sessResp = await fetch('/voice/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agent_id: document.getElementById('agent-id').value,
        user_id: document.getElementById('user-id').value,
        context: buildSessionContext(),
      }),
    });

    if (!sessResp.ok) {
      const err = await sessResp.json().catch(() => ({}));
      throw new Error(err.detail || `Session creation failed (HTTP ${sessResp.status})`);
    }

    const session = await sessResp.json();
    sessionId = session.session_id;
    const secret = session.client_secret;
    if (!secret) throw new Error('Voice service is not configured.');

    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      throw new Error('Microphone access denied');
    }

    initViz(micStream);
    pc = new RTCPeerConnection();
    pc.ontrack = (e) => {
      if (e.streams[0]) document.getElementById('remote-audio').srcObject = e.streams[0];
    };
    pc.onconnectionstatechange = () => {
      if (pc?.connectionState === 'failed') showError('WebRTC connection failed');
      if (pc?.connectionState === 'disconnected') stopCall();
    };

    micStream.getAudioTracks().forEach((t) => pc.addTrack(t, micStream));
    dc = pc.createDataChannel('oai-events');
    dc.addEventListener('open', onDataChannelOpen);
    dc.addEventListener('message', (e) => handleEvent(JSON.parse(e.data)));
    dc.addEventListener('close', () => { if (sessionId) stopCall(); });

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    await new Promise((resolve) => {
      if (pc.iceGatheringState === 'complete') return resolve();
      const tid = setTimeout(resolve, 4000);
      pc.addEventListener('icegatheringstatechange', function check() {
        if (pc.iceGatheringState === 'complete') {
          clearTimeout(tid);
          pc.removeEventListener('icegatheringstatechange', check);
          resolve();
        }
      });
    });

    const sdpResp = await fetch('https://api.openai.com/v1/realtime/calls', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${secret}`,
        'Content-Type': 'application/sdp',
      },
      body: pc.localDescription.sdp,
    });

    if (!sdpResp.ok) {
      throw new Error(`Voice service connection failed (${sdpResp.status})`);
    }

    await pc.setRemoteDescription({ type: 'answer', sdp: await sdpResp.text() });

    setStatus('connected');
    startTimer();
    setCallUI(true);
    setAvatarState('listening');
    document.getElementById('text-input-field').disabled = false;
    document.getElementById('btn-send-text').disabled = false;
    document.getElementById('insight-panel').classList.add('open');
    showToast('You’re connected. Start speaking anytime.');
  } catch (err) {
    showError(err.message);
    setStatus('error');
    setBtnEnabled('start', true);
    setAvatarState('idle');
    cleanup();
  }
}

function stopCall() {
  if (sessionId) {
    fetch(`/voice/session/${sessionId}/end`, { method: 'POST' }).catch(() => {});
  }
  cleanup();
  sessionId = null;
  stopTimer();
  setStatus('disconnected');
  setCallUI(false);
  isMuted = false;
  document.getElementById('btn-mute').classList.remove('muted');
  document.getElementById('text-input-field').disabled = true;
  document.getElementById('btn-send-text').disabled = true;
  setBtnEnabled('start', true);
  setAvatarState('idle');
  document.getElementById('info-active-tool').textContent = '—';
}

function cleanup() {
  if (dc) { try { dc.close(); } catch {} dc = null; }
  if (pc) { try { pc.close(); } catch {} pc = null; }
  if (micStream) { micStream.getTracks().forEach((t) => t.stop()); micStream = null; }
  destroyViz();
  document.getElementById('remote-audio').srcObject = null;
  currentUserEl = null;
  currentAiEl = null;
  lastTranscript = '';
  isAiResponding = false;
  aiTranscriptFinalized = false;
  toolCallActive = false;
  stopHoldSound();
}

function setMicEnabled(enabled) {
  if (micStream) micStream.getAudioTracks().forEach((t) => { t.enabled = enabled; });
}

function toggleMute() {
  isMuted = !isMuted;
  setMicEnabled(!isMuted);
  document.getElementById('btn-mute').classList.toggle('muted', isMuted);
}

function sendTextMessage() {
  const input = document.getElementById('text-input-field');
  const text = input.value.trim();
  if (!text || !sessionId || !dc || dc.readyState !== 'open') return;
  input.value = '';
  const userEl = addMsg('user', text);
  finaliseText(userEl, text);
  lastTranscript = text;
  detectWorkOrder(text);
  detectIntent(text);
  dc.send(JSON.stringify({
    type: 'conversation.item.create',
    item: { type: 'message', role: 'user', content: [{ type: 'input_text', text }] },
  }));
  dc.send(JSON.stringify({ type: 'response.create' }));
  input.focus();
}

document.getElementById('text-input-field').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && sessionId) sendTextMessage();
});

function onDataChannelOpen() {
  dc.send(JSON.stringify({
    type: 'session.update',
    session: {
      type: 'realtime',
      input_audio_transcription: { model: 'whisper-1' },
      turn_detection: {
        type: 'server_vad',
        threshold: 0.85,
        prefix_padding_ms: 300,
        silence_duration_ms: 1200,
      },
    },
  }));
}

function handleEvent(event) {
  switch (event.type) {
    case 'input_audio_buffer.speech_started':
      lastTranscript = '';
      toolCallActive = false;
      if (isAiResponding) {
        dc.send(JSON.stringify({ type: 'response.cancel' }));
        isAiResponding = false;
        currentAiEl = null;
      }
      startUserViz();
      currentUserEl = addMsg('user', '');
      break;

    case 'conversation.item.input_audio_transcription.delta':
      if (!currentUserEl) currentUserEl = addMsg('user', '');
      appendText(currentUserEl, event.delta || '');
      break;

    case 'conversation.item.input_audio_transcription.completed':
      lastTranscript = event.transcript || '';
      if (currentUserEl) {
        finaliseText(currentUserEl, lastTranscript);
        currentUserEl = null;
      }
      detectWorkOrder(lastTranscript);
      detectIntent(lastTranscript);
      hideViz();
      break;

    case 'response.created':
      isAiResponding = true;
      aiTranscriptFinalized = false;
      startAiViz();
      break;

    case 'response.audio_transcript.delta':
      if (!currentAiEl) currentAiEl = addMsg('ai', '');
      appendText(currentAiEl, event.delta || '');
      break;

    case 'response.audio_transcript.done':
      if (currentAiEl && !aiTranscriptFinalized) {
        finaliseText(currentAiEl, event.transcript || '');
        currentAiEl = null;
        aiTranscriptFinalized = true;
      }
      hideViz();
      break;

    case 'response.done': {
      isAiResponding = false;
      if (!aiTranscriptFinalized) {
        for (const item of (event.response?.output || [])) {
          if (item.type !== 'message' || item.role !== 'assistant') continue;
          for (const part of (item.content || [])) {
            const text = part.transcript || part.text || '';
            if (text) {
              if (!currentAiEl) currentAiEl = addMsg('ai', '');
              finaliseText(currentAiEl, text);
              aiTranscriptFinalized = true;
            }
          }
        }
      }
      if (currentAiEl) {
        const bubble = currentAiEl.querySelector('.body');
        if (!bubble?.textContent.trim()) {
          currentAiEl.remove();
          msgCount = Math.max(0, msgCount - 1);
        } else {
          bubble.classList.remove('streaming');
        }
        currentAiEl = null;
      }
      handleToolCalls(event.response?.output || []);
      hideViz();
      break;
    }

    case 'error': {
      const errMsg = event.error?.message || JSON.stringify(event.error);
      if (/cancel|no active response|response_not_active/i.test(errMsg)) break;
      showError(errMsg);
      hideViz();
      break;
    }
    default:
      break;
  }
}

async function handleToolCalls(outputs) {
  const calls = outputs.filter((item) => item.type === 'function_call');
  if (!calls.length) return;

  startHoldSound();
  startProcessingViz();
  toolCallActive = true;

  for (const item of calls) {
    let args = {};
    try { args = JSON.parse(item.arguments || '{}'); } catch {}
    if (lastTranscript) args.user_message = lastTranscript;

    document.getElementById('info-active-tool').textContent = formatToolName(item.name);
    addToolEntry('out', item.name, args.user_message || item.arguments);

    let outputPayload;
    try {
      const res = await fetch(`/voice/session/${sessionId}/tool-call`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool_name: item.name, args }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const summary = data.speak || data.answer || 'Completed';
      addToolEntry('in', item.name, summary);
      outputPayload = JSON.stringify({
        answer: data.answer || data.speak || '',
        speak: data.speak || data.answer || '',
      });
    } catch (err) {
      addToolEntry('err', item.name, 'Unable to complete this action');
      outputPayload = JSON.stringify({ error: err.message });
    }

    if (!toolCallActive) break;

    dc.send(JSON.stringify({
      type: 'conversation.item.create',
      item: {
        type: 'function_call_output',
        call_id: item.call_id,
        output: outputPayload,
      },
    }));
  }

  stopHoldSound();
  document.getElementById('info-active-tool').textContent = '—';
  hideViz();

  if (toolCallActive) {
    dc.send(JSON.stringify({ type: 'response.create' }));
    toolCallActive = false;
  }
}

function formatToolName(name) {
  const map = {
    run_agent: 'Agent lookup',
    search_knowledge: 'Knowledge search',
  };
  return map[name] || name.replace(/_/g, ' ');
}

function addMsg(role, text) {
  hideCaptionPlaceholder();
  const box = document.getElementById('transcript');
  const wrap = document.createElement('div');
  wrap.className = `caption-line ${role === 'user' ? 'user' : 'ai'}`;

  const label = document.createElement('span');
  label.className = 'caption-label';
  label.textContent = role === 'user' ? 'User' : 'Agent';

  const bubble = document.createElement('p');
  bubble.className = 'caption-text body streaming';
  bubble.textContent = text;

  wrap.appendChild(label);
  wrap.appendChild(bubble);
  box.appendChild(wrap);
  box.scrollTop = box.scrollHeight;
  msgCount++;
  fadeCaptions();
  return wrap;
}

function appendText(wrap, delta) {
  wrap.querySelector('.body').textContent += delta;
  document.getElementById('transcript').scrollTop = document.getElementById('transcript').scrollHeight;
}

function finaliseText(wrap, text) {
  const bubble = wrap.querySelector('.body');
  bubble.classList.remove('streaming');
  bubble.textContent = text;
  fadeCaptions();
}

function clearTranscript() {
  const box = document.getElementById('transcript');
  box.innerHTML = '<p class="caption-placeholder" id="caption-placeholder">Live captions will appear here during your call.</p>';
  document.getElementById('tool-entries').innerHTML = '';
  document.getElementById('timeline-empty').style.display = '';
  msgCount = 0;
  toolCount = 0;
  sessionWorkOrder = '';
  sessionIntent = '';
  document.getElementById('info-intent').textContent = '—';
  document.getElementById('info-work-order').textContent = '—';
  document.getElementById('info-active-tool').textContent = '—';
  currentUserEl = null;
  currentAiEl = null;
  lastTranscript = '';
  aiTranscriptFinalized = false;
  toolCallActive = false;
}

function addToolEntry(dir, name, detail) {
  toolCount++;
  document.getElementById('timeline-empty').style.display = 'none';

  const card = document.createElement('article');
  card.className = `timeline-card ${dir}`;
  const ts = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const title = formatToolName(name);
  const summary = dir === 'out' ? 'Requested' : dir === 'in' ? 'Completed' : 'Issue';

  card.innerHTML =
    `<div class="timeline-card-head"><strong>${esc(title)}</strong><time>${esc(ts)}</time></div>` +
    `<p><em>${esc(summary)}</em> — ${esc(String(detail).slice(0, 140))}</p>`;

  document.getElementById('tool-entries').prepend(card);
  document.getElementById('insight-panel').classList.add('open');

  if (dir === 'out') {
    document.getElementById('info-active-tool').textContent = title;
  }
}

function setBtnEnabled(which, enabled) {
  document.getElementById(`btn-${which}`).disabled = !enabled;
}

function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function buildSessionContext() {
  if (!authContext) return {};
  return {
    wwts_session: authContext.session,
    user_id: authContext.userId,
    env: authContext.env,
    source: authContext.source,
    version: authContext.version,
    expire_days: authContext.expireDays,
    customer_codes: authContext.customerCodes || [],
  };
}

function initAuthUI() {
  if (!authContext) return;
  document.getElementById('user-id').value = authContext.userId || '';
  const userLabel = authContext.userId || 'User';
  document.getElementById('auth-user').textContent = userLabel;
  document.getElementById('profile-initials').textContent =
    userLabel.slice(0, 2).toUpperCase();

  const env = (authContext.env || 'QA').toUpperCase();
  const badge = document.getElementById('env-badge');
  badge.textContent = env;
  badge.classList.toggle('qa', /qa|staging|stg/i.test(env));
  badge.classList.toggle('prod', /prod/i.test(env));

  if (authContext.session) {
    const sel = document.getElementById('agent-id');
    sel.value = 'wwts';
    sel.disabled = true;
  }
  updateAgentDisplay();
}

document.getElementById('agent-id')?.addEventListener('change', updateAgentDisplay);

initAuthUI();

function logout() {
  if (sessionId) stopCall();
  WwtsAuth.clearAuthContext();
  window.location.replace('/login');
}

window.startCall = startCall;
window.stopCall = stopCall;
window.toggleMute = toggleMute;
window.sendTextMessage = sendTextMessage;
window.toggleInsightPanel = toggleInsightPanel;
window.logout = logout;
