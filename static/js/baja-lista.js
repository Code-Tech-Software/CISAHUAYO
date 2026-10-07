/* CISAHUAYO · confirmación de baja en los listados (estudiantes y tutores)

   Una sola ventana sirve a todas las filas: al pulsar el botón de baja de una fila ([data-baja]) se le pone la ruta de
   esa fila (data-action), su nombre (data-nombre → los [data-baja-nombre]) y, si la fila trae un aviso (data-aviso), se
   muestra en el recuadro [data-baja-aviso].
*/
(() => {
  'use strict';

  const form = document.querySelector('[data-baja-form]');
  if (!form) return;

  document.addEventListener('click', (event) => {
    const opener = event.target.closest('[data-baja]');
    if (!opener) return;
    form.action = opener.dataset.action;
    form.querySelectorAll('[data-baja-nombre]').forEach((node) => { node.textContent = opener.dataset.nombre; });

    const aviso = form.querySelector('[data-baja-aviso]');
    if (aviso) {
      const texto = opener.dataset.aviso || '';
      aviso.hidden = !texto;
      aviso.querySelector('[data-baja-aviso-texto]').textContent = texto;
    }
  });
})();
