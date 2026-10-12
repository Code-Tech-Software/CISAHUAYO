/* Ajustes › Apariencia (templates/ajustes/apariencia.html).

   Cada cambio de tema o de menú lateral se ve al momento y se guarda solo en la cuenta (el botón «Guardar» queda
   para cuando no hay JavaScript). El modo claro/oscuro no va al servidor: es de este dispositivo y lo maneja app.js
   (eventos app:set-theme-mode y app:theme-mode-changed). */
(() => {
  const form = document.querySelector('[data-apariencia]');
  if (!form) return;

  const root = document.documentElement;
  const estado = form.querySelector('[data-guardado]');
  const pie = form.querySelector('[data-guardar]');
  const meta = document.querySelector('meta[name="theme-color"]');
  const modo = form.querySelector('[data-modo]');
  const MOTION_OK = window.matchMedia('(prefers-reduced-motion: no-preference)');

  if (pie) pie.hidden = true;

  const avisar = (texto, tipo = '') => {
    if (!estado) return;
    estado.textContent = texto;
    estado.dataset.estado = tipo;
  };

  /* Cambia los colores con un fundido suave cuando el navegador puede (View Transitions) */
  const pintar = (cambio) => {
    if (document.startViewTransition && MOTION_OK.matches) {
      document.startViewTransition(cambio);
    } else {
      cambio();
    }
  };

  let turno = 0;
  const guardar = async () => {
    const mio = ++turno;
    avisar('Guardando…');
    try {
      const respuesta = await fetch(form.action || window.location.href, {
        method: 'POST',
        body: new FormData(form),
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        credentials: 'same-origin',
      });
      const datos = await respuesta.json().catch(() => ({}));
      if (mio !== turno) return;   // ya hay un cambio más nuevo en camino
      if (!respuesta.ok || !datos.ok) throw new Error(datos.mensaje || '');
      avisar('Guardado', 'ok');
    } catch (error) {
      if (mio !== turno) return;
      avisar(error.message || 'No se pudo guardar: revisa tu conexión e inténtalo de nuevo.', 'error');
      if (pie) pie.hidden = false;
    }
  };

  form.addEventListener('change', (event) => {
    const campo = event.target;
    if (campo.name === 'tema') {
      pintar(() => {
        root.dataset.tema = campo.value;
        if (meta && campo.dataset.color) meta.content = campo.dataset.color;
      });
    } else if (campo.name === 'menu_lateral') {
      pintar(() => {
        if (campo.value === 'color') {
          root.dataset.menu = 'color';
        } else {
          delete root.dataset.menu;
        }
      });
    } else {
      return;   // el modo se queda en este dispositivo
    }
    guardar();
  });

  /* Modo claro / oscuro / automático: solo con JavaScript (lo recuerda el navegador) */
  if (modo) {
    const marcar = (valor) => {
      const opcion = modo.querySelector(`input[name="modo"][value="${valor}"]`);
      if (opcion) opcion.checked = true;
    };
    let actual = 'light';
    try {
      actual = localStorage.getItem('cisahuayo.theme') || 'light';
    } catch (error) {
      /* Sin almacenamiento: se muestra «Claro» */
    }
    marcar(actual);
    modo.hidden = false;
    modo.addEventListener('change', (event) => {
      if (event.target.name !== 'modo') return;
      pintar(() => document.dispatchEvent(new CustomEvent('app:set-theme-mode', { detail: event.target.value })));
    });
    /* Si se cambia con el botón de la luna, aquí también se marca */
    document.addEventListener('app:theme-mode-changed', (event) => marcar(event.detail));
  }
})();
