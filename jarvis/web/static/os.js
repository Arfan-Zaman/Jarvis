/* JARVIS AI Operating System: the desktop shell. Each app is a real JARVIS page in a window
   (an iframe of the same app in embedded mode), so everything that works in JARVIS works here. */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const icon = (d) => `<svg viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
  const api = async (method, path, body) => {
    const r = await fetch(path, { method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
    const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(d.error || `${path} failed`); return d;
  };

  const APPS = [
    { id: 'presence', name: 'JARVIS', core: true, w: 1180, h: 800, hint: 'talk, voice, the live face' },
    { id: 'chat', name: 'Chat', icon: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>', w: 980, h: 680, hint: 'conversations and files' },
    { id: 'dashboard', name: 'Dashboard', icon: '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>', w: 1000, h: 720, hint: 'overview and activity' },
    { id: 'tasks', name: 'Tasks', icon: '<path d="M9 6h11M9 12h11M9 18h11"/><path d="m3 6 1 1 2-2M3 12l1 1 2-2M3 18l1 1 2-2"/>', w: 860, h: 640, hint: 'tasks and reminders' },
    { id: 'goals', name: 'Goals', icon: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>', w: 900, h: 660, hint: 'give JARVIS a goal' },
    { id: 'memory', name: 'Memory', icon: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>', w: 860, h: 640, hint: 'what JARVIS knows and learns' },
    { id: 'projects', name: 'Projects', icon: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>', w: 860, h: 600, hint: 'your businesses' },
    { id: 'experiences', name: 'Experiences', icon: '<path d="M12 3v18M3 12h18"/><circle cx="12" cy="12" r="9"/>', w: 820, h: 600, hint: 'lessons learned' },
    { id: 'system', name: 'System', icon: '<path d="M12 3l7 3v5c0 4.4-3 8.2-7 10-4-1.8-7-5.6-7-10V6z"/>', w: 980, h: 720, hint: 'abilities, approvals, self-review' },
  ];
  const wins = new Map();
  let z = 10;
  const saved = (() => { try { return JSON.parse(localStorage.getItem('jarvis.os.windows') || '{}'); } catch (e) { return {}; } })();
  const save = () => {
    const out = {};
    wins.forEach((w, id) => { out[id] = { x: w.x, y: w.y, w: w.node.offsetWidth, h: w.node.offsetHeight, open: !w.node.hidden }; });
    try { localStorage.setItem('jarvis.os.windows', JSON.stringify(out)); } catch (e) { /* ignore */ }
  };

  // --- dock ---------------------------------------------------------------------------------
  const dock = $('dock');
  APPS.forEach((app, i) => {
    const b = el('button', 'dock-app' + (app.core ? ' core' : '')); b.type = 'button'; b.dataset.app = app.id;
    b.setAttribute('aria-label', app.name);
    if (app.core) b.append(el('i')); else b.innerHTML = icon(app.icon);          // fixed markup, never user text
    b.append(el('span', 'tip', app.name));
    b.addEventListener('click', () => toggle(app.id));
    dock.append(b);
    if (i === 0) dock.append(el('span', 'dock-sep'));
  });
  const markRunning = () => dock.querySelectorAll('.dock-app').forEach((b) => b.classList.toggle('running', wins.has(b.dataset.app)));

  // --- windows ------------------------------------------------------------------------------
  function focus(id) {
    const w = wins.get(id); if (!w) return;
    wins.forEach((o) => o.node.classList.remove('focused'));
    w.node.style.zIndex = String(++z); w.node.classList.add('focused');
    $('app-title').textContent = APPS.find((a) => a.id === id).name;
  }
  function place(w) { w.node.style.transform = `translate(${w.x}px, ${w.y}px)`; }

  function open(id) {
    if (wins.has(id)) { const w = wins.get(id); w.node.hidden = false; focus(id); save(); return; }
    const app = APPS.find((a) => a.id === id); if (!app) return;
    const desk = $('windows').getBoundingClientRect();
    const s = saved[id] || {};
    const width = Math.min(s.w || app.w, desk.width - 40), height = Math.min(s.h || app.h, desk.height - 110);
    const n = wins.size;
    const w = { node: el('section', 'os-win'), x: s.x ?? Math.max(20, (desk.width - width) / 2 + n * 28 - 60), y: s.y ?? Math.max(12, 20 + n * 24) };
    w.node.style.width = `${width}px`; w.node.style.height = `${height}px`;
    const dockIcon = dock.querySelector(`[data-app="${id}"]`).getBoundingClientRect();
    w.node.style.setProperty('--origin-x', `${dockIcon.left + dockIcon.width / 2 - w.x}px`);   // opens from its dock icon
    const bar = el('div', 'win-bar'), lights = el('div', 'win-lights');
    const close = el('button', 'c'), min = el('button', 'm'), max = el('button', 'x');
    close.type = min.type = max.type = 'button';
    close.setAttribute('aria-label', `Close ${app.name}`); min.setAttribute('aria-label', `Minimise ${app.name}`); max.setAttribute('aria-label', `Maximise ${app.name}`);
    lights.append(close, min, max); bar.append(lights, el('span', 'win-title', app.name));
    const body = el('div', 'win-body'), frame = el('iframe');
    frame.src = `/?embed=1#${id}`; frame.title = app.name;
    frame.setAttribute('allow', 'microphone; clipboard-write');
    body.append(frame); w.node.append(bar, body);
    $('windows').append(w.node); wins.set(id, w); place(w); focus(id); markRunning();

    close.addEventListener('click', (e) => { e.stopPropagation(); shut(id); });
    min.addEventListener('click', (e) => { e.stopPropagation(); w.node.hidden = true; save(); });
    max.addEventListener('click', (e) => { e.stopPropagation(); w.node.classList.toggle('max'); });
    bar.addEventListener('dblclick', () => w.node.classList.toggle('max'));
    w.node.addEventListener('pointerdown', () => focus(id), true);
    // drag by the title bar: transform only, the iframe ignores the pointer meanwhile
    bar.addEventListener('pointerdown', (e) => {
      if (e.target.closest('.win-lights') || w.node.classList.contains('max')) return;
      const sx = e.clientX - w.x, sy = e.clientY - w.y; bar.setPointerCapture(e.pointerId); frame.style.pointerEvents = 'none';
      const move = (ev) => { w.x = Math.max(-w.node.offsetWidth + 120, Math.min(desk.width - 120, ev.clientX - sx)); w.y = Math.max(0, Math.min(desk.height - 60, ev.clientY - sy)); place(w); };
      const up = () => { bar.removeEventListener('pointermove', move); frame.style.pointerEvents = ''; save(); };
      bar.addEventListener('pointermove', move); bar.addEventListener('pointerup', up, { once: true });
    });
    new ResizeObserver(() => save()).observe(w.node);
    save();
  }
  function shut(id) {
    const w = wins.get(id); if (!w) return;
    w.node.classList.add('closing');
    setTimeout(() => { w.node.remove(); wins.delete(id); markRunning(); save(); }, 160);
  }
  function toggle(id) {
    const w = wins.get(id);
    if (!w) return open(id);
    if (w.node.hidden) { w.node.hidden = false; focus(id); }
    else if (w.node.classList.contains('focused')) { w.node.hidden = true; }
    else focus(id);
    save();
  }

  // --- top bar ------------------------------------------------------------------------------
  const tickClock = () => { $('os-clock').textContent = new Date().toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }); };
  tickClock(); setInterval(tickClock, 15000);
  const STATE_WORDS = { calm: 'Standing by', analysing: 'Thinking', planning: 'Planning', executing: 'Working', approval: 'Needs your approval',
    awaiting: 'Waiting for you', success: 'Done', failure: 'Something failed', concerned: 'Checking a problem', resolute: 'Retrying' };
  async function live() {
    try {
      const d = await api('GET', '/api/live');
      const words = d.step && d.step.description ? d.step.description.split('…')[0] : STATE_WORDS[d.state] || 'Standing by';
      $('os-state').lastChild.textContent = words;
      const spec = (window.JarvisIdentity && JarvisIdentity.STATES[d.state]) || JarvisIdentity.STATES.calm;
      document.documentElement.style.setProperty('--jv-hero-rgb', spec.color.join(','));
    } catch (e) { $('os-state').lastChild.textContent = 'Offline'; }
  }
  live(); setInterval(live, 2500);
  async function mac() {
    try {
      const m = await api('GET', '/api/mac/status');
      $('os-battery').textContent = (m.battery || '').split(';')[0];
      $('os-wifi').textContent = m.wifi_ip && m.wifi_ip !== 'not connected' ? 'Wi-Fi' : 'Offline';
    } catch (e) { /* ignore */ }
  }
  mac(); setInterval(mac, 120000);

  // --- widgets (the live panels) ----------------------------------------------------------------
  const deck = JarvisDeck.build({});
  $('widgets-left').append(...deck.left.children);
  $('widgets-right').append(...deck.right.children);

  // --- notifications: reminders due and approvals waiting ------------------------------------------
  const seen = new Set(); let notes = [];
  const toast = (title, text, appId) => {
    const t = el('div', 'os-toast'); t.append(el('b', null, title), el('div', 'dk-hint', text));
    if (appId) { t.style.cursor = 'pointer'; t.addEventListener('click', () => open(appId)); }
    $('toasts-os').append(t); setTimeout(() => t.remove(), 6000);
  };
  async function checkNotes() {
    try {
      const [approvals, due] = await Promise.all([api('GET', '/api/approvals?status=pending'), api('GET', '/api/reminders/due').catch(() => ({ items: [] }))]);
      const items = [...approvals.items.map((a) => ({ key: `a${a.id}`, title: 'Needs your approval', text: a.summary, app: 'system' })),
        ...((due.items || due || []).map((r) => ({ key: `r${r.id}-${r.next_at || r.fired_at || ''}`, title: 'Reminder', text: r.text, app: 'tasks' })))];
      items.forEach((n) => { if (!seen.has(n.key)) { seen.add(n.key); if (notes.length) toast(n.title, n.text, n.app); } });
      notes = items;
      $('bell-count').hidden = !items.length; $('bell-count').textContent = String(items.length);
      $('notes').replaceChildren(...(items.length ? items.map((n) => { const d = el('div', 'note'); d.append(el('b', null, n.title), el('span', null, n.text)); d.addEventListener('click', () => open(n.app)); return d; })
        : [el('div', 'note', 'No notifications.')]));
    } catch (e) { /* next round */ }
  }
  checkNotes(); setInterval(checkNotes, 15000);
  $('bell').addEventListener('click', () => { $('notes').hidden = !$('notes').hidden; });

  // --- command bar (⌘K): open apps, or ask JARVIS. No animation: it opens many times a day. ------------
  const palette = $('palette'), pinput = $('palette-input'), plist = $('palette-list'), panswer = $('palette-answer');
  let pick = 0, matches = [];
  const showPalette = () => { palette.hidden = false; pinput.value = ''; panswer.replaceChildren(); renderList(); pinput.focus(); };
  const hidePalette = () => { palette.hidden = true; };
  function renderList() {
    const q = pinput.value.trim().toLowerCase();
    matches = APPS.filter((a) => !q || a.name.toLowerCase().includes(q) || a.hint.includes(q)).slice(0, 6);
    pick = Math.min(pick, Math.max(0, matches.length - 1));
    const rows = matches.map((a, i) => { const b = el('button', 'palette-item' + (i === pick ? ' on' : '')); b.type = 'button';
      b.append(el('span', null, `Open ${a.name}`), el('small', null, a.hint)); b.addEventListener('click', () => { hidePalette(); open(a.id); }); return b; });
    if (q) { const ask = el('button', 'palette-item' + (matches.length === 0 ? ' on' : '')); ask.type = 'button';
      ask.append(el('span', null, `Ask JARVIS: “${pinput.value.trim()}”`), el('small', null, 'Enter')); ask.addEventListener('click', () => askJarvis(pinput.value.trim())); rows.push(ask); }
    plist.replaceChildren(...rows);
  }
  async function askJarvis(text) {
    if (!text) return;
    panswer.replaceChildren(el('div', 'dk-hint', 'JARVIS is working on it…'));
    let convo = null;
    try { const s = JSON.parse(localStorage.getItem('jarvis.conversation') || 'null'); if (s && Date.now() - s.at < 3 * 3600 * 1000) convo = s.id; } catch (e) { /* ignore */ }
    try {
      const r = await api('POST', '/api/chat', { message: text, conversation_id: convo });
      try { localStorage.setItem('jarvis.conversation', JSON.stringify({ id: r.conversation.id, at: Date.now() })); } catch (e) { /* ignore */ }
      panswer.replaceChildren(JarvisUI.richText(r.reply.content));
    } catch (e) { panswer.replaceChildren(el('div', 'dk-hint', e.message)); }
  }
  pinput.addEventListener('input', () => { pick = 0; renderList(); });
  pinput.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); const n = plist.children.length; pick = (pick + (e.key === 'ArrowDown' ? 1 : n - 1)) % Math.max(1, n); [...plist.children].forEach((c, i) => c.classList.toggle('on', i === pick)); }
    if (e.key === 'Enter') { e.preventDefault(); const item = plist.children[pick] || plist.lastChild; if (item) item.click(); }
    if (e.key === 'Escape') hidePalette();
  });
  palette.addEventListener('pointerdown', (e) => { if (e.target === palette) hidePalette(); });
  $('ask-open').addEventListener('click', showPalette);
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); palette.hidden ? showPalette() : hidePalette(); }
    if (e.key === 'Escape' && !$('notes').hidden) $('notes').hidden = true;
  });

  // --- boot: once per session, then restore the windows that were open -----------------------------------
  let booted = false; try { booted = sessionStorage.getItem('jarvis.os.booted') === '1'; sessionStorage.setItem('jarvis.os.booted', '1'); } catch (e) { /* ignore */ }
  if (booted || JarvisMotion.reduce()) $('boot').hidden = true; else setTimeout(() => { $('boot').hidden = true; }, 1800);
  const reopen = Object.entries(saved).filter(([, s]) => s.open).map(([id]) => id);
  setTimeout(() => (reopen.length ? reopen : ['presence']).forEach(open), booted ? 0 : 1300);
})();
