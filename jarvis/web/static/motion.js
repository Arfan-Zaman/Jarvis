/* JarvisMotion: the motion helpers every page uses. Composite-only (transform/opacity) or a single
   canvas; constant motion is CSS (runs on the compositor even when the page is busy); nothing runs
   when there is nothing to show. */
(() => {
  'use strict';
  const reduce = () => window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const NS = 'http://www.w3.org/2000/svg';
  const svg = (tag, attrs) => { const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); return n; };
  // how fast the reticle turns and whether the sweep shows, per state (state indication)
  const PACE = { calm: [1, 0], listening: [2, 0.6], analysing: [3.2, 1], planning: [2.4, 1], executing: [4, 1], speaking: [1.6, 0.4],
    approval: [0.6, 0], awaiting: [0.8, 0], success: [2, 0.8], failure: [0.4, 0], error: [0.4, 0], warning: [0.8, 0],
    concerned: [0.8, 0.3], resolute: [0.3, 0], offline: [0.2, 0], warm: [1.4, 0.3], curious: [1.8, 0.5], sad: [0.5, 0], angry: [2.6, 0.7] };

  function ring(r, count, majorEvery, len, cls) {
    const g = svg('g', { class: `ring ${cls}` });
    for (let i = 0; i < count; i++) {
      const a = (i / count) * Math.PI * 2, major = i % majorEvery === 0, l = major ? len * 1.8 : len;
      g.append(svg('line', { class: major ? 'tick major' : 'tick', 'vector-effect': 'non-scaling-stroke', x1: 50 + Math.cos(a) * r, y1: 50 + Math.sin(a) * r,
        x2: 50 + Math.cos(a) * (r - l), y2: 50 + Math.sin(a) * (r - l) }));
    }
    return g;
  }
  const arcPath = (r, from, to) => {
    const p = (t) => [50 + Math.cos(t) * r, 50 + Math.sin(t) * r];
    const [x1, y1] = p(from), [x2, y2] = p(to);
    return `M ${x1} ${y1} A ${r} ${r} 0 ${to - from > Math.PI ? 1 : 0} 1 ${x2} ${y2}`;
  };

  /** Reticle + voice line around a JarvisIdentity. Wraps setState/setLevel; returns { destroy }. */
  function attach(stage, identity) {
    const box = document.createElement('div'); box.className = 'reticle'; box.setAttribute('aria-hidden', 'true');
    const s = svg('svg', { viewBox: '0 0 100 100' });
    s.append(ring(49, 144, 12, 0.9, 'ring-a'), ring(46, 72, 6, 0.6, 'ring-b'));
    const arcs = svg('g', { class: 'ring ring-c' });
    [[0.15, 0.85], [1.4, 2.05], [2.7, 3.0], [3.5, 4.4], [5.0, 5.7]].forEach(([a, b]) => arcs.append(svg('path', { class: 'arc', 'vector-effect': 'non-scaling-stroke', d: arcPath(42, a, b) })));
    s.append(arcs, svg('circle', { class: 'sweep', 'vector-effect': 'non-scaling-stroke', cx: 50, cy: 50, r: 47.5, pathLength: 1000 }));
    box.append(s);
    const label = (cls) => { const n = document.createElement('div'); n.className = `reticle-label ${cls}`; box.append(n); return n; };
    const lState = label('tl'), lTime = label('tr'), lLevel = label('bl'), lMode = label('br');
    stage.append(box);

    const wave = document.createElement('canvas'); wave.className = 'voice-wave'; wave.setAttribute('aria-hidden', 'true');
    stage.after(wave);
    const history = new Float32Array(96); let level = 0, lastActive = 0, raf = 0, since = performance.now();

    const draw = () => {
      raf = 0;
      const dpr = Math.min(devicePixelRatio || 1, 2), w = wave.clientWidth, h = 38;
      if (!w) return;
      if (wave.width !== w * dpr) { wave.width = w * dpr; wave.height = h * dpr; }
      const ctx = wave.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
      history.copyWithin(0, 1); history[history.length - 1] = level;
      const accent = getComputedStyle(stage).getPropertyValue('--jv-accent-rgb').trim() || '255,46,136';
      const bw = w / history.length;
      for (let i = 0; i < history.length; i++) {
        const v = Math.max(0.04, history[i]), bh = v * (h - 4), x = i * bw;
        ctx.fillStyle = `rgba(${accent},${0.25 + 0.75 * (i / history.length)})`;
        ctx.fillRect(x + bw * 0.2, (h - bh) / 2, Math.max(1, bw * 0.6), bh);
      }
      if (performance.now() - lastActive < 1500) raf = requestAnimationFrame(draw);   // idle: stop drawing
    };
    const kick = () => { if (!raf && !reduce()) raf = requestAnimationFrame(draw); };

    const setState = identity.setState.bind(identity), setLevel = identity.setLevel.bind(identity);
    identity.setState = (name, line) => {
      setState(name, line);
      const [speed, sweep] = PACE[name] || [1, 0];
      box.style.setProperty('--r-speed', String(speed)); box.style.setProperty('--r-sweep', String(sweep));
      const spec = (JarvisIdentity.STATES[name] || {});
      lState.replaceChildren('STATE ', Object.assign(document.createElement('b'), { textContent: (spec.label || name).toUpperCase() }));
      since = performance.now();
    };
    identity.setLevel = (v) => { setLevel(v); level = Math.max(0, Math.min(1, v || 0)); if (level > 0.01) { lastActive = performance.now(); kick(); } };
    const clock = setInterval(() => {
      const t = Math.round((performance.now() - since) / 1000);
      lTime.textContent = `T+${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`;
      lLevel.textContent = `SIGNAL ${(level * 100).toFixed(0).padStart(3, '0')}`;
    }, 1000);
    lMode.textContent = 'LOCAL · SANDBOXED';
    lastActive = performance.now(); kick();
    identity.setState(identity.state || 'calm');      // fill the labels for the current state
    return { destroy() { clearInterval(clock); cancelAnimationFrame(raf); box.remove(); wave.remove(); } };
  }

  /** Count a number up from its current value (data that changed reads as changed). */
  function countTo(el, to, suffix = '') {
    const from = Number(String(el.dataset.value ?? '').replace(/[^\d.-]/g, '')) || 0;
    el.dataset.value = String(to);
    if (reduce() || from === to || !Number.isFinite(to)) { el.textContent = `${to}${suffix}`; return; }
    const start = performance.now(), dur = 420;
    const step = (now) => {
      const p = Math.min(1, (now - start) / dur), e = 1 - Math.pow(1 - p, 3);    // ease-out
      el.textContent = `${Math.round(from + (to - from) * e)}${suffix}`;
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  function flash(el) { if (!el || reduce()) return; el.classList.remove('data-flash'); void el.offsetWidth; el.classList.add('data-flash'); }

  /** The one choreographed entrance: stagger the page's panels, once per browser session. */
  function enter(root, groups) {
    let seen = false; try { seen = sessionStorage.getItem('jarvis.entered') === '1'; sessionStorage.setItem('jarvis.entered', '1'); } catch (e) { /* ignore */ }
    if (seen) return;
    let i = 0; groups.forEach((g) => [...g].forEach((n) => n.style.setProperty('--i', String(i++))));
    root.classList.add('deck-enter');
    setTimeout(() => root.classList.remove('deck-enter'), 1600);
  }

  /** Run fn when el first scrolls into view (and pause the work off-screen elsewhere). */
  function whenVisible(el, fn) {
    if (!('IntersectionObserver' in window)) { fn(); return () => {}; }
    const io = new IntersectionObserver((entries) => { if (entries.some((e) => e.isIntersecting)) { io.disconnect(); fn(); } }, { rootMargin: '120px' });
    io.observe(el); return () => io.disconnect();
  }

  window.JarvisMotion = { attach, countTo, flash, enter, whenVisible, reduce };
})();
