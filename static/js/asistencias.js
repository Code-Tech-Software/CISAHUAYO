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
  /* Si el profesor lo marcó presente o con retardo en alguna clase (data-pase) y se elige falta aplicándola a las
     materias, se avisa antes de guardar: esas materias también quedarán con falta. */
  const ventana = document.querySelector('[data-asistencia-form]');
  if (ventana) {
    const avisoPase = ventana.querySelector('[data-asistencia-aviso-pase]');
    let pase = '';
    const pintarAviso = () => {
      if (!avisoPase) return;
      const falta = ventana.querySelector('[name="estado"]:checked')?.value === 'FALTA';
      const propagar = ventana.querySelector('[name="propagar"]').checked;
      avisoPase.querySelector('[data-asistencia-pase-materias]').textContent = pase;
      avisoPase.hidden = !(pase && falta && propagar);
    };
    document.addEventListener('click', (event) => {
      const boton = event.target.closest('[data-asistencia-editar]');
      if (!boton) return;
      const { inscripcion, alumno, estado = '', hora = '', observaciones = '' } = boton.dataset;
      pase = boton.dataset.pase || '';
      ventana.querySelector('[name="inscripcion"]').value = inscripcion;
      ventana.querySelector('[data-asistencia-alumno]').textContent = alumno;
      const elegido = ventana.querySelector(`[name="estado"][value="${estado || 'PRESENTE'}"]`);
      if (elegido) elegido.checked = true;
      ventana.querySelector('[name="hora"]').value = hora;
      ventana.querySelector('[name="observaciones"]').value = observaciones;
      ventana.querySelector('[name="propagar"]').checked = true;
      pintarAviso();
    });
    ventana.addEventListener('change', (event) => {
      if (event.target.matches('[name="estado"], [name="propagar"]')) pintarAviso();
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
