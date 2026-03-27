// ═══════════════════════════════════════════════
//  ZENITH — app.js
//  Canvas: partículas de polvo + cuervos voladores
//  Buscador: animaciones de interacción + API
// ═══════════════════════════════════════════════

const API_URL = 'http://127.0.0.1:8000';
const PAGE_SIZE = 5;

// ── Canvas ──────────────────────────────────────
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');

function resize() {
  canvas.width = innerWidth;
  canvas.height = innerHeight;
}
resize();
window.addEventListener('resize', resize);

// ── Utilidades ──────────────────────────────────
function lerp(a, b, t) { return a + (b - a) * t; }
function rand(min, max) { return Math.random() * (max - min) + min; }

function escapeHtml(str) {
  return String(str ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

// ── Partículas de polvo/ceniza ───────────────────
const PARTICLE_COUNT = 55;
const particles = Array.from({ length: PARTICLE_COUNT }, () => spawnParticle(true));

function spawnParticle(randomY) {
  return {
    x: rand(0, innerWidth),
    y: randomY ? rand(0, innerHeight) : innerHeight + 10,
    r: rand(0.3, 1.7),
    vx: rand(-0.15, 0.15),
    vy: -(rand(0.1, 0.5)),
    life: 1,
    decay: rand(0.0005, 0.002),
    flicker: rand(0, Math.PI * 2),
  };
}

// ── Cuervos ─────────────────────────────────────
const RAVEN_COUNT = 3;
const ravens = Array.from({ length: RAVEN_COUNT }, (_, i) => spawnRaven(i));

function spawnRaven(i) {
  const fromLeft = Math.random() > 0.5;
  return {
    x: fromLeft ? -80 : innerWidth + 80,
    y: rand(innerHeight * 0.05, innerHeight * 0.38),
    dir: fromLeft ? 1 : -1,
    speed: rand(0.35, 0.95),
    wingPhase: rand(0, Math.PI * 2),
    wingSpeed: rand(0.04, 0.1),
    scale: rand(0.6, 1.1),
    opacity: 0,
    delay: i * 7000 + rand(1000, 5000),
    active: false,
    timer: 0,
  };
}

function drawRaven(x, y, wingPhase, scale, dir, opacity) {
  if (opacity <= 0) return;

  ctx.save();
  ctx.translate(x, y);
  ctx.scale(dir * scale, scale);
  ctx.globalAlpha = opacity * 0.22;
  ctx.fillStyle = '#c8922a';

  ctx.beginPath();
  ctx.ellipse(0, 0, 10, 5, 0, 0, Math.PI * 2);
  ctx.fill();

  ctx.beginPath();
  ctx.ellipse(11, -3, 5, 4, -0.3, 0, Math.PI * 2);
  ctx.fill();

  ctx.beginPath();
  ctx.moveTo(15, -3);
  ctx.lineTo(19, -2);
  ctx.lineTo(15, -1);
  ctx.fill();

  ctx.beginPath();
  ctx.moveTo(-9, 0);
  ctx.lineTo(-16, 3);
  ctx.lineTo(-14, 0);
  ctx.lineTo(-16, -2);
  ctx.fill();

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

  for (let i = 0; i < ravens.length; i++) {
    const r = ravens[i];
    r.timer += dt;

    if (!r.active) {
      if (r.timer >= r.delay) {
        r.active = true;
        r.timer = 0;
      }
      continue;
    }

    r.x += r.dir * r.speed;
    r.y += Math.sin(r.timer * 0.001) * 0.25;
    r.wingPhase += r.wingSpeed;

    const prog = r.dir === 1
      ? (r.x + 80) / (innerWidth + 160)
      : 1 - (r.x + 80) / (innerWidth + 160);

    r.opacity = Math.min(1, Math.min(prog * 5, (1 - prog) * 5));

    drawRaven(r.x, r.y, r.wingPhase, r.scale, r.dir, r.opacity);

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
const btn = document.getElementById('searchBtn');
const resultsEl = document.getElementById('results');
const statusEl = document.getElementById('status');
const suggestionEl = document.getElementById('suggestion');
const paginationEl = document.getElementById('pagination');

let currentQuery = '';
let currentPage = 1;
let searchSeq = 0;

function pulseBrand() {
  const brand = document.querySelector('.brand');
  if (!brand || typeof brand.animate !== 'function') return;

  brand.animate(
    [{ transform: 'scale(1)' }, { transform: 'scale(1.018)' }, { transform: 'scale(1)' }],
    { duration: 500, easing: 'ease-out' }
  );
}

function setLoadingState(message) {
  if (statusEl) statusEl.textContent = message;
  if (resultsEl) resultsEl.innerHTML = '';
  if (suggestionEl) {
    suggestionEl.hidden = true;
    suggestionEl.innerHTML = '';
  }
  if (paginationEl) {
    paginationEl.hidden = true;
    paginationEl.innerHTML = '';
  }
}

function normalizePdfUrl(url) {
  if (!url) return '#';
  if (url.startsWith('http://') || url.startsWith('https://')) return url;
  return `${API_URL}${url.startsWith('/') ? '' : '/'}${url}`;
}

function renderSuggestion(suggestion, originalQuery) {
  if (!suggestionEl) return;

  const cleanSuggestion = String(suggestion || '').trim();
  const cleanOriginal = String(originalQuery || '').trim();

  if (!cleanSuggestion || cleanSuggestion.toLowerCase() === cleanOriginal.toLowerCase()) {
    suggestionEl.hidden = true;
    suggestionEl.innerHTML = '';
    return;
  }

  suggestionEl.hidden = false;
  suggestionEl.innerHTML = `
    ¿Did you mean:
    <button type="button" class="suggestion-btn">${escapeHtml(cleanSuggestion)}</button>?
  `;

  const suggestionBtn = suggestionEl.querySelector('button');
  if (suggestionBtn) {
    suggestionBtn.addEventListener('click', () => {
      input.value = cleanSuggestion;
      triggerSearch(cleanSuggestion, 1);
    });
  }
}

function renderPagination(page, hasMore) {
  if (!paginationEl) return;

  const hasPrev = page > 1;

  if (!hasPrev && !hasMore) {
    paginationEl.hidden = true;
    paginationEl.innerHTML = '';
    return;
  }

  paginationEl.hidden = false;
  paginationEl.innerHTML = `
    ${hasPrev ? '<button type="button" class="page-btn" data-dir="prev">Former</button>' : ''}
    <span class="pagination-info">Página ${page}</span>
    ${hasMore ? '<button type="button" class="page-btn" data-dir="next">Following</button>' : ''}
  `;

  const prevBtn = paginationEl.querySelector('[data-dir="prev"]');
  const nextBtn = paginationEl.querySelector('[data-dir="next"]');

  if (prevBtn) {
    prevBtn.addEventListener('click', () => {
      triggerSearch(currentQuery, page - 1);
    });
  }

  if (nextBtn) {
    nextBtn.addEventListener('click', () => {
      triggerSearch(currentQuery, page + 1);
    });
  }
}

function renderResults(payload, queryFallback) {
  const query = payload?.query || queryFallback || '';
  const results = Array.isArray(payload?.results) ? payload.results : [];

  if (!resultsEl) return;

  if (!results.length) {
    resultsEl.innerHTML = `<div class="empty-state">No results found for <strong>${escapeHtml(query)}</strong>.</div>`;
    return;
  }

  resultsEl.innerHTML = results.map((r, idx) => {
    const title = r.file_name || r.relative_path || `Documento ${idx + 1}`;
    const url = normalizePdfUrl(r.pdf_url || r.relative_path || '#');

    return `
      <article class="result-card">
        <a class="result-title" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">
          ${escapeHtml(title)}
        </a>
      </article>
    `;
  }).join('');
}

async function triggerSearch(term, page = 1) {
  btn.classList.add('rip', 'glow');
  setTimeout(() => btn.classList.remove('rip'), 700);
  setTimeout(() => btn.classList.remove('glow'), 900);

  pulseBrand();

  const query = String(term || '').trim();
  if (!query) {
    input.focus();
    return;
  }

  currentQuery = query;
  currentPage = page;
  const requestId = ++searchSeq;

  setLoadingState(`Buscando "${query}"...`);

  try {
    const response = await fetch(`${API_URL}/search`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        query,
        page,
        page_size: PAGE_SIZE,
      }),
    });

    if (!response.ok) {
      const detail = await response.text().catch(() => '');
      throw new Error(`HTTP ${response.status} ${detail}`);
    }

    const data = await response.json();

    if (requestId !== searchSeq) return;

    if (statusEl) {
      statusEl.textContent = data.results?.length
        ? `Resultados para "${data.query}" — página ${data.page}`
        : `Sin resultados para "${data.query}"`;
    }

    renderSuggestion(data.did_you_mean, query);
    renderResults(data, query);
    renderPagination(data.page, !!data.has_more);
  } catch (error) {
    console.error('[Zenith] Error en búsqueda:', error);

    if (statusEl) {
      statusEl.textContent = 'Error conectando con la API de Zenith.';
    }

    if (resultsEl) {
      resultsEl.innerHTML = `
        <div class="empty-state">
          No se pudo completar la búsqueda. Revisa que la API esté corriendo en
          <strong>${API_URL}</strong>.
        </div>
      `;
    }

    if (suggestionEl) {
      suggestionEl.hidden = true;
      suggestionEl.innerHTML = '';
    }

    if (paginationEl) {
      paginationEl.hidden = true;
      paginationEl.innerHTML = '';
    }
  }
}

btn.addEventListener('click', () => {
  const t = input.value.trim();
  if (!t) {
    input.focus();
    return;
  }
  triggerSearch(t, 1);
});

input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    const t = input.value.trim();
    if (t) triggerSearch(t, 1);
  }
  if (e.key === 'Escape') {
    input.blur();
  }
});

window.addEventListener('load', () => {
  setTimeout(() => input.focus(), 300);
});