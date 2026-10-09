/* CISAHUAYO · confirmación de baja en los listados (estudiantes, tutores, profesores, materias y grados)

   Una sola ventana sirve a todas las filas: al pulsar el botón de baja de una fila ([data-baja]) se le pone la ruta de
   esa fila (data-action), su nombre (data-nombre → los [data-baja-nombre]) y, si la fila trae un aviso (data-aviso), se
   muestra en el recuadro [data-baja-aviso].

   Opciones por fila: cada casilla de la ventana va en un [data-baja-opcion="clave"] y solo aparece (marcada) si el botón
   trae data-opcion-clave con su texto, por ejemplo data-opcion-cuenta="También desactivar su cuenta «marta»". Si no lo
   trae, se oculta y su casilla se desactiva para que no se envíe.
*/
(() => {
  'use strict';

  const form = document.querySelector('[data-baja-form]');
  if (!form) return;

  const atributo = (clave) => `opcion${clave.charAt(0).toUpperCase()}${clave.slice(1)}`;

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

    form.querySelectorAll('[data-baja-opcion]').forEach((opcion) => {
      const texto = opener.dataset[atributo(opcion.dataset.bajaOpcion)] || '';
      const casilla = opcion.querySelector('input');
      opcion.hidden = !texto;
      casilla.disabled = !texto;
      casilla.checked = Boolean(texto);
      opcion.querySelector('[data-baja-opcion-texto]').textContent = texto;
    });
  });
})();
