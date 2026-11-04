(function () {
  'use strict';
  const canvas = document.getElementById('home-ascii-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  const hero = canvas.closest('.home-hero');
  const scene = canvas.parentElement;
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  // Hard budgets apply even at extreme zoom-out, on ultrawide displays and high DPR.
  const MAX_WIDTH = 2880, MAX_HEIGHT = 1800, MAX_CELLS = 16800;
  const FRAME_MS = 1000 / 24;
  const nearSet = '@#%O0*+', tailSet = '.:\' +*';
  let width = 1, height = 1, cols = 1, rows = 1;
  let visible = false, frame = 0, last = -Infinity, time = 0;
  let pointer = null, disposed = false;
  let glow = new Float32Array(1), marks = [' '];

  // The old scene's flowing punctuation field and persistent, scattered mouse ink.
  function baseChar(x, y) {
    const mix = Math.sin(x * 0.17 + time * 0.48) * 0.34
      + Math.cos(y * 0.21 - time * 0.36) * 0.28
      + Math.sin((x + y) * 0.09 + time * 0.24) * 0.22
      + Math.cos((x - y) * 0.07 - time * 0.18) * 0.16;
    return mix > 0.44 ? '.' : mix > 0.18 ? ':' : mix > -0.06 ? "'" : mix > -0.28 ? '`' : ',';
  }

  function stamp(px, py) {
    const gx = px * cols, gy = py * rows, radius = 3.2;
    for (let y = Math.max(0, Math.floor(gy - radius)); y <= Math.min(rows - 1, Math.ceil(gy + radius)); y++) {
      for (let x = Math.max(0, Math.floor(gx - radius)); x <= Math.min(cols - 1, Math.ceil(gx + radius)); x++) {
        const distance = Math.hypot(x - gx, y - gy);
        if (distance >= radius) continue;
        const k = y * cols + x;
        const strength = 1 - distance / radius;
        glow[k] = Math.max(glow[k], strength);
        if (Math.random() < strength * 0.65) {
          const set = distance < radius * 0.45 ? nearSet : tailSet;
          marks[k] = set[Math.floor(Math.random() * set.length)];
        }
      }
    }
  }

  function draw() {
    ctx.clearRect(0, 0, width, height);
    const day = document.documentElement.dataset.theme === 'day';
    const dx = width / cols, dy = height / rows;
    ctx.font = Math.max(9, Math.min(14, dy * 0.85)) + 'px Consolas, monospace';
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'center';
    for (let y = 0; y < rows; y++) {
      for (let x = 0; x < cols; x++) {
        const k = y * cols + x, ink = glow[k];
        ctx.fillStyle = ink > 0.04 ? (day ? '#20252b' : '#ecf6ff') : (day ? '#626a73' : '#a2d3ff');
        ctx.globalAlpha = ink > 0.04 ? Math.min(1, ink * 2.5) : (day ? 0.42 : 0.38);
        const char = ink > 0.04 && marks[k] !== ' ' ? marks[k] : baseChar(x, y);
        ctx.fillText(char, (x + 0.5) * dx, (y + 0.5) * dy);
      }
    }
    ctx.globalAlpha = 1;
  }

  function tick(now) {
    frame = 0;
    if (disposed || !visible || document.hidden || motion.matches) return;
    if (now - last >= FRAME_MS) {
      const dt = Number.isFinite(last) ? Math.min((now - last) / 1000, 0.1) : 0;
      time += dt;
      for (let k = 0; k < glow.length; k++) glow[k] = Math.max(0, glow[k] - dt * 0.50);
      last = now;
      draw();
    }
    frame = requestAnimationFrame(tick);
  }

  function sync() {
    cancelAnimationFrame(frame);
    frame = 0;
    last = -Infinity;
    if (disposed || !visible || document.hidden) return;
    if (motion.matches) draw();
    else frame = requestAnimationFrame(tick);
  }

  function resize() {
    // Expand beyond the content column without adding horizontal scrolling.
    const bodyRect = document.body.getBoundingClientRect();
    const heroRect = hero.getBoundingClientRect();
    const sceneWidth = Math.min(bodyRect.width, MAX_WIDTH);
    scene.style.width = sceneWidth + 'px';
    scene.style.left = (bodyRect.left + (bodyRect.width - sceneWidth) / 2 - heroRect.left) + 'px';
    const rect = scene.getBoundingClientRect();
    width = Math.max(1, Math.min(MAX_WIDTH, Math.round(rect.width)));
    height = Math.max(1, Math.min(MAX_HEIGHT, Math.round(rect.height)));
    // Fixed backing resolution: deliberately independent of devicePixelRatio.
    canvas.width = width;
    canvas.height = height;
    // Extra area adds symbols instead of stretching the existing field.
    const scale = Math.max(1, Math.sqrt((width / 10) * (height / 18) / MAX_CELLS));
    cols = Math.max(1, Math.floor(width / (10 * scale)));
    rows = Math.max(1, Math.floor(height / (18 * scale)));
    glow = new Float32Array(cols * rows);
    marks = new Array(cols * rows).fill(' ');
    pointer = null;
    draw();
    sync();
  }

  function move(event) {
    if (motion.matches || event.pointerType === 'touch') return;
    const rect = scene.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) {
      leave();
      return;
    }
    const next = { x: (event.clientX - rect.left) / rect.width, y: (event.clientY - rect.top) / rect.height };
    const prev = pointer || next;
    // Bound interpolation work even for a cursor jump across a huge screen.
    const steps = Math.min(96, Math.max(1, Math.ceil(Math.hypot((next.x - prev.x) * width, (next.y - prev.y) * height) / 6)));
    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      stamp(prev.x + (next.x - prev.x) * t, prev.y + (next.y - prev.y) * t);
    }
    pointer = next;
  }
  function leave() { pointer = null; }
  const sizeObserver = new ResizeObserver(resize);
  const visibilityObserver = new IntersectionObserver(function (entries) {
    visible = entries[0].isIntersecting;
    sync();
  });
  const themeObserver = new MutationObserver(function () {
    if (visible && !document.hidden) draw();
  });
  sizeObserver.observe(hero);
  visibilityObserver.observe(scene);
  window.addEventListener('resize', resize, { passive: true });
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  motion.addEventListener('change', sync);
  document.addEventListener('visibilitychange', sync);
  document.addEventListener('pointermove', move, { passive: true });
  document.addEventListener('pointerleave', leave, { passive: true });
  // BFCache restores this page with observers intact; other departures clean up.
  window.addEventListener('pagehide', function (event) {
    cancelAnimationFrame(frame);
    if (event.persisted) return;
    disposed = true;
    sizeObserver.disconnect();
    visibilityObserver.disconnect();
    themeObserver.disconnect();
    motion.removeEventListener('change', sync);
    document.removeEventListener('visibilitychange', sync);
    window.removeEventListener('resize', resize);
    document.removeEventListener('pointermove', move);
    document.removeEventListener('pointerleave', leave);
  });
  window.addEventListener('pageshow', sync);
})();
