/* CISAHUAYO · formulario de usuarios

   Ayuda a capturar: sugiere el usuario a partir del nombre (hasta que la persona lo escribe a mano), lo mantiene en
   minúsculas y sin caracteres no permitidos, y da formato al teléfono. El servidor valida todo otra vez.
*/
(() => {
  'use strict';

  const form = document.querySelector('#usuario-form');
  if (!form) return;

  const usuario = form.querySelector('[data-usuario]');
  const nombre = form.querySelector('[name="first_name"]');
  const apellidos = form.querySelector('[name="last_name"]');
  const { phoneDigits, formatPhone } = window.CISAHUAYO.forms;

  /* «María José» + «Núñez Ruiz» → «maria.nunez» */
  const limpiar = (texto) => texto.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '');
  const sugerencia = () => {
    const primerNombre = limpiar((nombre.value.trim().split(/\s+/)[0] ?? ''));
    const primerApellido = limpiar((apellidos.value.trim().split(/\s+/)[0] ?? ''));
    return [primerNombre, primerApellido].filter(Boolean).join('.');
  };

  /* Solo se sugiere en altas y mientras el usuario esté vacío o siga siendo la sugerencia anterior */
  let ultima = usuario.value;
  const sugerir = () => {
    if (usuario.value !== ultima) return;
    ultima = sugerencia();
    usuario.value = ultima;
  };
  if (!usuario.value) {
    nombre.addEventListener('input', sugerir);
    apellidos.addEventListener('input', sugerir);
  }

  usuario.addEventListener('input', () => {
    const limpio = usuario.value.toLowerCase().replace(/[^a-z0-9._-]/g, '');
    if (limpio !== usuario.value) usuario.value = limpio;
  });

  form.querySelectorAll('[data-phone]').forEach((campo) => {
    campo.addEventListener('blur', () => {
      if (phoneDigits(campo.value).length === 10) campo.value = formatPhone(campo.value);
    });
  });
})();
