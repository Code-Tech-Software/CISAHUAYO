/* CISAHUAYO · asistencias

   Comportamiento de las pantallas de la sección (la pantalla de la entrada tiene su propio script):
   - elegir una fecha envía el formulario de la página;
   - ventana para registrar o corregir la asistencia general de un alumno ([data-asistencia-editar]);
   - ventana para anular una justificación ([data-anular-justificacion]);
   - lista de la clase: contadores en vivo, «Todos presentes» y marca de lo que cambió ([data-roster]).
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

  /* --- Lista de la clase --------------------------------------------------------------------------------------------- */
  const lista = document.querySelector('[data-roster]');
  if (lista) {
    const radios = [...lista.querySelectorAll('input[data-estado]')];
    const conteos = {
      PRESENTE: lista.querySelector('[data-conteo="PRESENTE"]'),
      RETARDO: lista.querySelector('[data-conteo="RETARDO"]'),
      FALTA: lista.querySelector('[data-conteo="FALTA"]'),
    };
    const inicial = new Map(radios.filter((radio) => radio.checked).map((radio) => [radio.name, radio.value]));

    const actualizar = () => {
      const total = { PRESENTE: 0, RETARDO: 0, FALTA: 0 };
      radios.filter((radio) => radio.checked).forEach((radio) => {
        total[radio.value] += 1;
        radio.closest('[data-roster-row]')?.classList.toggle('is-changed', inicial.get(radio.name) !== radio.value);
      });
      Object.entries(conteos).forEach(([estado, nodo]) => {
        if (nodo) nodo.textContent = total[estado];
      });
    };

    lista.addEventListener('change', (event) => {
      if (event.target.matches('input[data-estado]')) actualizar();
    });

    lista.querySelector('[data-todos-presentes]')?.addEventListener('click', () => {
      radios.filter((radio) => radio.value === 'PRESENTE').forEach((radio) => {
        radio.checked = true;
      });
      actualizar();
    });

    /* Evita guardar dos veces con un doble clic */
    lista.addEventListener('submit', () => {
      const boton = lista.querySelector('button[type="submit"]');
      if (boton) boton.disabled = true;
    });

    actualizar();
  }
})();
