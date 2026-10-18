/* CISAHUAYO · Registrar o editar un evento de la agenda (templates/agenda/evento_form.html)

   Con «Todo el día» marcado se ocultan las horas; al desmarcarlo aparecen y se lleva el foco a la hora de inicio.
   Es solo ayuda: el servidor vuelve a revisar todo (Agenda/forms.py). Este archivo se vuelve a ejecutar cada vez que el
   formulario se abre en una ventana (modal-form.js): cada formulario se prepara una sola vez.
*/
(() => {
  'use strict';

  document.querySelectorAll('[data-agenda-formulario]').forEach((form) => {
    if (form.dataset.agendaListo) return;
    form.dataset.agendaListo = '1';

    const todoElDia = form.querySelector('[data-agenda-todo-el-dia]');
    const horas = form.querySelector('[data-agenda-horas]');
    if (!todoElDia || !horas) return;

    const revisar = (enfocar = false) => {
      horas.hidden = todoElDia.checked;
      if (enfocar && !todoElDia.checked) horas.querySelector('input')?.focus();
    };

    todoElDia.addEventListener('change', () => revisar(true));
    revisar();
  });
})();
