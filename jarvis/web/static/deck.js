/* The JARVIS page's side panels and lower sections (from the concept), live data only.
   JarvisDeck.build({ preview }) returns { left, right, states, abilities, stop }. The face itself,
   voice, files and approvals stay in app.js; this module never sets the face's state except for an
   owner-requested preview from the state gallery. */
(() => {
  'use strict';
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const api = async (path) => {
    const response = await fetch(path);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `${path} failed`);
    return data;
  };
  const ago = (iso) => {
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    return s < 90 ? 'just now' : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 129600 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`;
  };
  const when = (iso) => new Date(iso).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' });
  const card = (title, cls) => { const c = el('section', 'dk-card' + (cls ? ' ' + cls : '')); const h = el('h2', null, title); c.append(h); return [c, h]; };
  const kvRows = (dl, rows) => dl.replaceChildren(...rows.flatMap(([k, v]) => [el('dt', null, k), el('dd', null, v == null || v === '' ? '—' : String(v))]));
  const BACKGROUND = /^Tool call: (mac\.status|memory\.search|claude\.converse|web\.(search|fetch))/;
  const GALLERY = [['calm', 'Standing by'], ['listening', 'Hearing you'], ['analysing', 'Thinking it through'], ['planning', 'Forming a plan'],
    ['executing', 'Doing the work'], ['approval', 'Needs your decision'], ['success', 'Done and checked'], ['warm', 'Good news'],
    ['curious', 'Asking back'], ['sad', 'Bad news, gently'], ['angry', 'Firm, serious'], ['failure', 'Failed, says so']];

  function build(options = {}) {
    const timers = [], minis = [];
    // --- left: system, activity, this Mac
    const [sys] = card('System');
    const big = el('div', 'dk-big'), asks = el('div', 'dk-hint'), sysKv = el('dl', 'dk-kv');
    sys.append(big, asks, sysKv);
    const [act, actH] = card('Activity');
    actH.append(el('span', 'dk-hint', 'last 24 hours'));
    const actBig = el('div', 'dk-big'), actSub = el('div', 'dk-hint'), chart = el('canvas', 'dk-chart');
    chart.height = 80; chart.setAttribute('aria-label', 'Actions per hour, last 24 hours');
    const legend = el('div', 'dk-legend'); legend.append(el('i', 'dot pink'), 'actions', el('i', 'dot red'), 'failed');
    act.append(actBig, actSub, chart, legend);
    const [mac] = card('This Mac'); const macKv = el('dl', 'dk-kv'); mac.append(macKv);
    const left = el('aside', 'dk-left'); left.append(sys, act, mac);

    // --- right: current task, last result, coming up, needs you
    const [task, taskH] = card('Current task', 'bracket'); const taskPill = el('span', 'dk-pill', 'idle'); taskH.append(taskPill);
    const steps = el('ol', 'dk-steps'); task.append(steps);
    const [res, resH] = card('Last result', 'bracket'); const resPill = el('span', 'dk-pill'); resH.append(resPill);
    const resText = el('p', 'dk-result'), resWhen = el('p', 'dk-when'), resLink = el('a', 'dk-btn', 'All results'); resLink.href = '#goals';
    res.append(resText, resWhen, resLink);
    const [next] = card('Coming up'); const nextList = el('ul', 'dk-list'); next.append(nextList);
    const [need] = card('Needs you'); const needList = el('ul', 'dk-list'); need.append(needList);
    const right = el('aside', 'dk-right'); right.append(task, res, next, need);

    // --- states gallery and abilities
    const states = el('section', 'dk-section dk-states-section');
    const sh = el('div', 'dk-section-head'); sh.append(el('h2', null, 'States'), el('span', 'dk-hint', 'Motion only with a cause. Live renders of the real face.'));
    const grid = el('div', 'dk-states'); states.append(sh, grid);
    GALLERY.forEach(([name, meaning], i) => {
      const b = el('button', 'dk-state'); b.type = 'button';
      const thumb = el('div', 'dk-face'), text = el('div');
      const spec = (window.JarvisIdentity && JarvisIdentity.STATES[name]) || {};
      text.append(el('b', null, spec.label ? spec.label.charAt(0) + spec.label.slice(1).toLowerCase() : name), el('span', null, meaning));
      b.append(thumb, text); grid.append(b);
      timers.push(setTimeout(() => { const mini = JarvisIdentity.create(thumb, { compact: true }); mini.setState(name); minis.push(mini); }, 300 + i * 120));
      b.addEventListener('click', () => {
        grid.querySelectorAll('.dk-state').forEach((c) => c.classList.toggle('on', c === b));
        if (options.preview) options.preview(name, meaning);
        setTimeout(() => b.classList.remove('on'), 4000);
      });
    });
    const abilities = el('section', 'dk-section dk-abilities-section');
    const ah = el('div', 'dk-section-head'); ah.append(el('h2', null, 'Abilities'), el('span', 'dk-hint', 'Worked out live from what JARVIS can do right now.'));
    const agrid = el('div', 'dk-abilities'); abilities.append(ah, agrid);

    // --- data
    async function vitals() {
      const status = await api('/api/status');
      const ask = status.abilities.filter((a) => a.state === 'asks first').length;
      const on = status.abilities.filter((a) => a.state === 'on').length + ask;
      big.replaceChildren(String(on), el('small', null, ` of ${status.abilities.length} abilities available`));
      asks.textContent = ask ? `${ask} of them ask you first` : '';
      const c = status.counts || {};
      kvRows(sysKv, [['Model', status.ai.available ? status.ai.model : 'offline'], ['Memories', c.memories], ['Open tasks', c.tasks_open], ['Projects', c.projects], ['Tools', c.tools]]);
      agrid.replaceChildren(...status.abilities.map((a) => {
        const f = el('div', 'dk-ability'), t = el('b', null, a.name);
        t.append(el('em', a.state === 'asks first' ? 'asks' : a.state === 'on' ? '' : 'off', a.state));
        f.append(t, el('p', null, a.detail)); return f;
      }));
    }
    async function activity() {
      const { items } = await api('/api/runs?limit=200');
      const now = Date.now(), hours = Array.from({ length: 24 }, () => ({ all: 0, bad: 0 }));
      let total = 0, failed = 0, before = 0, last = null;
      for (const run of items) {
        const age = (now - new Date(run.created_at).getTime()) / 3600000;
        if (age < 24) { const b = hours[23 - Math.floor(age)]; b.all++; total++; if (['failed', 'refused'].includes(run.status)) { b.bad++; failed++; } }
        else if (age < 48) before++;
        if (!last && !BACKGROUND.test(run.goal || '') && ['completed', 'failed'].includes(run.status)) last = run;
      }
      actBig.replaceChildren(String(total), el('small', null, ' actions'));
      actSub.textContent = (total ? `${Math.round(100 * (total - failed) / total)}% worked · ` : '') + `${before} the day before`;
      draw(hours);
      if (last) {
        const r = last.result || {};
        const raw = typeof r === 'string' ? r : r.result || r.summary || r.reply || last.goal;
        const first = String(raw).replace(/[#*`>]/g, '').split(/(?<=[.!?])\s|\n/).map((x) => x.trim()).find((x) => x.length > 12) || last.goal;
        resText.textContent = first.length > 160 ? first.slice(0, 157) + '…' : first;
        resWhen.textContent = `${(last.goal || '').replace('Tool call: ', '')} · ${ago(last.updated_at || last.created_at)}`;
        resPill.textContent = last.status; resPill.className = 'dk-pill ' + (last.status === 'completed' ? 'ok' : 'bad');
      } else { resText.textContent = 'Nothing finished yet.'; }
    }
    function draw(hours) {
      const dpr = Math.min(devicePixelRatio || 1, 2), w = chart.clientWidth || 260, h = 80;
      chart.width = w * dpr; chart.height = h * dpr;
      const ctx = chart.getContext('2d'); ctx.scale(dpr, dpr);
      const max = Math.max(1, ...hours.map((b) => b.all)), bw = w / 24;
      hours.forEach((b, i) => {
        ctx.fillStyle = 'rgba(255,46,136,0.7)'; ctx.fillRect(i * bw + 1, h - (b.all / max) * (h - 6), bw - 2, (b.all / max) * (h - 6));
        ctx.fillStyle = '#fb7185'; ctx.fillRect(i * bw + 1, h - (b.bad / max) * (h - 6), bw - 2, (b.bad / max) * (h - 6));
      });
      ctx.fillStyle = 'rgba(255,255,255,0.08)'; ctx.fillRect(0, h - 1, w, 1);
    }
    async function macStatus() {
      try {
        const m = await api('/api/mac/status');
        kvRows(macKv, [['Battery', (m.battery || '').split(';')[0]], ['Free disk', `${m.disk_free} of ${m.disk_total}`], ['Wi-Fi', m.wifi_ip], ['Open apps', (m.open_apps || []).length]]);
      } catch (e) { kvRows(macKv, [['Status', 'unavailable']]); }
    }
    async function upcoming() {
      const data = await api('/api/reminders');
      const items = (data.items || data).filter((r) => r.status === 'active' && r.next_at).sort((a, b) => a.next_at.localeCompare(b.next_at)).slice(0, 5);
      nextList.replaceChildren(...(items.length ? items.map((r) => { const li = el('li'); li.append(el('span', null, r.text.split(':')[0].slice(0, 60)), el('span', null, when(r.next_at))); return li; })
        : [el('li', 'dk-muted', 'Nothing scheduled.')]));
    }
    async function needsYou() {
      const [approvals, review] = await Promise.all([api('/api/approvals?status=pending'), api('/api/self-review').catch(() => ({ proposals: [] }))]);
      const rows = approvals.items.map((a) => [a.summary, 'approve']);
      (review.proposals || []).forEach((p) => rows.push([`Self-review ${p.branch.replace('jarvis/self-review-', '')}`, 'review']));
      needList.replaceChildren(...(rows.length ? rows.slice(0, 5).map(([a, b]) => { const li = el('li'); const link = el('a', null, a); link.href = '#system'; li.append(link, el('span', null, b)); return li; })
        : [el('li', 'dk-muted', 'Nothing waiting.')]));
    }
    async function liveTask() {
      let data; try { data = await api('/api/live'); } catch (e) { return; }
      if (data.plan && data.plan.length) {
        steps.replaceChildren(...data.plan.map((p) => el('li', p.status === 'completed' ? 'done' : p.status, p.description + (p.status === 'completed' ? '  ✓' : ''))));
        taskPill.textContent = data.state; taskPill.className = 'dk-pill run';
      } else if (data.step) {
        steps.replaceChildren(el('li', 'running', data.step.description)); taskPill.textContent = 'working'; taskPill.className = 'dk-pill run';
      } else {
        steps.replaceChildren(el('li', 'dk-muted', 'No task running. Standing by.')); taskPill.textContent = 'idle'; taskPill.className = 'dk-pill';
      }
    }
    const refresh = () => Promise.allSettled([vitals(), activity(), upcoming(), needsYou()]);
    refresh(); macStatus(); liveTask();
    const intervals = [setInterval(refresh, 30000), setInterval(macStatus, 120000), setInterval(liveTask, 2000)];
    return {
      left, right, states, abilities, refresh,
      stop() { intervals.forEach(clearInterval); timers.forEach(clearTimeout); minis.forEach((m) => m.destroy()); },
    };
  }

  window.JarvisDeck = { build };
})();
