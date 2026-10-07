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

  /* ------------------------------------------------------- Contraseña de acceso */
  /* «Generar una» escribe una contraseña al azar fácil de dictar (sin vocales ni 0/o, 1/l/i), como en el alta de estudiantes. */
  const PASSWORD_ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789';
  qs('[data-password-generate]')?.addEventListener('click', () => {
    const input = qs('input[name="contrasena_inicial"]');
    const bytes = new Uint32Array(8);
    window.crypto.getRandomValues(bytes);
    input.value = [...bytes].map((n) => PASSWORD_ALPHABET[n % PASSWORD_ALPHABET.length]).join('');
    clearError(input.closest('.field'));
    dirty = true;
  });

  /* -------------------------------------------------------------- Usuario del tutor */
  /* Mientras no se escriba a mano, se propone con su nombre (el servidor da uno libre: maria.lopez, maria.lopez2…).
     Lo que se escriba se revisa: formato y que ningún otro tutor lo tenga. Al editar se respeta el que ya tiene. */
  const usuario = qs('input[data-usuario-url]');
  if (usuario) {
    const estado = qs('[data-usuario-estado]');
    const nombre = qs('input[name="nombre"]');
    const apellido = qs('input[name="apellido_paterno"]');
    let manual = usuario.value.trim() !== '';
    let timer;
    let ultima = 0;

    const consultar = async (extra = {}) => {
      const id = ++ultima;
      const url = new URL(usuario.dataset.usuarioUrl, window.location.origin);
      url.searchParams.set('nombre', nombre?.value ?? '');
      url.searchParams.set('apellido_paterno', apellido?.value ?? '');
      if (usuario.dataset.excluir) url.searchParams.set('excluir', usuario.dataset.excluir);
      Object.entries(extra).forEach(([clave, valor]) => url.searchParams.set(clave, valor));
      try {
        const respuesta = await fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        if (!respuesta.ok) return null;
        const datos = await respuesta.json();
        return id === ultima ? datos : null;   /* solo cuenta la respuesta más reciente */
      } catch (error) {
        return null;
      }
    };

    const proponer = () => {
      window.clearTimeout(timer);
      if (manual) return;
      if (!nombre?.value.trim() && !apellido?.value.trim()) {
        usuario.value = '';
        estado.textContent = '';
        return;
      }
      timer = window.setTimeout(async () => {
        const datos = await consultar();
        if (!datos || manual) return;
        usuario.value = datos.sugerido;
        clearError(usuario.closest('.field'));
        estado.textContent = `«${datos.sugerido}» está disponible.`;
      }, 300);
    };

    const revisar = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(async () => {
        const datos = await consultar({ usuario: usuario.value });
        if (!datos || !manual) return;
        if (datos.disponible) {
          clearError(usuario.closest('.field'));
          estado.textContent = datos.mensaje;
        } else {
          estado.textContent = '';
          showError(usuario, datos.mensaje);
        }
      }, 300);
    };

    nombre?.addEventListener('input', proponer);
    apellido?.addEventListener('input', proponer);
    usuario.addEventListener('input', () => {
      manual = usuario.value.trim() !== '';   /* si lo borra, se vuelve a proponer con su nombre */
      if (manual) revisar();
      else proponer();
    });
  }

  /* Si el servidor devolvió errores, el cursor va al primer campo con problema. */
  qs('.field.is-invalid .field__control')?.focus();
})();
