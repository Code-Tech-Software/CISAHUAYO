/* CISAHUAYO · listado de inscripciones

   Prepara la ventana de confirmación de baja con los datos de la fila que la abrió.
*/
(() => {
  'use strict';

  const form = document.querySelector('[data-baja-form]');
  if (!form) return;

  document.addEventListener('click', (event) => {
    const opener = event.target.closest('[data-baja]');
    if (!opener) return;
    form.action = opener.dataset.action;
    form.querySelector('[data-baja-alumno]').textContent = opener.dataset.alumno;
    form.querySelector('[data-baja-detalle]').textContent = opener.dataset.detalle;
  });
})();
