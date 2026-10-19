/* CISAHUAYO · formularios de reuniones con familias (registrar la llamada y los participantes)

   La regla del acompañante directivo, en vivo: al marcar a un docente se resalta el acompañante y, si no hay ninguno
   elegido, se avisa. Es solo ayuda: el servidor (Reuniones/reglas.py) vuelve a revisar todo. Se vuelve a ejecutar cada
   vez que el formulario se abre en una ventana (modal-form.js): cada bloque se prepara una sola vez.
*/
(() => {
  'use strict';

  document.querySelectorAll('[data-reuniones-participantes]').forEach((bloque) => {
    if (bloque.dataset.reunionesListo) return;
    bloque.dataset.reunionesListo = '1';

    const formulario = bloque.closest('form');
    const docentes = () => [...bloque.querySelectorAll('[data-reuniones-docente]')].filter((c) => c.checked);
    const zona = bloque.querySelector('[data-reuniones-acompanante]');
    const aviso = bloque.querySelector('[data-reuniones-sin-acompanante]');
    const selector = formulario?.querySelector('select[name="acompanante"]');
    const casillas = () => [...(formulario?.querySelectorAll('input[name="acompanantes"]') || [])];
    const despues = formulario?.querySelector('input[name="acompanante_despues"]');

    const revisar = () => {
      const conDocente = docentes().length > 0;
      const elegido = selector ? Boolean(selector.value) : casillas().some((c) => c.checked);
      zona?.classList.toggle('is-requerido', conDocente);
      if (selector) selector.required = conDocente && !despues?.checked;
      if (aviso) aviso.hidden = !conDocente || elegido;
    };

    formulario?.addEventListener('change', revisar);
    revisar();
  });
})();
