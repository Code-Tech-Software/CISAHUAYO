/* CISAHUAYO · formulario de inscripción

   Elegir al alumno con la búsqueda en vivo (alumnos:buscar). El servidor vuelve a validar todo.
*/
(() => {
  'use strict';

  const form = document.querySelector('[data-inscripcion-form]');
  if (!form?.dataset.searchUrl) return;

  const { liveSearch, alumnoResult } = window.CISAHUAYO;
  const qs = (selector) => form.querySelector(selector);

  const alumnoInput = qs('input[name="alumno"]');
  const searchBlock = qs('[data-picker-search]');
  const searchInput = qs('[data-picker-input]');
  const results = qs('[data-picker-results]');
  const chosen = qs('[data-picker-chosen]');
  const chosenAvatar = qs('[data-picker-avatar]');
  const chosenName = qs('[data-picker-name]');
  const missing = qs('[data-picker-error]');

  const choose = (alumno) => {
    alumnoInput.value = alumno.id;
    chosenName.textContent = alumno.nombre;
    chosenAvatar.textContent = alumno.iniciales;
    chosenAvatar.className = `avatar avatar--tone-${(Number(alumno.id) % 6) + 1}`;
    chosen.hidden = false;
    searchBlock.hidden = true;
    missing.hidden = true;
  };

  const clear = () => {
    alumnoInput.value = '';
    chosen.hidden = true;
    searchBlock.hidden = false;
    searchInput.value = '';
  };

  liveSearch({
    input: searchInput,
    box: results,
    url: form.dataset.searchUrl,
    emptyText: 'No hay estudiantes con ese dato.',
    render: alumnoResult,
    onPick(alumno) {
      choose(alumno);
      qs('[name="ciclo"]')?.focus();
    },
  });

  qs('[data-picker-change]').addEventListener('click', () => {
    clear();
    searchInput.focus();
  });

  form.addEventListener('submit', (event) => {
    if (!alumnoInput.value) {
      event.preventDefault();
      missing.hidden = false;
      searchInput.focus();
      return;
    }
    const button = qs('button[type="submit"]');
    button.disabled = true; /* evita inscribir dos veces con un doble clic */
  });

  if (!alumnoInput.value) searchInput.focus();
})();
