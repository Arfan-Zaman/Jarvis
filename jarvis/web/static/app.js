'use strict';

/* JARVIS interface. Plain JavaScript, no dependencies, no build step.
   All content is inserted as text nodes, never as HTML. */

const $ = (selector) => document.querySelector(selector);
const state = { projects: [], conversationId: null, timer: null, navigation: 0, cleanup: [] };

// --- helpers ---------------------------------------------------------------
// Pictures JARVIS made: a workspace image path in a reply is shown as the picture itself.
const WORKSPACE_IMAGE = /workspace\/(images\/[\w.-]+\.(?:png|jpe?g|webp|gif))/gi;
function workspaceImages(text) {
  const names = [...new Set([...String(text || '').matchAll(WORKSPACE_IMAGE)].map((m) => m[1]))];
  return names.length ? h('div', { class: 'msg-images' }, names.map((name) =>
    h('a', { href: `/api/files/${name}`, target: '_blank', rel: 'noopener' },
      h('img', { src: `/api/files/${name}`, alt: 'Picture made by JARVIS', loading: 'lazy',
        style: 'max-width:100%;max-height:420px;border-radius:10px;margin-top:8px;display:block' })))) : null;
}

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  attrs = attrs || {};
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false || key === 'value') continue;
    if (key === 'class') el.className = value;
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  if (attrs.value !== undefined && attrs.value !== null) el.value = attrs.value;
  return el;
}

async function api(method, path, body) {
  const response = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function toast(message, isError) {
  const el = h('div', { class: 'toast' + (isError ? ' error' : '') }, message);
  $('#toasts').append(el);
  setTimeout(() => el.remove(), isError ? 7000 : 3000);
}

/** Run an async action, showing any failure instead of swallowing it. */
function act(fn) {
  return async (...args) => {
    try { return await fn(...args); } catch (error) { toast(error.message, true); }
  };
}

function when(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

function bytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

const label = (value) => String(value).replace(/_/g, ' ');
const chip = (text, tone) => h('span', { class: 'chip' + (tone ? ' ' + tone : '') }, text);
const projectName = (id) => (state.projects.find((p) => p.id === id) || {}).name;

function dialog({ title, text, note, okLabel, danger, input }) {
  const box = $('#confirm');
  $('#confirm-title').textContent = title;
  $('#confirm-text').textContent = text || '';
  $('#confirm-note').textContent = note || '';
  const field = $('#confirm-input');
  field.hidden = !input;
  field.value = '';
  field.placeholder = input || '';
  const ok = $('#confirm-ok');
  ok.textContent = okLabel || 'Confirm';
  ok.className = 'btn ' + (danger ? 'danger' : 'primary');
  return new Promise((resolve) => {
    const finish = (confirmed) => {
      ok.onclick = $('#confirm-cancel').onclick = box.onclose = null;
      if (box.open) box.close();
      resolve(confirmed ? (input ? field.value.trim() : true) : null);
    };
    ok.onclick = () => finish(true);
    $('#confirm-cancel').onclick = () => finish(false);
    box.onclose = () => finish(false);
    box.showModal();
    (input ? field : $('#confirm-cancel')).focus();
  });
}

/** Permanent deletion: the server refuses until the human approves. */
async function destroy(path, after) {
  const first = await api('DELETE', path);
  if (first.status === 'approval_required') {
    const approval = first.approval;
    const confirmed = await dialog({
      title: 'Permanent deletion',
      text: approval.summary,
      note: 'This cannot be undone. Archive instead if you might need it later.',
      okLabel: 'Delete permanently',
      danger: true,
    });
    if (!confirmed) {
      await api('POST', `/api/approvals/${approval.id}/deny`);
      return;
    }
    await api('POST', `/api/approvals/${approval.id}/approve`);
    await api('DELETE', `${path}?approval_id=${approval.id}`);
  }
  toast('Deleted permanently');
  await after();
  refreshChrome();
}

async function loadProjects() {
  state.projects = (await api('GET', '/api/projects?active=all')).items;
}

// --- forms -----------------------------------------------------------------
const VERIFICATION = ['unverified', 'user_provided', 'verified', 'disputed'];

function projectOptions() {
  return [['', 'No project'], ...state.projects.filter((p) => p.is_active).map((p) => [String(p.id), p.name])];
}

function control(spec) {
  const common = { name: spec.name, required: spec.required, placeholder: spec.placeholder };
  if (spec.type === 'textarea') return h('textarea', { ...common, value: spec.value });
  if (spec.type === 'select') {
    return h('select', { ...common, value: spec.value },
      spec.options.map((option) => {
        const [value, text] = Array.isArray(option) ? option : [option, label(option)];
        return h('option', { value }, text);
      }));
  }
  return h('input', { ...common, type: spec.type || 'text', value: spec.value, min: spec.min, max: spec.max, step: spec.step });
}

/** Build a form. `wide` specs take a full row; neighbouring others share a grid. */
function form(specs, submitLabel, onSubmit) {
  const field = (spec) => h('label', { class: 'field' }, spec.label, control(spec));
  const rows = [];
  for (const spec of specs) {
    const last = rows[rows.length - 1];
    if (spec.wide) rows.push(field(spec));
    else if (last && last.classList.contains('fields')) last.append(field(spec));
    else rows.push(h('div', { class: 'fields' }, field(spec)));
  }
  const el = h('form', { class: 'form' }, rows,
    h('div', { class: 'row end' }, h('button', { class: 'btn primary', type: 'submit' }, submitLabel)));
  el.addEventListener('submit', act(async (event) => {
    event.preventDefault();
    const data = {};
    for (const spec of specs) {
      let value = el.elements[spec.name].value;
      if (spec.name.endsWith('_id')) value = value ? Number(value) : null;
      else if (spec.type === 'number') value = Number(value);
      else if (spec.type === 'date' && !value) value = null;
      data[spec.name] = value;
    }
    await onSubmit(data);
    // Back to each field's starting value (reset() would blank the defaults).
    for (const spec of specs) el.elements[spec.name].value = spec.value ?? '';
    refreshChrome();
  }));
  return el;
}

const metaSpecs = (category) => [
  { name: 'category', label: 'Category', value: category || 'general', required: true },
  { name: 'project_id', label: 'Project', type: 'select', options: projectOptions(), value: '' },
  { name: 'source', label: 'Source', value: 'user', required: true },
  { name: 'verification_status', label: 'Verification', type: 'select', options: VERIFICATION, value: 'user_provided' },
  { name: 'confidence', label: 'Confidence (0–1)', type: 'number', min: 0, max: 1, step: 0.05, value: 1 },
];

// --- record rendering ------------------------------------------------------
function metaChips(record) {
  const tone = { verified: 'ok', user_provided: 'violet', disputed: 'bad', unverified: 'warn' }[record.verification_status];
  return h('div', { class: 'meta' },
    chip(record.category, 'violet'),
    record.project_id && projectName(record.project_id) ? chip(projectName(record.project_id)) : null,
    chip(label(record.verification_status), tone),
    chip(`confidence ${Math.round(record.confidence * 100)}%`),
    chip(`source: ${record.source}`),
    chip(when(record.created_at)),
    record.is_active ? null : chip('archived', 'pink'));
}

function recordActions(kind, record, reload) {
  return h('div', { class: 'actions' },
    record.is_active
      ? h('button', { class: 'btn sm', onclick: act(async () => { await api('POST', `/api/${kind}/${record.id}/archive`); await reload(); refreshChrome(); }) }, 'Archive')
      : h('button', { class: 'btn sm', onclick: act(async () => { await api('POST', `/api/${kind}/${record.id}/restore`); await reload(); refreshChrome(); }) }, 'Restore'),
    h('button', { class: 'btn sm danger', onclick: act(() => destroy(`/api/${kind}/${record.id}`, reload)) }, 'Delete'));
}

/** A searchable list with an "include archived" toggle. */
function listPanel(title, kind, renderItem, extraQuery) {
  const body = h('div', { class: 'list' });
  const search = h('input', { type: 'search', placeholder: 'Search…', 'aria-label': 'Search' });
  const archived = h('input', { type: 'checkbox', id: `archived-${kind}` });
  const reload = act(async () => {
    const params = new URLSearchParams(extraQuery || {});
    if (search.value.trim()) params.set('q', search.value.trim());
    if (archived.checked) params.set('active', 'all');
    const { items } = await api('GET', `/api/${kind}?${params}`);
    body.replaceChildren(...(items.length
      ? items.map((item) => renderItem(item, reload))
      : [h('div', { class: 'empty' }, search.value.trim() ? 'Nothing matches that search.' : 'Nothing here yet.')]));
  });
  let debounce;
  search.addEventListener('input', () => { clearTimeout(debounce); debounce = setTimeout(reload, 200); });
  archived.addEventListener('change', reload);
  const panel = h('div', { class: 'glass panel' },
    h('div', { class: 'row between' },
      h('h2', null, title),
      h('div', { class: 'row' },
        h('label', { class: 'row small muted', for: `archived-${kind}` }, archived, 'Include archived'))),
    search, body);
  return { panel, reload };
}

// --- views -----------------------------------------------------------------
const views = {};

views.dashboard = {
  title: 'Dashboard',
  subtitle: 'Command centre overview',
  async render(root) {
    const data = await api('GET', '/api/dashboard');
    const { status } = data;
    const counts = status.counts;
    const stat = (value, text, href) => {                 // a tile is a door: click to open that page
      const v = h('div', { class: 'value' }, '0');
      requestAnimationFrame(() => JarvisMotion.countTo(v, Number(value) || 0));
      return h('a', { class: 'glass stat stat-link', href }, v, h('div', { class: 'label' }, text));
    };

    const briefing = h('div', { class: 'glass panel' }, h('h2', null, 'Briefing'), h('div', { class: 'muted' }, 'Preparing today’s briefing…'));
    root.append(h('div', { class: 'stack' },
      aiBanner(status.ai),
      briefing,
      h('div', { class: 'grid stats' },
        stat(counts.tasks_open, 'Open tasks', '#tasks'),
        stat(counts.projects, 'Projects', '#projects'),
        stat(counts.memories, 'Memories', '#memory'),
        stat(counts.experiences, 'Experiences', '#experiences'),
        stat(counts.pending_approvals, 'Pending approvals', '#system')),
      h('div', { class: 'grid two' },
        h('div', { class: 'glass panel' }, h('h2', null, 'Open tasks'),
          data.open_tasks.length
            ? h('div', { class: 'list' }, data.open_tasks.map((task) => h('div', { class: 'item' },
              h('div', { class: 'grow' }, h('div', { class: 'title' }, task.title),
                h('div', { class: 'meta' }, chip(label(task.status), 'violet'), priorityChip(task.priority),
                  task.project_id && projectName(task.project_id) ? chip(projectName(task.project_id)) : null)))))
            : h('div', { class: 'empty' }, 'No open tasks.')),
        h('div', { class: 'glass panel' }, h('h2', null, 'Projects'),
          data.projects.length
            ? h('div', { class: 'list' }, data.projects.map((project) => h('div', { class: 'item' },
              h('div', { class: 'grow' }, h('div', { class: 'title' }, project.name),
                h('div', { class: 'muted small' }, project.description)),
              chip(project.status, 'ok'))))
            : h('div', { class: 'empty' }, 'No projects.'))),
      h('div', { class: 'glass panel' }, h('h2', null, 'Recent activity'), JarvisUI.eventLog(data.recent_events, when))));
    fillBriefing(briefing);
  },
};

const hostOf = (url) => { try { return new URL(url).hostname; } catch (e) { return url; } };

/** The day's spoken briefing as text, with where each headline and learned fact came from. */
async function fillBriefing(panel, refresh = false) {
  let data;
  try { data = await api('GET', '/api/briefing' + (refresh ? '?refresh=1' : '')); }
  catch (error) { panel.replaceChildren(h('h2', null, 'Briefing'), h('div', { class: 'empty' }, error.message)); return; }
  const again = h('button', { class: 'btn sm', type: 'button', onclick: () => {
    again.disabled = true; again.textContent = 'Preparing…'; fillBriefing(panel, true);
  } }, 'Make a new one');
  const sources = (data.sources || []).map((s) => h('div', { class: 'item' }, h('div', { class: 'grow' },
    h('div', { class: 'small' }, s.title.length > 140 ? s.title.slice(0, 139) + '…' : s.title),
    h('div', { class: 'meta' }, chip(s.kind === 'headline' ? 'Headline' : 'Learned', s.kind === 'headline' ? 'violet' : 'ok'),
      h('a', { href: s.url, target: '_blank', rel: 'noopener', class: 'muted small' }, hostOf(s.url))))));
  panel.replaceChildren(
    h('h2', null, 'Briefing'),
    h('p', null, data.text),
    h('div', { class: 'meta' }, chip(data.day), data.partial ? chip('headlines still coming', 'warn') : null, again),
    ...(sources.length ? [h('div', { class: 'list' }, sources)] : []));
}

function aiBanner(ai) {
  if (ai.configured && ai.available) {
    return h('div', { class: 'banner ok' }, h('div', null,
      h('strong', null, `AI connected: ${ai.name} (${ai.model})`), h('span', { class: 'muted' }, ai.detail)));
  }
  return h('div', { class: 'banner' }, h('div', null,
    h('strong', null, 'No AI model is connected'),
    h('span', { class: 'muted' }, `${ai.detail} Everything else works; chat cannot generate replies.`)));
}

const priorityChip = (priority) => chip(priority, { urgent: 'pink', high: 'warn' }[priority]);

function eventTable(events) {
  if (!events.length) return h('div', { class: 'empty' }, 'No activity recorded yet.');
  const tone = { warning: 'warn', error: 'bad' };
  return h('div', { class: 'scroll-x' }, h('table', null,
    h('tr', null, ['When', 'Category', 'Action', 'Actor', 'Message'].map((name) => h('th', null, name))),
    events.map((event) => h('tr', null,
      h('td', { class: 'muted small' }, when(event.created_at)),
      h('td', null, chip(event.category, tone[event.level])),
      h('td', { class: 'mono' }, event.action),
      h('td', { class: 'muted' }, event.actor),
      h('td', { class: 'wrap' }, event.message)))));
}

// One continuing conversation shared by the JARVIS page and the Chat page (and kept across
// reloads), so switching pages never loses the thread. A new one starts after 3 quiet hours.
const CONVO_KEY = 'jarvis.conversation', CONVO_IDLE_MS = 3 * 60 * 60 * 1000;
function currentConversation() {
  try {
    const saved = JSON.parse(localStorage.getItem(CONVO_KEY) || 'null');
    return saved && Date.now() - saved.at < CONVO_IDLE_MS ? saved.id : null;
  } catch (e) { return null; }
}
function rememberConversation(id) {
  try { if (id) localStorage.setItem(CONVO_KEY, JSON.stringify({ id, at: Date.now() })); else localStorage.removeItem(CONVO_KEY); } catch (e) { /* private window */ }
}
/** Upload files for JARVIS; returns [{path, name}] for the ones that were accepted. */
async function uploadFiles(files) {
  const done = [];
  for (const file of files) {
    const response = await fetch(`/api/files?name=${encodeURIComponent(file.name)}`, {
      method: 'POST', headers: { 'Content-Type': file.type || 'application/octet-stream' }, body: file });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) { toast(data.error || `Could not attach ${file.name}`, true); continue; }
    done.push(data);
  }
  return done;
}

views.chat = {
  title: 'Chat',
  subtitle: 'Conversations are stored locally',
  async render(root) {
    const status = await api('GET', '/api/status');
    state.conversationId = currentConversation() || state.conversationId;   // follow the JARVIS page's thread
    const threads = h('div', { class: 'glass threads' });
    const messages = h('div', { class: 'messages' });
    const input = h('textarea', { placeholder: 'Message JARVIS…', title: 'Enter to send, Shift+Enter for a new line', 'aria-label': 'Message' });
    const send = h('button', { class: 'btn primary', type: 'submit' }, 'Send');

    const runTone = { completed: 'ok', failed: 'bad', blocked: 'warn', waiting_approval: 'pink', interrupted: 'warn', cancelled: null };
    const actionCard = (runId) => {
      const card = h('div', { class: 'action-card' }, h('span', { class: 'muted small' }, 'Loading action…'));
      api('GET', `/api/runs/${runId}`).then(({ report }) => {
        const resume = act(async () => { await api('POST', `/api/runs/${runId}/resume`); await openThread(); refreshChrome(); });
        card.replaceChildren(
          h('div', { class: 'row' }, h('span', { class: 'small muted' }, `Action #${runId}`),
            chip(label(report.status), runTone[report.status]), report.verified_complete ? chip('verified', 'ok') : null),
          report.changes_made.length ? h('ul', { class: 'small' }, report.changes_made.map((c) => h('li', null, `${c.tool}: ${c.what}`))) : null,
          h('div', { class: 'row' },
            h('a', { class: 'btn sm', href: '#goals' }, 'Details'),
            report.status === 'waiting_approval' ? h('a', { class: 'btn sm', href: '#system' }, 'Review approval') : null,
            ['waiting_approval', 'interrupted'].includes(report.status) ? h('button', { class: 'btn sm primary', onclick: resume }, 'Continue') : null));
      }).catch(() => card.replaceChildren(h('span', { class: 'muted small' }, `Action #${runId}`)));
      return card;
    };

    const bubble = (message) => h('div', { class: `msg ${message.role}` },
      h('div', { class: 'who' }, message.role === 'assistant' ? `JARVIS · ${message.model || message.provider || ''}`
        : message.role === 'system' ? 'System notice' : 'You'),
      message.role === 'assistant' ? JarvisUI.richText(message.content) : h('div', { class: 'wrap' }, message.content),
      workspaceImages(message.content),
      message.role === 'assistant' ? h('div', { class: 'msg-tools' }, JarvisUI.copyButton(message.content)) : null,
      message.memory_refs && message.memory_refs.length
        ? h('div', { class: 'meta' }, chip('From memory', 'violet'),
          message.memory_refs.map((ref) => h('span', { class: 'chip', title: ref.content },
            ref.content.length > 48 ? ref.content.slice(0, 47) + '…' : ref.content)))
        : null,
      message.run_id ? actionCard(message.run_id) : null);

    // suggestions for an empty conversation, from what JARVIS is set up to do for the owner
    const SUGGEST = ['What should I do this week to grow Monsoor Motors?', 'Plan this week for Aureus Detailing',
      'What did you learn for me today?', 'How much battery and disk space do I have?', 'Remind me at 5pm to check the stock list'];
    let seenCount = 0;
    const showMessages = (list) => {
      if (!list.length) {
        const ideas = h('div', { class: 'suggest' }, ...SUGGEST.map((text) => {
          const b = h('button', { class: 'suggest-chip', type: 'button' }, text);
          b.addEventListener('click', () => { input.value = text; composer.requestSubmit(); });
          return b;
        }));
        messages.replaceChildren(h('div', { class: 'empty' }, h('div', null, 'Ask JARVIS anything, or start with one of these:'), ideas));
        seenCount = 0; return;
      }
      const nodes = list.map(bubble);
      nodes.forEach((n, i) => { if (i >= seenCount && seenCount) n.classList.add('msg-in'); });   // only what is new animates
      seenCount = list.length;
      messages.replaceChildren(...nodes);
      messages.scrollTop = messages.scrollHeight;
    };

    let threadQuery = '';
    const threadSearch = h('input', { class: 'thread-search', placeholder: 'Search conversations', 'aria-label': 'Search conversations' });
    threadSearch.addEventListener('input', () => { threadQuery = threadSearch.value.trim().toLowerCase(); loadThreads(); });
    const loadThreads = async () => {
      const all = (await api('GET', '/api/conversations')).items;
      const items = threadQuery ? all.filter((item) => (item.title || '').toLowerCase().includes(threadQuery)) : all;
      threads.replaceChildren(threadSearch,
        h('button', { class: 'btn sm', onclick: () => { state.conversationId = null; rememberConversation(null); showMessages([]); loadThreads(); input.focus(); } }, '+ New conversation'),
        ...items.map((item) => h('button', {
          class: 'thread' + (item.id === state.conversationId ? ' active' : ''), title: item.title,
          onclick: act(async () => { state.conversationId = item.id; rememberConversation(item.id); await openThread(); }),
        }, item.title)));
    };

    const openThread = async () => {
      if (state.conversationId === null) return showMessages([]);
      try {
        showMessages((await api('GET', `/api/conversations/${state.conversationId}`)).messages);
      } catch (error) {
        state.conversationId = null;
        showMessages([]);
      }
      await loadThreads();
    };

    // --- voice: push-to-talk in, spoken replies out (all processed on this Mac) ---
    const voiceOk = status.voice || {};
    const remembered = (() => { try { return localStorage.getItem('jarvis.speak') === 'on'; } catch (e) { return false; } })();
    const voice = { speakReplies: remembered, speakNext: false, recorder: null, audio: null };
    const voiceLine = h('div', { class: 'voice-line muted small' });
    const setVoiceLine = (text) => { voiceLine.textContent = text || ''; voiceLine.hidden = !text; };
    setVoiceLine('');

    const stopSpeaking = () => { if (voice.audio) { voice.audio.pause(); voice.audio = null; } speaker.classList.remove('speaking'); };
    const speak = async (text) => {
      stopSpeaking();
      setVoiceLine('Speaking…');
      try {
        const response = await fetch('/api/voice/speak', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
        if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || 'Speech failed');
        const audio = new Audio(URL.createObjectURL(await response.blob()));
        voice.audio = audio;
        speaker.classList.add('speaking');
        audio.onended = () => { speaker.classList.remove('speaking'); setVoiceLine(''); voice.audio = null; };
        await audio.play();
      } catch (error) { setVoiceLine(''); toast(error.message, true); }
    };

    const SLEEP = /^\s*(go to sleep|sleep now|that'?s all|goodbye,? jarvis|you can (go to )?sleep)/i;
    const finishRecording = async (blob) => {
      setVoiceLine('Transcribing…');
      try {
        const response = await fetch('/api/voice/transcribe', { method: 'POST', headers: { 'Content-Type': blob.type || 'audio/webm' }, body: blob });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || 'Could not understand the recording');
        const heard = (data.text || '').trim();
        if (!heard) { setVoiceLine(''); toast("I didn't catch that. Try again a little closer to the microphone."); return; }
        if (SLEEP.test(heard)) { setVoiceLine(''); await speak('Very good, sir. I shall be here when you need me.'); return; }
        input.value = heard;
        voice.speakNext = true;               // a spoken question gets a spoken answer
        setVoiceLine('');
        composer.requestSubmit();
      } catch (error) { setVoiceLine(''); toast(error.message, true); }
    };

    const mic = h('button', { class: 'btn icon-btn', type: 'button', title: voiceOk.listening ? 'Talk to JARVIS (click to start, click again to stop)' : `Voice input unavailable: missing ${(voiceOk.missing || []).join(', ')}`, 'aria-label': 'Talk to JARVIS', disabled: !voiceOk.listening }, '🎙');
    mic.addEventListener('click', act(async () => {
      if (voice.recorder) { voice.recorder.stop(); return; }
      stopSpeaking();
      let stream;
      try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
      catch (error) { throw new Error('Microphone access was blocked. Allow it for this page in the browser settings.'); }
      const chunks = [];
      const recorder = new MediaRecorder(stream);
      voice.recorder = recorder;
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        voice.recorder = null;
        mic.classList.remove('recording');
        finishRecording(new Blob(chunks, { type: recorder.mimeType || 'audio/webm' }));
      };
      recorder.start();
      mic.classList.add('recording');
      setVoiceLine('Listening… click the microphone again when you have finished.');
    }));

    const speaker = h('button', { class: 'btn icon-btn' + (voice.speakReplies ? ' on' : ''), type: 'button', 'aria-pressed': String(voice.speakReplies), title: voiceOk.speaking ? 'Read every reply aloud' : 'Spoken replies unavailable', 'aria-label': 'Read replies aloud', disabled: !voiceOk.speaking }, '🔊');
    speaker.addEventListener('click', () => {
      if (voice.audio) { stopSpeaking(); setVoiceLine(''); return; }   // a click while speaking stops it
      voice.speakReplies = !voice.speakReplies;
      speaker.classList.toggle('on', voice.speakReplies);
      speaker.setAttribute('aria-pressed', String(voice.speakReplies));
      try { localStorage.setItem('jarvis.speak', voice.speakReplies ? 'on' : 'off'); } catch (e) { /* private mode */ }
    });

    const picker = h('input', { type: 'file', multiple: true, hidden: true, 'aria-hidden': 'true' });
    const clip = h('button', { class: 'btn icon-btn', type: 'button', title: 'Attach files or photos', 'aria-label': 'Attach files or photos' }, '📎');
    const attached = h('div', { class: 'meta attach-row' });
    let pendingFiles = [];
    const showAttached = () => attached.replaceChildren(...pendingFiles.map((f, i) => {
      const x = h('button', { class: 'btn sm', type: 'button', 'aria-label': `Remove ${f.name}` }, '×');
      x.addEventListener('click', () => { pendingFiles.splice(i, 1); showAttached(); });
      return h('span', { class: 'chip' }, f.name.replace(/^\d{8}-\d{6}-/, ''), ' ', x);
    }));
    const addFiles = async (files) => { pendingFiles.push(...await uploadFiles(files)); showAttached(); input.focus(); };
    clip.addEventListener('click', () => picker.click());
    picker.addEventListener('change', () => { addFiles([...picker.files]); picker.value = ''; });
    messages.addEventListener('dragover', (e) => e.preventDefault());
    messages.addEventListener('drop', (e) => { e.preventDefault(); addFiles([...e.dataTransfer.files]); });

    const composer = h('form', { class: 'composer' }, picker, clip, mic, input, speaker, send);
    composer.addEventListener('submit', act(async (event) => {
      event.preventDefault();
      const text = input.value.trim();
      const files = pendingFiles.map((f) => f.path);
      if (!text && !files.length) return;
      pendingFiles = []; showAttached();
      send.disabled = true;
      // Show the message and a thinking indicator at once; the first reply after a restart
      // can take ~20 seconds while the model loads.
      messages.querySelector('.empty')?.remove();
      messages.append(bubble({ role: 'user', content: text + (files.length ? `\n📎 ${files.length} file${files.length > 1 ? 's' : ''}` : '') }),
        h('div', { class: 'msg assistant thinking' }, h('div', { class: 'who' }, 'JARVIS'),
          h('div', { class: 'thinking-line' }, 'Thinking…'),
          h('div', { class: 'muted small' }, 'The first reply after JARVIS starts can take up to 30 seconds.')));
      messages.scrollTop = messages.scrollHeight;
      input.value = '';
      const progress = setInterval(async () => {          // say what it is doing, e.g. "Working with Claude Code… 1m 20s"
        try {
          const live = await api('GET', '/api/live');
          const line = messages.querySelector('.thinking .thinking-line');
          if (line && live.step && live.step.description) line.textContent = live.step.description;
        } catch (e) { /* try again */ }
      }, 2000);
      try {
        const result = await api('POST', '/api/chat', { message: text, attachments: files, conversation_id: state.conversationId, voice: voice.speakNext });
        state.conversationId = result.conversation.id;
        rememberConversation(state.conversationId);
        await openThread();
        if ((voice.speakNext || voice.speakReplies) && result.reply && result.reply.content) speak(result.reply.content);
      } catch (error) {
        messages.querySelector('.thinking')?.remove();
        input.value = text;                        // give the message back so it can be resent
        throw error;
      } finally {
        clearInterval(progress);
        voice.speakNext = false;
        send.disabled = false;
        input.focus();
      }
    }));
    const fitInput = JarvisUI.autoGrow(input);
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); composer.requestSubmit(); setTimeout(fitInput, 0); }
    });

    root.append(h('div', { class: 'stack' },
      status.ai.configured && status.ai.available ? null : aiBanner(status.ai),
      h('div', { class: 'chat' }, threads, h('div', { class: 'glass conversation' }, messages, voiceLine, attached, composer))));
    await loadThreads();
    await openThread();
  },
};

views.goals = {
  title: 'Goals',
  subtitle: 'Give JARVIS a goal; it plans, acts through its tools, and reports what was verified',
  async render(root) {
    const status = await api('GET', '/api/status');
    const connected = status.ai.configured && status.ai.available;
    const list = h('div', { class: 'stack' });
    const tone = { completed: 'ok', failed: 'bad', blocked: 'warn', waiting_approval: 'pink', cancelled: null, interrupted: 'warn', running: 'violet', pending: null };
    const control = (path, body) => act(async () => { await api('POST', path, body || {}); await reload(); refreshChrome(); });

    const card = (report) => h('div', { class: 'glass panel' },
      h('div', { class: 'row between' }, h('div', { class: 'title grow wrap' }, report.goal),
        chip(label(report.status), tone[report.status]), report.verified_complete ? chip('verified', 'ok') : null),
      h('p', { class: 'wrap' }, report.summary),
      report.plan.length ? h('div', { class: 'list' }, report.plan.map((step) => h('div', { class: 'item' },
        h('div', { class: 'grow' }, h('div', null, `${step.position}. ${step.description}`),
          step.note ? h('div', { class: 'muted small wrap' }, step.note) : null),
        chip(step.tool), chip(label(step.status), tone[step.status])))) : null,
      report.model_summary ? h('p', { class: 'muted small wrap' }, `Model's own summary (not verified): ${report.model_summary}`) : null,
      h('div', { class: 'row end' },
        h('span', { class: 'muted small grow' }, `Run #${report.run_id} · ${when(report.created_at)}`),
        report.status === 'blocked' ? h('button', { class: 'btn sm primary', onclick: act(async () => {
          const answer = await dialog({ title: 'JARVIS needs information', text: report.question, okLabel: 'Send and continue', input: 'Your answer…' });
          if (answer) await control(`/api/runs/${report.run_id}/resume`, { answer })();
        }) }, 'Answer') : null,
        ['waiting_approval', 'interrupted'].includes(report.status)
          ? h('button', { class: 'btn sm primary', onclick: control(`/api/runs/${report.run_id}/resume`) }, 'Continue') : null,
        report.status === 'waiting_approval' ? h('a', { class: 'btn sm', href: '#system' }, 'Review approval') : null,
        ['blocked', 'waiting_approval', 'interrupted'].includes(report.status)
          ? h('button', { class: 'btn sm', onclick: control(`/api/runs/${report.run_id}/cancel`) }, 'Cancel') : null));

    const reload = act(async () => {
      const { items } = await api('GET', '/api/runs?kind=goal&limit=15');
      const runs = await Promise.all(items.map((run) => api('GET', `/api/runs/${run.id}`)));
      list.replaceChildren(...(runs.length ? runs.map((run) => card(run.report))
        : [h('div', { class: 'glass panel empty' }, 'No goals have been run yet.')]));
    });

    const goal = h('textarea', { name: 'goal', required: true, placeholder: 'For example: add a high-priority task to review this week\'s open jobs' });
    const submit = h('button', { class: 'btn primary', type: 'submit', disabled: !connected }, 'Run goal');
    const entry = h('form', { class: 'form' }, h('label', { class: 'field' }, 'Goal', goal), h('div', { class: 'row end' }, submit));
    entry.addEventListener('submit', act(async (event) => {
      event.preventDefault();
      submit.disabled = true;
      try {
        await api('POST', '/api/runs', { goal: goal.value });
        goal.value = '';
        await reload();
        refreshChrome();
      } finally { submit.disabled = !connected; }
    }));

    root.append(h('div', { class: 'stack' },
      connected ? null : h('div', { class: 'banner' }, h('div', null, h('strong', null, 'Goals need an AI model'),
        h('span', { class: 'muted' }, 'The reasoning engine is built, but no model is connected to do the planning, so goals cannot run yet.'))),
      h('div', { class: 'glass panel' }, h('h2', null, 'New goal'), entry), list));
    await reload();
  },
};

views.memory = {
  title: 'Memory',
  subtitle: 'Facts and notes JARVIS retains, with their provenance',
  async render(root) {
    const { panel, reload } = listPanel('Stored memories', 'memories', (memory, again) =>
      h('div', { class: 'item' + (memory.is_active ? '' : ' archived') },
        h('div', { class: 'grow' }, h('div', { class: 'wrap' }, memory.content), metaChips(memory)),
        recordActions('memories', memory, again)));
    // continuous learning: what JARVIS has been reading about on its own
    const learnBody = h('div', { class: 'stack' });
    const learnBtn = h('button', { class: 'btn sm', type: 'button' }, 'Learn now');
    const showLearn = async () => {
      const s = await api('GET', '/api/learn');
      const last = s.last || {};
      learnBody.replaceChildren(
        h('div', { class: 'muted small' }, s.enabled
          ? `Learning on its own every ${s.interval_minutes} minutes while idle. Facts are saved as unverified, with their source.`
          : 'Continuous learning is off (JARVIS_LEARN=0).'),
        last.at ? h('div', null, last.ok
          ? `Last read about “${last.query}”: ${last.saved} new fact${last.saved === 1 ? '' : 's'} from ${last.read.length} page${last.read.length === 1 ? '' : 's'}.`
          : `Last pass found nothing new (${last.error}).`, h('span', { class: 'muted small' }, ` ${new Date(last.at).toLocaleString()}`)) : h('div', { class: 'muted small' }, 'No learning pass yet.'),
        ...(s.recent.length ? [h('div', { class: 'meta' }, ...s.recent.slice().reverse().map((q) => chip(q)))] : []));
    };
    learnBtn.addEventListener('click', act(async () => {
      learnBtn.disabled = true; learnBtn.textContent = 'Reading…';
      const before = ((await api('GET', '/api/learn')).last || {}).at;
      await api('POST', '/api/learn/run');
      for (let i = 0; i < 90; i++) {                    // a pass takes about a minute on the local model
        await new Promise((r) => setTimeout(r, 2000));
        const s = await api('GET', '/api/learn');
        if (s.last && s.last.at !== before) break;
      }
      learnBtn.disabled = false; learnBtn.textContent = 'Learn now';
      await showLearn(); await reload();
    }));
    root.append(h('div', { class: 'stack' },
      h('div', { class: 'glass panel' }, h('div', { class: 'row between' }, h('h2', { class: 'grow' }, 'Learning'), learnBtn), learnBody),
      h('div', { class: 'glass panel' }, h('h2', null, 'Add a memory'),
        form([{ name: 'content', label: 'What should JARVIS remember?', type: 'textarea', required: true, wide: true }, ...metaSpecs()],
          'Save memory', async (data) => { await api('POST', '/api/memories', data); toast('Memory saved'); await reload(); })),
      panel));
    await Promise.all([reload(), showLearn().catch(() => learnBody.replaceChildren(h('div', { class: 'muted small' }, 'Learning status is unavailable.')))]);
  },
};

views.tasks = {
  title: 'Tasks',
  subtitle: 'What needs doing',
  async render(root) {
    const { panel, reload } = listPanel('All tasks', 'tasks', (task, again) => {
      const done = task.status === 'completed';
      const toggle = h('input', { type: 'checkbox', 'aria-label': done ? 'Reopen task' : 'Complete task' });
      toggle.checked = done;
      toggle.addEventListener('change', act(async () => {
        await api('POST', `/api/tasks/${task.id}/${done ? 'reopen' : 'complete'}`);
        await again();
        refreshChrome();
      }));
      const addLesson = act(async () => {
        const lesson = await dialog({ title: 'Record a lesson', text: `What did “${task.title}” teach you?`,
          note: 'Saved as an experience linked to this task.', okLabel: 'Save lesson', input: 'Lesson learned…' });
        if (!lesson) return;
        await api('POST', '/api/experiences', { title: `Task completed: ${task.title}`.slice(0, 300), lesson,
          outcome: 'success', category: 'task', source: `task:${task.id}`, task_id: task.id, project_id: task.project_id });
        toast('Lesson saved to Experiences');
        refreshChrome();
      });
      return h('div', { class: 'item' + (done ? ' done' : '') + (task.is_active ? '' : ' archived') },
        toggle,
        h('div', { class: 'grow' }, h('div', { class: 'title' }, task.title),
          task.description ? h('div', { class: 'muted wrap' }, task.description) : null,
          h('div', { class: 'meta' }, chip(label(task.status), done ? 'ok' : 'violet'), priorityChip(task.priority),
            task.project_id && projectName(task.project_id) ? chip(projectName(task.project_id)) : null,
            task.due_at ? chip(`due ${task.due_at}`) : null,
            done ? chip(`completed ${when(task.completed_at)}`) : null,
            task.is_active ? null : chip('archived', 'pink'))),
        h('div', { class: 'actions' },
          done ? h('button', { class: 'btn sm', onclick: addLesson }, '+ Lesson') : null,
          [...recordActions('tasks', task, again).childNodes]));
    });
    root.append(h('div', { class: 'stack' },
      h('div', { class: 'glass panel' }, h('h2', null, 'Add a task'),
        form([
          { name: 'title', label: 'Task', required: true, wide: true },
          { name: 'description', label: 'Details (optional)', type: 'textarea', wide: true },
          { name: 'priority', label: 'Priority', type: 'select', options: ['low', 'normal', 'high', 'urgent'], value: 'normal' },
          { name: 'project_id', label: 'Project', type: 'select', options: projectOptions(), value: '' },
          { name: 'due_at', label: 'Due date', type: 'date' },
        ], 'Add task', async (data) => { await api('POST', '/api/tasks', data); toast('Task added'); await reload(); })),
      remindersPanel(),
      panel));
    await reload();
  },
};

/** Reminders and scheduled jobs: what is set, when each fires next, and a way to cancel. */
function remindersPanel() {
  const body = h('div', { class: 'list' });
  const reload = act(async () => {
    const { items } = await api('GET', '/api/reminders');
    body.replaceChildren(...(items.length ? items.map((item) => h('div', { class: 'item' },
      h('div', { class: 'grow' }, h('div', { class: 'title' }, item.text),
        h('div', { class: 'meta' }, chip(item.kind === 'job' ? 'job' : 'reminder', item.kind === 'job' ? 'violet' : 'ok'),
          chip(item.when), item.last_result && item.kind === 'job' ? h('span', { class: 'muted small wrap' }, `Last run: ${item.last_result.slice(0, 140)}`) : null)),
      h('div', { class: 'actions' }, h('button', { class: 'btn sm danger', onclick: act(async () => {
        await api('POST', `/api/reminders/${item.id}/cancel`); toast('Cancelled'); await reload(); }) }, 'Cancel'))))
      : [h('div', { class: 'empty' }, 'No reminders. Say “Jarvis, remind me at 5pm to call the supplier”.')]));
  });
  const add = form([
    { name: 'text', label: 'What', required: true, wide: true },
    { name: 'when', label: 'When (e.g. at 5pm, tomorrow morning, every weekday at 8am)', required: true, wide: true },
    { name: 'kind', label: 'Type', type: 'select', options: ['reminder', 'job'], value: 'reminder' },
  ], 'Set', async (data) => { const made = await api('POST', '/api/reminders', data); toast(made.summary); await reload(); });
  reload();
  return h('div', { class: 'glass panel' }, h('h2', null, 'Reminders'), body, h('details', null, h('summary', { class: 'small muted' }, 'Set one here'), add));
}

views.projects = {
  title: 'Projects',
  subtitle: 'Workspaces that tasks, memories and experiences attach to',
  async render(root) {
    const cards = h('div', { class: 'grid cards' });
    const reload = act(async () => {
      await loadProjects();
      const active = state.projects.filter((project) => project.is_active);
      const archived = state.projects.filter((project) => !project.is_active);
      const tallies = await Promise.all(active.map(async (project) => {
        const [tasks, memories] = await Promise.all([
          api('GET', `/api/tasks?project_id=${project.id}`), api('GET', `/api/memories?project_id=${project.id}`)]);
        return { open: tasks.items.filter((task) => ['pending', 'in_progress'].includes(task.status)).length, memories: memories.items.length };
      }));
      const card = (project, tally) => h('div', { class: 'glass panel' + (project.is_active ? '' : ' item archived') },
        h('div', { class: 'row between' }, h('div', { class: 'title' }, project.name), chip(project.is_active ? project.status : 'archived', project.is_active ? 'ok' : 'pink')),
        h('p', { class: 'muted wrap' }, project.description || 'No description.'),
        h('div', { class: 'meta' }, chip(project.category, 'violet'),
          tally ? chip(`${tally.open} open task${tally.open === 1 ? '' : 's'}`) : null,
          tally ? chip(`${tally.memories} memor${tally.memories === 1 ? 'y' : 'ies'}`) : null,
          chip(`source: ${project.source}`)),
        h('div', { class: 'row end' }, [...recordActions('projects', project, reload).childNodes]));
      cards.replaceChildren(...[...active.map((project, index) => card(project, tallies[index])), ...archived.map((project) => card(project))]);
      if (!state.projects.length) cards.append(h('div', { class: 'empty' }, 'No projects yet.'));
    });
    root.append(h('div', { class: 'stack' }, cards,
      h('div', { class: 'glass panel' }, h('h2', null, 'Add a project'),
        form([
          { name: 'name', label: 'Name', required: true },
          { name: 'category', label: 'Category', value: 'general', required: true },
          { name: 'description', label: 'Description', type: 'textarea', wide: true },
        ], 'Create project', async (data) => {
          await api('POST', '/api/projects', { ...data, verification_status: 'user_provided' });
          toast('Project created');
          await reload();
        }))));
    await reload();
  },
};

views.experiences = {
  title: 'Experiences',
  subtitle: 'What happened, how it went, and what to do next time',
  async render(root) {
    const tone = { success: 'ok', failure: 'bad', mixed: 'warn' };
    const { panel, reload } = listPanel('Recorded experiences', 'experiences', (item, again) =>
      h('div', { class: 'item' + (item.is_active ? '' : ' archived') },
        h('div', { class: 'grow' },
          h('div', { class: 'row' }, h('div', { class: 'title' }, item.title), chip(item.outcome, tone[item.outcome])),
          item.description ? h('div', { class: 'muted wrap' }, item.description) : null,
          item.lesson ? h('div', { class: 'wrap' }, h('span', { class: 'muted' }, 'Lesson: '), item.lesson) : null,
          metaChips(item)),
        recordActions('experiences', item, again)));
    root.append(h('div', { class: 'stack' },
      h('div', { class: 'glass panel' }, h('h2', null, 'Record an experience'),
        form([
          { name: 'title', label: 'What happened?', required: true, wide: true },
          { name: 'description', label: 'Details (optional)', type: 'textarea', wide: true },
          { name: 'lesson', label: 'Lesson for next time', type: 'textarea', wide: true },
          { name: 'outcome', label: 'Outcome', type: 'select', options: ['success', 'failure', 'mixed', 'unknown'], value: 'unknown' },
          ...metaSpecs(),
        ], 'Save experience', async (data) => { await api('POST', '/api/experiences', data); toast('Experience saved'); await reload(); })),
      panel));
    await reload();
  },
};

/** Weekly self-review: JARVIS's proposed changes to its own code, waiting for the owner. */
function selfReviewPanel() {
  const body = h('div', { class: 'stack' }, h('div', { class: 'muted small' }, 'Loading…'));
  const runBtn = h('button', { class: 'btn sm', type: 'button' }, 'Review now');
  const decide = (branch, verb) => act(async () => {
    if (verb === 'approve' && !(await dialog({ title: 'Merge this self-review?', text: branch,
      note: 'The tests run on the merged result first; nothing is merged if they fail. Nothing is pushed.', okLabel: 'Approve and merge' }))) return;
    if (verb === 'reject' && !(await dialog({ title: 'Reject this self-review?', text: branch,
      note: 'Deletes the branch and its worktree.', okLabel: 'Reject and delete', danger: true }))) return;
    const out = await api('POST', `/api/self-review/${branch}/${verb}`);
    toast(out.message || 'Done');
    await load();
  });
  const proposal = (p) => h('div', { class: 'item' },
    h('div', { class: 'grow stack' },
      h('div', { class: 'title mono' }, p.branch),
      h('div', { class: 'meta' }, p.tests_ok === undefined ? null : chip(p.tests_ok ? 'tests pass' : 'tests fail', p.tests_ok ? 'ok' : 'bad'),
        p.at ? chip(when(p.at)) : null),
      p.self_review ? h('pre', { class: 'wrap small' }, p.self_review) : h('div', { class: 'muted small' }, 'No SELF_REVIEW.md on this branch.'),
      p.diff_stat ? h('pre', { class: 'mono small scroll-x' }, p.diff_stat) : null),
    h('div', { class: 'actions' },
      h('button', { class: 'btn sm', onclick: decide(p.branch, 'reject') }, 'Reject'),
      h('button', { class: 'btn sm danger', onclick: decide(p.branch, 'approve') }, 'Approve')));
  const load = async () => {
    const s = await api('GET', '/api/self-review');
    const last = s.last || {};
    body.replaceChildren(
      h('div', { class: 'muted small' }, s.enabled
        ? `Every ${s.interval_days} days while idle, Claude Code reviews JARVIS's code and logs and proposes fixes on a separate branch. Nothing reaches main until you approve.`
        : 'Self-review is off (JARVIS_REVIEW=0). You can still run one now.'),
      s.running ? h('div', null, chip('reviewing now…', 'warn')) : null,
      last.at ? h('div', null, last.ok ? last.summary : `Last pass did not finish: ${last.error}`,
        h('span', { class: 'muted small' }, ` ${new Date(last.at).toLocaleString()}`)) : h('div', { class: 'muted small' }, 'No self-review pass yet.'),
      s.error ? h('div', { class: 'muted small' }, s.error) : null,
      s.proposals.length ? h('div', { class: 'list' }, s.proposals.map(proposal)) : h('div', { class: 'empty' }, 'No proposals waiting.'));
    runBtn.disabled = !!s.running;
  };
  runBtn.addEventListener('click', act(async () => {
    runBtn.disabled = true; runBtn.textContent = 'Starting…';
    await api('POST', '/api/self-review/run');
    toast('Self-review started. It can take up to half an hour.');
    runBtn.textContent = 'Review now';
    await load();
  }));
  load().catch(() => body.replaceChildren(h('div', { class: 'muted small' }, 'Self-review status is unavailable.')));
  return h('div', { class: 'glass panel' }, h('div', { class: 'row between' }, h('h2', { class: 'grow' }, 'Self-review'), runBtn), body);
}

views.system = {
  title: 'System status',
  subtitle: 'Health, safety, backups and the audit trail',
  async render(root) {
    const [status, approvals, backups, agents, events, tools, executions] = await Promise.all([
      api('GET', '/api/status'), api('GET', '/api/approvals?status=pending'), api('GET', '/api/backups'),
      api('GET', '/api/agents'), api('GET', '/api/events?limit=60'), api('GET', '/api/tools'),
      api('GET', '/api/executions?limit=25')]);
    const stepTone = { succeeded: 'ok', failed: 'bad', refused: 'bad', waiting_approval: 'warn' };
    const kv = (pairs) => h('dl', { class: 'kv' }, pairs.map(([key, value]) => [h('dt', null, key), h('dd', null, value)]));
    const rerender = () => show('system');

    root.append(h('div', { class: 'stack' },
      aiBanner(status.ai),
      h('div', { class: 'grid two' },
        h('div', { class: 'glass panel' }, h('h2', null, 'Core'), kv([
          ['Version', status.version],
          ['Environment', status.environment],
          ['Uptime', `${Math.floor(status.uptime_seconds / 60)} min`],
          ['Database', h('span', { class: 'mono' }, status.database.path)],
          ['Schema', `v${status.database.schema_version}`],
          ['Size', bytes(status.database.size_bytes)],
          ['Integrity', status.database.integrity_ok ? chip('ok', 'ok') : chip('FAILED', 'bad')],
        ])),
        h('div', { class: 'glass panel' }, h('h2', null, 'AI provider'), kv([
          ['Provider', status.ai.name],
          ['Type', status.ai.kind],
          ['Configured', status.ai.configured ? chip('yes', 'ok') : chip('no', 'pink')],
          ['Available', status.ai.available ? chip('yes', 'ok') : chip('no', 'pink')],
          ['Model', status.ai.model || '—'],
          ['Detail', status.ai.detail],
        ])),
        h('div', { class: 'glass panel' }, h('h2', null, 'Safety'), kv([
          ['Mode', status.safety.read_only ? chip('read-only', 'warn') : chip('read / write', 'ok')],
          ['Abilities', h('div', { class: 'stack ability-list' }, ...(status.abilities || []).map((a) => h('div', { class: 'row', title: a.detail },
            chip(a.name, { on: 'ok', 'asks first': 'pink', basic: 'warn', partly: 'warn', 'local only': 'warn' }[a.state] || null),
            h('span', { class: 'small muted' }, a.state === 'on' ? a.detail : `${a.state}: ${a.detail}`))))],
          ['Runs automatically', h('div', { class: 'meta' }, (status.safety.automatic || []).map((name) => chip(label(name), 'ok')))],
          ['Asks you first', h('div', { class: 'meta' }, status.safety.approval_required_for.map((name) => chip(label(name), 'pink')))],
          ['Workspace', h('span', { class: 'mono' }, status.safety.workspace || '')],
          ['Approval lifetime', `${status.safety.approval_ttl_minutes} min, single use`],
          ['External AI', status.external_ai && status.external_ai.on
            ? h('div', null, chip('Claude: on', 'violet'), h('div', { class: 'small muted' }, `${status.external_ai.used_for.join(', ')}. ${status.external_ai.kept_private}.`))
            : chip('none', 'ok')],
          ['Not built yet', status.not_built_yet.length ? status.not_built_yet.join(', ') : 'nothing'],
        ])),
        h('div', { class: 'glass panel' },
          h('div', { class: 'row between' }, h('h2', null, `Backups (${backups.items.length}, keeps ${status.backups.keep})`),
            h('button', { class: 'btn sm primary', onclick: act(async () => { await api('POST', '/api/backups', { label: 'manual' }); toast('Backup created'); rerender(); }) }, 'Back up now')),
          backups.items.length
            ? h('div', { class: 'list' }, backups.items.slice(0, 6).map((item) => h('div', { class: 'item' },
              h('div', { class: 'grow mono' }, item.name), h('span', { class: 'muted small' }, `${bytes(item.size_bytes)} · ${when(item.created_at)}`))))
            : h('div', { class: 'empty' }, 'No backups yet.'),
          h('p', { class: 'muted small' }, 'Restore from the command line: python3 -m jarvis restore <name>'))),
      h('div', { class: 'glass panel' }, h('h2', null, 'Pending approvals'),
        approvals.items.length
          ? h('div', { class: 'list' }, approvals.items.map((item) => h('div', { class: 'item' },
            h('div', { class: 'grow' }, h('div', { class: 'title' }, item.summary),
              h('div', { class: 'meta' }, chip(label(item.category), 'pink'), chip(item.action), chip(`requested by ${item.requested_by}`), chip(`expires ${when(item.expires_at)}`))),
            h('div', { class: 'actions' },
              h('button', { class: 'btn sm', onclick: act(async () => { await api('POST', `/api/approvals/${item.id}/deny`); rerender(); }) }, 'Deny'),
              h('button', { class: 'btn sm danger', onclick: act(async () => { await api('POST', `/api/approvals/${item.id}/approve`); toast('Approved. The requester may now proceed once.'); rerender(); }) }, 'Approve'))))
          )
          : h('div', { class: 'empty' }, 'Nothing is waiting for approval.')),
      selfReviewPanel(),
      h('div', { class: 'glass panel' }, h('h2', null, 'Agents'),
        h('div', { class: 'list' }, agents.items.map((agent) => h('div', { class: 'item' },
          h('div', { class: 'grow' }, h('div', { class: 'title mono' }, agent.name), h('div', { class: 'muted small' }, agent.description)),
          chip(agent.kind, 'violet'), chip(agent.status, agent.status === 'active' ? 'ok' : null))))),
      h('div', { class: 'glass panel' }, h('h2', null, `Tools (${tools.items.length})`),
        h('div', { class: 'list' }, tools.items.map((tool) => h('div', { class: 'item' },
          h('div', { class: 'grow' }, h('div', { class: 'title mono' }, tool.name), h('div', { class: 'muted small' }, tool.description)),
          chip(label(tool.permission), tool.requires_approval ? 'pink' : tool.permission === 'write' ? 'violet' : 'ok'))))),
      h('div', { class: 'glass panel' }, h('h2', null, 'Recent tool executions'),
        executions.items.length
          ? h('div', { class: 'scroll-x' }, h('table', null,
            h('tr', null, ['When', 'Tool', 'Result', 'Actor', 'Time', 'Error'].map((name) => h('th', null, name))),
            executions.items.map((step) => h('tr', null,
              h('td', { class: 'muted small' }, when(step.started_at)), h('td', { class: 'mono' }, step.tool),
              h('td', null, chip(label(step.status), stepTone[step.status])), h('td', { class: 'muted' }, step.actor),
              h('td', { class: 'muted small' }, `${step.duration_ms} ms`), h('td', { class: 'wrap' }, step.error || '')))))
          : h('div', { class: 'empty' }, 'No tools have been executed yet.')),
      h('div', { class: 'glass panel' }, h('h2', null, 'Audit trail and system events'), eventTable(events.items))));
  },
};


// --- Presence: JARVIS's operating environment ---------------------------------
const STATE_DESCRIPTIONS = {
  calm: 'Calm. Observant.', listening: 'Focused. Attentive.', analysing: 'Processing information.',
  planning: 'Evaluating options.', executing: 'Performing the operation.', concerned: 'Issue detected.',
  resolute: 'Taking action.', approval: 'Your decision is required.', awaiting: 'Waiting for your answer.',
  speaking: 'Responding.', success: 'Operation completed.', failure: 'Operation failed.',
  warning: 'Attention required.', error: 'Something is not responding.', offline: 'Not connected.',
  warm: 'Glad.', curious: 'Curious.', sad: 'Saddened.', angry: 'Angry.',
};

function stateRgb(name) {
  const spec = (window.JarvisIdentity && JarvisIdentity.STATES[name]) || { color: [255, 45, 140] };
  return spec.color.join(',');
}

/** The feeling of one sentence, as an identity state. Words first, punctuation second. */
const FEELINGS = [
  ['angry', /\b(angry|furious|outrage\w*|unacceptable|infuriat\w*|hate|enough|stop (it|that)|how dare|ridiculous|disgust\w*)\b|!{2,}/i],
  ['sad', /\b(sorry|sad|sadly|unfortunately|regret\w*|grie\w*|loss|lost|miss(ed)? you|condolence\w*|passed away|died|heartbreak\w*|i'?m afraid|lonely|disappoint\w*)\b/i],
  ['concerned', /\b(warning|careful|danger\w*|risk\w*|failed|failure|problem|issue|error|broken|urgent|caution)\b/i],
  ['warm', /\b(great|glad|happy|excellent|wonderful|congrat\w*|love|lovely|delight\w*|awesome|well done|brilliant|thank(s| you)|welcome|good news|fantastic|perfect|cheers)\b|[😊😄🎉❤]/iu],
  ['resolute', /\b(done|completed|on it|proceeding|will do|certainly|consider it done|executing|right away)\b/i],
  ['curious', /\?\s*$|\b(interesting|curious|i wonder|tell me more|what if|fascinating)\b/i],
];
function feel(sentence) {
  for (const [state, pattern] of FEELINGS) if (pattern.test(sentence)) return state;
  return 'speaking';
}
function sentences(text) {
  const clean = String(text || '').replace(/```[\s\S]*?```/g, ' (code shown on screen) ').replace(/[#*_`>]+/g, '').trim();
  const parts = clean.match(/[^.!?\n]+[.!?]*["')\]]*\s*/g) || [clean];
  const out = [];                                         // join tiny fragments so speech flows
  for (const p of parts.map((x) => x.trim()).filter(Boolean)) {
    if (out.length && (out[out.length - 1].length < 25 || p.length < 12)) out[out.length - 1] += ' ' + p; else out.push(p);
  }
  return out.slice(0, 40);
}
async function fetchSpeech(text) {
  const response = await fetch('/api/voice/speak', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || 'Speech failed');
  return URL.createObjectURL(await response.blob());
}

// What JARVIS is saying right now, so it can be cut off mid-sentence.
const speech = { active: false, stop: false, cancelNext: false, audio: null, current: '', wake: null };
/** Resolve with the promise's value, or null the moment speech is stopped. */
function unlessStopped(promise) {
  return Promise.race([promise, new Promise((resolve) => { speech.wake = () => resolve(null); })]);
}
/** Stop talking now (or skip the reply that is about to be spoken). */
function stopSpeaking() {
  speech.stop = true;
  if (!speech.active) speech.cancelNext = true;
  if (speech.audio) { speech.audio.pause(); speech.audio.dispatchEvent(new Event('ended')); }
  if (speech.wake) speech.wake();
}

/** Speak a reply sentence by sentence: each one's feeling drives the swarm,
 *  the next sentence is prepared while this one plays (less waiting).
 *  Returns false if it was interrupted. */
async function speakWith(identity, text) {
  if (speech.cancelNext) { speech.cancelNext = false; return false; }
  const list = sentences(text);
  if (!list.length) return true;
  speech.active = true; speech.stop = false;
  try {
    let next = fetchSpeech(list[0]);
    for (let i = 0; i < list.length; i++) {
      const url = await unlessStopped(next);
      if (speech.stop || !url) { if (url) URL.revokeObjectURL(url); return false; }
      if (i + 1 < list.length) next = fetchSpeech(list[i + 1]);
      speech.current = list[i];
      identity.setState(feel(list[i]), list[i].length > 140 ? list[i].slice(0, 137) + '…' : list[i]);
      await playClip(identity, url);
      URL.revokeObjectURL(url);
      if (speech.stop) return false;
    }
    return true;
  } finally {
    speech.active = false; speech.current = ''; speech.audio = null;
  }
}

async function playClip(identity, url) {
  const audio = new Audio(url);
  speech.audio = audio;
  let meter = null;
  try {                                   // real amplitude, not an animation loop
    const context = new (window.AudioContext || window.webkitAudioContext)();
    const source = context.createMediaElementSource(audio);
    const analyser = context.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser); analyser.connect(context.destination);
    const data = new Uint8Array(analyser.frequencyBinCount);
    meter = setInterval(() => {
      analyser.getByteTimeDomainData(data);
      let peak = 0; for (const v of data) peak = Math.max(peak, Math.abs(v - 128));
      identity.setLevel(peak / 90);
    }, 60);
    audio.onended = () => { clearInterval(meter); identity.setLevel(0); context.close(); };
  } catch (e) { /* playback still works without the meter */ }
  await audio.play();
  await new Promise((resolve) => { audio.addEventListener('ended', resolve, { once: true }); audio.addEventListener('error', resolve, { once: true }); });
  if (meter) clearInterval(meter);
  identity.setLevel(0);
}

views.presence = {
  title: 'JARVIS',
  subtitle: '',
  async render(root) {
    const [status, executions] = await Promise.all([api('GET', '/api/status'), api('GET', '/api/executions?limit=100')]);
    const connected = status.ai.configured && status.ai.available;
    const hero = h('section', { class: 'presence-hero' });
    const stage = h('div', { class: 'presence-stage' });
    const label = h('div', { class: 'label' });
    const line = h('div', { class: 'line' });
    const identity = JarvisIdentity.create(stage, {
      onLine: (text, lab, name) => { label.textContent = lab; line.textContent = text; hero.style.setProperty('--jv-hero-rgb', stateRgb(name)); },
    });
    state.cleanup.push(() => identity.destroy());

    const time = h('div', { class: 'time' }), date = h('div', { class: 'date' });
    const tick = () => { const now = new Date(); time.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); date.textContent = now.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }); };
    tick(); const clock = setInterval(tick, 15000); state.cleanup.push(() => clearInterval(clock));

    // --- real metrics only ---
    const checks = [status.database.integrity_ok, status.database.schema_version === status.database.expected_schema_version,
      status.backups.count > 0, connected, status.voice && status.voice.listening && status.voice.speaking];
    const health = Math.round(100 * checks.filter(Boolean).length / checks.length);
    const runs = executions.items.length;
    const okRate = runs ? Math.round(100 * executions.items.filter((e) => e.status === 'succeeded').length / runs) : null;
    const callout = (pos, k, v, hint) => h('div', { class: `hud-callout ${pos}` },
      h('div', { class: 'v' }, String(v)), h('div', { class: 'k' }, k), h('div', { class: 'hint' }, hint));
    const metric = (k, v, unit, hint) => h('div', { class: 'metric' }, h('div', { class: 'k' }, k), h('div', { class: 'v' }, v, unit ? h('small', null, unit) : null), hint ? h('div', { class: 'hint' }, hint) : null);
    const stream = h('div', { class: 'stream' });
    const showActivity = (items) => {
      stream.replaceChildren(...(items.length ? items.slice(-6).reverse().map((e) => h('div', { class: 'stream-item ' + (e.status === 'succeeded' ? 'ok' : e.status === 'failed' || e.status === 'refused' ? 'bad' : 'run') },
        h('span', { class: 'dot' }), h('div', null, e.description || e.tool, ' ', h('span', { class: 'muted' }, label_(e.status))))) : [h('div', { class: 'muted small' }, 'No activity yet.')]));
    };
    const label_ = (s) => String(s || '').replace(/_/g, ' ');
    showActivity(executions.items.slice(0, 6).reverse().map((e) => ({ tool: e.tool, status: e.status })));

    // --- command bar ---
    const input = h('input', { placeholder: connected ? 'Speak or type your command…' : 'No AI model is connected', 'aria-label': 'Command', disabled: !connected });
    const you = h('div', { class: 'you' }), reply = h('div', { class: 'reply' }), memoryLine = h('div', { class: 'meta' });
    const voiceOk = status.voice || {};
    const mic = h('button', { class: 'round-btn', type: 'button', title: 'Talk to JARVIS', 'aria-label': 'Talk to JARVIS', disabled: !voiceOk.listening || !connected }, '🎙');
    const send = h('button', { class: 'round-btn', type: 'submit', title: 'Send', 'aria-label': 'Send', disabled: !connected }, '➤');
    // --- files and photos: 📎, or drop them anywhere on this page ---
    const picker = h('input', { type: 'file', multiple: true, hidden: true, 'aria-hidden': 'true' });
    const attach = h('button', { class: 'round-btn', type: 'button', title: 'Attach files or photos', 'aria-label': 'Attach files or photos', disabled: !connected }, '📎');
    const attachRow = h('div', { class: 'meta attach-row' });
    let pending = [];                                   // uploaded, waiting to be sent: {path, name}
    const showPending = () => attachRow.replaceChildren(...pending.map((f, i) => {
      const x = h('button', { class: 'btn sm', type: 'button', 'aria-label': `Remove ${f.name}` }, '×');
      x.addEventListener('click', () => { pending.splice(i, 1); showPending(); });
      return h('span', { class: 'chip' }, f.name.replace(/^\d{8}-\d{6}-/, ''), ' ', x);
    }));
    async function addFiles(files) {
      for (const file of files) {
        const response = await fetch(`/api/files?name=${encodeURIComponent(file.name)}`, {
          method: 'POST', headers: { 'Content-Type': file.type || 'application/octet-stream' }, body: file });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) { toast(data.error || `Could not attach ${file.name}`, true); continue; }
        pending.push(data); showPending();
      }
      input.focus();
    }
    attach.addEventListener('click', () => picker.click());
    picker.addEventListener('change', () => { addFiles([...picker.files]); picker.value = ''; });
    hero.addEventListener('dragover', (e) => { e.preventDefault(); hero.classList.add('dropping'); });
    hero.addEventListener('dragleave', () => hero.classList.remove('dropping'));
    hero.addEventListener('drop', (e) => { e.preventDefault(); hero.classList.remove('dropping'); addFiles([...e.dataTransfer.files]); });

    // --- one-click approval, right under the reply (never granted by speech) ---
    const decision = h('div', { class: 'row approve-row' });
    async function offerApproval(runId) {
      decision.replaceChildren();
      const run = await api('GET', `/api/runs/${runId}`).catch(() => null);
      if (!run) return;
      // a single tool waiting (e.g. a priced picture), or a multi-step goal paused for approval
      const waitingStep = run.kind !== 'goal' ? (run.steps || []).slice().reverse().find((st) => st.status === 'waiting_approval' && st.approval_id) : null;
      let approval = run.report && run.report.approval;
      if (waitingStep) approval = (await api('GET', '/api/approvals?status=pending')).items.find((x) => x.id === waitingStep.approval_id);
      if (!approval || approval.status !== 'pending') return;
      const yes = h('button', { class: 'btn primary', type: 'button' }, 'Approve');
      const no = h('button', { class: 'btn', type: 'button' }, 'Deny');
      decision.replaceChildren(h('span', { class: 'grow small' }, approval.summary), no, yes);
      no.addEventListener('click', act(async () => {
        await api('POST', `/api/approvals/${approval.id}/deny`); await api('POST', `/api/runs/${runId}/cancel`).catch(() => {});
        decision.replaceChildren(); reply.textContent = 'Cancelled. Nothing was done.'; identity.setState('calm');
      }));
      yes.addEventListener('click', act(async () => {
        decision.replaceChildren(); identity.setState('executing', 'Approved. Working on it…');
        await api('POST', `/api/approvals/${approval.id}/approve`);
        if (waitingStep) {                              // re-run that exact tool call with the approval
          const out = await api('POST', `/api/tools/${waitingStep.tool}/execute`, { inputs: waitingStep.input, approval_id: approval.id, run_id: runId });
          const made = out.output || {};
          reply.textContent = out.ok ? (made.path ? `Here it is${typeof made.cost === 'number' ? ` (${made.cost} credits)` : ''}. Saved to ${made.path}` : (made.result || 'Done.')) : `That failed: ${out.error}`;
          const pictures = typeof workspaceImages === 'function' ? workspaceImages(reply.textContent) : null; if (pictures) reply.append(pictures);
          identity.setState(out.ok ? 'success' : 'failure'); refreshChrome();
          return;
        }
        const report = await api('POST', `/api/runs/${runId}/resume`);
        const done = await api('GET', `/api/runs/${runId}`);
        const results = (done.steps || []).filter((st) => st.status === 'succeeded' && st.output && typeof st.output.result === 'string').map((st) => st.output.result);
        reply.textContent = results.join('\n\n') || (report.summary || report.status || 'Done.');
        identity.setState(report.status === 'completed' ? 'success' : report.status === 'failed' ? 'failure' : 'calm');
        if (localStorageGet('jarvis.speak') === 'on' || convo.on) await speakWith(identity, reply.textContent).catch(() => {});
        refreshChrome();
      }));
    }

    const form = h('form', { class: 'presence-command' }, picker, attach, mic, input, send);
    let speakNext = false, busy = false, settle = null;

    async function submit(text) {
      if ((!text && !pending.length) || busy) return;
      const files = pending.map((f) => f.path); pending = []; showPending();
      busy = true; send.disabled = mic.disabled = true; clearTimeout(settle); decision.replaceChildren();
      input.value = ''; you.textContent = `You: ${text || '(files)'}${files.length ? `  📎 ${files.length}` : ''}`; reply.textContent = ''; memoryLine.replaceChildren();
      identity.setState('analysing', 'Understood. Reviewing…');
      let baseline = 0;
      try { const before = await api('GET', '/api/live'); baseline = before.run_id || before.last_run || 0; } catch (e) { /* ignore */ }
      const poll = setInterval(async () => {            // follow the real run while it works
        try {
          const live = await api('GET', '/api/live');
          if (live.run_id && live.run_id > baseline) {
            const [s, l] = JarvisIdentity.fromLive(live);
            if (!['success', 'failure', 'calm'].includes(s)) identity.setState(s, l);
            showActivity(live.activity || []);
          }
        } catch (e) { /* the next poll will try again */ }
      }, 450);
      try {
        const result = await api('POST', '/api/chat', { message: text, attachments: files, conversation_id: currentConversation(), voice: speakNext });
        rememberConversation(result.conversation.id);
        if (result.reply.run_id) offerApproval(result.reply.run_id);
        clearInterval(poll);
        const shownText = result.reply.content.replace(/ Approve or deny it on the System page, then press Continue\./, ' Approve or deny it below.');
        reply.replaceChildren(JarvisUI.richText(shownText)); reply.classList.remove('msg-in'); void reply.offsetWidth; reply.classList.add('msg-in');
        const pictures = workspaceImages(result.reply.content); if (pictures) reply.append(pictures);
        if (result.reply.memory_refs) memoryLine.replaceChildren(chip('From memory', 'violet'), ...result.reply.memory_refs.map((r) => chip(r.content.length > 40 ? r.content.slice(0, 39) + '…' : r.content)));
        const live = await api('GET', '/api/live').catch(() => null);
        if (live && live.run_id && live.run_id > baseline) {
          const [s, l] = JarvisIdentity.fromLive(live);
          identity.setState(s, l);
          showActivity(live.activity || []);
        } else {
          identity.setState(result.reply.role === 'system' ? 'warning' : 'calm', '');
        }
        if (speakNext || localStorageGet('jarvis.speak') === 'on') {
          const said = sentences(result.reply.content);         // long answers: say the start, show the rest
          const spoken = said.length > 3 ? said.slice(0, 3).join(' ') + ' The rest is on screen.' : result.reply.content;
          await speakWith(identity, spoken).catch((e) => toast(e.message, true));
        }
        const final = identity.state;
        if (['success', 'speaking', 'warm', 'curious', 'sad', 'angry', 'resolute', 'concerned'].includes(final) && !convo.on) settle = setTimeout(() => identity.setState('calm'), 3000);
        refreshChrome();
      } catch (error) {
        clearInterval(poll);
        identity.setState('error', error.message);
      } finally {
        busy = false; speakNext = false; send.disabled = false; mic.disabled = !voiceOk.listening; input.focus();
      }
    }
    form.addEventListener('submit', (event) => { event.preventDefault(); submit(input.value.trim()); });

    // --- reminders: when one fires while this page is open, JARVIS says it ---
    let announcing = false;
    async function announceReminders() {
      if (busy || announcing) return;
      announcing = true;
      try {
        const { items } = await api('GET', '/api/reminders/due');
        if (!items.length) return;
        const said = items.map((a) => a.text).join(' ');
        you.textContent = ''; reply.textContent = said; memoryLine.replaceChildren(chip('Reminder', 'violet'));
        identity.setState('resolute', said);
        if (voiceOk.speaking) await speakWith(identity, said).catch(() => {});   // the browser may block sound until a click
        refreshChrome();
        clearTimeout(settle); settle = setTimeout(() => { if (!busy) identity.setState('calm'); }, 6000);
      } catch (e) { /* the next check will try again */ } finally { announcing = false; }
    }
    const reminderPoll = setInterval(announceReminders, 15000); state.cleanup.push(() => clearInterval(reminderPoll));
    setTimeout(announceReminders, 1500);

    async function transcribe(blob) {
      const response = await fetch('/api/voice/transcribe', { method: 'POST', headers: { 'Content-Type': blob.type || 'audio/webm' }, body: blob });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'Could not understand the recording');
      return (data.text || '').trim();
    }

    // --- hands-free: always listening for its name; "Jarvis" opens a conversation ---
    // waiting: short utterances are transcribed locally and checked for the name.
    // talking: every utterance is a message; ~25 s of silence or "stop" returns to waiting.
    const WAKE = /\b(jarvis|jarvi|javis|jervis|jarves|jarviss)\b[\s,.!?:-]*/i;
    const convo = { on: false, talking: false };
    const convoBtn = h('button', { class: 'btn sm', type: 'button', disabled: !voiceOk.listening || !voiceOk.speaking || !connected }, 'Hands-free: off');
    const setBtn = () => { convoBtn.textContent = convo.on ? (convo.talking ? 'In conversation · end' : 'Hands-free: on') : 'Hands-free: off'; convoBtn.classList.toggle('primary', convo.on); };
    async function listenOnce(stream, opts = {}) {
      const context = new (window.AudioContext || window.webkitAudioContext)();
      const analyser = context.createAnalyser(); analyser.fftSize = 1024;
      context.createMediaStreamSource(stream).connect(analyser);
      const data = new Uint8Array(analyser.fftSize), chunks = [];
      const rec = new MediaRecorder(stream);
      rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      rec.start(250);
      let spoke = false, loudFor = 0;
      const started = performance.now();
      let lastVoice = started;
      await new Promise((resolve) => {
        const tick = setInterval(() => {
          analyser.getByteTimeDomainData(data);
          let sum = 0; for (const v of data) { const d = (v - 128) / 128; sum += d * d; }
          const rms = Math.sqrt(sum / data.length), now = performance.now();
          if (!opts.quiet) identity.setLevel(Math.min(1, rms * 7));
          if (rms > 0.035) { loudFor += 50; if (loudFor > 150) spoke = true; lastVoice = now; } else loudFor = 0;
          const done = !convo.on || (opts.abort && opts.abort()) || (spoke && now - lastVoice > (opts.quiet ? 1100 : 1700)) || now - started > 25000 || (!spoke && now - started > 12000);
          if (done) { clearInterval(tick); resolve(); }
        }, 50);
      });
      const stopped = new Promise((r) => { rec.onstop = r; });
      rec.stop(); await stopped; context.close(); if (!opts.quiet) identity.setLevel(0);
      return spoke ? new Blob(chunks, { type: rec.mimeType || 'audio/webm' }) : null;
    }
    async function bargeIn(stream, watch) {
      while (!watch.done && convo.on) {
        const blob = await listenOnce(stream, { quiet: true, abort: () => watch.done });
        if (watch.done || !blob) continue;
        let text = '';
        try { text = await transcribe(blob); } catch (e) { continue; }
        if (watch.skip && watch.skip.test(text) && !watch.skip.test(speech.current)) {   // "skip" during the briefing
          stopSpeaking(); watch.heard = ''; identity.setState('listening', 'Okay. Go ahead.'); return;
        }
        const hit = text.match(WAKE);
        if (!hit || /jarvis/i.test(speech.current)) continue;  // its own voice saying its name is not a call
        stopSpeaking();
        convo.talking = true; setBtn();
        watch.heard = text.slice(hit.index + hit[0].length).trim();
        identity.setState('listening', 'Go ahead.');
        return;
      }
    }
    // a press on JARVIS while it talks mutes it until it is called again
    stage.addEventListener('pointerdown', () => {
      if (!speech.active && !busy) return;
      stopSpeaking();
      convo.talking = false; setBtn();
      setTimeout(() => identity.setState('calm', 'Muted. Say “Jarvis” when you need me.'), 60);
    });
    // the morning briefing: played on the first "Jarvis" of the day, or when asked for
    const BRIEFING_ASK = /\b(briefing|brief me|morning (update|summary|rundown)|what'?s (on )?(my|the) day)\b/i;
    const SKIP = /\b(skip|stop|enough|later|not now|that'?s (enough|fine)|quiet)\b/i;
    const localDay = () => { const d = new Date(); return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`; };
    const briefedToday = () => localStorageGet('jarvis.briefed') === localDay();
    async function playBriefing(stream) {
      try { localStorage.setItem('jarvis.briefed', localDay()); } catch (e) { /* private window */ }
      identity.setState('analysing', 'Getting your briefing…');
      let data;
      try { data = await api('GET', '/api/briefing'); } catch (e) { identity.setState('listening', 'Yes?'); return null; }
      you.textContent = 'Morning briefing'; reply.textContent = data.text; memoryLine.replaceChildren();
      const watch = { done: false, heard: null, skip: SKIP };
      const watching = bargeIn(stream, watch);             // "skip", "stop" or "Jarvis" cuts it short
      await speakWith(identity, data.text).catch(() => {});
      watch.done = true; await watching;
      return watch.heard;
    }

    async function handsFree() {
      let stream;
      try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }); }
      catch (e) { convo.on = false; setBtn(); identity.setState('calm', 'Allow the microphone to talk hands-free.'); return; }
      let quiet = 0, queued = null, carry = '';
      while (convo.on) {
        let heard = '';
        if (queued) { heard = queued; queued = null; }              // said right after interrupting
        else {
          if (!convo.talking) identity.setState('calm', 'Say “Jarvis” to talk.');
          else identity.setState('listening', 'Go ahead.');
          const blob = await listenOnce(stream);
          if (!convo.on) break;
          if (!blob) { if (convo.talking && ++quiet >= 2) { convo.talking = false; setBtn(); } continue; }
          quiet = 0;
          try { heard = await transcribe(blob); } catch (error) { continue; }
        }
        if (!heard || /^\W*$/.test(heard)) continue;
        if (!convo.talking) {
          const hit = heard.match(WAKE);
          if (!hit) continue;                                  // not for JARVIS: ignored, never sent anywhere
          convo.talking = true; setBtn();
          heard = heard.slice(hit.index + hit[0].length).trim();
          if ((!heard || heard.split(/\s+/).length < 2) && !briefedToday()) {   // first "Jarvis" of the day
            const after = await playBriefing(stream);
            if (after) queued = after;
            else if (!speech.stop) identity.setState('listening', 'Anything else?');
            continue;
          }
          if (!heard || heard.split(/\s+/).length < 2) { identity.setState('listening', 'Yes?'); await speakWith(identity, 'Yes?').catch(() => {}); continue; }
        }
        if (BRIEFING_ASK.test(heard) && heard.split(/\s+/).length <= 8) {     // "what's my briefing"
          const after = await playBriefing(stream);
          if (after) queued = after;
          continue;
        }
        // "So...", "Um", "Alright, so": the start of a thought, not a message. Keep it, add the next part.
        if (convo.talking && /^(so|um+|uh+|er+|hmm+|alright|all right|okay|ok|well|and|but|like|right|listen|look)([\s,.!?…-]+(so|um+|uh+|then|listen|look))*[\s,.!?…-]*$/i.test(heard)) {
          carry = (carry + ' ' + heard).trim(); continue;
        }
        if (carry) { heard = `${carry} ${heard}`; carry = ''; }
        if (/^(stop|end|that'?s all|goodbye|bye)( (the )?conversation)?[.!]*$/i.test(heard)) {
          convo.talking = false; setBtn(); await speakWith(identity, 'Standing by.').catch(() => {}); continue;
        }
        speakNext = true;
        const watch = { done: false, heard: null };
        const watching = bargeIn(stream, watch);              // "Jarvis" while it thinks or talks cuts it off
        await submit(heard);
        watch.done = true; await watching;
        if (watch.heard) queued = watch.heard;
      }
      stream.getTracks().forEach((t) => t.stop());
      convo.talking = false; setBtn();
      identity.setState('calm', 'Hands-free is off.');
    }
    convoBtn.addEventListener('click', () => {
      if (convo.on && convo.talking) { convo.talking = false; setBtn(); return; }   // end this conversation, keep listening
      convo.on = !convo.on; setBtn();
      try { localStorage.setItem('jarvis.handsfree', convo.on ? 'on' : 'off'); } catch (e) { /* private window */ }
      if (convo.on) handsFree();
    });
    state.cleanup.push(() => { convo.on = false; });
    // on by default once the owner has allowed the microphone; a click is never needed again
    if (!convoBtn.disabled && localStorageGet('jarvis.handsfree') !== 'off') { convo.on = true; setBtn(); setTimeout(handsFree, 600); }

    let recorder = null;
    mic.addEventListener('click', act(async () => {
      if (recorder) { recorder.stop(); return; }
      let stream_;
      try { stream_ = await navigator.mediaDevices.getUserMedia({ audio: true }); }
      catch (e) { throw new Error('Microphone access was blocked. Allow it for this page in the browser settings.'); }
      const chunks = [];
      recorder = new MediaRecorder(stream_);
      recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      recorder.onstop = async () => {
        stream_.getTracks().forEach((t) => t.stop());
        mic.classList.remove('recording');
        const blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
        recorder = null;
        identity.setState('analysing', 'Transcribing…');
        try {
          const heard = await transcribe(blob);
          if (!heard) { identity.setState('calm', "I didn't catch that."); return; }
          speakNext = true;
          submit(heard);
        } catch (error) { identity.setState('error', error.message); }
      };
      recorder.start();
      mic.classList.add('recording');
      identity.setState('listening', "I'm listening. Click again when you've finished.");
    }));

    const previewBtn = h('button', { class: 'btn sm', type: 'button' }, 'Preview all states');
    const simBadge = chip('SIMULATION · not real activity', 'pink'); simBadge.hidden = true;
    let stopPreview = null;
    previewBtn.addEventListener('click', () => {
      if (stopPreview) { stopPreview(); stopPreview = null; simBadge.hidden = true; previewBtn.textContent = 'Preview all states'; identity.setState('calm'); return; }
      simBadge.hidden = false; previewBtn.textContent = 'Stop preview';
      stopPreview = identity.preview();
    });
    state.cleanup.push(() => stopPreview && stopPreview());

    hero.append(
      h('div', { class: 'presence-head' },
        h('div', { class: 'presence-mark' }, h('div', null, h('div', { class: 'name' }, 'JARVIS'), h('div', { class: 'motto' }, 'Your private executive intelligence'))),
        h('div', { class: 'presence-clock' }, time, date)),
      stage,
      h('div', { class: 'presence-state' }, label, line),
      form,
      attachRow,
      h('div', { class: 'presence-exchange' }, you, reply, decision, memoryLine),
      h('div', { class: 'row end presence-tools' }, convoBtn, simBadge, previewBtn));

    // the concept's panels around the face: system, activity, Mac, task, result, schedule, decisions
    let previewTimer = null;
    const deck = JarvisDeck.build({ preview: (name, meaning) => {
      clearTimeout(previewTimer);
      identity.setState(name, `Preview: ${meaning.toLowerCase()}`);
      previewTimer = setTimeout(() => identity.setState('calm'), 4000);
    } });
    state.cleanup.push(() => { deck.stop(); clearTimeout(previewTimer); });
    const layout = h('div', { class: 'presence deck' }, deck.left, hero, deck.right, deck.states, deck.abilities);
    root.append(layout);
    const hud = JarvisMotion.attach(stage, identity);               // reticle + live voice line
    state.cleanup.push(() => hud.destroy());
    JarvisMotion.enter(layout, [deck.left.children, [hero], deck.right.children, [deck.states, deck.abilities]]);
    identity.setState(connected ? 'calm' : 'offline', connected ? 'Standing by.' : status.ai.detail);
    if (connected) input.focus();
  },
};

function localStorageGet(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }

/** Compact identity for the JARVIS Desktop panel. The app drives it through window.jarvisDesktop. */
views.desktop = {
  title: 'JARVIS', subtitle: '',
  async render(root) {
    document.documentElement.classList.add('desktop-mode');
    const stage = h('div', { class: 'desktop-identity' });
    root.append(stage);
    const identity = JarvisIdentity.create(stage, { compact: true });
    let poll = null;
    const follow = () => {                 // while thinking, show what the engine is really doing
      clearInterval(poll);
      poll = setInterval(async () => {
        try {
          const live = await api('GET', '/api/live');
          if (live.run_id) { const [s, l] = JarvisIdentity.fromLive(live); if (s !== 'calm') identity.setState(s, l); }
        } catch (e) { /* keep the current state */ }
      }, 500);
    };
    window.jarvisDesktop = {
      setState(name, line) { clearInterval(poll); identity.setState(name, line); if (name === 'analysing') follow(); },
      setLevel(v) { identity.setLevel(v); },
    };
    identity.setState('calm');
  },
};

// --- shell -----------------------------------------------------------------
async function refreshChrome() {
  try {
    const status = await api('GET', '/api/status');
    const connected = status.ai.configured && status.ai.available;
    $('#ai-dot').className = 'dot ' + (connected ? 'ok' : 'off');
    $('#ai-label').textContent = connected ? `AI: ${status.ai.name}` : 'No AI connected';
    $('#ai-pill').title = status.ai.detail;
    $('#brand-version').textContent = `core v${status.version}`;
    const badge = $('#approval-badge');
    badge.hidden = !status.counts.pending_approvals;
    badge.textContent = status.counts.pending_approvals;
  } catch (error) {
    $('#ai-dot').className = 'dot off';
    $('#ai-label').textContent = 'JARVIS is not responding';
  }
}

async function show(name) {
  const view = views[name] || views.presence;
  const key = views[name] ? name : 'presence';
  const token = ++state.navigation;
  state.cleanup.splice(0).forEach((fn) => { try { fn(); } catch (e) { /* already gone */ } });
  document.body.classList.toggle('presence-mode', key === 'presence');
  document.querySelectorAll('.nav a').forEach((link) => {
    const active = link.dataset.view === key;
    link.classList.toggle('active', active);
    if (active) { link.setAttribute('aria-current', 'page'); link.scrollIntoView({ block: 'nearest', inline: 'nearest' }); }
    else link.removeAttribute('aria-current');
  });
  $('#view-title').textContent = view.title;
  $('#view-subtitle').textContent = view.subtitle;
  document.title = `${view.title} · JARVIS`;
  const root = h('section', { id: 'view' });
  try {
    await loadProjects();
    await view.render(root);
  } catch (error) {
    root.replaceChildren(h('div', { class: 'banner' }, h('div', null, h('strong', null, 'This page could not load'), h('span', { class: 'muted' }, error.message))));
  }
  if (token !== state.navigation) return;  // a newer navigation has taken over
  $('#view').replaceWith(root);
}

// A small live JARVIS in every page header, following the real run state.
let headerOrb = null;
function startHeaderOrb() {
  const host = document.getElementById('topbar-orb');
  if (!host || headerOrb || !window.JarvisIdentity) return;
  headerOrb = JarvisIdentity.create(host, { compact: true });
  headerOrb.setState('calm');
  setInterval(async () => {
    if (document.hidden || document.body.classList.contains('presence-mode')) return;
    try { const [s] = JarvisIdentity.fromLive(await api('GET', '/api/live')); headerOrb.setState(s); } catch (e) { /* next tick */ }
  }, 3000);
}

// Inside a JARVIS OS window: no sidebar or header orb, the page fills the window.
const EMBEDDED = new URLSearchParams(location.search).has('embed');
if (EMBEDDED) document.documentElement.classList.add('embedded');
const route = async () => { if (!EMBEDDED) startHeaderOrb(); await show(location.hash.replace('#', '') || 'presence'); window.scrollTo(0, 0); };
window.addEventListener('hashchange', route);
route();
refreshChrome();
state.timer = setInterval(refreshChrome, 30000);
