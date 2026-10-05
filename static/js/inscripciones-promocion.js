/* CISAHUAYO · reinscripción en bloque

   Mientras se elige el grado de destino de cada grado, resume cuántos alumnos se reinscribirán,
   cuántos egresarán y cuántos quedan sin cambios. El servidor recalcula todo al confirmar.
*/
(() => {
  'use strict';

  const form = document.querySelector('[data-promocion]');
  if (!form) return;

  const rows = [...form.querySelectorAll('[data-promo-row]')];
  const total = (name) => form.querySelector(`[data-promo-total="${name}"]`);
  const submit = form.querySelector('[data-promo-submit]');
  const label = form.querySelector('[data-promo-submit-label]');

  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  const update = () => {
    const sums = { reinscribir: 0, egresar: 0, omitir: 0 };
    rows.forEach((row) => {
      const value = row.querySelector('[data-promo-select]').value;
      const kind = value === 'omitir' ? 'omitir' : value === 'egresar' ? 'egresar' : 'reinscribir';
      sums[kind] += Number(row.dataset.cantidad);
    });
    Object.entries(sums).forEach(([name, value]) => { total(name).textContent = value; });

    const parts = [];
    if (sums.reinscribir) parts.push(`Reinscribir a ${plural(sums.reinscribir, 'alumno', 'alumnos')}`);
    if (sums.egresar) parts.push(`${parts.length ? 'egresar' : 'Egresar'} a ${plural(sums.egresar, 'alumno', 'alumnos')}`);
    label.textContent = parts.join(' y ') || 'Nada que reinscribir';
    submit.disabled = !parts.length;
  };

  form.addEventListener('change', (event) => {
    if (event.target.matches('[data-promo-select]')) update();
  });

  form.addEventListener('submit', () => { submit.disabled = true; }); /* evita enviarlo dos veces */
  update();
})();
