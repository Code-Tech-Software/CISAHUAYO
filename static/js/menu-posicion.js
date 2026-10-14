/* CISAHUAYO · posición del menú lateral

   El menú se desplaza dentro de su propia caja (.nav) y cada opción abre una página nueva: sin esto, en cada página
   volvía al principio (pedido del 2026-10-14). Se carga sin `defer` justo después del menú (partials/sidebar.html),
   así aparece ya en la posición en que se dejó, sin saltar. Si la opción activa quedara fuera de la vista, se muestra.
*/
(() => {
  'use strict';

  const nav = document.querySelector('[data-sidebar] .nav');
  if (!nav) return;
  const CLAVE = 'cisahuayo.sidebar.desplazamiento';

  try {
    const guardado = sessionStorage.getItem(CLAVE);
    if (guardado !== null) nav.scrollTop = Number(guardado) || 0;
  } catch (error) {
    /* Sin almacenamiento: el menú empieza arriba, como siempre */
  }

  const activo = nav.querySelector('.nav__link[aria-current="page"]');
  if (activo) {
    const caja = nav.getBoundingClientRect();
    const opcion = activo.getBoundingClientRect();
    const margen = 16;
    if (opcion.top < caja.top) nav.scrollTop -= caja.top - opcion.top + margen;
    else if (opcion.bottom > caja.bottom) nav.scrollTop += opcion.bottom - caja.bottom + margen;
  }

  const guardar = () => {
    try {
      sessionStorage.setItem(CLAVE, String(Math.round(nav.scrollTop)));
    } catch (error) {
      /* Sin almacenamiento */
    }
  };
  nav.addEventListener('click', (evento) => {
    if (evento.target.closest('a[href]')) guardar();
  });
  window.addEventListener('pagehide', guardar);
})();
