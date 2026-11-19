/* CISAHUAYO · agregar horario o receso, y «También se da» al editar un bloque

   Cada día marcado muestra su propia hora de inicio y de fin (una fila [data-horario-dia] por día de la semana). Al
   desmarcar un día su fila se quita de la vista y sus campos se desactivan, así que no se envían ni se guardan; si se
   vuelve a marcar, aparece con lo que ya tenía. Con dos o más días aparece «Usar la hora del <día> en los demás días»,
   que copia la primera hora del primero (para cuando sí es la misma). En el receso, [data-marcar-grados] marca o
   desmarca todos los grupos. El servidor vuelve a revisar todo al guardar.

   Materias (2026-11-19): un día puede tener otra hora, para darla otra vez más tarde (primera y cuarta hora). «Otra
   hora el lunes» [data-otra-hora] muestra la siguiente [data-horario-tramo] escondida; «Quitar» [data-quitar-hora] la
   vacía y la esconde. Las escondidas van desactivadas: no se envían.
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
  const horasDe = (elemento) => [...elemento.querySelectorAll('input[type="time"]')];
  const tramosDe = (fila) => [...fila.querySelectorAll('[data-horario-tramo]')];
  /* La primera hora de cada día (la que copia «Usar la hora del <día>…»); si el día no tiene tramos, todas sus horas */
  const primeraHoraDe = (fila) => horasDe(tramosDe(fila)[0] ?? fila);
  const avisar = (campos) => campos.forEach((campo) => campo.dispatchEvent(new Event('change', { bubbles: true })));

  const visibles = () => filas.filter((fila) => !fila.hidden);

  const actualizar = () => {
    filas.forEach((fila) => {
      const marcada = Boolean(casillaDe(fila)?.checked);
      fila.hidden = !marcada;
      const tramos = tramosDe(fila);
      if (tramos.length) {
        tramos.forEach((tramo) => horasDe(tramo).forEach((campo) => { campo.disabled = !marcada || tramo.hidden; }));
        const mas = fila.querySelector('[data-otra-hora]');
        if (mas) mas.hidden = tramos.every((tramo) => !tramo.hidden);
      } else {
        horasDe(fila).forEach((campo) => { campo.disabled = !marcada; });
      }
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
    const [inicio, fin] = primeraHoraDe(primero);
    if (!inicio.value || !fin.value) {
      (inicio.value ? fin : inicio).focus();   /* con static/js/hora.js el foco pasa a su campo visible */
      return;
    }
    demas.forEach((fila) => {
      const [otroInicio, otroFin] = primeraHoraDe(fila);
      otroInicio.value = inicio.value;
      otroFin.value = fin.value;
      /* Avisa de cada cambio: el campo de hora lo muestra y la ventana sabe que hubo cambios */
      avisar([otroInicio, otroFin]);
    });
  });

  /* Otra hora el mismo día: muestra la siguiente escondida y pone el foco en su hora de inicio */
  contenedor.addEventListener('click', (evento) => {
    const mas = evento.target.closest('[data-otra-hora]');
    if (mas) {
      const fila = mas.closest('[data-horario-dia]');
      const siguiente = tramosDe(fila).find((tramo) => tramo.hidden);
      if (!siguiente) return;
      siguiente.hidden = false;
      actualizar();
      horasDe(siguiente)[0]?.focus();
      return;
    }
    const quitar = evento.target.closest('[data-quitar-hora]');
    if (quitar) {
      const tramo = quitar.closest('[data-horario-tramo]');
      const campos = horasDe(tramo);
      campos.forEach((campo) => { campo.value = ''; });
      avisar(campos);
      tramo.hidden = true;
      tramo.querySelectorAll('.field__error').forEach((error) => error.remove());
      tramo.querySelectorAll('.is-invalid').forEach((campo) => campo.classList.remove('is-invalid'));
      actualizar();
      quitar.closest('[data-horario-dia]').querySelector('[data-otra-hora]')?.focus();
    }
  });

  casillas.forEach((casilla) => casilla.addEventListener('change', actualizar));

  /* Editar un bloque: al marcar otro día en «También se da», se propone la hora del bloque para no escribirla dos
     veces. En el mismo día del bloque no (chocaría con él): ahí va otra hora, que se escribe. */
  const diaDelBloque = form.querySelector('select[name="dia_semana"]');
  if (diaDelBloque) {
    const [horaInicio, horaFin] = ['hora_inicio', 'hora_fin'].map((nombre) => form.querySelector(`input[name="${nombre}"]`));
    casillas.forEach((casilla) => casilla.addEventListener('change', () => {
      if (!casilla.checked || casilla.value === diaDelBloque.value) return;
      const fila = filas.find((f) => f.dataset.horarioDia === casilla.value);
      const [inicio, fin] = fila ? primeraHoraDe(fila) : [];
      if (!inicio || inicio.value || fin.value || !horaInicio?.value || !horaFin?.value) return;
      inicio.value = horaInicio.value;
      fin.value = horaFin.value;
      avisar([inicio, fin]);
    }));
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
