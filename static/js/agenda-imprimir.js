/* CISAHUAYO · el mes de la agenda para imprimir (templates/agenda/imprimir.html): al abrirse pide imprimir (desde el
   diálogo también se guarda en PDF) y el botón lo vuelve a pedir. */
(() => {
  'use strict';

  document.querySelector('[data-imprimir]')?.addEventListener('click', () => window.print());
  window.addEventListener('load', () => window.setTimeout(() => window.print(), 300), { once: true });
})();
