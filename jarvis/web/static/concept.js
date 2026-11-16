/* JARVIS concept page: every number and line comes from JARVIS's own API. Nothing is simulated
   except the state gallery, whose faces are labelled as examples of each state. */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const api = async (method, path, body) => {
    const response = await fetch(path, { method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `${path} failed`);
    return data;
  };
  const ago = (iso) => {
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    return s < 90 ? 'just now' : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 129600 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`;
  };
  const until = (iso) => {
    const d = new Date(iso);
    return d.toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' });
  };

  // --- the face -----------------------------------------------------------------
  const face = JarvisIdentity.create($('stage'), {
    onLine: (text, label) => { $('s-label').textContent = label.charAt(0) + label.slice(1).toLowerCase(); $('s-line').textContent = text; },
  });
  let previewUntil = 0;

  const tick = () => { $('clock').textContent = new Date().toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }); };
  tick(); setInterval(tick, 15000);

  // --- live state and the current task -------------------------------------------------
  async function live() {
    let data;
    try { data = await api('GET', '/api/live'); } catch (e) { return; }
    if (Date.now() > previewUntil) { const [s, l] = JarvisIdentity.fromLive(data); face.setState(s, l); }
    const steps = $('t-steps'), pill = $('t-pill');
    if (data.plan && data.plan.length) {
      steps.replaceChildren(...data.plan.map((p) => el('li', p.status === 'completed' ? 'done' : p.status, `${p.description}${p.status === 'completed' ? '  ✓' : ''}`)));
      pill.textContent = data.state; pill.className = 'pill run';
    } else if (data.step) {
      steps.replaceChildren(el('li', 'running', data.step.description));
      pill.textContent = 'working'; pill.className = 'pill run';
    } else {
      steps.replaceChildren(el('li', 'muted', 'No task running. Standing by.'));
      pill.textContent = 'idle'; pill.className = 'pill';
    }
  }
  live(); setInterval(live, 1500);

  // --- system, activity, result, coming up, needs you --------------------------------------
  async function vitals() {
    const status = await api('GET', '/api/status');
    const on = status.abilities.filter((a) => a.state === 'on' || a.state === 'asks first').length;
    $('v-abilities').textContent = on; $('v-total').textContent = status.abilities.length;
    const c = status.counts || {};
    const kv = [['Model', status.ai.available ? status.ai.model : 'offline'], ['Memories', c.memories],
      ['Open tasks', c.tasks_open], ['Projects', c.projects], ['Tools', c.tools]];
    $('v-kv').replaceChildren(...kv.flatMap(([k, v]) => [el('dt', null, k), el('dd', null, v == null ? '–' : String(v))]));
    $('features').replaceChildren(...status.abilities.map((a) => {
      const card = el('div', 'feature');
      const title = el('b', null, a.name);
      const badge = el('em', a.state === 'asks first' ? 'asks' : a.state === 'on' ? '' : 'off', a.state);
      title.append(badge);
      card.append(title, el('p', null, a.detail));
      return card;
    }));
  }

  async function activity() {
    const { items } = await api('GET', '/api/runs?limit=200');
    const now = Date.now(), hours = Array.from({ length: 24 }, () => ({ all: 0, bad: 0 }));
    let total = 0, failed = 0, last = null;
    for (const run of items) {
      const age = (now - new Date(run.created_at).getTime()) / 3600000;
      if (age < 24) {
        const bucket = hours[23 - Math.floor(age)];
        bucket.all++; total++;
        if (['failed', 'refused'].includes(run.status)) { bucket.bad++; failed++; }
      }
      if (!last && ['completed', 'failed'].includes(run.status)) last = run;
    }
    $('a-runs').textContent = total;
    $('a-ok').textContent = total ? `${Math.round(100 * (total - failed) / total)}% worked` : '';
    draw(hours);
    if (last) {
      const r = last.result || {};
      const text = typeof r === 'string' ? r : r.result || r.summary || r.reply || last.goal;
      $('r-text').textContent = String(text).replace(/[#*`]/g, '').slice(0, 420);
      $('r-pill').textContent = `${last.status} · ${ago(last.updated_at || last.created_at)}`;
      $('r-pill').className = 'pill ' + (last.status === 'completed' ? 'ok' : 'bad');
    }
  }

  function draw(hours) {
    const canvas = $('a-chart'), dpr = Math.min(devicePixelRatio || 1, 2);
    const w = canvas.clientWidth, h = 90;
    canvas.width = w * dpr; canvas.height = h * dpr;
    const ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr);
    const max = Math.max(1, ...hours.map((b) => b.all)), bw = w / 24;
    hours.forEach((b, i) => {
      const bh = (b.all / max) * (h - 8), fh = (b.bad / max) * (h - 8);
      ctx.fillStyle = 'rgba(255,46,136,0.75)'; ctx.fillRect(i * bw + 1, h - bh, bw - 2, bh);
      ctx.fillStyle = 'rgba(251,113,133,1)'; ctx.fillRect(i * bw + 1, h - fh, bw - 2, fh);
    });
    ctx.fillStyle = 'rgba(255,255,255,0.08)'; ctx.fillRect(0, h - 1, w, 1);
  }

  async function mac() {
    try {
      const out = await api('POST', '/api/tools/mac.status/execute', { inputs: {} });
      const m = out.output || {};
      $('m-kv').replaceChildren(...[['Battery', (m.battery || '').split(';')[0]], ['Free disk', `${m.disk_free} of ${m.disk_total}`],
        ['Wi-Fi', m.wifi_ip], ['Open apps', (m.open_apps || []).length]].flatMap(([k, v]) => [el('dt', null, k), el('dd', null, String(v))]));
    } catch (e) { $('m-kv').replaceChildren(el('dt', null, 'Unavailable'), el('dd', null, '')); }
  }

  async function upcoming() {
    const data = await api('GET', '/api/reminders');
    const items = (data.items || data).filter((r) => r.status === 'active' && r.next_at).sort((a, b) => a.next_at.localeCompare(b.next_at)).slice(0, 5);
    if (!items.length) return;
    $('n-list').replaceChildren(...items.map((r) => {
      const li = el('li'); li.append(el('span', null, r.text.split(':')[0].slice(0, 60)), el('span', null, until(r.next_at))); return li;
    }));
  }

  async function needsYou() {
    const [approvals, review] = await Promise.all([api('GET', '/api/approvals?status=pending'), api('GET', '/api/self-review').catch(() => ({ proposals: [] }))]);
    const rows = approvals.items.map((a) => [a.summary, 'approve on System']);
    (review.proposals || []).forEach((p) => rows.push([`Self-review proposal ${p.branch.replace('jarvis/self-review-', '')}`, 'review on System']));
    if (!rows.length) return;
    $('d-list').replaceChildren(...rows.slice(0, 5).map(([a, b]) => { const li = el('li'); const link = el('a', null, a); link.href = '/#system'; li.append(link, el('span', null, b)); return li; }));
  }

  // --- state gallery: live renders of the real face in each state ---------------------------
  const GALLERY = [['calm', 'Standing by'], ['listening', 'Hearing you'], ['analysing', 'Thinking it through'], ['planning', 'Forming a plan'],
    ['executing', 'Doing the work'], ['approval', 'Needs your decision'], ['success', 'Done and checked'], ['warm', 'Good news'],
    ['curious', 'Asking back'], ['sad', 'Bad news, gently'], ['angry', 'Firm, serious'], ['failure', 'Failed, says so']];
  const gallery = $('gallery');
  GALLERY.forEach(([name, meaning], i) => {
    const card = el('button', 'state-card'); card.type = 'button';
    const thumb = el('div', 'face');
    const text = el('div'); text.append(el('b', null, (JarvisIdentity.STATES[name] || {}).label ? JarvisIdentity.STATES[name].label.charAt(0) + JarvisIdentity.STATES[name].label.slice(1).toLowerCase() : name), el('span', null, meaning));
    card.append(thumb, text); gallery.append(card);
    setTimeout(() => { const mini = JarvisIdentity.create(thumb, { compact: true }); mini.setState(name); }, 200 + i * 120);   // staggered
    card.addEventListener('click', () => {                 // preview on the main face for a few seconds
      gallery.querySelectorAll('.state-card').forEach((c) => c.classList.toggle('on', c === card));
      previewUntil = Date.now() + 4000; face.setState(name, `Preview: ${meaning.toLowerCase()}`);
      setTimeout(() => card.classList.remove('on'), 4000);
    });
  });

  // --- talk to JARVIS (same conversation as the main page) --------------------------------------
  $('command').addEventListener('submit', async (event) => {
    event.preventDefault();
    const input = $('cmd'), text = input.value.trim();
    if (!text) return;
    input.value = ''; $('reply').textContent = '…';
    let convo = null;
    try { const saved = JSON.parse(localStorage.getItem('jarvis.conversation') || 'null'); if (saved && Date.now() - saved.at < 3 * 3600 * 1000) convo = saved.id; } catch (e) { /* ignore */ }
    try {
      const result = await api('POST', '/api/chat', { message: text, conversation_id: convo });
      try { localStorage.setItem('jarvis.conversation', JSON.stringify({ id: result.conversation.id, at: Date.now() })); } catch (e) { /* ignore */ }
      $('reply').textContent = result.reply.content;
      activity();
    } catch (error) { $('reply').textContent = error.message; }
  });

  const refresh = () => Promise.allSettled([vitals(), activity(), upcoming(), needsYou()]);
  refresh(); mac(); setInterval(refresh, 30000); setInterval(mac, 120000);
})();
