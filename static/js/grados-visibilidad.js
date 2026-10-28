/* CISAHUAYO · «Visible en el sistema» de los grados (templates/grados/_visibilidad.html)

   El interruptor guarda al cambiarlo (Grados/views.grado_visibilidad, que vuelve a revisar el permiso) y regresa a la
   misma página. Sin JavaScript queda el botón «Guardar». Mientras se envía, el interruptor se bloquea para no mandarlo
   dos veces.
*/
(() => {
  'use strict';

  document.querySelectorAll('form[data-visibilidad]').forEach((form) => {
    const interruptor = form.querySelector('input[name="visible"]');
    form.querySelector('[data-visibilidad-guardar]')?.setAttribute('hidden', '');
    interruptor?.addEventListener('change', () => {
      form.requestSubmit();
      interruptor.disabled = true;   /* después de enviar: una casilla desactivada no se envía */
    });
  });
})();
