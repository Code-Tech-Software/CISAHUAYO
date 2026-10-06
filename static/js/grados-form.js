/* CISAHUAYO · formulario de grados

   Propone la equivalencia habitual en la continuidad escolar al elegir nivel y número: un número (primaria 1–6,
   secundaria 7–9, preparatoria 10 en adelante) o un código con letra (K1, K2, K3 en preescolar). Solo propone: si la
   persona ya escribió otra, no se la cambia. El servidor aplica la misma regla y valida que no se repita.
*/
(() => {
  'use strict';

  const equivalencia = document.querySelector('input[name="equivalencia"][data-bases]');
  if (!equivalencia) return;

  const nivel = document.querySelector('select[name="nivel"]');
  const numero = document.querySelector('input[name="numero"]');
  if (!nivel || !numero) return;

  const bases = JSON.parse(equivalencia.dataset.bases);
  const prefijos = JSON.parse(equivalencia.dataset.prefijos || '{}');
  const sugerencia = () => {
    const grado = Number(numero.value);
    if (!grado) return '';
    if (prefijos[nivel.value] !== undefined) return `${prefijos[nivel.value]}${grado}`;
    return bases[nivel.value] === undefined ? '' : String(bases[nivel.value] + grado);
  };

  /* Se actualiza mientras el campo siga vacío o con la última propuesta (nunca pisa lo que la persona escribió) */
  let ultima = equivalencia.value === sugerencia() ? equivalencia.value : null;
  const proponer = () => {
    if (equivalencia.value !== '' && equivalencia.value !== ultima) return;
    ultima = sugerencia();
    equivalencia.value = ultima;
  };

  nivel.addEventListener('change', proponer);
  numero.addEventListener('input', proponer);
  if (!equivalencia.value) proponer();
})();
