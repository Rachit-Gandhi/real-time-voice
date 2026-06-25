'use strict';

if (!WwtsAuth.requireAuth('/login')) { /* redirecting */ }

const authContext = WwtsAuth.getAuthContext();

const AGENT_LABELS = {
  wwts: { name: 'WWTS Support Agent', sub: 'Voice Assistant' },
};

// Transcription model for the caller's speech.
//  - Default (English/off): whisper-1.
//  - Hinglish on: gpt-4o-transcribe — the latest prompt-following transcribe
//    model, so we can FORCE romanised (Latin-script) Hinglish output. whisper-1
//    and the streaming gpt-realtime-whisper ignore/disallow the prompt and emit
//    Devanagari for Hindi speech; gpt-4o-mini-transcribe follows it weakly.
//    Change this if your account uses another id.
const HINGLISH_TRANSCRIBE_MODEL = 'gpt-4o-transcribe';
const HINGLISH_TRANSCRIBE_PROMPT =
  'The speaker talks in Hinglish (a casual Hindi-English mix). Transcribe it ONLY ' +
  'in Roman/Latin (English) script — never Devanagari. Keep English words in English. ' +
  'Example style: "mera laptop overheat ho raha hai aur ye band ho jaata hai".';

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
let chatMode = false;
let chatThreadId = null;
let chatBusy = false;
// The last utterance we actually dispatched to the backend in voice mode. Reset
// to null at the start of every genuine user turn (speech or typed). Guards
// against the realtime model re-emitting run_wwts with no fresh caller input,
// which would otherwise march the scripted agent forward on its own.
let lastSentUserMessage = null;
// Resolves when the in-flight user transcription completes. The realtime model
// can fire a run_wwts tool call before whisper finishes transcribing the
// caller's speech; we await this so the backend gets the FULL utterance (with
// the symptom and product reference) instead of an early fragment.
let userTurnPending = null;
let resolveUserTurn = null;
let userTurnTranscriptionFinalized = true;
// Grace timer for a transient WebRTC 'disconnected' state before we end the call.
let connDropTimer = null;
// ISO timestamp for when the current call/chat session started — saved with the
// transcript when the session ends.
let sessionStartedAt = null;

function byId(id) {
  return document.getElementById(id);
}

function setText(id, text) {
  const el = byId(id);
  if (el) el.textContent = text;
}

function setDisplay(id, value) {
  const el = byId(id);
  if (el) el.style.display = value;
}

function addClass(id, className) {
  byId(id)?.classList.add(className);
}

function setActiveTool(text) {
  setText('info-active-tool', text);
}

function getAgentId() {
  return byId('agent-id')?.value || 'wwts';
}

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
  const wrap = byId('avatar-wrap');
  const statusEl = byId('agent-status');
  const labels = {
    idle: 'Idle',
    listening: 'Listening',
    speaking: 'Speaking',
    thinking: 'Thinking',
  };
  const label = labels[state] || 'Idle';
  setText('info-agent-state', label);
  setText('voice-rail-state', label);

  const visual = (state === 'speaking' || state === 'thinking' || state === 'listening') ? state : 'idle';
  if (wrap) wrap.className = `avatar-wrap state-${visual}`;

  if (!statusEl) return;
  statusEl.textContent = '';
  statusEl.className = 'agent-status';
  if (state === 'speaking') {
    statusEl.textContent = 'Speaking';
  } else if (state === 'thinking') {
    statusEl.textContent = 'Thinking';
    statusEl.classList.add('thinking');
  }
}

function setCallUI(inCall) {
  const dock = byId('call-dock');
  dock?.classList.toggle('in-call', inCall);
  setDisplay('pre-call-settings', inCall ? 'none' : '');
  const timer = byId('call-timer');
  timer?.classList.toggle('idle', !inCall);
  if (!inCall && timer) timer.textContent = 'Ready to connect';
}

function updateAgentDisplay() {
  const id = getAgentId();
  const meta = AGENT_LABELS[id] || { name: id, sub: 'Voice Assistant' };
  setText('agent-display-name', meta.name);
  const sub = document.querySelector('.agent-sub');
  if (sub) sub.textContent = meta.sub;
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
  const panel = byId('insight-panel');
  const open = panel?.classList.toggle('open') || false;
  byId('panel-toggle')?.setAttribute('aria-expanded', String(open));
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

function startUserViz() {
  setAvatarState('listening');
}

function startAiViz() {
  if (vizAnimId) { cancelAnimationFrame(vizAnimId); vizAnimId = null; }
  setAvatarState('speaking');
}

function hideViz() {
  if (vizAnimId) { cancelAnimationFrame(vizAnimId); vizAnimId = null; }
  if (!sessionId) setAvatarState('idle');
  else setAvatarState('listening');
}

function destroyViz() {
  hideViz();
  if (audioCtx) { try { audioCtx.close(); } catch {} audioCtx = null; }
  analyser = null;
}

function startProcessingViz() {
  if (vizAnimId) { cancelAnimationFrame(vizAnimId); vizAnimId = null; }
  setAvatarState('thinking');
  setActiveTool('Running…');
}

function detectWorkOrder(text) {
  const m = String(text).match(/\b[A-Z]{2}\d{6,}\b/i);
  if (m) {
    sessionWorkOrder = m[0].toUpperCase();
    setText('info-work-order', sessionWorkOrder);
  }
}

function detectIntent(text) {
  const t = String(text).toLowerCase();
  if (/work order|workorder/.test(t)) {
    sessionIntent = 'Work order inquiry';
    setText('info-intent', sessionIntent);
  }
}

async function startCall() {
  if (sessionId || chatMode) return;
  setStatus('connecting');
  setBtnEnabled('start', false);
  setBtnEnabled('chat', false);
  clearError();
  clearTranscript();
  setAvatarState('thinking');

  try {
    const sessResp = await fetch('/voice/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agent_id: getAgentId(),
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
      const st = pc?.connectionState;
      if (st === 'connected') {
        if (connDropTimer) { clearTimeout(connDropTimer); connDropTimer = null; }
        return;
      }
      if (st === 'failed') {
        if (connDropTimer) { clearTimeout(connDropTimer); connDropTimer = null; }
        showError('The voice connection dropped. Please try again.');
        stopCall();
        return;
      }
      if (st === 'disconnected' && !connDropTimer) {
        // 'disconnected' is usually a brief, self-recovering ICE hiccup — DON'T
        // end the call immediately (that caused random shutdowns). Give it a
        // grace window; only end if it hasn't reconnected by then.
        connDropTimer = setTimeout(() => {
          connDropTimer = null;
          if (sessionId && pc && pc.connectionState !== 'connected') {
            showError('The voice connection was lost.');
            stopCall();
          }
        }, 8000);
      }
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
    sessionStartedAt = new Date().toISOString();
    startTimer();
    setCallUI(true);
    setAvatarState('listening');
    document.getElementById('text-input-field').disabled = false;
    document.getElementById('btn-send-text').disabled = false;
    addClass('insight-panel', 'open');
    showToast('You’re connected. Start speaking anytime.');
  } catch (err) {
    showError(err.message);
    setStatus('error');
    setBtnEnabled('start', true);
    setBtnEnabled('chat', true);
    setAvatarState('idle');
    cleanup();
  }
}

function startChat() {
  if (sessionId || chatMode) return;
  clearTranscript();
  chatMode = true;
  chatBusy = false;
  sessionStartedAt = new Date().toISOString();
  chatThreadId = (window.crypto && crypto.randomUUID)
    ? crypto.randomUUID()
    : `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  setStatus('connected');
  setCallUI(true);
  document.getElementById('call-dock').classList.add('chat-mode');
  document.getElementById('btn-mute').style.display = 'none';
  document.getElementById('call-timer').textContent = 'Chat session';
  document.getElementById('text-input-field').disabled = false;
  document.getElementById('btn-send-text').disabled = false;
  addClass('insight-panel', 'open');
  setAvatarState('idle');
  // Let the backend agent open the conversation (greet + ask the caller's name).
  postChat('hello', { renderUser: false });
  document.getElementById('text-input-field').focus();
}

function applyAgentState(data) {
  if (data.intent) {
    sessionIntent = formatToolName(String(data.intent));
    setText('info-intent', sessionIntent);
  }
  const wo = data.wo_number || data.created_wo_number;
  if (wo) {
    sessionWorkOrder = String(wo);
    setText('info-work-order', sessionWorkOrder);
  }
  if (data.session_expired) {
    showError('Your WWTS session has expired. Please sign out and log in again.');
  }
}

async function postChat(text, { renderUser = true } = {}) {
  if (!text || chatBusy) return;
  if (renderUser) {
    finaliseText(addMsg('user', ''), text);
    detectWorkOrder(text);
    detectIntent(text);
  }
  chatBusy = true;
  setAvatarState('thinking');
  const aiEl = addMsg('ai', '');
  aiEl.querySelector('.body').textContent = '…';

  try {
    const res = await fetch('/agents/wwts/invoke', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text,
        thread_id: chatThreadId,
        user_id: document.getElementById('user-id').value
          || (authContext && authContext.userId) || '',
        context: buildSessionContext(),
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    finaliseText(aiEl, data.answer || data.speak || '(no response)');
    applyAgentState(data);
  } catch (err) {
    finaliseText(aiEl, 'Sorry — I could not reach the assistant. Please try again.');
    showError(err.message);
  } finally {
    chatBusy = false;
    setAvatarState('idle');
    document.getElementById('text-input-field').focus();
  }
}

function sendChatTurn() {
  const input = document.getElementById('text-input-field');
  const text = input.value.trim();
  if (!text || chatBusy) return;
  input.value = '';
  postChat(text, { renderUser: true });
}

function collectTurns() {
  return [...document.querySelectorAll('#transcript .caption-line')]
    .map((el) => ({
      role: el.classList.contains('user') ? 'user' : 'agent',
      text: (el.querySelector('.body')?.textContent || '').trim(),
    }))
    .filter((t) => t.text);
}

function saveTranscript(turns, mode) {
  if (!turns || !turns.length) return;
  const ctx = authContext || {};
  fetch('/transcripts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      turns,
      mode,
      agent_id: getAgentId(),
      user_id: document.getElementById('user-id').value || ctx.userId || '',
      user_name: ctx.userName || ctx.userId || '',
      started_at: sessionStartedAt || new Date().toISOString(),
      ended_at: new Date().toISOString(),
    }),
  })
    .then((res) => {
      if (res.ok) showToast('Transcript saved.');
    })
    .catch(() => { /* non-blocking */ });
}

function stopCall() {
  // Snapshot and persist the conversation before any teardown clears it. Only
  // when a session is actually active, so repeat/spurious calls don't re-save.
  if (sessionId || chatMode) {
    saveTranscript(collectTurns(), chatMode ? 'chat' : 'voice');
  }
  sessionStartedAt = null;

  // Tear down a live voice session if there is one. Done unconditionally (not in
  // an else) so End always works even if chat mode also got toggled on.
  if (sessionId) {
    fetch(`/voice/session/${sessionId}/end`, { method: 'POST' }).catch(() => {});
    cleanup();
    sessionId = null;
    stopTimer();
  }
  // Tear down a chat session if there is one.
  if (chatMode) {
    chatMode = false;
    chatThreadId = null;
    chatBusy = false;
  }
  document.getElementById('call-dock').classList.remove('chat-mode');
  document.getElementById('btn-mute').style.display = '';
  isMuted = false;
  document.getElementById('btn-mute').classList.remove('muted');
  setStatus('disconnected');
  setCallUI(false);
  document.getElementById('text-input-field').disabled = true;
  document.getElementById('btn-send-text').disabled = true;
  setBtnEnabled('start', true);
  setBtnEnabled('chat', true);
  setAvatarState('idle');
  setActiveTool('—');
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
  lastSentUserMessage = null;
  if (resolveUserTurn) resolveUserTurn();
  userTurnPending = null;
  resolveUserTurn = null;
  userTurnTranscriptionFinalized = true;
  if (connDropTimer) { clearTimeout(connDropTimer); connDropTimer = null; }
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
  if (chatMode) { sendChatTurn(); return; }
  const input = document.getElementById('text-input-field');
  const text = input.value.trim();
  if (!text || !sessionId || !dc || dc.readyState !== 'open') return;
  input.value = '';
  const userEl = addMsg('user', text);
  finaliseText(userEl, text);
  lastTranscript = text;
  lastSentUserMessage = null;
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
  if (e.key === 'Enter' && (sessionId || chatMode)) sendTextMessage();
});

function onDataChannelOpen() {
  const transcription = isHinglish()
    ? { model: HINGLISH_TRANSCRIBE_MODEL, prompt: HINGLISH_TRANSCRIBE_PROMPT }
    : { model: 'gpt-realtime-whisper', language: 'en' };
  dc.send(JSON.stringify({
    type: 'session.update',
    session: {
      type: 'realtime',
      input_audio_transcription: transcription,
      turn_detection: {
        type: 'server_vad',
        // Higher threshold + longer required silence so background noise / room
        // tone doesn't trip a "speech" segment that the transcriber then
        // hallucinates into phantom phrases ("See ya.", "Thanks for watching").
        threshold: 0.9,
        prefix_padding_ms: 300,
        silence_duration_ms: 1400,
      },
    },
  }));
  // Greet on connect: seed an opening turn so the backend agent greets the
  // caller and asks for their name before they have to say anything.
  dc.send(JSON.stringify({
    type: 'conversation.item.create',
    item: { type: 'message', role: 'user', content: [{ type: 'input_text', text: 'hello' }] },
  }));
  dc.send(JSON.stringify({ type: 'response.create' }));
}

// Phrases speech-to-text models emit from silence/noise (YouTube-caption
// training residue). When one of these is the WHOLE utterance, it's almost
// certainly a phantom — drop it rather than treat it as a real turn.
const _HALLUCINATION_PHRASES = new Set([
  'see ya', 'see you', 'see you next time', 'thanks for watching',
  'thank you for watching', 'thanks for watching', 'please subscribe',
  'subscribe', 'like and subscribe', 'you', 'bye', 'bye bye', 'bye-bye',
  'goodbye', 'thank you', 'thanks', 'thank you so much', 'thanks a lot',
  'subtitles by the amara org community', 'transcription by castingwords',
]);

function isLikelyHallucination(text) {
  const norm = String(text || '').toLowerCase().replace(/[^\w\s]/g, '').replace(/\s+/g, ' ').trim();
  if (!norm) return true;
  return _HALLUCINATION_PHRASES.has(norm);
}

// Best-effort Devanagari → Roman transliteration. Realtime transcription often
// ignores the romanise prompt and returns Hindi in Devanagari; we romanise it
// ourselves so Hinglish captions (and the text sent to the backend) are always
// Latin-script. ASCII passes through unchanged, so it's safe to always apply.
const _DEVA_VOWEL = { 'अ':'a','आ':'aa','इ':'i','ई':'ii','उ':'u','ऊ':'uu','ऋ':'ri','ए':'e','ऐ':'ai','ओ':'o','औ':'au','ं':'n','ः':'h','ँ':'n','ॐ':'om' };
const _DEVA_MATRA = { 'ा':'aa','ि':'i','ी':'ii','ु':'u','ू':'uu','ृ':'ri','े':'e','ै':'ai','ो':'o','ौ':'au' };
const _DEVA_CONS = {
  'क':'k','ख':'kh','ग':'g','घ':'gh','ङ':'ng','च':'ch','छ':'chh','ज':'j','झ':'jh','ञ':'ny',
  'ट':'t','ठ':'th','ड':'d','ढ':'dh','ण':'n','त':'t','थ':'th','द':'d','ध':'dh','न':'n',
  'प':'p','फ':'ph','ब':'b','भ':'bh','म':'m','य':'y','र':'r','ल':'l','व':'v','श':'sh',
  'ष':'sh','स':'s','ह':'h','क़':'q','ख़':'kh','ग़':'g','ज़':'z','ड़':'r','ढ़':'rh','फ़':'f','य़':'y',
};
const _DEVA_DIGIT = { '०':'0','१':'1','२':'2','३':'3','४':'4','५':'5','६':'6','७':'7','८':'8','९':'9' };

function devanagariToRoman(text) {
  const s = String(text || '');
  if (!/[ऀ-ॿ]/.test(s)) return s; // no Devanagari → leave as-is
  const chars = [...s];
  let out = '';
  for (let i = 0; i < chars.length; i++) {
    const ch = chars[i];
    if (_DEVA_CONS[ch] !== undefined) {
      out += _DEVA_CONS[ch];
      const next = chars[i + 1];
      if (next === '्') { i++; }                         // virama: suppress vowel
      else if (_DEVA_MATRA[next] !== undefined) { out += _DEVA_MATRA[next]; i++; }
      else {
        // Inherent 'a', except drop it word-finally (Hindi schwa deletion) so
        // नाम → "naam" not "naama". Word end = next char is non-Devanagari/space/end.
        const wordEnd = next === undefined || !/[ऀ-ॿ]/.test(next);
        if (!wordEnd) out += 'a';
      }
    } else if (_DEVA_VOWEL[ch] !== undefined) {
      out += _DEVA_VOWEL[ch];
    } else if (_DEVA_MATRA[ch] !== undefined) {
      out += _DEVA_MATRA[ch];
    } else if (_DEVA_DIGIT[ch] !== undefined) {
      out += _DEVA_DIGIT[ch];
    } else if (ch === '्' || ch === '॰' || ch === 'ऽ') {
      /* drop standalone virama / abbreviation / avagraha */
    } else {
      out += ch;                                          // ASCII, space, punct
    }
  }
  return out;
}

function handleEvent(event) {
  switch (event.type) {
    case 'input_audio_buffer.speech_started':
      lastTranscript = '';
      lastSentUserMessage = null;
      toolCallActive = false;
      userTurnTranscriptionFinalized = false;
      // Arm a fresh waiter for this turn's transcription result.
      if (resolveUserTurn) resolveUserTurn();
      userTurnPending = new Promise((res) => { resolveUserTurn = res; });
      if (isAiResponding) {
        dc.send(JSON.stringify({ type: 'response.cancel' }));
        isAiResponding = false;
        currentAiEl = null;
      }
      startUserViz();
      // Don't create the bubble yet — wait for an actual transcript delta/result,
      // so a speech segment that turns out to be silence/noise leaves no empty
      // phantom bubble behind. The delta/completed handlers create it lazily.
      break;

    case 'conversation.item.input_audio_transcription.delta':
      // Arm the waiter here too, in case deltas arrive without a preceding
      // speech_started — so a tool call still waits for the completed transcript.
      userTurnTranscriptionFinalized = false;
      if (!userTurnPending) userTurnPending = new Promise((res) => { resolveUserTurn = res; });
      if (!currentUserEl) currentUserEl = addMsg('user', '');
      appendText(currentUserEl, event.delta || '');
      break;

    case 'conversation.item.input_audio_transcription.completed': {
      let transcript = (event.transcript || '').trim();
      if (isHinglish()) transcript = devanagariToRoman(transcript);
      // Drop phantom transcripts produced from silence/noise: remove the bubble
      // and cancel any response the model started generating for the phantom.
      if (isLikelyHallucination(transcript)) {
        if (currentUserEl) {
          currentUserEl.remove();
          currentUserEl = null;
          msgCount = Math.max(0, msgCount - 1);
        }
        lastTranscript = '';
        lastSentUserMessage = null;
        userTurnTranscriptionFinalized = true;
        if (resolveUserTurn) { resolveUserTurn(); resolveUserTurn = null; userTurnPending = null; }
        if (isAiResponding) {
          try { dc.send(JSON.stringify({ type: 'response.cancel' })); } catch {}
          isAiResponding = false;
          if (currentAiEl) { currentAiEl.remove(); currentAiEl = null; }
        }
        hideViz();
        break;
      }
      lastTranscript = transcript;
      if (!currentUserEl) currentUserEl = addMsg('user', '');
      finaliseText(currentUserEl, lastTranscript);
      currentUserEl = null;
      userTurnTranscriptionFinalized = true;
      // Unblock any tool dispatch waiting on this turn's finalized transcript.
      if (resolveUserTurn) { resolveUserTurn(); resolveUserTurn = null; userTurnPending = null; }
      detectWorkOrder(lastTranscript);
      detectIntent(lastTranscript);
      hideViz();
      break;
    }

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

function getLatestUserUtterance({ allowLive = true } = {}) {
  if (lastTranscript && String(lastTranscript).trim()) return String(lastTranscript).trim();
  if (!allowLive) return '';
  if (currentUserEl) {
    const live = currentUserEl.querySelector('.body')?.textContent?.trim();
    if (live) return live;
  }
  const bubbles = document.querySelectorAll('.caption-line.user .body');
  if (bubbles.length) {
    const latest = bubbles[bubbles.length - 1]?.textContent?.trim();
    if (latest) return latest;
  }
  return '';
}

async function waitForFinalUserTranscript(timeoutMs = 10000) {
  if (!userTurnPending) return userTurnTranscriptionFinalized;
  await Promise.race([
    userTurnPending,
    new Promise((r) => setTimeout(r, timeoutMs)),
  ]);
  return userTurnTranscriptionFinalized;
}

async function handleToolCalls(outputs) {
  const calls = outputs.filter((item) => item.type === 'function_call');
  if (!calls.length) return;

  // The model often fires the tool call before whisper finishes transcribing the
  // caller. Wait for the finalized transcript so the backend gets the full
  // utterance — symptom + product reference — not an early fragment.
  const transcriptReady = await waitForFinalUserTranscript();

  startHoldSound();
  startProcessingViz();
  toolCallActive = true;
  let advanced = false;

  for (const item of calls) {
    let args = {};
    try { args = JSON.parse(item.arguments || '{}'); } catch {}
    const userMsg = getLatestUserUtterance({ allowLive: transcriptReady }) ||
      (transcriptReady ? (args.user_message || '') : '');

    if (!userMsg) {
      dc.send(JSON.stringify({
        type: 'conversation.item.create',
        item: {
          type: 'function_call_output',
          call_id: item.call_id,
          output: JSON.stringify({ answer: '', speak: '' }),
        },
      }));
      continue;
    }

    // The realtime model can re-emit run_wwts with no fresh caller input (mic
    // noise, or the model nudging another call after reading the result). Never
    // advance the backend script on a repeat of the message we just sent —
    // acknowledge the call with an empty result and skip the follow-up
    // response.create, so the agent waits for the caller instead of replying to
    // itself and marching through the script.
    if (userMsg && userMsg === lastSentUserMessage) {
      dc.send(JSON.stringify({
        type: 'conversation.item.create',
        item: {
          type: 'function_call_output',
          call_id: item.call_id,
          output: JSON.stringify({ answer: '', speak: '' }),
        },
      }));
      continue;
    }

    args.user_message = userMsg;
    lastSentUserMessage = userMsg;
    advanced = true;

    setActiveTool(formatToolName(item.name));
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
  setActiveTool('—');
  hideViz();

  // Only ask the model to speak again when we actually relayed a fresh result.
  // If every call was a no-input repeat, stay silent and wait for the caller.
  if (toolCallActive && advanced) {
    dc.send(JSON.stringify({ type: 'response.create' }));
  }
  toolCallActive = false;
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
  const toolEntries = byId('tool-entries');
  if (toolEntries) toolEntries.innerHTML = '';
  setDisplay('timeline-empty', '');
  msgCount = 0;
  toolCount = 0;
  sessionWorkOrder = '';
  sessionIntent = '';
  setText('info-intent', '—');
  setText('info-work-order', '—');
  setActiveTool('—');
  currentUserEl = null;
  currentAiEl = null;
  lastTranscript = '';
  lastSentUserMessage = null;
  aiTranscriptFinalized = false;
  toolCallActive = false;
}

function addToolEntry(dir, name, detail) {
  toolCount++;
  setDisplay('timeline-empty', 'none');

  const card = document.createElement('article');
  card.className = `timeline-card ${dir}`;
  const ts = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const title = formatToolName(name);
  const summary = dir === 'out' ? 'Requested' : dir === 'in' ? 'Completed' : 'Issue';

  card.innerHTML =
    `<div class="timeline-card-head"><strong>${esc(title)}</strong><time>${esc(ts)}</time></div>` +
    `<p><em>${esc(summary)}</em> — ${esc(String(detail).slice(0, 140))}</p>`;

  byId('tool-entries')?.prepend(card);
  addClass('insight-panel', 'open');

  if (dir === 'out') {
    setActiveTool(title);
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

function isHinglish() {
  return localStorage.getItem('wwts_hinglish') === '1';
}

function setHinglish(on) {
  localStorage.setItem('wwts_hinglish', on ? '1' : '0');
  showToast(on
    ? 'Hinglish on — replies and transcription in romanised Hinglish (from your next call).'
    : 'Hinglish off.');
}

function buildSessionContext() {
  if (!authContext) return { hinglish: isHinglish() };
  return {
    hinglish: isHinglish(),
    wwts_session: authContext.session,
    user_id: authContext.userId,
    env: authContext.env,
    source: authContext.source,
    version: authContext.version,
    expire_days: authContext.expireDays,
    customer_codes: authContext.customerCodes || [],
    authorized_functions: authContext.authorizedFunctions || [],
    user_name: authContext.userName || '',
    user_type: authContext.userType || '',
  };
}

function initAuthUI() {
  if (!authContext) return;
  document.getElementById('user-id').value = authContext.userId || '';
  const userLabel = authContext.userName || authContext.userId || 'User';
  document.getElementById('auth-user').textContent = userLabel;
  document.getElementById('profile-initials').textContent =
    userLabel.slice(0, 2).toUpperCase();

  if (authContext.session) {
    const sel = byId('agent-id');
    if (sel) {
      sel.value = 'wwts';
      sel.disabled = true;
    }
  }
  updateAgentDisplay();
}

byId('agent-id')?.addEventListener('change', updateAgentDisplay);

function initHinglishToggle() {
  const cb = byId('hinglish-toggle');
  if (cb) cb.checked = isHinglish();
}

initAuthUI();
initHinglishToggle();

function logout() {
  if (sessionId) stopCall();
  WwtsAuth.clearAuthContext();
  window.location.replace('/login');
}

window.startCall = startCall;
window.startChat = startChat;
window.stopCall = stopCall;
window.toggleMute = toggleMute;
window.sendTextMessage = sendTextMessage;
window.toggleInsightPanel = toggleInsightPanel;
window.setHinglish = setHinglish;
window.logout = logout;
