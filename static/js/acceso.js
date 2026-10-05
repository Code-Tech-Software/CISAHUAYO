/* CISAHUAYO · pantallas de acceso

   - Botón para mostrar u ocultar la contraseña.
   - Aviso cuando está activado el bloqueo de mayúsculas.
   - Botón «Entrando…» al enviar, para evitar doble envío (se restablece si el navegador vuelve a esta página con «atrás»).
*/
(() => {
  'use strict';

  const form = document.querySelector('[data-access-form]');
  if (!form) return;

  const password = form.querySelector('input[type="password"]');
  const toggle = form.querySelector('[data-password-toggle]');
  const capsNotice = form.querySelector('[data-caps-aviso]');
  const submit = form.querySelector('button[type="submit"]');

  /* ------------------------------------------------------------ Mostrar la contraseña */
  toggle?.addEventListener('click', () => {
    const visible = password.type === 'password';
    password.type = visible ? 'text' : 'password';
    toggle.setAttribute('aria-pressed', String(visible));
    toggle.setAttribute('aria-label', visible ? 'Ocultar la contraseña' : 'Mostrar la contraseña');
    password.focus();
  });

  /* ------------------------------------------------------------------ Bloqueo de mayúsculas */
  const syncCaps = (event) => {
    if (!capsNotice || typeof event.getModifierState !== 'function') return;
    capsNotice.hidden = !event.getModifierState('CapsLock');
  };
  password?.addEventListener('keydown', syncCaps);
  password?.addEventListener('keyup', syncCaps);
  password?.addEventListener('blur', () => { if (capsNotice) capsNotice.hidden = true; });

  /* ---------------------------------------------------------------------------------- Envío */
  if (!submit) return;
  const label = submit.innerHTML;

  const restore = () => {
    submit.classList.remove('is-loading');
    submit.disabled = false;
    submit.innerHTML = label;
  };

  form.addEventListener('submit', (event) => {
    if (event.defaultPrevented || !form.checkValidity()) return;
    /* Se deshabilita después del evento: un botón deshabilitado no manda su valor y el formulario aún no lo ha leído */
    window.setTimeout(() => {
      submit.classList.add('is-loading');
      submit.disabled = true;
      submit.firstChild.textContent = 'Entrando… ';
    }, 0);
  });

  window.addEventListener('pageshow', (event) => { if (event.persisted) restore(); });
})();
