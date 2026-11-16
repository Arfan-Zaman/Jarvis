/* Interface helpers: rich (but safe) reply text, copy buttons, an interactive activity log.
   Everything is built with DOM nodes and textContent; nothing from a reply is ever parsed as HTML. */
(() => {
  'use strict';
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };

  async function copy(text, button) {
    try { await navigator.clipboard.writeText(text); } catch (e) {
      const t = el('textarea'); t.value = text; document.body.append(t); t.select(); document.execCommand('copy'); t.remove();
    }
    if (button) { const old = button.textContent; button.textContent = 'Copied'; setTimeout(() => { button.textContent = old; }, 1200); }
  }

  // inline: **bold**, `code`, [text](https://…) and bare https:// links
  function inline(text) {
    const frag = document.createDocumentFragment();
    const re = /(\*\*[^*]+\*\*)|(`[^`]+`)|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s)<]+[^\s).,;:!?<])/g;
    let at = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > at) frag.append(text.slice(at, m.index));
      if (m[1]) frag.append(el('strong', null, m[1].slice(2, -2)));
      else if (m[2]) frag.append(el('code', 'rt-code', m[2].slice(1, -1)));
      else {
        const href = m[4] || m[5], a = el('a', 'rt-link', m[3] || href);
        a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer'; frag.append(a);
      }
      at = m.index + m[0].length;
    }
    if (at < text.length) frag.append(text.slice(at));
    return frag;
  }

  /** Reply text with paragraphs, headings, lists, code blocks (with copy) and links. */
  function richText(source) {
    const root = el('div', 'rich');
    const lines = String(source || '').replace(/\r/g, '').split('\n');
    let list = null, para = [];
    const flushPara = () => { if (para.length) { const p = el('p'); p.append(inline(para.join(' '))); root.append(p); para = []; } };
    const flushList = () => { list = null; };
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const fence = line.match(/^```(\w*)/);
      if (fence) {
        flushPara(); flushList();
        const body = []; i++;
        while (i < lines.length && !/^```/.test(lines[i])) body.push(lines[i++]);
        const code = body.join('\n'), block = el('div', 'rt-block'), bar = el('div', 'rt-bar');
        const btn = el('button', 'rt-copy', 'Copy'); btn.type = 'button'; btn.addEventListener('click', () => copy(code, btn));
        bar.append(el('span', null, fence[1] || 'code'), btn);
        const pre = el('pre'); pre.append(el('code', null, code));
        block.append(bar, pre); root.append(block); continue;
      }
      const head = line.match(/^(#{1,4})\s+(.*)/);
      if (head) { flushPara(); flushList(); const hd = el('h4', 'rt-h'); hd.append(inline(head[2])); root.append(hd); continue; }
      const item = line.match(/^\s*([-*•]|\d+[.)])\s+(.*)/);
      if (item) {
        flushPara();
        const ordered = /\d/.test(item[1]);
        if (!list || list.tagName !== (ordered ? 'OL' : 'UL')) { list = el(ordered ? 'ol' : 'ul', 'rt-list'); root.append(list); }
        const li = el('li'); li.append(inline(item[2])); list.append(li); continue;
      }
      if (!line.trim()) { flushPara(); flushList(); continue; }
      flushList(); para.push(line.trim());
    }
    flushPara();
    return root;
  }

  function copyButton(text) { const b = el('button', 'rt-copy msg-copy', 'Copy'); b.type = 'button'; b.addEventListener('click', () => copy(text, b)); return b; }

  /** The activity log with category filters and search. */
  function eventLog(events, when) {
    const wrap = el('div', 'evlog');
    if (!events.length) { wrap.append(el('div', 'empty', 'No activity recorded yet.')); return wrap; }
    const counts = {};
    events.forEach((e) => { counts[e.category] = (counts[e.category] || 0) + 1; });
    let active = null, query = '';
    const bar = el('div', 'evlog-bar'), chips = el('div', 'evlog-chips');
    const search = el('input', 'evlog-search'); search.placeholder = 'Search activity'; search.setAttribute('aria-label', 'Search activity');
    const mk = (name, n) => { const b = el('button', 'evlog-chip', n == null ? name : `${name} ${n}`); b.type = 'button'; b.dataset.cat = name; return b; };
    chips.append(mk('all', events.length), ...Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([c, n]) => mk(c, n)));
    bar.append(chips, search);
    const table = el('table'), head = el('tr');
    ['When', 'Category', 'Action', 'Message'].forEach((t) => head.append(el('th', null, t)));
    const body = el('tbody'); table.append(head, body);
    const shown = el('div', 'evlog-count');
    const render = () => {
      const q = query.toLowerCase();
      const rows = events.filter((e) => (!active || e.category === active) && (!q || `${e.action} ${e.message} ${e.actor}`.toLowerCase().includes(q)));
      body.replaceChildren(...rows.map((e) => {
        const tr = el('tr', e.level === 'error' ? 'bad' : e.level === 'warning' ? 'warn' : '');
        tr.append(el('td', 'muted small', when(e.created_at)), el('td', null, e.category), el('td', 'mono', e.action), el('td', 'wrap', e.message));
        return tr;
      }));
      shown.textContent = `${rows.length} of ${events.length}`;
      chips.querySelectorAll('.evlog-chip').forEach((c) => c.classList.toggle('on', (c.dataset.cat === 'all' && !active) || c.dataset.cat === active));
    };
    chips.addEventListener('click', (ev) => { const c = ev.target.closest('.evlog-chip'); if (!c) return; active = c.dataset.cat === 'all' ? null : c.dataset.cat; render(); });
    search.addEventListener('input', () => { query = search.value.trim(); render(); });
    const scroll = el('div', 'scroll-x'); scroll.append(table);
    wrap.append(bar, scroll, shown); render();
    return wrap;
  }

  /** Grow a textarea with its content, up to its CSS max-height. */
  function autoGrow(textarea) {
    const fit = () => { textarea.style.height = 'auto'; textarea.style.height = `${textarea.scrollHeight}px`; };
    textarea.addEventListener('input', fit); return fit;
  }

  window.JarvisUI = { richText, copyButton, copy, eventLog, autoGrow };
})();
