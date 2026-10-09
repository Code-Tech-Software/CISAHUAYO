/* CISAHUAYO · periodos de evaluación

   Prepara la ventana para eliminar un periodo con los datos del botón que la abrió ([data-eliminar-periodo]).
*/
(() => {
  'use strict';

  const form = document.querySelector('[data-eliminar-periodo-form]');
  if (!form) return;

  document.addEventListener('click', (event) => {
    const opener = event.target.closest('[data-eliminar-periodo]');
    if (!opener) return;
    form.action = opener.dataset.action;
    form.querySelector('[data-eliminar-periodo-nombre]').textContent = opener.dataset.nombre;
  });
})();
