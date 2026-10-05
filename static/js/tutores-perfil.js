/* CISAHUAYO · perfil del tutor

   Maneja las ventanas de vínculo: elegir un alumno con la búsqueda en vivo (alta del vínculo),
   precargar los datos al editarlo y confirmar la desvinculación.
*/
(() => {
  'use strict';

  const { liveSearch, alumnoResult } = window.CISAHUAYO;
  const qs = (selector, scope = document) => scope.querySelector(selector);
  const qsa = (selector, scope = document) => [...scope.querySelectorAll(selector)];

  /* ===================================================== Vincular o editar un vínculo */
  const modal = qs('[data-link-modal]');
  if (modal) {
    const form = qs('form', modal);
    const alumnoInput = qs('input[name="alumno"]', form);
    const searchBlock = qs('[data-link-search]', form);
    const searchInput = qs('[data-link-search-input]', form);
    const results = qs('[data-link-results]', form);
    const chosen = qs('[data-link-chosen]', form);
    const chosenAvatar = qs('[data-link-chosen-avatar]', form);
    const chosenName = qs('[data-link-chosen-name]', form);
    const alumnoError = qs('[data-link-alumno-error]', form);
    const title = qs('[data-link-title]', modal);
    const submit = qs('[data-link-submit]', form);
    const checkbox = (name) => qs(`input[name="${name}"]`, form);

    const FLAGS = {
      tutor_principal: false,
      contacto_emergencia: false,
      autorizado_recoger: false,
      recibe_notificaciones: true,
      responsable_pagos: false,
      activo: true,
    };

    const choose = (alumno) => {
      alumnoInput.value = alumno.id;
      chosenName.textContent = alumno.nombre;
      chosenAvatar.textContent = alumno.iniciales;
      chosenAvatar.className = `avatar avatar--tone-${(Number(alumno.id) % 6) + 1}`;
      chosen.hidden = false;
      searchBlock.hidden = true;
      alumnoError.hidden = true;
    };

    const clearChoice = () => {
      alumnoInput.value = '';
      chosen.hidden = true;
      searchBlock.hidden = false;
      searchInput.value = '';
    };

    const search = liveSearch({
      input: searchInput,
      box: results,
      url: modal.dataset.searchUrl,
      emptyText: 'No hay alumnos con ese dato.',
      render: alumnoResult,
      onPick(alumno) {
        searchInput.value = '';
        choose(alumno);
        qs('select[name="parentesco"]', form).focus();
      },
    });

    const changeButton = qs('[data-link-change]', form);
    changeButton.addEventListener('click', () => {
      clearChoice();
      searchInput.focus();
    });

    const reset = () => {
      search.close();
      clearChoice();
      form.reset();
      Object.entries(FLAGS).forEach(([name, value]) => { checkbox(name).checked = value; });
      qs('select[name="parentesco"]', form).value = '';
      qs('textarea[name="observaciones"]', form).value = '';
      alumnoError.hidden = true;
      qsa('.field.is-invalid', form).forEach((field) => field.classList.remove('is-invalid'));
    };

    /* Se prepara el formulario según el botón que abrió la ventana. */
    document.addEventListener('click', (event) => {
      const opener = event.target.closest('[data-link-new], [data-link-edit]');
      if (!opener) return;
      reset();

      if (opener.hasAttribute('data-link-new')) {
        changeButton.hidden = false;
        title.textContent = 'Vincular alumno';
        submit.textContent = 'Guardar vínculo';
        window.setTimeout(() => searchInput.focus(), 60);
        return;
      }

      const data = opener.dataset;
      changeButton.hidden = true; /* al editar, el alumno no cambia: otro alumno sería otro vínculo */
      title.textContent = 'Editar vínculo';
      submit.textContent = 'Guardar cambios';
      choose({ id: data.alumnoId, nombre: data.alumnoNombre, iniciales: data.alumnoIniciales });
      qs('select[name="parentesco"]', form).value = data.parentesco;
      checkbox('tutor_principal').checked = data.principal === '1';
      checkbox('contacto_emergencia').checked = data.emergencia === '1';
      checkbox('autorizado_recoger').checked = data.recoger === '1';
      checkbox('recibe_notificaciones').checked = data.notificaciones === '1';
      checkbox('responsable_pagos').checked = data.pagos === '1';
      checkbox('activo').checked = data.activo === '1';
      qs('textarea[name="observaciones"]', form).value = data.observaciones;
    });

    form.addEventListener('submit', (event) => {
      if (alumnoInput.value) return;
      event.preventDefault();
      alumnoError.hidden = false;
      searchInput.focus();
    });
  }

  /* ============================================================== Desvincular */
  document.addEventListener('click', (event) => {
    const opener = event.target.closest('[data-unlink]');
    if (!opener) return;
    qs('[data-unlink-id]').value = opener.dataset.vinculoId;
    qs('[data-unlink-name]').textContent = opener.dataset.alumnoNombre;
  });
})();
