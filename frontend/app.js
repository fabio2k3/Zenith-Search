// Minimal JS: animaciones y manejo Enter/click (sin envío a backend)
(() => {
  const input = document.getElementById('q');
  const btn = document.getElementById('searchBtn');
  const btnRipple = btn.querySelector('.ripple');

  // Ejecuta animación visual y devuelve el término buscado (para integrarlo luego)
  function triggerSearchVisual(term) {
    // ripple
    btn.classList.add('ripple-animate','searching');
    // eliminar clases después de la animación
    setTimeout(() => {
      btn.classList.remove('ripple-animate');
    }, 700);
    setTimeout(() => btn.classList.remove('searching'), 900);

    // ligero "eco" en la marca (pequeña escala)
    const brand = document.querySelector('.brand');
    brand.animate([{ transform: 'scale(1)' }, { transform: 'scale(1.02)' }, { transform: 'scale(1)' }], {
      duration: 520, easing: 'ease-out'
    });

    // Por ahora solo mostramos en consola — reemplaza esto para conectar al backend.
    console.log('[Zenith] búsqueda iniciada →', term);
  }

  btn.addEventListener('click', () => {
    const term = input.value.trim();
    if (!term) {
      input.focus();
      return;
    }
    triggerSearchVisual(term);
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const term = input.value.trim();
      if (!term) return;
      triggerSearchVisual(term);
    } else if (e.key === 'Escape') {
      input.blur();
    }
  });

  // foco inicial opcional: coloca el cursor en la barra al cargar
  window.addEventListener('load', () => {
    // pequeña demora para que el efecto se sienta natural
    setTimeout(() => input.focus(), 260);
  });
})();