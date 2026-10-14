/* CISAHUAYO · asistencias

   Comportamiento de las pantallas de la sección (la pantalla de la entrada tiene su propio script):
   - elegir una fecha envía el formulario de la página;
   - ventana para registrar o corregir la asistencia general de un alumno ([data-asistencia-editar]);
   - ventana para anular una justificación ([data-anular-justificacion]).
*/
(() => {
  'use strict';

  /* --- Fechas: al elegir una, se envía el formulario al que pertenece ---------------------------------------- */
  document.addEventListener('change', (event) => {
    const campo = event.target;
    if (!campo.matches('input[type="date"]') || !campo.value) return;
    const formulario = campo.form;
    if (formulario && (campo.hasAttribute('data-fecha-input') || formulario.hasAttribute('data-autosubmit'))) {
      formulario.requestSubmit();
    }
  });

  /* --- Corregir la asistencia general de un alumno ------------------------------------------------------------ */
  const ventana = document.querySelector('[data-asistencia-form]');
  if (ventana) {
    document.addEventListener('click', (event) => {
      const boton = event.target.closest('[data-asistencia-editar]');
      if (!boton) return;
      const { inscripcion, alumno, estado = '', hora = '', observaciones = '' } = boton.dataset;
      ventana.querySelector('[name="inscripcion"]').value = inscripcion;
      ventana.querySelector('[data-asistencia-alumno]').textContent = alumno;
      const elegido = ventana.querySelector(`[name="estado"][value="${estado || 'PRESENTE'}"]`);
      if (elegido) elegido.checked = true;
      ventana.querySelector('[name="hora"]').value = hora;
      ventana.querySelector('[name="observaciones"]').value = observaciones;
      ventana.querySelector('[name="propagar"]').checked = true;
    });
  }

  /* --- Anular una justificación ----------------------------------------------------------------------------------- */
  const anular = document.querySelector('[data-anular-form]');
  if (anular) {
    document.addEventListener('click', (event) => {
      const boton = event.target.closest('[data-anular-justificacion]');
      if (!boton) return;
      anular.action = boton.dataset.action;
      anular.querySelector('[data-anular-alumno]').textContent = boton.dataset.alumno;
      anular.querySelector('[data-anular-dia]').textContent = boton.dataset.dia;
    });
  }
})();
