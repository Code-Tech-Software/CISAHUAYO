/* CISAHUAYO · formularios de reuniones con familias (registrar la llamada, los participantes y programar)

   - La regla del acompañante directivo, en vivo: al marcar a un docente se resalta el acompañante y, si no hay ninguno
     elegido, se avisa.
   - Programar o reprogramar: al elegir uno de los horarios libres sugeridos se llenan la fecha, las horas y la sala.
   Es solo ayuda: el servidor (Reuniones/reglas.py) vuelve a revisar todo. Se vuelve a ejecutar cada vez que el
   formulario se abre en una ventana (modal-form.js): cada bloque se prepara una sola vez.
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

  document.querySelectorAll('[data-reuniones-sugeridos]').forEach((bloque) => {
    if (bloque.dataset.reunionesListo) return;
    bloque.dataset.reunionesListo = '1';

    const formulario = bloque.closest('form');
    const poner = (nombre, valor) => {
      const campo = formulario?.querySelector(`[name="${nombre}"]`);
      if (!campo) return;
      campo.value = valor;
      campo.dispatchEvent(new Event('change', { bubbles: true }));
    };
    bloque.addEventListener('click', (evento) => {
      const boton = evento.target.closest('button[data-fecha]');
      if (!boton) return;
      poner('fecha', boton.dataset.fecha);
      poner('hora_inicio', boton.dataset.inicio);
      poner('hora_fin', boton.dataset.fin);
      poner('sala', boton.dataset.sala);
      bloque.querySelectorAll('button[data-fecha]').forEach((otro) => otro.setAttribute('aria-pressed', String(otro === boton)));
      formulario?.querySelector('[name="fecha"]')?.focus({ preventScroll: true });
    });
  });
})();
