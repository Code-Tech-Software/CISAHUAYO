/* CISAHUAYO · agregar horario o recreo

   Cada día marcado muestra su propia hora de inicio y de fin (una fila [data-horario-dia] por día de la semana). Al
   desmarcar un día su fila se quita de la vista y sus campos se desactivan, así que no se envían ni se guardan; si se
   vuelve a marcar, aparece con lo que ya tenía. Con dos o más días aparece «Usar la hora del <día> en los demás días»,
   que copia la del primero (para cuando sí es la misma). En el recreo, [data-marcar-grados] marca o desmarca todos los
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
      (inicio.value ? fin : inicio).focus();
      return;
    }
    demas.forEach((fila) => {
      const [otroInicio, otroFin] = horasDe(fila);
      otroInicio.value = inicio.value;
      otroFin.value = fin.value;
    });
    form.dispatchEvent(new Event('input', { bubbles: true }));   /* para que la ventana sepa que hubo cambios */
  });

  casillas.forEach((casilla) => casilla.addEventListener('change', actualizar));
  actualizar();

  /* Recreo: marcar o desmarcar todos los grupos de una vez */
  const marcarGrados = form.querySelector('[data-marcar-grados]');
  if (marcarGrados) {
    const grados = [...form.querySelectorAll('input[name="grados"]')];
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
