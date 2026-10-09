/* CISAHUAYO · horario de un grado

   Prepara la ventana de confirmación para quitar un bloque (de una materia o un recreo) con los datos del botón que la
   abrió: cada botón [data-eliminar] abre su ventana (data-modal-open) y llena el formulario [data-eliminar-form] de ella.
*/
(() => {
  'use strict';

  document.addEventListener('click', (event) => {
    const opener = event.target.closest('[data-eliminar]');
    if (!opener) return;
    const form = document.getElementById(opener.dataset.modalOpen)?.querySelector('[data-eliminar-form]');
    if (!form) return;
    form.action = opener.dataset.action;
    form.querySelector('[data-eliminar-materia]').textContent = opener.dataset.materia;
    form.querySelector('[data-eliminar-detalle]').textContent = opener.dataset.detalle.toLowerCase();
  });
})();
