/* CISAHUAYO · una hoja para imprimir con opciones arriba (templates/alumnos/lista_hoja.html): el botón abre el diálogo de
   impresión (desde ahí también se guarda en PDF). No imprime sola al abrirse: primero se eligen las opciones. */
(() => {
  'use strict';

  document.querySelector('[data-imprimir]')?.addEventListener('click', () => window.print());
})();
