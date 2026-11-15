'use strict';

/* JARVIS visual identity: face, sensor eyes and intelligence core.
 *
 * One reusable component used by the Presence page and the desktop panel.
 *   const jarvis = JarvisIdentity.create(element, { compact: false });
 *   jarvis.setState('executing', 'Searching the web…');
 *   jarvis.setLevel(0.6);   // voice level while speaking (0..1)
 *
 * States carry meaning; animation only shows cognition. When nothing happens
 * JARVIS is almost still. Every state shown on the real pages comes from real
 * events (the server's /api/live, the microphone, audio playback). The only
 * exception is preview(), which is labelled as a simulation where it is used.
 *
 * Original design: an obsidian, faceted mask that emerges from darkness, with
 * slanted sensor apertures for eyes. No human face, no conventional robot head.
 */
(function () {
  const PINK = [255, 45, 140], VIOLET = [124, 77, 255], WHITE = [232, 234, 245], RED = [255, 59, 59], GREY = [120, 124, 140];
  const AMBER = [255, 138, 76], SKY = [92, 132, 255];

  // label, line (character language), core behaviour, eye and face geometry
  const STATES = {
    calm:      { label: 'CALM',        line: 'Standing by.',                              color: PINK,   mix: 0,   speed: 0.12, glow: 0.35, eye: 0.85, face: 0.55, brow: 0,  paths: 0, particles: 0 },
    listening: { label: 'LISTENING',   line: "I'm listening.",                            color: PINK,   mix: 0,   speed: 0.22, glow: 0.8,  eye: 1.0,  face: 0.8,  brow: 0,  paths: 0, particles: 0, focus: true },
    analysing: { label: 'ANALYSING',   line: "I'm analysing the available evidence.",     color: PINK,   mix: 0.55, speed: 0.9, glow: 0.7,  eye: 0.75, face: 0.75, brow: 2,  paths: 0, particles: 0, flicker: true },
    planning:  { label: 'PLANNING',    line: 'Forming a plan.',                           color: VIOLET, mix: 0.35, speed: 0.55, glow: 0.75, eye: 0.7, face: 0.8,  brow: 3,  paths: 4, particles: 0, grow: true },
    executing: { label: 'EXECUTING',   line: 'Executing.',                                color: PINK,   mix: 0.15, speed: 0.45, glow: 0.95, eye: 0.7, face: 0.85, brow: 3,  paths: 2, particles: 14 },
    concerned: { label: 'CONCERNED',   line: "A step failed. I'm isolating the cause.",   color: PINK,   mix: 0,   speed: 0.2,  glow: 1.0,  eye: 0.5,  face: 0.9,  brow: 7,  paths: 1, particles: 0 },
    resolute:  { label: 'RESOLUTE',    line: 'I have a solution. Proceeding.',            color: PINK,   mix: 0,   speed: 0.03, glow: 1.0,  eye: 0.38, face: 0.95, brow: 9,  paths: 1, particles: 4, still: true },
    approval:  { label: 'APPROVAL',    line: 'This step needs your decision.',            color: WHITE,  mix: 0.5, speed: 0.06, glow: 0.8,  eye: 0.6,  face: 0.85, brow: 4,  paths: 0, particles: 0, gate: true },
    awaiting:  { label: 'AWAITING YOU', line: 'One decision is needed before I proceed.', color: PINK,   mix: 0,   speed: 0.1,  glow: 0.7,  eye: 0.9,  face: 0.75, brow: 1,  paths: 0, particles: 0, focus: true },
    speaking:  { label: 'SPEAKING',    line: '',                                          color: PINK,   mix: 0,   speed: 0.18, glow: 0.85, eye: 0.85, face: 0.8,  brow: 0,  paths: 0, particles: 0, voice: true },
    success:   { label: 'COMPLETED',   line: 'Completed. The result has been verified.',  color: PINK,   mix: 0,   speed: 0.15, glow: 0.9,  eye: 0.85, face: 0.75, brow: 0,  paths: 0, particles: 0, burst: true },
    failure:   { label: 'FAILED',      line: 'I have not marked this as complete.',       color: RED,    mix: 0,   speed: 0.05, glow: 0.7,  eye: 0.45, face: 0.8,  brow: 6,  paths: 0, particles: 0, disrupt: true },
    warning:   { label: 'WARNING',     line: 'Attention required.',                       color: RED,    mix: 0.4, speed: 0.1,  glow: 0.8,  eye: 0.5,  face: 0.85, brow: 6,  paths: 0, particles: 0 },
    error:     { label: 'ERROR',       line: 'Something is not responding.',              color: RED,    mix: 0,   speed: 0.04, glow: 0.65, eye: 0.4,  face: 0.7,  brow: 5,  paths: 0, particles: 0, disrupt: true },
    // emotions while speaking, chosen per sentence from what JARVIS is saying
    warm:      { label: 'WARM',        line: '',                                          color: AMBER,  mix: 0,    speed: 0.3, glow: 1.0,  eye: 0.95, face: 0.8,  brow: 0,  paths: 0, particles: 0, voice: true, lively: true },
    curious:   { label: 'CURIOUS',     line: '',                                          color: VIOLET, mix: 0.45, speed: 0.4, glow: 0.85, eye: 1.0,  face: 0.8,  brow: 1,  paths: 0, particles: 0, voice: true, tilt: true },
    sad:       { label: 'SAD',         line: '',                                          color: SKY,    mix: 0.6,  speed: 0.06, glow: 0.45, eye: 0.55, face: 0.6, brow: 0,  paths: 0, particles: 0, voice: true, sag: true },
    angry:     { label: 'ANGRY',       line: '',                                          color: RED,    mix: 0.15, speed: 0.6, glow: 1.0,  eye: 0.35, face: 0.95, brow: 9,  paths: 0, particles: 0, voice: true, rage: true },
    offline:   { label: 'OFFLINE',     line: 'The intelligence is not connected.',        color: GREY,   mix: 0,   speed: 0.02, glow: 0.2,  eye: 0.25, face: 0.35, brow: 0,  paths: 0, particles: 0 },
  };

  const mixColor = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));
  const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
  const reducedMotion = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // --- the face (static SVG built once; geometry changes are CSS transforms) ---
  // Right-half geometry, mirrored for the left. viewBox 0 0 400 400, centre line x = 200.
  // No inline style attributes: the page's security policy forbids them, so shading
  // values travel in data-* attributes and are applied through the CSSOM.
  const FACETS = [
    [[200, 26], [262, 50], [250, 118], [200, 136]],               // forehead plate
    [[262, 50], [320, 96], [304, 148], [250, 118]],               // brow plate
    [[320, 96], [352, 160], [342, 222], [304, 148]],              // temple
    [[250, 118], [304, 148], [294, 198], [222, 188]],             // eye socket
    [[304, 148], [342, 222], [316, 284], [294, 198]],             // cheek blade
    [[294, 198], [316, 284], [272, 334], [240, 262]],             // lower cheek
    [[200, 136], [250, 118], [222, 188], [214, 252], [200, 264]], // nose ridge
    [[222, 188], [294, 198], [240, 262], [214, 252]],             // under-eye
    [[214, 252], [240, 262], [272, 334], [234, 370], [200, 384], [200, 264]], // jaw
    [[352, 160], [394, 214], [384, 300], [316, 284], [342, 222]], // side cowl
    [[316, 284], [384, 300], [334, 352], [272, 334]],             // lower cowl
  ];
  const CREST = [[200, 22], [212, 34], [208, 128], [200, 138], [192, 128], [188, 34]];
  const mirror = (pts) => pts.map(([x, y]) => [400 - x, y]);
  const poly = (pts) => pts.map((p) => p.join(',')).join(' ');
  const EYE_R = [[220, 184], [304, 144], [312, 157], [238, 202]];
  const CONTOURS_R = [                                            // pink edge highlights
    [[252, 120], [304, 150], [296, 198]],
    [[306, 154], [334, 224], [310, 284]],
    [[322, 100], [350, 160]],
    [[276, 334], [236, 368]],
    [[354, 166], [390, 216], [382, 296]],
    [[262, 54], [252, 116]],
  ];

  function faceSVG(id) {
    const facets = FACETS.flatMap((f, i) => {
      const shade = (0.55 + ((i * 7) % 5) * 0.11).toFixed(2), shadeL = (Number(shade) - 0.08).toFixed(2);
      return [`<polygon class="jv-facet" data-shade="${shade}" fill="url(#${id}-metal)" points="${poly(f)}"/>`,
              `<polygon class="jv-facet" data-shade="${shadeL}" fill="url(#${id}-metal)" points="${poly(mirror(f))}"/>`];
    }).join('');
    const line = (pts) => `<polyline class="jv-edge" points="${poly(pts)}"/>`;
    const contours = CONTOURS_R.flatMap((c) => [line(c), line(mirror(c))]).join('');
    const grille = [0, 1, 2, 3, 4].map((i) =>
      `<line class="jv-grille" data-i="${i}" x1="${186 + i * 1.5}" y1="${300 + i * 9}" x2="${214 - i * 1.5}" y2="${300 + i * 9}"/>`).join('');
    const eye = (pts, side) => {
      const hot = side === 'r' ? [[232, 192], [304, 152]] : [[168, 192], [96, 152]];
      return `
      <g class="jv-eye jv-eye-${side}">
        <polygon class="jv-eye-socket" points="${poly(pts)}"/>
        <g class="jv-aperture">
          <polygon class="jv-eye-bloom" points="${poly(pts)}" filter="url(#${id}-bloom)"/>
          <polygon class="jv-eye-glow" points="${poly(pts)}" filter="url(#${id}-blur)"/>
          <polygon class="jv-eye-iris" points="${poly(pts)}"/>
          <line class="jv-eye-hot" x1="${hot[0][0]}" y1="${hot[0][1]}" x2="${hot[1][0]}" y2="${hot[1][1]}"/>
        </g>
        <ellipse class="jv-pupil" cx="${(pts[0][0] + pts[2][0]) / 2}" cy="${(pts[0][1] + pts[2][1]) / 2 + 2}" rx="8" ry="2.2"/>
      </g>`;
    };
    return `
      <svg class="jv-face" viewBox="0 0 400 400" aria-hidden="true">
        <defs>
          <linearGradient id="${id}-metal" x1="0" y1="0" x2="0.35" y2="1">
            <stop offset="0" stop-color="#26262f"/><stop offset="0.45" stop-color="#121218"/><stop offset="1" stop-color="#040405"/>
          </linearGradient>
          <linearGradient id="${id}-crest" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stop-color="#3a3a46"/><stop offset="1" stop-color="#0b0b0f"/>
          </linearGradient>
          <filter id="${id}-blur" x="-60%" y="-300%" width="220%" height="700%"><feGaussianBlur stdDeviation="5"/></filter>
          <filter id="${id}-bloom" x="-100%" y="-500%" width="300%" height="1100%"><feGaussianBlur stdDeviation="16"/></filter>
        </defs>
        <g class="jv-mask">
          ${facets}
          <polygon class="jv-crest" fill="url(#${id}-crest)" points="${poly(CREST)}"/>
          <line class="jv-ridge" x1="200" y1="138" x2="200" y2="384"/>
          ${contours}
          <line class="jv-brow jv-brow-r" x1="230" y1="170" x2="310" y2="134"/>
          <line class="jv-brow jv-brow-l" x1="170" y1="170" x2="90" y2="134"/>
          ${eye(EYE_R, 'r')}${eye(mirror(EYE_R), 'l')}
          <g class="jv-mouth">${grille}</g>
        </g>
      </svg>`;
  }

  // --- the core: a living neural structure drawn on canvas ---
  function fibonacciSphere(n) {
    const points = [], golden = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < n; i++) {
      const y = 1 - (i / (n - 1)) * 2, r = Math.sqrt(1 - y * y), a = golden * i;
      points.push([Math.cos(a) * r, y, Math.sin(a) * r]);
    }
    return points;
  }

  // --- art mode: rendered character files (see NEXT_SESSION.md / docs) ---
  // Per state: the still to show and, optionally, a seamless loop. A missing
  // state still falls back to base.png (the eye glow still carries the state's
  // colour); with no rendered files at all the vector face above is used.
  const ART = {
    calm:      { still: 'base.png',      loop: 'idle.mp4' },
    listening: { still: 'listening.png' },
    analysing: { still: 'analysing.png', loop: 'thinking.mp4' },
    planning:  { still: 'planning.png',  loop: 'thinking.mp4' },
    executing: { still: 'executing.png', loop: 'executing.mp4' },
    concerned: { still: 'concerned.png' },
    resolute:  { still: 'resolute.png' },
    approval:  { still: 'approval.png' },
    awaiting:  { still: 'listening.png' },
    speaking:  { still: 'base.png',      loop: 'idle.mp4' },
    success:   { still: 'success.png' },
    failure:   { still: 'critical.png',  alt: 'error.png' },
    warning:   { still: 'warning.png' },
    error:     { still: 'error.png' },
    offline:   { still: 'base.png' },
  };
  // Eye centres in the rendered frame (fractions of width/height) and slant.
  const ART_EYES = [{ x: 0.405, y: 0.455, rot: '18deg' }, { x: 0.595, y: 0.455, rot: '-18deg' }];
  let artIndex = null;
  function artAssets() {
    if (!artIndex) {
      artIndex = fetch('/api/identity/assets', { cache: 'no-cache' })
        .then((r) => (r.ok ? r.json() : { files: [] }))
        .then((d) => ({ base: d.base || '/static/identity/', files: new Set(d.files || []) }))
        .catch(() => ({ base: '/static/identity/', files: new Set() }));
    }
    return artIndex;
  }
  function pickArt(index, name, allowLoop) {
    const a = ART[name] || ART.calm, has = (f) => f && index.files.has(f);
    if (allowLoop && has(a.loop)) return a.loop;
    for (const f of [a.still, a.alt, 'base.png']) if (has(f)) return f;
    return null;
  }

  // --- nanobot swarm: the rendered face rebuilt from thousands of glowing particles ---
  // Each particle takes its home position, colour and depth from base.png. On a
  // cycle the swarm divides into fragments that fly around the core, merges again
  // at a shifted place and drifts home. Real-time; no files beyond base.png.
  const smooth = (a, b, x) => { const k = Math.max(0, Math.min(1, (x - a) / (b - a))); return k * k * (3 - 2 * k); };
  const hash = (n) => { const s = Math.sin(n * 127.1 + 311.7) * 43758.5453; return s - Math.floor(s); };

  function loadSwarm(url, count) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.decoding = 'async';
      img.onerror = reject;
      img.onload = () => {
        const S = 180, c = document.createElement('canvas');
        c.width = c.height = S;
        const g = c.getContext('2d', { willReadFrequently: true });
        g.drawImage(img, 0, 0, S, S);
        const data = g.getImageData(0, 0, S, S).data;
        const pool = [], cumulative = [];
        let total = 0;
        for (let y = 0; y < S; y++) for (let x = 0; x < S; x++) {
          const i = (y * S + x) * 4, lum = Math.max(data[i], data[i + 1], data[i + 2]) / 255;
          if (lum < 0.1) continue;
          total += 0.35 + lum ** 1.15; cumulative.push(total); pool.push(i);   // dark plates still get bots
        }
        if (!pool.length) { reject(new Error('empty image')); return; }
        resolve(makeSwarm(pool, cumulative, total, data, S, count));
      };
      img.src = url;
    });
  }

  function makeSwarm(pool, cumulative, total, data, S, N) {
    const f = () => new Float32Array(N);
    const hx = f(), hy = f(), hz = f(), x = f(), y = f(), z = f(), vx = f(), vy = f(), vz = f();
    const cr = f(), cg = f(), cb = f(), lum = f(), seed = f(), cl = new Uint8Array(N);
    const K = 5, cx0 = new Float32Array(K), cy0 = new Float32Array(K), cn = new Float32Array(K);
    for (let n = 0; n < N; n++) {
      let lo = 0, hi = cumulative.length - 1;
      const r = Math.random() * total;
      while (lo < hi) { const m = (lo + hi) >> 1; if (cumulative[m] < r) lo = m + 1; else hi = m; }
      const i = pool[lo], px = (i / 4) % S, py = Math.floor(i / 4 / S);
      hx[n] = (px + Math.random()) / S - 0.5; hy[n] = (py + Math.random()) / S - 0.5;
      cr[n] = data[i]; cg[n] = data[i + 1]; cb[n] = data[i + 2];
      lum[n] = Math.max(cr[n], cg[n], cb[n]) / 255;
      const d2 = hx[n] * hx[n] + hy[n] * hy[n];
      hz[n] = Math.max(0, 0.22 - d2 * 0.9) + (lum[n] - 0.4) * 0.08;   // a sculpted, bulging mask
      seed[n] = Math.random() * 1000;
      const a = Math.atan2(hy[n], hx[n]);                               // fragments: slices of the face
      cl[n] = Math.floor(((a + Math.PI) / (Math.PI * 2)) * K) % K;
      cx0[cl[n]] += hx[n]; cy0[cl[n]] += hy[n]; cn[cl[n]]++;
      const s = 0.7 + Math.random() * 0.6, b = Math.random() * Math.PI * 2;  // start scattered: it assembles
      x[n] = Math.cos(b) * s; y[n] = Math.sin(b) * s; z[n] = (Math.random() - 0.5) * 0.6;
    }
    for (let k = 0; k < K; k++) { cx0[k] /= cn[k] || 1; cy0[k] /= cn[k] || 1; }
    const ccx = new Float32Array(K), ccy = new Float32Array(K), ccz = new Float32Array(K);

    let lastNow = 0;
    function snap() { x.set(hx); y.set(hy); z.set(hz); vx.fill(0); vy.fill(0); vz.fill(0); }

    // 3D reticle: three tilted rings of bots around the head, broken into arcs
    const RINGS = [{ r: 0.6, tilt: 1.25, roll: 0.25, speed: 0.22, arcs: [[0, 0.3], [0.38, 0.62], [0.7, 0.93]] },
                   { r: 0.68, tilt: 1.42, roll: -0.35, speed: -0.15, arcs: [[0.05, 0.95]] },
                   { r: 0.77, tilt: 1.1, roll: 0.6, speed: 0.1, arcs: [[0, 0.12], [0.2, 0.45], [0.55, 0.6], [0.66, 0.9]] }];
    const ringPts = [];
    RINGS.forEach((ring, i) => {
      const count = Math.round(ring.r * (N > 2000 ? 420 : 220));
      for (let j = 0; j < count; j++) {
        const u = j / count;
        if (ring.arcs.some(([a, b]) => u >= a && u <= b)) ringPts.push([i, u * Math.PI * 2]);
      }
    });
    const TOTAL = N + ringPts.length;
    const out = new Float32Array(TOTAL * 7);          // x, y, size, r, g, b, a (pixels)

    // One simulation step plus projection; fills `out`, returns the point count.
    function frame(w, now, o) {
      const { spec, state, t, gaze, level, color, dpr } = o;
      if (o.reduced && !o.snapped) { snap(); o.snapped = true; }
      const sec = now / 1000;
      const steps = lastNow ? Math.max(1, Math.min(30, Math.round((now - lastNow) / 16.7))) : 1;
      lastNow = now;
      const period = spec.still || state === 'offline' ? 0 : state === 'executing' ? 9 : state === 'calm' || state === 'speaking' ? 16 : 12;
      let split = 0, offX = 0, offY = 0;
      if (period && !o.reduced) {
        const cycle = Math.floor(sec / period), c = (sec % period) / period;
        split = smooth(0.5, 0.58, c) * (1 - smooth(0.72, 0.8, c));
        const sx = (hash(cycle) - 0.5) * 0.34, sy = (hash(cycle + 7) - 0.5) * 0.22;
        const shift = smooth(0.7, 0.78, c) * (1 - smooth(0.82, 1, c));
        offX = sx * shift; offY = sy * shift;
      }
      for (let k = 0; k < K; k++) {
        const a = (k / K) * Math.PI * 2 + sec * (state === 'executing' ? 1.1 : 0.55);
        ccx[k] = Math.cos(a) * 0.5; ccy[k] = Math.sin(a) * 0.36; ccz[k] = Math.sin(a * 2) * 0.35;
      }
      let swell = 1;
      if (spec.sag) { offY += 0.05; split = 0; }                       // sadness: the swarm sinks, holds together
      if (spec.lively) swell += 0.025 * Math.sin(sec * 5);              // warmth: a buoyant pulse
      if (spec.tilt) offX += 0.03 * Math.sin(sec * 1.3);               // curiosity: leans in
      if (spec.burst && t < 1.6) swell += 0.55 * Math.sin(Math.PI * t / 1.6);
      const shimmer = state === 'analysing' || state === 'planning' ? 0.014 : 0.004;
      const kick = spec.disrupt && t < 0.9 ? (1 - t / 0.9) * 0.02 : spec.rage ? 0.007 + level * 0.01 : 0;   // anger trembles
      const spring = split > 0.05 ? 0.035 : 0.055, damp = 0.86;
      const tilt = gaze[0] * 0.6 + (spec.still ? 0 : Math.sin(sec / 4.5) * 0.18), pitch = -gaze[1] * 0.4;
      const ct = Math.cos(tilt), st = Math.sin(tilt), cp = Math.cos(pitch), sp = Math.sin(pitch);
      const W = w * 0.78, mid = w / 2, accent = color;
      const mix = { angry: 0.9, warm: 0.7, sad: 0.75, curious: 0.5, warning: 0.75, error: 0.75, failure: 0.75 }[state] ?? (spec.mix > 0.3 ? 0.45 : 0.15);
      const flicker = spec.flicker ? 0.65 + 0.35 * Math.sin(now / 80) : 1;
      const glow = Math.max(0.25, spec.glow) * flicker;
      const big = w / dpr > 400 ? 1.3 : 1;
      let m = 0;
      const emit = (X, Y, Z, size, r, g, b, a) => {
        const p = 2.6 / (2.6 - Z), fog = Math.max(0.25, Math.min(1, 0.65 + Z * 0.9));
        out[m++] = mid + X * W * p; out[m++] = mid + Y * W * p; out[m++] = size * p * dpr * big;
        out[m++] = r / 255; out[m++] = g / 255; out[m++] = b / 255; out[m++] = Math.min(1, a * fog);
      };
      for (let n = 0; n < N; n++) {
        const k = cl[n], s = seed[n];
        let tx = hx[n] * swell + offX, ty = hy[n] * swell + offY, tz = hz[n];
        if (split > 0) {
          const fx = ccx[k] + (hx[n] - cx0[k]) * 0.42, fy = ccy[k] + (hy[n] - cy0[k]) * 0.42;
          tx += (fx - tx) * split; ty += (fy - ty) * split; tz += (ccz[k] - tz) * split;
        }
        const amp = shimmer + split * 0.03;
        tx += Math.sin(sec * 1.7 + s) * amp; ty += Math.cos(sec * 1.3 + s * 1.3) * amp; tz += Math.sin(sec + s * 0.7) * amp;
        if (!o.reduced) for (let step = 0; step < steps; step++) {
          vx[n] = (vx[n] + (tx - x[n]) * spring + (kick ? (Math.random() - 0.5) * kick : 0)) * damp;
          vy[n] = (vy[n] + (ty - y[n]) * spring + (kick ? (Math.random() - 0.5) * kick : 0)) * damp;
          vz[n] = (vz[n] + (tz - z[n]) * spring) * damp;
          x[n] += vx[n]; y[n] += vy[n]; z[n] += vz[n];
        }
        let X = x[n] * ct + z[n] * st, Z = -x[n] * st + z[n] * ct, Y = y[n];
        [Y, Z] = [Y * cp - Z * sp, Y * sp + Z * cp];
        const L = lum[n], speed = Math.abs(vx[n]) + Math.abs(vy[n]);
        let a = (0.42 + 0.75 * L) * glow + Math.min(0.35, speed * 7);
        if (spec.voice && L > 0.6) a += level * 0.8;
        const twinkle = 0.85 + 0.15 * Math.sin(sec * 3 + s);
        emit(X, Y, Z, L > 0.7 ? 3.2 : 2.1, cr[n] + (accent[0] - cr[n]) * mix, cg[n] + (accent[1] - cg[n]) * mix,
             cb[n] + (accent[2] - cb[n]) * mix, a * twinkle);
      }
      // rings: real 3D circles, spinning in their own planes, seen through the same camera
      const spin = sec * (spec.speed || 1);
      for (const [i, u] of ringPts) {
        const ring = RINGS[i], ang = u + spin * ring.speed;
        let X = Math.cos(ang) * ring.r, Y = Math.sin(ang) * ring.r, Z = 0;
        const cT = Math.cos(ring.tilt), sT = Math.sin(ring.tilt);       // tip the ring back
        [Y, Z] = [Y * cT, Y * sT];
        const cR = Math.cos(ring.roll), sR = Math.sin(ring.roll);       // and roll it
        [X, Y] = [X * cR - Y * sR, X * sR + Y * cR];
        let X2 = X * ct + Z * st, Z2 = -X * st + Z * ct, Y2 = Y;
        [Y2, Z2] = [Y2 * cp - Z2 * sp, Y2 * sp + Z2 * cp];
        emit(X2, Y2 + 0.02, Z2, 1.9, accent[0], accent[1], accent[2], 0.6 * glow);
      }
      return m / 7;
    }

    // Canvas 2D fallback (no WebGL).
    function draw(ctx, w, now, o) {
      const count = frame(w, now, o);
      ctx.clearRect(0, 0, w, w);
      ctx.globalCompositeOperation = 'lighter';
      for (let i = 0; i < count; i++) {
        const q = i * 7, size = out[q + 2];
        ctx.fillStyle = `rgba(${out[q + 3] * 255 | 0},${out[q + 4] * 255 | 0},${out[q + 5] * 255 | 0},${out[q + 6].toFixed(3)})`;
        ctx.fillRect(out[q] - size / 2, out[q + 1] - size / 2, size, size);
      }
      ctx.globalCompositeOperation = 'source-over';
    }

    return { draw, frame, out };
  }

  // WebGL renderer for the swarm: soft glowing sprites, additive light, a bloom pass.
  function makeGL(canvas) {
    const gl = canvas.getContext('webgl', { alpha: true, premultipliedAlpha: true, antialias: false });
    if (!gl) return null;
    const shader = (type, src) => {
      const sh = gl.createShader(type); gl.shaderSource(sh, src); gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(sh));
      return sh;
    };
    const prog = gl.createProgram();
    gl.attachShader(prog, shader(gl.VERTEX_SHADER, `
      attribute vec2 a_pos; attribute float a_size; attribute vec4 a_col;
      uniform vec2 u_res; uniform float u_scale; varying vec4 v_col;
      void main() {
        vec2 clip = a_pos / u_res * 2.0 - 1.0;
        gl_Position = vec4(clip.x, -clip.y, 0.0, 1.0);
        gl_PointSize = max(1.0, a_size * u_scale);
        v_col = a_col;
      }`));
    gl.attachShader(prog, shader(gl.FRAGMENT_SHADER, `
      precision mediump float; varying vec4 v_col; uniform float u_gain; uniform float u_core;
      void main() {
        float d = length(gl_PointCoord - 0.5) * 2.0;
        if (d > 1.0) discard;
        float light = mix(exp(-d * d * 3.0), exp(-d * d * 9.0) + 0.6 * exp(-d * d * 40.0), u_core);
        float a = v_col.a * light * u_gain;
        vec3 hot = mix(v_col.rgb, vec3(1.0), u_core * 0.55 * exp(-d * d * 30.0));
        gl_FragColor = vec4(hot * a, a);
      }`));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return null;
    const buf = gl.createBuffer();
    const loc = (n) => gl.getAttribLocation(prog, n), u = (n) => gl.getUniformLocation(prog, n);
    const aPos = loc('a_pos'), aSize = loc('a_size'), aCol = loc('a_col');
    const uRes = u('u_res'), uScale = u('u_scale'), uGain = u('u_gain'), uCore = u('u_core');
    return {
      render(data, count, w) {
        gl.viewport(0, 0, w, w);
        gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
        if (!count) return;
        gl.useProgram(prog);
        gl.bindBuffer(gl.ARRAY_BUFFER, buf);
        gl.bufferData(gl.ARRAY_BUFFER, data.subarray(0, count * 7), gl.DYNAMIC_DRAW);
        gl.enableVertexAttribArray(aPos); gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 28, 0);
        gl.enableVertexAttribArray(aSize); gl.vertexAttribPointer(aSize, 1, gl.FLOAT, false, 28, 8);
        gl.enableVertexAttribArray(aCol); gl.vertexAttribPointer(aCol, 4, gl.FLOAT, false, 28, 12);
        gl.uniform2f(uRes, w, w);
        gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE);       // light adds up: see-through bots
        gl.uniform1f(uScale, 6.0); gl.uniform1f(uGain, 0.05); gl.uniform1f(uCore, 0.0);   // bloom
        gl.drawArrays(gl.POINTS, 0, count);
        gl.uniform1f(uScale, 1.9); gl.uniform1f(uGain, 0.95); gl.uniform1f(uCore, 1.0);   // bots
        gl.drawArrays(gl.POINTS, 0, count);
      },
    };
  }

  let counter = 0;

  function create(host, options = {}) {
    const id = `jv${++counter}`;
    const compact = !!options.compact;
    const root = document.createElement('div');
    root.className = 'jv-identity' + (compact ? ' jv-compact' : '');
    root.innerHTML = `<canvas class="jv-core"></canvas>
      <div class="jv-art" aria-hidden="true"><div class="jv-art-stack">
        <div class="jv-art-bloom"></div>
        ${ART_EYES.map(() => '<div class="jv-art-eye"></div>').join('')}
      </div></div>${faceSVG(id)}`;
    host.append(root);
    const artStack = root.querySelector('.jv-art-stack');
    root.querySelectorAll('.jv-art-eye').forEach((el, i) => {
      el.style.setProperty('--x', ART_EYES[i].x); el.style.setProperty('--y', ART_EYES[i].y);
      el.style.setProperty('--rot', ART_EYES[i].rot);
    });
    let art = null, artShown = null, artCurrent = null, artToken = 0;

    // Crossfade to the state's still/loop. Loaded fully before it is shown.
    function showArt() {
      if (!art) return;
      const file = pickArt(art, state, !options.static && !reducedMotion());
      if (!file) { root.classList.remove('jv-art-mode'); return; }
      root.classList.add('jv-art-mode');
      if (file === artShown) return;
      artShown = file;
      const token = ++artToken, isVideo = file.endsWith('.mp4');
      const el = document.createElement(isVideo ? 'video' : 'img');
      el.className = 'jv-art-media';
      if (isVideo) { el.muted = true; el.loop = true; el.playsInline = true; el.autoplay = true; }
      else { el.alt = ''; el.decoding = 'async'; }
      const reveal = () => {
        if (token !== artToken) { el.remove(); return; }
        const old = artCurrent; artCurrent = el;
        void el.offsetWidth;                         // commit opacity 0 so the fade runs
        el.classList.add('jv-on');
        if (old) { old.classList.remove('jv-on'); setTimeout(() => old.remove(), 650); }
      };
      el.addEventListener(isVideo ? 'loadeddata' : 'load', reveal, { once: true });
      el.addEventListener('error', () => {         // file vanished: forget it, choose again
        art.files.delete(file); el.remove();
        if (token === artToken) { artShown = null; showArt(); }
      }, { once: true });
      artStack.prepend(el);
      el.src = art.base + file;
    }
    let swarm = null, glr = null, glCanvasEl = null;
    const swarmOpts = { snapped: false };
    if (options.art !== false) artAssets().then((index) => {
      art = index; showArt();
      if (!options.static && options.swarm !== false && index.files.has('base.png')) {
        loadSwarm(index.base + 'base.png', compact ? 1300 : 3200)
          .then((s) => {
            swarm = s;
            const glCanvas = document.createElement('canvas');
            glCanvas.className = 'jv-gl';
            try { glr = makeGL(glCanvas); } catch (e) { glr = null; }
            if (glr) { canvas.after(glCanvas); glCanvasEl = glCanvas; }
            root.classList.add('jv-swarm-mode'); resize();
          })
          .catch(() => {});                       // stays on the still art
      }
    });
    const canvas = root.querySelector('canvas');
    const ctx = canvas.getContext('2d');
    const eyes = [...root.querySelectorAll('.jv-pupil')];
    root.querySelectorAll('[data-shade]').forEach((el) => el.style.setProperty('--shade', el.dataset.shade));
    root.querySelectorAll('[data-i]').forEach((el) => el.style.setProperty('--i', el.dataset.i));

    const nodes = fibonacciSphere(compact ? 40 : 72);
    const edges = [];
    nodes.forEach((a, i) => {
      const near = nodes.map((b, j) => [j, (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2])
        .filter(([j]) => j !== i).sort((p, q) => p[1] - q[1]).slice(0, 3);
      near.forEach(([j]) => { if (i < j) edges.push([i, j]); });
    });
    const neighbours = nodes.map((_, i) => edges.filter((e) => e[0] === i || e[1] === i).map((e) => (e[0] === i ? e[1] : e[0])));

    let state = 'calm', spec = STATES.calm, enteredAt = performance.now(), level = 0;
    let angle = 0, size = 0, dpr = 1, frame = 0, raf = 0, running = true;
    let pointer = null, gaze = [0, 0], gazeTarget = [0, 0], lastPointerMove = 0;
    let paths = [];

    function randomPath(length) {
      let at = Math.floor(Math.random() * nodes.length);
      const path = [at];
      for (let k = 1; k < length; k++) {
        const options = neighbours[at].filter((n) => !path.includes(n));
        if (!options.length) break;
        at = options[Math.floor(Math.random() * options.length)];
        path.push(at);
      }
      return path;
    }

    function resize() {
      const box = root.getBoundingClientRect();
      size = Math.max(60, Math.min(box.width, box.height || box.width));
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = canvas.height = Math.round(size * dpr);
      canvas.style.width = canvas.style.height = `${size}px`;
      if (glCanvasEl) {
        glCanvasEl.width = glCanvasEl.height = canvas.width;
        glCanvasEl.style.width = glCanvasEl.style.height = `${size}px`;
      }
    }

    function apply() {
      root.dataset.state = state;
      const c = mixColor(spec.color, VIOLET, spec.mix);
      root.style.setProperty('--jv-accent', `rgb(${c.join(',')})`);
      root.style.setProperty('--jv-accent-rgb', c.join(','));
      root.style.setProperty('--jv-eye-open', spec.eye);
      root.style.setProperty('--jv-face', spec.face);
      root.style.setProperty('--jv-glow', spec.glow);
      root.style.setProperty('--jv-brow', `${spec.brow}deg`);
      paths = Array.from({ length: spec.paths }, () => randomPath(compact ? 5 : 7));
      showArt();
    }

    function setState(name, line) {
      if (!STATES[name]) name = 'calm';
      if (name !== state) { state = name; spec = STATES[name]; enteredAt = performance.now(); apply(); }
      if (options.static) requestAnimationFrame(() => draw(enteredAt + 900));
      if (options.onLine) options.onLine(line != null && line !== '' ? line : spec.line, spec.label, name);
      if (reducedMotion()) draw(performance.now());
    }

    function project(p, tilt) {
      const ca = Math.cos(angle), sa = Math.sin(angle);
      let x = p[0] * ca + p[2] * sa, z = -p[0] * sa + p[2] * ca, y = p[1];
      const ct = Math.cos(tilt[1]), st = Math.sin(tilt[1]);
      [y, z] = [y * ct - z * st, y * st + z * ct];
      const cp = Math.cos(tilt[0]), sp = Math.sin(tilt[0]);
      [x, z] = [x * cp + z * sp, -x * sp + z * cp];
      return [x, y, z];
    }

    function draw(now) {
      const t = (now - enteredAt) / 1000;
      const w = canvas.width, cx = w / 2, cy = w / 2;
      const R = w * (compact ? 0.36 : 0.34);
      const color = mixColor(spec.color, VIOLET, spec.mix);
      if (swarm) {
        Object.assign(swarmOpts, { spec, state, t, gaze, level, color, dpr, reduced: reducedMotion() });
        if (glr) { ctx.clearRect(0, 0, w, w); glr.render(swarm.out, swarm.frame(w, now, swarmOpts), w); }
        else swarm.draw(ctx, w, now, swarmOpts);
        return;
      }
      ctx.clearRect(0, 0, w, w);

      // breathing / expansion / disruption
      let scale = 1 + (spec.still ? 0 : 0.012 * Math.sin(now / 1300));
      if (spec.burst && t < 1.4) scale += 0.08 * Math.sin(Math.min(t / 1.4, 1) * Math.PI);
      if (spec.voice) scale += level * 0.05;
      const jitter = spec.disrupt && t < 0.7 ? (1 - t / 0.7) * w * 0.012 : 0;
      const tilt = [gaze[0] * 0.35, gaze[1] * 0.25];

      // nodes
      const pts = nodes.map((p) => {
        const [x, y, z] = project(p, tilt);
        return [cx + x * R * scale + (jitter ? (Math.random() - 0.5) * jitter : 0), cy + y * R * scale * 0.94, z];
      });
      const flicker = spec.flicker ? 0.6 + 0.4 * Math.sin(now / 90) : 1;

      // connections
      ctx.lineWidth = Math.max(0.6, dpr * 0.6);
      for (const [i, j] of edges) {
        const depth = (pts[i][2] + pts[j][2] + 2) / 4;
        ctx.strokeStyle = rgba(color, (0.05 + 0.16 * depth) * spec.glow * flicker);
        ctx.beginPath(); ctx.moveTo(pts[i][0], pts[i][1]); ctx.lineTo(pts[j][0], pts[j][1]); ctx.stroke();
      }

      // pointer: the core responds locally
      let px = null, py = null;
      if (pointer && now - lastPointerMove < 2500) {
        const box = canvas.getBoundingClientRect();
        px = (pointer[0] - box.left) * dpr; py = (pointer[1] - box.top) * dpr;
        if (px < 0 || py < 0 || px > w || py > w) px = py = null;
      }
      for (const [x, y, z] of pts) {
        const near = px == null ? 0 : Math.max(0, 1 - Math.hypot(x - px, y - py) / (w * 0.18));
        const depth = (z + 1) / 2;
        ctx.fillStyle = rgba(color, (0.15 + 0.6 * depth) * spec.glow + near * 0.6);
        ctx.beginPath(); ctx.arc(x, y, (0.8 + depth * 1.4 + near * 2) * dpr, 0, Math.PI * 2); ctx.fill();
      }

      // pathways: planning grows them, executing sends energy along them
      ctx.lineWidth = 1.6 * dpr;
      paths.forEach((path, k) => {
        const grown = spec.grow ? Math.min(path.length, 1 + ((t * 2.2 - k * 0.4) % (path.length + 2))) : path.length;
        ctx.strokeStyle = rgba(color, 0.55 * spec.glow);
        ctx.beginPath();
        for (let s = 0; s < Math.floor(grown); s++) {
          const p = pts[path[s]];
          if (s === 0) ctx.moveTo(p[0], p[1]); else ctx.lineTo(p[0], p[1]);
        }
        ctx.stroke();
      });
      if (spec.particles && paths.length) {
        for (let n = 0; n < spec.particles; n++) {
          const path = paths[n % paths.length];
          const pos = ((t * (spec.still ? 0.4 : 1.2) + n / spec.particles) % 1) * (path.length - 1);
          const s = Math.floor(pos), f = pos - s, a = pts[path[s]], b = pts[path[Math.min(s + 1, path.length - 1)]];
          ctx.fillStyle = rgba(color, 0.95);
          ctx.beginPath(); ctx.arc(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, 1.8 * dpr, 0, Math.PI * 2); ctx.fill();
        }
      }

      // rings
      const rings = compact ? [1.18, 1.32] : [1.16, 1.3, 1.44];
      rings.forEach((k, i) => {
        const turn = now / 1000 * spec.speed * (i % 2 ? -0.6 : 0.4) + i * 1.7;
        ctx.strokeStyle = rgba(color, (0.18 + 0.25 * spec.glow) * (1 - i * 0.18));
        ctx.lineWidth = (i === 0 ? 1.4 : 0.9) * dpr;
        const arcs = spec.gate && i === 1 ? [[0.05, 0.95]] : [[0, 0.32], [0.42, 0.62], [0.7, 0.9]];
        arcs.forEach(([a, b]) => {
          ctx.beginPath();
          ctx.ellipse(cx, cy, R * k * scale, R * k * scale * 0.94, 0, turn + a * Math.PI * 2, turn + b * Math.PI * 2);
          ctx.stroke();
        });
      });
      if (spec.burst && t < 1.4) {                    // controlled release on success
        ctx.strokeStyle = rgba(color, 0.6 * (1 - t / 1.4));
        ctx.lineWidth = 2 * dpr;
        ctx.beginPath(); ctx.arc(cx, cy, R * (1.2 + t * 0.4), 0, Math.PI * 2); ctx.stroke();
      }
      // speaking: the voice level shows on the mask's grille
      if (spec.voice) root.style.setProperty('--jv-level', level.toFixed(2));
    }

    function loop(now) {
      if (!running) return;
      raf = requestAnimationFrame(loop);
      // gaze eases toward the pointer (or straight ahead)
      gaze[0] += (gazeTarget[0] - gaze[0]) * 0.08;
      gaze[1] += (gazeTarget[1] - gaze[1]) * 0.08;
      eyes.forEach((eye) => { eye.style.transform = `translate(${(gaze[0] * 5).toFixed(2)}px, ${(gaze[1] * 3).toFixed(2)}px)`; });
      // art mode: subtle 3D parallax toward the cursor; voice level on the eyes
      if (artCurrent) {
        artStack.style.transform = `rotateY(${(gaze[0] * 5).toFixed(2)}deg) rotateX(${(-gaze[1] * 4).toFixed(2)}deg) translate(${(gaze[0] * 1.2).toFixed(2)}%, ${(gaze[1] * 0.8).toFixed(2)}%)`;
        root.style.setProperty('--jv-level', spec.voice ? level.toFixed(2) : '0');
      }
      angle += 0.016 * spec.speed;
      // stillness: when calm and nobody is moving, draw rarely
      const idle = (state === 'calm' || state === 'offline') && now - lastPointerMove > 3000;
      frame++;
      if (reducedMotion() || (!swarm && idle && frame % 6)) return;
      draw(now);
    }

    function onPointer(event) {
      pointer = [event.clientX, event.clientY];
      lastPointerMove = performance.now();
      const box = root.getBoundingClientRect();
      const dx = (event.clientX - (box.left + box.width / 2)) / Math.max(window.innerWidth / 2, 1);
      const dy = (event.clientY - (box.top + box.height / 2)) / Math.max(window.innerHeight / 2, 1);
      gazeTarget = spec.still ? [0, 0] : [Math.max(-1, Math.min(1, dx)), Math.max(-1, Math.min(1, dy))];
    }
    function onLeave() { gazeTarget = [0, 0]; pointer = null; }

    resize(); apply();
    const observer = new ResizeObserver(() => { resize(); if (options.static) draw(enteredAt + 900); });
    observer.observe(root);
    if (options.static) {                  // a still portrait (state gallery): no animation loop
      running = false;
      requestAnimationFrame(() => draw(enteredAt + 900));
    } else {
      window.addEventListener('pointermove', onPointer, { passive: true });
      document.addEventListener('mouseleave', onLeave);
      raf = requestAnimationFrame(loop);
      if (reducedMotion()) draw(performance.now());
    }

    let previewTimer = null;
    return {
      get state() { return state; },
      setState,
      setLevel(v) { level = Math.max(0, Math.min(1, v || 0)); },
      /** Cycle through every state. SIMULATION ONLY: callers must label it as such. */
      preview(onStep) {
        const names = Object.keys(STATES);
        let i = 0;
        clearInterval(previewTimer);
        const step = () => { const n = names[i++ % names.length]; setState(n); if (onStep) onStep(n); };
        step();
        previewTimer = setInterval(step, 2600);
        return () => clearInterval(previewTimer);
      },
      stopPreview() { clearInterval(previewTimer); },
      destroy() {
        running = false; cancelAnimationFrame(raf); clearInterval(previewTimer);
        observer.disconnect();
        window.removeEventListener('pointermove', onPointer);
        document.removeEventListener('mouseleave', onLeave);
        root.remove();
      },
    };
  }

  /** Map the server's /api/live state onto the identity (with the real detail). */
  function fromLive(live) {
    if (!live) return ['calm', ''];
    const step = live.step ? `${live.step.description}` : '';
    switch (live.state) {
      case 'executing': return ['executing', step ? `Executing: ${step}` : 'Executing.'];
      case 'planning': return ['planning', live.plan && live.plan.length ? `Plan formed: ${live.plan.length} step${live.plan.length === 1 ? '' : 's'}.` : 'Forming a plan.'];
      case 'approval': return ['approval', live.detail || STATES.approval.line];
      case 'awaiting': return ['awaiting', live.detail || STATES.awaiting.line];
      case 'failure': return ['failure', live.detail ? `The operation failed. ${live.detail}` : STATES.failure.line];
      default: return [live.state in STATES ? live.state : 'calm', ''];
    }
  }

  window.JarvisIdentity = { create, fromLive, STATES };
})();
