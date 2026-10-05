/* CISAHUAYO · horario de un grado

   Prepara la ventana de confirmación para quitar un bloque con los datos del bloque que la abrió.
*/
(() => {
  'use strict';

  const form = document.querySelector('[data-eliminar-form]');
  if (!form) return;

  document.addEventListener('click', (event) => {
    const opener = event.target.closest('[data-eliminar]');
    if (!opener) return;
    form.action = opener.dataset.action;
    form.querySelector('[data-eliminar-materia]').textContent = opener.dataset.materia;
    form.querySelector('[data-eliminar-detalle]').textContent = opener.dataset.detalle.toLowerCase();
  });
})();
