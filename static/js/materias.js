/* CISAHUAYO · materias y plan de estudios

   Prepara la ventana de confirmación para quitar una materia de un grado con los datos de la fila que la abrió.
*/
(() => {
  'use strict';

  const form = document.querySelector('[data-quitar-form]');
  if (!form) return;

  document.addEventListener('click', (event) => {
    const opener = event.target.closest('[data-quitar]');
    if (!opener) return;
    form.action = opener.dataset.action;
    form.querySelector('[data-quitar-materia]').textContent = opener.dataset.materia;
    form.querySelector('[data-quitar-grado]').textContent = opener.dataset.grado;
  });
})();
