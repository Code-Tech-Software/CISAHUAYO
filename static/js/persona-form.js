/* CISAHUAYO · formularios de personas (tutores y profesores)

   Ayuda a capturar (CURP en mayúsculas con retroalimentación, teléfonos con formato) y valida
   en el navegador antes de enviar. El servidor vuelve a validar todo.
*/
(() => {
  'use strict';

  const form = document.querySelector('[data-persona-form]');
  if (!form) return;

  const { CURP_RE, normalizeCurp, parseCurp, phoneDigits, formatPhone, clearError, showError } = window.CISAHUAYO.forms;
  const qs = (selector, scope = form) => scope.querySelector(selector);
  const qsa = (selector, scope = form) => [...scope.querySelectorAll(selector)];

  /* ------------------------------------------------------------------ Validación */
  const messageFor = (control) => {
    const value = control.value.trim();
    if (!value) return control.required ? 'Este campo es obligatorio.' : '';
    if (control.matches('[data-curp-optional]') && !CURP_RE.test(normalizeCurp(value))) {
      return 'La CURP no tiene un formato válido (18 caracteres).';
    }
    if (control.dataset.phone !== undefined && phoneDigits(value).length !== 10) {
      return 'Ingresa un teléfono de 10 dígitos.';
    }
    if (!control.validity.valid) {
      if (control.validity.typeMismatch && control.type === 'email') return 'Escribe un correo válido.';
      if (control.validity.patternMismatch) return 'El código postal tiene 5 dígitos.';
      return control.validationMessage;
    }
    return '';
  };

  const controls = () => qsa('input:not([type="hidden"]), select, textarea').filter((control) => !control.disabled);

  /* Los errores se quitan al corregir el campo. */
  form.addEventListener('input', (event) => {
    const field = event.target.closest?.('.field');
    if (field?.classList.contains('is-invalid')) clearError(field);
  });

  /* ------------------------------------------------------------------------ CURP */
  const curpInput = qs('[data-curp-optional]');
  const feedback = qs('[data-curp-feedback]');
  if (curpInput && feedback) {
    const defaultHint = feedback.textContent;
    const longDate = new Intl.DateTimeFormat('es-MX', { day: 'numeric', month: 'long', year: 'numeric' });
    const sync = () => {
      const position = curpInput.selectionStart;
      const normalized = normalizeCurp(curpInput.value);
      if (normalized !== curpInput.value) {
        curpInput.value = normalized;
        curpInput.setSelectionRange(position, position);
      }
      const data = parseCurp(normalized);
      if (data) {
        feedback.textContent = `CURP válida: ${data.sex === 'M' ? 'hombre' : 'mujer'}, nació el ${longDate.format(data.date)}.`;
      } else {
        feedback.textContent = normalized.length === 18 ? 'Revisa la CURP: parece que tiene un error.' : defaultHint;
      }
    };
    curpInput.addEventListener('input', sync);
    if (curpInput.value) sync();
  }

  /* ------------------------------------------------------------------- Teléfonos */
  qsa('[data-phone]').forEach((input) => {
    input.addEventListener('blur', () => {
      if (phoneDigits(input.value).length === 10) input.value = formatPhone(input.value);
    });
  });

  /* ---------------------------------------------------------------- Envío y salida */
  let dirty = false;
  form.addEventListener('input', () => { dirty = true; });
  form.addEventListener('change', () => { dirty = true; });
  window.addEventListener('beforeunload', (event) => {
    if (!dirty || !form.isConnected) return;   /* en la ventana modal, el formulario se desecha al cerrarla */
    event.preventDefault();
    event.returnValue = '';
  });

  form.addEventListener('submit', (event) => {
    let first = null;
    controls().forEach((control) => {
      const message = messageFor(control);
      showError(control, message);
      if (message && !first) first = control;
    });
    if (first) {
      event.preventDefault();
      first.focus();
      return;
    }
    dirty = false;
    const button = qs('[data-submit]');
    button.disabled = true;
    button.lastChild.textContent = ' Guardando…';
  });

  /* Si el servidor devolvió errores, el cursor va al primer campo con problema. */
  qs('.field.is-invalid .field__control')?.focus();
})();
