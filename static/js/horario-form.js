/* CISAHUAYO · agregar horario o receso, y «También se da otros días» al editar un bloque

   Cada día marcado muestra su propia hora de inicio y de fin (una fila [data-horario-dia] por día de la semana). Al
   desmarcar un día su fila se quita de la vista y sus campos se desactivan, así que no se envían ni se guardan; si se
   vuelve a marcar, aparece con lo que ya tenía. Con dos o más días aparece «Usar la hora del <día> en los demás días»,
   que copia la del primero (para cuando sí es la misma). En el receso, [data-marcar-grados] marca o desmarca todos los
   grupos. El servidor vuelve a revisar todo al guardar.
*/
(() => {
  'use strict';

  const contenedor = document.querySelector('[data-horario-dias]');
  if (!contenedor) return;
  const form = contenedor.closest('form');
  const vacio = contenedor.querySelector('[data-horario-vacio]');
  const copiar = contenedor.querySelector('[data-misma-hora]');
  const copiarTexto = contenedor.querySelector('[data-misma-hora-texto]');
  const filas = [...contenedor.querySelectorAll('[data-horario-dia]')];
  const casillas = [...form.querySelectorAll('input[name="dias"]')];

  const casillaDe = (fila) => casillas.find((casilla) => casilla.value === fila.dataset.horarioDia);
  const nombreDe = (fila) => fila.querySelector('legend')?.textContent.trim().toLowerCase() ?? '';
  const horasDe = (fila) => [...fila.querySelectorAll('input[type="time"]')];

  const visibles = () => filas.filter((fila) => !fila.hidden);

  const actualizar = () => {
    filas.forEach((fila) => {
      const marcada = Boolean(casillaDe(fila)?.checked);
      fila.hidden = !marcada;
      horasDe(fila).forEach((campo) => { campo.disabled = !marcada; });
    });
    const dias = visibles();
    if (vacio) vacio.hidden = dias.length > 0;
    if (copiar) {
      copiar.hidden = dias.length < 2;
      if (dias.length >= 2 && copiarTexto) copiarTexto.textContent = `Usar la hora del ${nombreDe(dias[0])} en los demás días`;
    }
  };

  copiar?.addEventListener('click', () => {
    const [primero, ...demas] = visibles();
    if (!primero) return;
    const [inicio, fin] = horasDe(primero);
    if (!inicio.value || !fin.value) {
      (inicio.value ? fin : inicio).focus();   /* con static/js/hora.js el foco pasa a su campo visible */
      return;
    }
    demas.forEach((fila) => {
      const [otroInicio, otroFin] = horasDe(fila);
      otroInicio.value = inicio.value;
      otroFin.value = fin.value;
      /* Avisa de cada cambio: el campo de hora lo muestra y la ventana sabe que hubo cambios */
      [otroInicio, otroFin].forEach((campo) => campo.dispatchEvent(new Event('change', { bubbles: true })));
    });
  });

  casillas.forEach((casilla) => casilla.addEventListener('change', actualizar));

  /* Editar un bloque: «También se da otros días» no ofrece el día del propio bloque (moverlo es cambiar el día de
     arriba) y, al marcar otro día, le propone la hora del bloque para no escribirla dos veces. */
  const diaDelBloque = form.querySelector('select[name="dia_semana"]');
  if (diaDelBloque) {
    const [horaInicio, horaFin] = ['hora_inicio', 'hora_fin'].map((nombre) => form.querySelector(`input[name="${nombre}"]`));
    const bloquearDia = () => {
      casillas.forEach((casilla) => {
        const mismo = casilla.value === diaDelBloque.value;
        if (mismo) casilla.checked = false;
        casilla.disabled = mismo;
        casilla.closest('.choice')?.setAttribute('title', mismo ? 'Es el día de este bloque' : '');
      });
      actualizar();
    };
    casillas.forEach((casilla) => casilla.addEventListener('change', () => {
      if (!casilla.checked) return;
      const fila = filas.find((f) => f.dataset.horarioDia === casilla.value);
      const [inicio, fin] = fila ? horasDe(fila) : [];
      if (!inicio || inicio.value || fin.value || !horaInicio?.value || !horaFin?.value) return;
      inicio.value = horaInicio.value;
      fin.value = horaFin.value;
      [inicio, fin].forEach((campo) => campo.dispatchEvent(new Event('change', { bubbles: true })));
    }));
    diaDelBloque.addEventListener('change', bloquearDia);
    bloquearDia();
  }

  actualizar();

  /* Receso: marcar o desmarcar todos los grupos de una vez */
  const marcarGrados = form.querySelector('[data-marcar-grados]');
  if (marcarGrados) {
    const grados = [...form.querySelectorAll('input[name="grupos"]')];
    const rotular = () => {
      marcarGrados.textContent = grados.length && grados.every((grado) => grado.checked) ? 'Desmarcar todos' : 'Marcar todos';
    };
    marcarGrados.addEventListener('click', () => {
      const marcar = !grados.every((grado) => grado.checked);
      grados.forEach((grado) => { grado.checked = marcar; });
      rotular();
      form.dispatchEvent(new Event('change', { bubbles: true }));   /* para que la ventana sepa que hubo cambios */
    });
    grados.forEach((grado) => grado.addEventListener('change', rotular));
    rotular();
  }
})();
