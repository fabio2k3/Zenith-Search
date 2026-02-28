// ═══════════════════════════════════════════════
//  ZENITH — app.js
//  Canvas: partículas de polvo + cuervos voladores
//  Buscador: animaciones de interacción
// ═══════════════════════════════════════════════

// ── Canvas ──────────────────────────────────────
const canvas = document.getElementById('canvas');
const ctx    = canvas.getContext('2d');

function resize() {
  canvas.width  = innerWidth;
  canvas.height = innerHeight;
}
resize();
window.addEventListener('resize', resize);

// ── Utilidades ──────────────────────────────────
function lerp(a, b, t) { return a + (b - a) * t; }
function rand(min, max) { return Math.random() * (max - min) + min; }

// ── Partículas de polvo/ceniza ───────────────────
const PARTICLE_COUNT = 55;
const particles = Array.from({ length: PARTICLE_COUNT }, () => spawnParticle(true));

function spawnParticle(randomY) {
  return {
    x:       rand(0, innerWidth),
    y:       randomY ? rand(0, innerHeight) : innerHeight + 10,
    r:       rand(0.3, 1.7),
    vx:      rand(-0.15, 0.15),
    vy:      -(rand(0.1, 0.5)),
    life:    1,
    decay:   rand(0.0005, 0.002),
    flicker: rand(0, Math.PI * 2),
  };
}

// ── Cuervos ─────────────────────────────────────
const RAVEN_COUNT = 3;
const ravens = Array.from({ length: RAVEN_COUNT }, (_, i) => spawnRaven(i));

function spawnRaven(i) {
  const fromLeft = Math.random() > 0.5;
  return {
    x:         fromLeft ? -80 : innerWidth + 80,
    y:         rand(innerHeight * 0.05, innerHeight * 0.38),
    dir:       fromLeft ? 1 : -1,
    speed:     rand(0.35, 0.95),
    wingPhase: rand(0, Math.PI * 2),
    wingSpeed: rand(0.04, 0.1),
    scale:     rand(0.6, 1.1),
    opacity:   0,
    delay:     i * 7000 + rand(1000, 5000),
    active:    false,
    timer:     0,
  };
}

function drawRaven(x, y, wingPhase, scale, dir, opacity) {
  if (opacity <= 0) return;
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(dir * scale, scale);
  ctx.globalAlpha = opacity * 0.22;
  ctx.fillStyle   = '#c8922a';

  // Cuerpo
  ctx.beginPath();
  ctx.ellipse(0, 0, 10, 5, 0, 0, Math.PI * 2);
  ctx.fill();

  // Cabeza
  ctx.beginPath();
  ctx.ellipse(11, -3, 5, 4, -0.3, 0, Math.PI * 2);
  ctx.fill();

  // Pico
  ctx.beginPath();
  ctx.moveTo(15, -3);
  ctx.lineTo(19, -2);
  ctx.lineTo(15, -1);
  ctx.fill();

  // Cola
  ctx.beginPath();
  ctx.moveTo(-9, 0);
  ctx.lineTo(-16, 3);
  ctx.lineTo(-14, 0);
  ctx.lineTo(-16, -2);
  ctx.fill();

  // Alas que baten
  const wUp = Math.sin(wingPhase) * 12;

  ctx.beginPath();
  ctx.moveTo(-4, -2);
  ctx.quadraticCurveTo(2, -10 - wUp, 12, -6 - wUp * 0.5);
  ctx.quadraticCurveTo(4, -2, -4, -2);
  ctx.fill();

  ctx.beginPath();
  ctx.moveTo(-4, 2);
  ctx.quadraticCurveTo(2, 10 + wUp * 0.6, 12, 6 + wUp * 0.3);
  ctx.quadraticCurveTo(4, 2, -4, 2);
  ctx.fill();

  ctx.restore();
}

// ── Loop de animación ────────────────────────────
let last = 0;

function loop(ts) {
  const dt = ts - last;
  last = ts;
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // Partículas
  for (let i = 0; i < particles.length; i++) {
    const p = particles[i];
    p.flicker += 0.04;
    p.x += p.vx + Math.sin(p.flicker * 0.7) * 0.12;
    p.y += p.vy;
    p.life -= p.decay;

    if (p.life <= 0 || p.y < -10) {
      particles[i] = spawnParticle(false);
      continue;
    }

    const alpha = p.life * 0.28 * (0.7 + 0.3 * Math.sin(p.flicker));
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(200,158,60,${alpha})`;
    ctx.fill();
  }

  // Cuervos
  for (let i = 0; i < ravens.length; i++) {
    const r = ravens[i];
    r.timer += dt;

    if (!r.active) {
      if (r.timer >= r.delay) { r.active = true; r.timer = 0; }
      continue;
    }

    r.x         += r.dir * r.speed;
    r.y         += Math.sin(r.timer * 0.001) * 0.25;
    r.wingPhase += r.wingSpeed;

    // Fade in/out en los bordes de pantalla
    const prog  = r.dir === 1
      ? (r.x + 80)  / (innerWidth + 160)
      : 1 - (r.x + 80) / (innerWidth + 160);
    r.opacity = Math.min(1, Math.min(prog * 5, (1 - prog) * 5));

    drawRaven(r.x, r.y, r.wingPhase, r.scale, r.dir, r.opacity);

    // Reiniciar al salir de pantalla
    if (r.x < -100 || r.x > innerWidth + 100) {
      ravens[i] = spawnRaven(i);
      ravens[i].delay = rand(2000, 10000);
    }
  }

  requestAnimationFrame(loop);
}

requestAnimationFrame(loop);

// ── Buscador ─────────────────────────────────────
const input = document.getElementById('q');
const btn   = document.getElementById('searchBtn');

function triggerSearch(term) {
  btn.classList.add('rip', 'glow');
  setTimeout(() => btn.classList.remove('rip'),  700);
  setTimeout(() => btn.classList.remove('glow'), 900);

  document.querySelector('.brand').animate(
    [{ transform: 'scale(1)' }, { transform: 'scale(1.018)' }, { transform: 'scale(1)' }],
    { duration: 500, easing: 'ease-out' }
  );

  // Conecta aquí con tu backend
  console.log('[Zenith] →', term);
}

btn.addEventListener('click', () => {
  const t = input.value.trim();
  if (!t) { input.focus(); return; }
  triggerSearch(t);
});

input.addEventListener('keydown', e => {
  if (e.key === 'Enter')  { const t = input.value.trim(); if (t) triggerSearch(t); }
  if (e.key === 'Escape') { input.blur(); }
});

window.addEventListener('load', () => {
  setTimeout(() => input.focus(), 300);
});