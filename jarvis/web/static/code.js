/* Agent mode, the terminal and website preview. Plain DOM; every piece of text goes in as text, never HTML.
   app.js registers these as the Code, Terminal and Preview pages. */
(() => {
  'use strict';
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const btn = (text, cls, onclick) => { const b = el('button', 'btn ' + (cls || ''), text); b.type = 'button'; if (onclick) b.addEventListener('click', onclick); return b; };
  const api = async (method, path, body) => {
    const r = await fetch(path, { method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
    const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(d.error || `${path} failed (${r.status})`); return d;
  };
  const LIVE = ['running', 'waiting_approval'];
  const STATUS = { running: 'Working', waiting_approval: 'Needs your approval', waiting_owner: 'Waiting for your answer',
    completed: 'Done', failed: 'Stopped: failed', stopped: 'Stopped' };
  const short = (p) => String(p || '').replace(/^\/Users\/[^/]+/, '~');
  const openApp = (app) => { try { window.parent.postMessage({ jarvis: 'open', app }, location.origin); } catch (e) { /* not in the OS */ } if (window.parent === window) location.hash = app; };
  const showPreview = (url) => { try { localStorage.setItem('jarvis.preview.url', url); } catch (e) { /* ignore */ } openApp('preview'); };

  function diffView(text) {
    const pre = el('pre', 'cd-diff');
    String(text || '').split('\n').forEach((line) => {
      const cls = line.startsWith('+++') || line.startsWith('---') ? 'meta' : line.startsWith('@@') ? 'hunk' : line.startsWith('+') ? 'add' : line.startsWith('-') ? 'del' : '';
      pre.append(el('span', cls, line + '\n'));
    });
    return pre;
  }

  const VERB = {
    list: (i) => ['List', i.path || '.'], read: (i) => ['Read', i.path], glob: (i) => ['Find', i.pattern],
    search: (i) => ['Search', i.pattern], write: (i) => ['Write', i.path], edit: (i) => ['Edit', i.path],
    look: (i) => ['Run', i.command], run: (i) => ['Run', i.command], web_search: (i) => ['Web search', i.query],
    web_read: (i) => ['Read page', i.url], preview: (i) => ['Preview', i.path], subagent: (i) => ['Sub-agent', i.task],
  };

  // --- Code: agent mode ----------------------------------------------------------------------
  async function agent(root) {
    const wrap = el('div', 'cd'), side = el('aside', 'cd-side glass'), main = el('div', 'cd-main glass');
    wrap.append(side, main); root.append(wrap);
    let current = null, timer = null, shown = 0, lastAction = null;

    const newBtn = btn('New task', 'primary sm', () => { current = null; renderNew(); renderList(); });
    const list = el('div', 'cd-list');
    side.append(el('div', 'cd-side-head'), list);
    side.firstChild.append(el('b', null, 'Sessions'), newBtn);

    async function renderList() {
      try {
        const d = await api('GET', '/api/agent');
        list.replaceChildren(...(d.items.length ? d.items.map((s) => {
          const b = el('button', 'cd-item' + (current && current.id === s.id ? ' on' : '')); b.type = 'button';
          b.append(el('span', 'cd-item-title', s.title), el('small', 'cd-st ' + s.status, STATUS[s.status] || s.status));
          b.addEventListener('click', () => openSession(s.id)); return b;
        }) : [el('div', 'muted small', 'No sessions yet.')]));
        return d;
      } catch (e) { list.replaceChildren(el('div', 'muted small', e.message)); return null; }
    }

    function renderNew() {
      clearInterval(timer);
      const form = el('form', 'cd-new');
      const task = el('textarea', 'cd-task'); task.rows = 5; task.required = true;
      task.placeholder = 'What should JARVIS do? For example: build a one-page website for Aureus Detailing with prices and a booking button.';
      task.setAttribute('aria-label', 'Task');
      const folder = el('input'); folder.placeholder = "Folder (blank = JARVIS's workspace), e.g. ~/Documents/Monsoor Motors";
      folder.setAttribute('aria-label', 'Folder'); folder.setAttribute('list', 'cd-folders');
      const options = el('datalist'); options.id = 'cd-folders';
      const go = el('button', 'btn primary', 'Start'); go.type = 'submit';
      const note = el('p', 'muted small', "In the workspace JARVIS writes files freely. In your own folders every edit and every command waits for your Approve.");
      const row = el('div', 'row'); row.append(folder, go);
      form.append(el('h3', null, 'New task'), task, row, options, note);
      api('GET', '/api/folders?path=' + encodeURIComponent('~')).then((d) => {
        options.replaceChildren(...d.folders.map((f) => { const o = el('option'); o.value = `~/${f}`; return o; }));
      }).catch(() => {});
      form.addEventListener('submit', async (e) => {
        e.preventDefault(); go.disabled = true;
        try { const s = await api('POST', '/api/agent', { task: task.value, folder: folder.value.trim() || null }); await openSession(s.id); }
        catch (err) { note.textContent = err.message; note.className = 'cd-bad small'; go.disabled = false; }
      });
      main.replaceChildren(form); task.focus();
    }

    async function openSession(id) {
      clearInterval(timer); shown = 0; lastAction = null;
      const s = await api('GET', `/api/agent/${id}`);
      current = s;
      const head = el('div', 'cd-head'), log = el('div', 'cd-log'), todos = el('div', 'cd-todos'), composer = el('form', 'cd-compose');
      const title = el('div', 'cd-title'); title.append(el('b', null, s.title), el('small', 'muted', short(s.folder)));
      const state = el('span', 'cd-st'), stop = btn('Stop', 'sm', async () => { await api('POST', `/api/agent/${id}/stop`); tick(); });
      head.append(title, state, stop);
      const input = el('textarea'); input.rows = 2; input.placeholder = 'Tell JARVIS more, or answer its question'; input.setAttribute('aria-label', 'Message');
      const send = el('button', 'btn primary', 'Send'); send.type = 'submit';
      composer.append(input, send);
      composer.addEventListener('submit', async (e) => {
        e.preventDefault(); if (!input.value.trim()) return;
        send.disabled = true;
        try { await api('POST', `/api/agent/${id}/message`, { text: input.value }); input.value = ''; await tick(); }
        catch (err) { log.append(el('div', 'cd-bad small', err.message)); } finally { send.disabled = false; }
      });
      input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) composer.requestSubmit(); });
      main.replaceChildren(head, todos, log, composer);
      renderList();

      const step = (st, all) => {
        const box = el('div', 'cd-step ' + st.kind);
        if (st.kind === 'user') { box.append(el('div', 'cd-who', 'You'), el('div', null, st.text)); return box; }
        if (st.kind === 'action') {
          if (st.action === 'todo' || st.action === 'done' || st.action === 'ask') return null;
          const [verb, what] = (VERB[st.action] || (() => [st.action, '']))(st.input || {});
          if (st.thought) box.append(el('div', 'cd-thought', st.thought));
          const line = el('div', 'cd-call'); line.append(el('span', 'cd-verb', verb), el('code', null, String(what || '').slice(0, 300)));
          box.append(line); lastAction = box; return box;
        }
        if (st.kind === 'result') {
          const host = lastAction || box;
          const d = el('details', 'cd-out' + (st.ok ? '' : ' bad'));
          const first = String(st.text || '').split('\n')[0].slice(0, 160);
          d.append(el('summary', null, st.ok ? first : 'Failed: ' + first));
          if (st.diff) { d.open = true; d.append(diffView(st.diff)); }
          else d.append(el('pre', null, st.text));
          if (st.url) { const a = btn('Open in Preview', 'sm', () => showPreview(st.url)); host.append(a); }
          if (!st.ok) host.classList.add('failed');
          host.append(d); return host === box ? box : null;
        }
        if (st.kind === 'approval') {
          box.append(el('div', 'cd-who', 'Needs your approval'), el('div', null, st.text));
          if (st.command) box.append(el('pre', 'cd-cmd', st.command));
          if (st.diff) box.append(diffView(st.diff));
          const waiting = all.status === 'waiting_approval' && all.steps.filter((x) => x.kind === 'approval').pop() === st;
          if (waiting) {
            const row = el('div', 'row');
            const decide = (verb) => async () => { row.querySelectorAll('button').forEach((b) => { b.disabled = true; });
              try { await api('POST', `/api/approvals/${st.approval_id}/${verb}`); row.replaceChildren(el('span', 'muted small', verb === 'approve' ? 'Approved' : 'Denied')); setTimeout(tick, 400); }
              catch (e) { row.append(el('span', 'cd-bad small', e.message)); } };
            row.append(btn('Approve', 'primary sm', decide('approve')), btn('Deny', 'sm', decide('deny')));
            box.append(row);
          } else box.append(el('div', 'muted small', 'Decided'));
          return box;
        }
        if (st.kind === 'question') { box.append(el('div', 'cd-who', 'JARVIS asks'), el('div', null, st.text)); return box; }
        if (st.kind === 'done') { box.append(el('div', 'cd-who', 'Done'), window.JarvisUI ? JarvisUI.richText(st.text) : el('div', null, st.text)); return box; }
        if (st.kind === 'error') { box.append(el('div', 'cd-who', 'Stopped'), el('div', null, st.text)); return box; }
        box.append(el('div', 'muted small', st.text)); return box;
      };

      async function tick() {
        let d;
        try { d = await api('GET', `/api/agent/${id}`); } catch (e) { return; }
        if (!current || current.id !== id) return;
        current = d;
        state.textContent = STATUS[d.status] || d.status; state.className = 'cd-st ' + d.status;
        stop.hidden = !LIVE.includes(d.status) && d.status !== 'waiting_owner';
        todos.replaceChildren(...(d.todos || []).map((t) => el('span', 'cd-todo ' + t.status, (t.status === 'completed' ? '✓ ' : t.status === 'in_progress' ? '▸ ' : '○ ') + t.content)));
        todos.hidden = !(d.todos || []).length;
        const near = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
        // approval cards change when decided: re-render from the last approval onwards
        const lastAppr = d.steps.map((x) => x.kind).lastIndexOf('approval');
        if (lastAppr >= 0 && lastAppr < shown) {
          while (log.childElementCount && log.lastChild.dataset.index >= lastAppr) log.lastChild.remove();
          shown = lastAppr; lastAction = null;
        }
        for (; shown < d.steps.length; shown++) {
          const node = step(d.steps[shown], d);
          if (node) { node.dataset.index = shown; log.append(node); }
        }
        if (LIVE.includes(d.status)) {
          if (!log.querySelector('.cd-working')) log.append(el('div', 'cd-working muted small', 'Working…'));
          else log.append(log.querySelector('.cd-working'));
        } else log.querySelector('.cd-working')?.remove();
        if (near) log.scrollTop = log.scrollHeight;
        input.placeholder = d.status === 'waiting_owner' ? 'Answer JARVIS' : 'Tell JARVIS more, or ask for a change';
        if (!LIVE.includes(d.status)) { clearInterval(timer); renderList(); }
      }
      await tick();
      log.scrollTop = log.scrollHeight;
      timer = setInterval(tick, 1200);
    }

    const d = await renderList();
    if (d && d.items.length && LIVE.includes(d.items[0].status)) openSession(d.items[0].id); else renderNew();
    return () => clearInterval(timer);
  }

  // --- Terminal ----------------------------------------------------------------------------
  async function terminal(root) {
    const box = el('div', 'tm glass'), out = el('pre', 'tm-out'), line = el('form', 'tm-line');
    const prompt = el('span', 'tm-prompt'), input = el('input', 'tm-input');
    input.setAttribute('aria-label', 'Command'); input.autocomplete = 'off'; input.spellcheck = false;
    const stop = btn('Stop (Ctrl+C)', 'sm', () => job && api('POST', `/api/terminal/${job}/stop`));
    stop.hidden = true;
    line.append(prompt, input, stop); box.append(out, line); root.append(box);
    const note = el('p', 'muted small', 'Your own terminal, in a login shell. Each command is written to the audit log. JARVIS never types here; its own commands ask for your Approve.');
    root.append(note);
    let cwd = '', job = null, length = 0, poll = null;
    const history = (() => { try { return JSON.parse(localStorage.getItem('jarvis.terminal.history') || '[]'); } catch (e) { return []; } })();
    let hpos = history.length;
    const write = (text, cls) => { const s = el('span', cls, text); out.append(s); out.scrollTop = out.scrollHeight; };
    const setPrompt = () => { prompt.textContent = `${short(cwd)} %`; };
    try { const s = await api('GET', '/api/terminal'); cwd = s.cwd; } catch (e) { write(e.message + '\n', 'tm-err'); }
    setPrompt(); write('JARVIS terminal. Type a command and press Enter. "clear" clears the screen.\n', 'tm-dim');

    const follow = async () => {
      try {
        const v = await api('GET', `/api/terminal/${job}?since=${length}`);
        if (v.output) write(v.output); length = v.length;
        if (v.status !== 'running') {
          clearInterval(poll); poll = null; job = null; stop.hidden = true; cwd = v.cwd; setPrompt();
          if (v.exit_code) write(`[exit ${v.exit_code}]\n`, 'tm-err');
          input.placeholder = '';
        }
      } catch (e) { clearInterval(poll); poll = null; job = null; stop.hidden = true; }
    };
    line.addEventListener('submit', async (e) => {
      e.preventDefault();
      const text = input.value; input.value = '';
      if (job) { write(text + '\n', 'tm-dim'); await api('POST', `/api/terminal/${job}/input`, { text }).catch(() => {}); return; }
      if (!text.trim()) return;
      if (text.trim() === 'clear') { out.replaceChildren(); return; }
      history.push(text); hpos = history.length;
      try { localStorage.setItem('jarvis.terminal.history', JSON.stringify(history.slice(-200))); } catch (er) { /* ignore */ }
      write(`${short(cwd)} % ${text}\n`, 'tm-cmd');
      try {
        const v = await api('POST', '/api/terminal', { command: text });
        job = v.id; length = 0; stop.hidden = false; input.placeholder = 'Running… type here to send input';
        poll = setInterval(follow, 300); follow();
      } catch (er) { write(er.message + '\n', 'tm-err'); }
    });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowUp' && hpos > 0) { e.preventDefault(); input.value = history[--hpos] || ''; }
      if (e.key === 'ArrowDown') { e.preventDefault(); hpos = Math.min(history.length, hpos + 1); input.value = history[hpos] || ''; }
      if (e.key === 'c' && e.ctrlKey && job) { e.preventDefault(); api('POST', `/api/terminal/${job}/stop`); }
      if (e.key === 'l' && e.ctrlKey) { e.preventDefault(); out.replaceChildren(); }
    });
    box.addEventListener('click', () => { if (!window.getSelection().toString()) input.focus(); });
    input.focus();
    return () => clearInterval(poll);
  }

  // --- Preview -------------------------------------------------------------------------------
  async function preview(root) {
    const bar = el('div', 'pv-bar glass'), frameBox = el('div', 'pv-frame glass');
    const url = el('input', 'grow'); url.setAttribute('aria-label', 'Address'); url.readOnly = true;
    const sites = el('select'); sites.setAttribute('aria-label', 'Sites in the workspace');
    const reload = btn('Reload', 'sm'), open = el('a', 'btn sm', 'Open in browser');
    open.target = '_blank'; open.rel = 'noopener noreferrer';
    bar.append(sites, url, reload, open);
    const frame = el('iframe'); frame.title = 'Website preview';
    frame.setAttribute('sandbox', 'allow-scripts allow-forms allow-same-origin allow-popups');
    const empty = el('div', 'pv-empty muted', 'No site yet. Ask JARVIS to build one, for example: "build me a website for Aureus Detailing".');
    frameBox.append(empty, frame); root.append(bar, frameBox);
    const go = (u) => { if (!u) return; url.value = u; open.href = u; frame.src = u; empty.hidden = true; frame.hidden = false; };
    frame.hidden = true;
    reload.addEventListener('click', () => { if (url.value) frame.src = url.value; });
    sites.addEventListener('change', async () => { if (!sites.value) return; try { go((await api('POST', '/api/preview', { path: sites.value })).url); } catch (e) { empty.textContent = e.message; } });
    try {
      const d = await api('GET', '/api/preview');
      const pick = el('option', null, d.sites.length ? 'Choose a site…' : 'No sites in the workspace'); pick.value = '';
      sites.replaceChildren(pick, ...d.sites.map((s) => { const o = el('option', null, s); o.value = s; return o; }));
    } catch (e) { /* ignore */ }
    const fromStore = () => { try { const u = localStorage.getItem('jarvis.preview.url'); if (u && u !== url.value) go(u); } catch (e) { /* ignore */ } };
    fromStore();
    if (!url.value) {                                   // nothing chosen yet: the site JARVIS previewed last, or the first one
      try {
        const d = await api('GET', '/api/preview');
        if (d.last) go(d.last);
        else if (d.sites.length) { sites.value = d.sites[0]; sites.dispatchEvent(new Event('change')); }
      } catch (e) { /* ignore */ }
    }
    window.addEventListener('storage', fromStore);
    return () => window.removeEventListener('storage', fromStore);
  }

  window.JarvisCode = { agent, terminal, preview };
})();
