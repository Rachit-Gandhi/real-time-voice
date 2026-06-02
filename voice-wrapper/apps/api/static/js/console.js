'use strict';

if (!WwtsAuth.requireAuth('/login')) {
  // Redirecting to login
}

const authContext = WwtsAuth.getAuthContext();

const EMPTY_STATE_HTML = `
  <div class="empty-state" id="empty-state">
    <div class="empty-orb" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
        <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
      </svg>
    </div>
    <h3>Ready when you are</h3>
    <p>Choose an agent and start a call. Your microphone will connect to a realtime voice session with live transcription.</p>
    <p class="empty-hint">Press Start call · or type below once connected</p>
  </div>`;

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

function setVoiceStrip(mode) {
  const strip = document.getElementById('voice-strip');
  if (!mode) {
    strip.className = 'voice-strip';
    return;
  }
  strip.className = `voice-strip active ${mode}`;
}

function setCallUI(inCall) {
  document.getElementById('btn-start').classList.toggle('hidden', inCall);
  document.getElementById('btn-stop').classList.toggle('visible', inCall);
  document.getElementById('btn-mute').classList.toggle('visible', inCall);
}

function syncTranscriptState() {
  const box = document.getElementById('transcript');
  const hasMessages = msgCount > 0;
  box.classList.toggle('has-messages', hasMessages);
  const empty = document.getElementById('empty-state');
  if (empty) empty.classList.toggle('hidden', hasMessages);
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
    _holdGain.gain.linearRampToValueAtTime(0.08, now + 0.04);
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
  timerInterval = setInterval(() => {
    const s = Math.floor((Date.now() - timerStart) / 1000);
    const mm = String(Math.floor(s / 60)).padStart(2, '0');
    const ss = String(s % 60).padStart(2, '0');
    document.getElementById('session-timer').textContent = `${mm}:${ss}`;
  }, 1000);
}

function stopTimer() {
  if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }
  document.getElementById('session-timer').textContent = '';
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
  const N = Math.min(14, buf.length);
  const barW = 4;
  const gap = 2;
  for (let i = 0; i < N; i++) {
    const val = buf[i] / 255;
    const h = Math.max(3, val * canvas.height);
    const x = i * (barW + gap);
    const y = canvas.height - h;
    const alpha = 0.35 + val * 0.65;
    ctx.fillStyle = `rgba(110, 201, 168, ${alpha})`;
    if (ctx.roundRect) {
      ctx.beginPath();
      ctx.roundRect(x, y, barW, h, 1);
      ctx.fill();
    } else {
      ctx.fillRect(x, y, barW, h);
    }
  }
  vizAnimId = requestAnimationFrame(drawViz);
}

function startUserViz() {
  document.getElementById('vs-label').textContent = 'Listening';
  setVoiceStrip('user-speaking');
  if (analyser && !vizAnimId) drawViz();
}

function startAiViz() {
  if (vizAnimId) { cancelAnimationFrame(vizAnimId); vizAnimId = null; }
  document.getElementById('vs-label').textContent = 'Speaking';
  setVoiceStrip('ai-speaking');
}

function hideViz() {
  if (vizAnimId) { cancelAnimationFrame(vizAnimId); vizAnimId = null; }
  setVoiceStrip('');
  const canvas = document.getElementById('viz-canvas');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
}

function destroyViz() {
  hideViz();
  if (audioCtx) { try { audioCtx.close(); } catch {} audioCtx = null; }
  analyser = null;
}

function startProcessingViz() {
  if (vizAnimId) { cancelAnimationFrame(vizAnimId); vizAnimId = null; }
  document.getElementById('vs-label').textContent = 'Processing';
  setVoiceStrip('processing');
}

async function startCall() {
  setStatus('connecting');
  setBtnEnabled('start', false);
  clearError();
  clearTranscript();

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

    document.getElementById('session-info').textContent =
      `Session ${sessionId.slice(0, 8)}…`;

    if (!secret) throw new Error('No client_secret — check OPENAI_API_KEY in voice-wrapper .env');

    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      throw new Error('Microphone access denied — please allow mic access and try again.');
    }

    initViz(micStream);

    pc = new RTCPeerConnection();

    pc.ontrack = (e) => {
      const audio = document.getElementById('remote-audio');
      if (e.streams[0]) audio.srcObject = e.streams[0];
    };

    pc.onconnectionstatechange = () => {
      if (pc?.connectionState === 'failed') showError('WebRTC connection failed.');
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
      const body = await sdpResp.text();
      throw new Error(`OpenAI rejected SDP (${sdpResp.status}): ${body}`);
    }

    await pc.setRemoteDescription({ type: 'answer', sdp: await sdpResp.text() });

    setStatus('connected');
    startTimer();
    setCallUI(true);
    document.getElementById('text-input-field').disabled = false;
    document.getElementById('btn-send-text').disabled = false;
  } catch (err) {
    showError(err.message);
    setStatus('error');
    setBtnEnabled('start', true);
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
  document.getElementById('session-info').textContent = '';
  setCallUI(false);
  isMuted = false;
  const btnMute = document.getElementById('btn-mute');
  btnMute.classList.remove('muted');
  document.getElementById('text-input-field').disabled = true;
  document.getElementById('btn-send-text').disabled = true;
  setBtnEnabled('start', true);
  hideViz();
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
  isMuted = false;
  document.getElementById('text-input-field').disabled = true;
  document.getElementById('btn-send-text').disabled = true;
  stopHoldSound();
}

function setMicEnabled(enabled) {
  if (micStream) micStream.getAudioTracks().forEach((t) => { t.enabled = enabled; });
}

function toggleMute() {
  isMuted = !isMuted;
  setMicEnabled(!isMuted);
  const btn = document.getElementById('btn-mute');
  btn.classList.toggle('muted', isMuted);
  btn.innerHTML = isMuted
    ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><line x1="1" y1="1" x2="23" y2="23"/></svg> Unmute'
    : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/></svg> Mute';
}

function sendTextMessage() {
  const input = document.getElementById('text-input-field');
  const text = input.value.trim();
  if (!text || !sessionId || !dc || dc.readyState !== 'open') return;
  input.value = '';

  const userEl = addMsg('user', text);
  finaliseText(userEl, text);
  lastTranscript = text;

  dc.send(JSON.stringify({
    type: 'conversation.item.create',
    item: {
      type: 'message',
      role: 'user',
      content: [{ type: 'input_text', text }],
    },
  }));
  dc.send(JSON.stringify({ type: 'response.create' }));
  input.focus();
}

document.getElementById('text-input-field').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && sessionId) sendTextMessage();
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
          updateMsgCount();
          syncTranscriptState();
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
      addToolEntry('in', item.name, data.speak || data.answer || JSON.stringify(data));
      outputPayload = JSON.stringify({
        answer: data.answer || data.speak || '',
        speak: data.speak || data.answer || '',
      });
    } catch (err) {
      addToolEntry('err', item.name, err.message);
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
  hideViz();

  if (toolCallActive) {
    dc.send(JSON.stringify({ type: 'response.create' }));
    toolCallActive = false;
  }
}

function addMsg(role, text) {
  const box = document.getElementById('transcript');

  const wrap = document.createElement('div');
  wrap.className = `msg ${role}`;

  const meta = document.createElement('div');
  meta.className = 'msg-meta';

  const badge = document.createElement('span');
  badge.className = 'msg-badge';
  badge.textContent = role === 'user' ? 'You' : 'Agent';

  const ts = document.createElement('span');
  ts.className = 'msg-ts';
  ts.textContent = new Date().toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });

  meta.appendChild(badge);
  meta.appendChild(ts);

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble body streaming';
  bubble.textContent = text;

  wrap.appendChild(meta);
  wrap.appendChild(bubble);
  box.appendChild(wrap);
  box.scrollTop = box.scrollHeight;

  msgCount++;
  updateMsgCount();
  syncTranscriptState();

  return wrap;
}

function appendText(wrap, delta) {
  wrap.querySelector('.body').textContent += delta;
  const box = document.getElementById('transcript');
  box.scrollTop = box.scrollHeight;
}

function finaliseText(wrap, text) {
  const bubble = wrap.querySelector('.body');
  bubble.classList.remove('streaming');
  bubble.textContent = text;
}

function updateMsgCount() {
  document.getElementById('msg-count').textContent =
    msgCount ? `${msgCount} message${msgCount !== 1 ? 's' : ''}` : '';
}

function clearTranscript() {
  const box = document.getElementById('transcript');
  box.innerHTML = EMPTY_STATE_HTML;
  box.classList.remove('has-messages');
  document.getElementById('tool-entries').innerHTML = '';
  msgCount = 0;
  toolCount = 0;
  updateMsgCount();
  const badge = document.getElementById('tool-badge');
  badge.textContent = '0';
  badge.classList.remove('has-items');
  document.getElementById('tool-panel').classList.remove('open');
  document.getElementById('tool-toggle-fab').classList.remove('visible', 'has-items');
  currentUserEl = null;
  currentAiEl = null;
  lastTranscript = '';
  aiTranscriptFinalized = false;
  toolCallActive = false;
}

function toggleToolPanel() {
  const panel = document.getElementById('tool-panel');
  const open = panel.classList.toggle('open');
  document.getElementById('tool-toggle-fab').setAttribute('aria-expanded', String(open));
}

function addToolEntry(dir, name, detail) {
  toolCount++;
  const badge = document.getElementById('tool-badge');
  badge.textContent = toolCount;
  badge.classList.add('has-items');

  const fab = document.getElementById('tool-toggle-fab');
  fab.classList.add('visible', 'has-items');

  const entry = document.createElement('div');
  entry.className = 'tool-entry';
  const ts = new Date().toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
  const arrowCls = dir === 'out' ? 'te-out' : dir === 'in' ? 'te-in' : 'te-err';
  const arrow = dir === 'out' ? '→' : dir === 'in' ? '←' : '⚠';

  entry.innerHTML =
    `<span class="te-ts">${esc(ts)}</span> ` +
    `<span class="${arrowCls}">${arrow}</span> ` +
    `<span class="te-name">${esc(name)}</span>` +
    `<span class="te-value"> ${esc(String(detail).slice(0, 120))}</span>`;

  const container = document.getElementById('tool-entries');
  container.appendChild(entry);
  container.scrollTop = container.scrollHeight;

  if (toolCount === 1) {
    document.getElementById('tool-panel').classList.add('open');
    fab.setAttribute('aria-expanded', 'true');
  }
}

function setStatus(s) {
  document.getElementById('status-dot').className = `status-dot ${s}`;
  document.getElementById('status-label').textContent = s;
}

function setBtnEnabled(which, enabled) {
  document.getElementById(`btn-${which}`).disabled = !enabled;
}

function showError(msg) {
  document.getElementById('error-text').textContent = msg;
  document.getElementById('error-banner').classList.add('visible');
}

function clearError() {
  document.getElementById('error-text').textContent = '';
  document.getElementById('error-banner').classList.remove('visible');
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

if (authContext) {
  document.getElementById('user-id').value = authContext.userId || '';
  const label = [authContext.userId, authContext.env].filter(Boolean).join(' · ');
  document.getElementById('auth-user').textContent = label;
  document.getElementById('auth-chip').classList.add('visible');
  if (authContext.session) {
    const sel = document.getElementById('agent-id');
    sel.value = 'wwts';
    sel.disabled = true;
  }
}

function logout() {
  if (sessionId) stopCall();
  WwtsAuth.clearAuthContext();
  window.location.replace('/login');
}

// Expose handlers for inline onclick attributes
window.startCall = startCall;
window.stopCall = stopCall;
window.toggleMute = toggleMute;
window.sendTextMessage = sendTextMessage;
window.toggleToolPanel = toggleToolPanel;
window.logout = logout;
