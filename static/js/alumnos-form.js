/* CISAHUAYO · asistente de registro y edición de alumnos

   Es un único formulario dividido en pasos: este script muestra un paso a la vez,
   valida cada uno antes de avanzar, ayuda a capturar (CURP, foto, contraseña) y
   administra las tarjetas de tutores. El servidor vuelve a validar todo al enviar.

     Pasos        Navegación, validación por paso y barra de progreso
     CURP         Deduce fecha de nacimiento y sexo
     Foto         Vista previa y límite de tamaño
     Acceso       Generar y copiar la contraseña; inscripción opcional
     Tutores      Tarjetas dinámicas (nuevo o existente) y búsqueda en vivo
     Revisión     Resumen final antes de guardar
*/
(() => {
  'use strict';

  const form = document.querySelector('[data-wizard]');
  if (!form) return;

  const { icon, liveSearch, forms } = window.CISAHUAYO;
  const { CURP_RE, normalizeCurp, parseCurp, phoneDigits, formatPhone, clearError, showError } = forms;
  const qs = (selector, scope = form) => scope.querySelector(selector);
  const qsa = (selector, scope = form) => [...scope.querySelectorAll(selector)];

  const isEdit = form.dataset.edit === 'true';
  const MAX_PHOTO_BYTES = 5 * 1024 * 1024;
  const PASSWORD_ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789';
  const motionOk = window.matchMedia('(prefers-reduced-motion: no-preference)');

  const panels = qsa('[data-step-panel]');
  const items = qsa('[data-step-item]');
  const lastIndex = panels.length - 1;
  const stepKeys = panels.map((panel) => panel.dataset.stepPanel);
  const stepTitles = panels.map((panel) => qs('.wizard__panel-title', panel).textContent.trim());

  const prevButton = qs('[data-step-prev]');
  const nextButton = qs('[data-step-next]');
  const submitButton = qs('[data-step-submit]');
  const summary = qs('[data-step-summary]');

  const randomPassword = (length = 8) => {
    const bytes = new Uint32Array(length);
    window.crypto.getRandomValues(bytes);
    return [...bytes].map((n) => PASSWORD_ALPHABET[n % PASSWORD_ALPHABET.length]).join('');
  };
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  /* ================================================================ Validación */
  const cardOf = (control) => control.closest('[data-tutor-form]');

  /* ¿Está oculto algún ancestro entre el nodo y el panel? (el panel mismo puede estar oculto: no es el caso) */
  function isHiddenWithin(node, scope) {
    for (let current = node; current && current !== scope; current = current.parentElement) {
      if (current.hidden) return true;
    }
    return false;
  }

  function controlsOf(scope) {
    return qsa('input, select, textarea', scope).filter(
      (control) => control.type !== 'hidden' && !control.disabled && !isHiddenWithin(control, scope),
    );
  }

  function messageFor(control) {
    if (control.type === 'radio') {
      const group = qsa(`input[type="radio"][name="${CSS.escape(control.name)}"]`);
      return control.required && !group.some((radio) => radio.checked) ? 'Elige una opción.' : '';
    }
    if (control.type === 'checkbox' || control.type === 'file') return '';

    const value = control.value.trim();
    const isNewTutor = cardOf(control)?.dataset.mode === 'nuevo';
    if (!value) {
      const required = control.required
        || control.dataset.required !== undefined
        || (control.dataset.requiredNew !== undefined && isNewTutor);
      return required ? 'Este campo es obligatorio.' : '';
    }
    if (control.matches('[data-curp], [data-curp-optional]') && !CURP_RE.test(normalizeCurp(value))) {
      return 'La CURP no tiene un formato válido (18 caracteres).';
    }
    if (control.dataset.phone !== undefined && phoneDigits(value).length !== 10) {
      return 'Ingresa un teléfono de 10 dígitos.';
    }
    if (!control.validity.valid) {
      if (control.validity.typeMismatch && control.type === 'email') return 'Escribe un correo válido.';
      if (control.validity.patternMismatch) return control.name.endsWith('cp') ? 'El código postal tiene 5 dígitos.' : 'El formato no es válido.';
      if (control.validity.tooLong) return 'El texto es demasiado largo.';
      return control.validationMessage;
    }
    return '';
  }

  /* Valida un paso; devuelve el primer control con error (o null). */
  function validateStep(index) {
    const panel = panels[index];
    const seenGroups = new Set();
    let first = null;

    controlsOf(panel).forEach((control) => {
      if (control.type === 'radio') {
        if (seenGroups.has(control.name)) return;
        seenGroups.add(control.name);
      }
      const message = messageFor(control);
      showError(control, message);
      if (message && !first) first = control;
    });

    if (stepKeys[index] === 'tutores') {
      qs('[data-tutor-empty-error]')?.remove();
      if (!isEdit && !activeCards().length) {
        const note = el('p', 'field__error', 'Agrega al menos un tutor para continuar.');
        note.setAttribute('data-tutor-empty-error', '');
        note.setAttribute('role', 'alert');
        emptyBox.append(note);
        first = first ?? searchInput;
      }
    }

    items[index].classList.toggle('has-error', Boolean(first));
    return first;
  }

  /* Los errores se quitan al corregir el campo. */
  form.addEventListener('input', (event) => {
    const field = event.target.closest?.('.field');
    if (field?.classList.contains('is-invalid')) clearError(field);
  });
  form.addEventListener('change', (event) => {
    const field = event.target.closest?.('.field');
    if (field?.classList.contains('is-invalid')) clearError(field);
  });

  /* ================================================================== Pasos */
  let current = 0;
  const done = new Set();

  function renderStepper() {
    items.forEach((item, index) => {
      const button = qs('.stepper__button', item);
      const hasError = item.classList.contains('has-error');
      const isDone = index !== current && !hasError && (isEdit || done.has(index));
      item.classList.toggle('is-current', index === current);
      item.classList.toggle('is-done', isDone);
      if (index === current) {
        button.setAttribute('aria-current', 'step');
      } else {
        button.removeAttribute('aria-current');
      }
      qs('[data-step-status]', item).textContent = hasError ? ', con errores' : (index === current ? ', paso actual' : (isDone ? ', completado' : ''));
    });
    form.style.setProperty('--progress', `${((current + 1) / panels.length) * 100}%`);
    summary.textContent = `Paso ${current + 1} de ${panels.length} · ${stepTitles[current]}`;
    prevButton.hidden = current === 0;
    nextButton.hidden = current === lastIndex;
    submitButton.hidden = !(isEdit || current === lastIndex);
  }

  function show(index, { focus = false } = {}) {
    current = index;
    panels.forEach((panel, i) => { panel.hidden = i !== index; });
    if (stepKeys[index] === 'revision') renderReview();
    renderStepper();
    if (focus) {
      const title = qs('.wizard__panel-title', panels[index]);
      title.tabIndex = -1;
      title.focus({ preventScroll: true });
      qs('.wizard__nav-steps').scrollIntoView({ block: 'start', behavior: motionOk.matches ? 'smooth' : 'auto' });
    }
  }

  /* Al avanzar se valida cada paso intermedio (al registrar); retroceder siempre es libre. */
  function goTo(target, { focus = true } = {}) {
    target = Math.max(0, Math.min(lastIndex, target));
    if (!isEdit && target > current) {
      for (let i = current; i < target; i += 1) {
        const invalid = validateStep(i);
        if (invalid) {
          show(i, { focus: true });
          invalid.focus();
          return false;
        }
        done.add(i);
      }
    }
    show(target, { focus });
    return true;
  }

  prevButton.addEventListener('click', () => goTo(current - 1));
  nextButton.addEventListener('click', () => goTo(current + 1));
  form.addEventListener('click', (event) => {
    const goto = event.target.closest('[data-step-goto], [data-review-edit]');
    if (!goto) return;
    goTo(Number(goto.dataset.stepGoto ?? goto.dataset.reviewEdit));
  });

  /* Enter avanza de paso en lugar de enviar el formulario por accidente. */
  form.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' || event.defaultPrevented) return;
    if (event.target.matches('textarea, button, a, [data-tutor-search-input]')) return;
    event.preventDefault();
    if (current < lastIndex) goTo(current + 1);
  });

  /* ============================================================ CURP inteligente */
  const curpInput = qs('[data-curp]');
  const birthInput = qs('[data-fecha-nacimiento]');
  const sexInputs = qsa('input[name="sexo"]');
  const curpFeedback = qs('[data-curp-feedback]');
  const curpDefaultHint = curpFeedback?.textContent ?? '';

  if (curpInput && birthInput) {
    const sexLabel = { M: 'masculino', F: 'femenino' };
    const longDate = new Intl.DateTimeFormat('es-MX', { day: 'numeric', month: 'long', year: 'numeric' });

    const sync = () => {
      const position = curpInput.selectionStart;
      const normalized = normalizeCurp(curpInput.value);
      if (normalized !== curpInput.value) {
        curpInput.value = normalized;
        curpInput.setSelectionRange(position, position);
      }
      const data = parseCurp(normalized);
      if (!data) {
        curpFeedback.textContent = normalized.length === 18 ? 'Revisa la CURP: parece que tiene un error.' : curpDefaultHint;
        return;
      }
      const sexGroup = sexInputs[0]?.closest('.field');
      if (!birthInput.value || birthInput.dataset.auto === '1') {
        birthInput.value = data.iso;
        birthInput.dataset.auto = '1';
        clearError(birthInput.closest('.field'));
      }
      if (sexInputs.length && (!sexInputs.some((radio) => radio.checked) || sexGroup.dataset.auto === '1')) {
        sexInputs.forEach((radio) => { radio.checked = radio.value === data.sex; });
        sexGroup.dataset.auto = '1';
        clearError(sexGroup);
      }
      const matches = birthInput.value === data.iso;
      curpFeedback.textContent = matches
        ? `CURP válida: nació el ${longDate.format(data.date)} · sexo ${sexLabel[data.sex]}.`
        : `La CURP indica nacimiento el ${longDate.format(data.date)}, pero la fecha capturada es distinta. Revísala.`;
    };

    curpInput.addEventListener('input', sync);
    birthInput.addEventListener('input', () => { birthInput.dataset.auto = ''; sync(); });
    sexInputs.forEach((radio) => radio.addEventListener('change', () => { radio.closest('.field').dataset.auto = ''; }));
    if (!isEdit && curpInput.value) sync();
  }

  /* ================================================================== Fotografía */
  const photoInput = qs('input[type="file"][name="fotografia"]');
  const photoPreview = qs('[data-photo-preview]');
  const photoHint = qs('[data-photo-hint]');
  if (photoInput && photoPreview) {
    const originalPreview = [...photoPreview.childNodes];
    const defaultHint = photoHint.textContent;
    let objectUrl = null;

    photoInput.addEventListener('change', () => {
      const file = photoInput.files[0];
      photoHint.classList.remove('field__error');
      photoHint.textContent = defaultHint;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = null;

      if (!file) {
        photoPreview.replaceChildren(...originalPreview);
        return;
      }
      if (!file.type.startsWith('image/') || file.size > MAX_PHOTO_BYTES) {
        photoInput.value = '';
        photoPreview.replaceChildren(...originalPreview);
        photoHint.classList.add('field__error');
        photoHint.textContent = file.type.startsWith('image/') ? 'La fotografía no debe pesar más de 5 MB.' : 'Elige un archivo de imagen (JPG o PNG).';
        return;
      }
      objectUrl = URL.createObjectURL(file);
      const image = el('img', 'photo-field__img');
      image.alt = 'Vista previa de la fotografía';
      image.src = objectUrl;
      photoPreview.replaceChildren(image);
    });
  }

  /* ============================================== Contraseña e inscripción (alta) */
  qs('[data-password-generate]')?.addEventListener('click', () => {
    const input = qs('input[name="contrasena_inicial"]');
    input.value = randomPassword();
    clearError(input.closest('.field'));
  });

  const enroll = qs('[data-enroll]');
  if (enroll) {
    const toggle = qs('input[type="checkbox"]', enroll);
    const fields = qs('[data-enroll-fields]', enroll);
    const sync = () => { fields.hidden = !toggle.checked; };
    toggle.addEventListener('change', sync);
    sync();
  }

  /* ===================================================================== Tutores */
  const tutorList = qs('[data-tutor-list]');
  const tutorTemplate = qs('template[data-tutor-template]');
  const totalForms = qs('input[name="tutores-TOTAL_FORMS"]');
  const emptyBox = qs('[data-tutor-empty]');
  const searchInput = qs('[data-tutor-search-input]');
  const resultsBox = qs('[data-tutor-results]');

  const isRemoved = (card) => card.hidden;
  const allCards = () => qsa('[data-tutor-form]', tutorList);
  const activeCards = () => allCards().filter((card) => !isRemoved(card));
  const field = (card, suffix) => qs(`[name$="-${suffix}"]`, card);
  const tutorIdOf = (card) => field(card, 'tutor').value;

  function refreshTutors() {
    const hasTutors = activeCards().length > 0;
    emptyBox.hidden = hasTutors;
    if (hasTutors) qs('[data-tutor-empty-error]')?.remove();
  }

  /* Solo un tutor principal: al marcar uno, se desmarcan los demás. */
  tutorList.addEventListener('change', (event) => {
    if (!event.target.name?.endsWith('-tutor_principal') || !event.target.checked) return;
    activeCards().forEach((card) => {
      const other = field(card, 'tutor_principal');
      if (other !== event.target) other.checked = false;
    });
  });

  function ensurePrincipal() {
    const cards = activeCards();
    if (cards.length && !cards.some((card) => field(card, 'tutor_principal').checked)) {
      field(cards[0], 'tutor_principal').checked = true;
    }
  }

  function setMode(card, mode) {
    card.dataset.mode = mode;
    field(card, 'modo').value = mode;
    qs('[data-tutor-new]', card).hidden = mode === 'existente';
    qs('[data-tutor-existing]', card).hidden = mode !== 'existente';
  }

  function fact(card, name, iconName, text) {
    const node = qs(`[data-fact="${name}"]`, card);
    node.replaceChildren();
    if (!text) return;
    node.append(icon(iconName), document.createTextNode(` ${text}`));
  }

  function addCard(mode, tutor) {
    const index = Number(totalForms.value);
    tutorList.insertAdjacentHTML('beforeend', tutorTemplate.innerHTML.replaceAll('__prefix__', String(index)));
    totalForms.value = String(index + 1);
    const card = tutorList.lastElementChild;
    setMode(card, mode);

    if (mode === 'existente') {
      field(card, 'tutor').value = tutor.id;
      qs('[data-tutor-name]', card).textContent = tutor.nombre;
      qs('[data-tutor-sub]', card).textContent = 'Tutor ya registrado';
      const avatar = qs('[data-tutor-avatar]', card);
      avatar.textContent = tutor.iniciales;
      avatar.className = `avatar avatar--lg avatar--tone-${(tutor.id % 6) + 1}`;
      fact(card, 'telefono', 'phone', formatPhone(tutor.telefono));
      fact(card, 'correo', 'mail', tutor.correo);
      fact(card, 'ocupacion', 'user', tutor.ocupacion);
      qs('[data-fact="alumnos"]', card).textContent = tutor.alumnos.length ? `También es tutor de: ${tutor.alumnos.join(', ')}.` : '';
    }

    if (!activeCards().some((other) => other !== card && field(other, 'tutor_principal').checked)) {
      field(card, 'tutor_principal').checked = true;
    }
    refreshTutors();
    (mode === 'existente' ? field(card, 'parentesco') : field(card, 'nombre')).focus();
    card.scrollIntoView({ block: 'center', behavior: motionOk.matches ? 'smooth' : 'auto' });
    return card;
  }

  /* El encabezado de un tutor nuevo refleja lo que se va escribiendo. */
  tutorList.addEventListener('input', (event) => {
    const card = cardOf(event.target);
    if (!card || card.dataset.mode !== 'nuevo') return;
    if (!/-(nombre|apellido_paterno|apellido_materno|telefono)$/.test(event.target.name)) return;
    const name = ['nombre', 'apellido_paterno', 'apellido_materno'].map((suffix) => field(card, suffix).value.trim()).filter(Boolean).join(' ');
    qs('[data-tutor-name]', card).textContent = name || 'Tutor nuevo';
    const phone = field(card, 'telefono').value.trim();
    qs('[data-tutor-sub]', card).textContent = phone ? formatPhone(phone) : 'Completa sus datos de contacto';
    qs('[data-tutor-avatar]', card).textContent = ((field(card, 'nombre').value[0] ?? '') + (field(card, 'apellido_paterno').value[0] ?? '')).toUpperCase() || '+';
  });

  tutorList.addEventListener('click', (event) => {
    const remove = event.target.closest('[data-tutor-remove]');
    if (!remove) return;
    const card = cardOf(remove);
    qs('input[name$="-DELETE"]', card).checked = true;
    card.hidden = true; /* sigue en el formulario: así el servidor sabe qué vínculo quitar */
    ensurePrincipal();
    refreshTutors();
  });

  qs('[data-tutor-add]').addEventListener('click', () => addCard('nuevo'));

  /* --- Búsqueda de tutores existentes (componente compartido liveSearch) ---------------------- */
  liveSearch({
    input: searchInput,
    box: resultsBox,
    url: form.dataset.searchUrl,
    emptyText: 'No hay tutores con ese dato. Puedes crear uno nuevo.',
    isDisabled: (tutor) => activeCards().some((card) => tutorIdOf(card) === String(tutor.id)),
    render(tutor) {
      const added = activeCards().some((card) => tutorIdOf(card) === String(tutor.id));
      const option = el('button');
      const avatar = el('span', `avatar avatar--tone-${(tutor.id % 6) + 1}`, tutor.iniciales);
      avatar.setAttribute('aria-hidden', 'true');
      const text = el('span', 'live-result__text');
      text.append(
        el('span', 'live-result__name', tutor.nombre + (added ? ' (ya agregado)' : '')),
        el('span', 'live-result__meta', [formatPhone(tutor.telefono), tutor.ocupacion].filter(Boolean).join(' · ')),
      );
      if (tutor.alumnos.length) text.append(el('span', 'live-result__meta', `Tutor de: ${tutor.alumnos.join(', ')}`));
      option.append(avatar, text);
      return option;
    },
    onPick(tutor) {
      searchInput.value = '';
      addCard('existente', tutor);
    },
  });

  /* ==================================================================== Revisión */
  const labelOf = (fieldNode) => {
    const label = qs('.field__label', fieldNode);
    return label ? label.textContent.replace(/\s*\*$/, '').trim() : '';
  };

  function valueOf(fieldNode) {
    const radios = qsa('input[type="radio"]', fieldNode);
    if (radios.length) return radios.find((radio) => radio.checked)?.closest('.choice')?.textContent.trim() ?? '';
    const control = qs('select, textarea, input:not([type="hidden"]):not([type="file"]):not([type="checkbox"])', fieldNode);
    if (!control) return '';
    if (control.tagName === 'SELECT') return control.value ? control.selectedOptions[0].textContent.trim() : '';
    if (control.name === 'contrasena_inicial') return control.value ? '•'.repeat(8) : 'Se generará una automáticamente';
    if (control.type === 'date' && control.value) {
      const [year, month, day] = control.value.split('-').map(Number);
      return new Intl.DateTimeFormat('es-MX', { day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(year, month - 1, day));
    }
    return control.value.trim();
  }

  function detailsFor(panel) {
    const list = el('dl', 'details');
    qsa('.field', panel).forEach((fieldNode) => {
      /* La inscripción se resume aparte; los tutores tienen su propia sección. */
      if (isHiddenWithin(fieldNode, panel) || fieldNode.closest('[data-tutor-form], [data-enroll]')) return;
      const label = labelOf(fieldNode);
      if (!label) return;
      const value = valueOf(fieldNode);
      const item = el('div', 'details__item');
      item.append(el('dt', 'details__label', label), el('dd', `details__value${value ? '' : ' details__value--empty'}`, value || 'No registrado'));
      list.append(item);
    });
    return list;
  }

  function reviewSection(index, iconName, title, content) {
    const section = el('section', 'review__section');
    const head = el('div', 'review__head');
    const heading = el('h3', 'review__title');
    heading.append(icon(iconName), document.createTextNode(` ${title}`));
    const edit = el('button', 'btn btn--sm');
    edit.type = 'button';
    edit.dataset.reviewEdit = String(index);
    edit.append(icon('pencil'), document.createTextNode(' Editar'));
    head.append(heading, edit);
    section.append(head, content);
    return section;
  }

  function renderReview() {
    const review = qs('[data-review]');
    const blocks = [];

    const identity = detailsFor(panels[0]);
    const photo = photoInput?.files[0];
    const photoItem = el('div', 'details__item');
    photoItem.append(el('dt', 'details__label', 'Fotografía'), el('dd', 'details__value', photo ? photo.name : (qs('.photo-field__img') ? 'Fotografía actual' : 'Sin fotografía')));
    identity.prepend(photoItem);
    blocks.push(reviewSection(0, 'user', 'Identidad', identity));
    blocks.push(reviewSection(1, 'map-pin', 'Domicilio y salud', detailsFor(panels[1])));

    const school = detailsFor(panels[2]);
    if (enroll && qs('input[type="checkbox"]', enroll).checked) {
      const item = el('div', 'details__item details__item--wide');
      const cycle = valueOf(qs('[name="insc-ciclo"]').closest('.field'));
      const grade = valueOf(qs('[name="insc-grado"]').closest('.field'));
      item.append(el('dt', 'details__label', 'Inscripción'), el('dd', 'details__value', `${grade || 'Sin grado'} · Ciclo ${cycle || 'sin elegir'}`));
      school.append(item);
    }
    blocks.push(reviewSection(2, 'graduation-cap', 'Datos escolares', school));

    const tutors = el('ul', 'review__tutors');
    activeCards().forEach((card) => {
      const row = el('li', 'review__tutor');
      const strong = el('strong', '', qs('[data-tutor-name]', card).textContent);
      row.append(strong);
      const kinship = field(card, 'parentesco');
      if (kinship.value) row.append(el('span', 'tag tag--info', kinship.selectedOptions[0].textContent.trim()));
      qsa('.choice--check', card).forEach((choice) => {
        const input = qs('input', choice);
        if (input.checked && input.name.match(/-(tutor_principal|contacto_emergencia|autorizado_recoger|responsable_pagos)$/)) {
          row.append(el('span', 'tag tag--primary', choice.textContent.trim()));
        }
      });
      const phone = card.dataset.mode === 'nuevo' ? formatPhone(field(card, 'telefono').value) : qs('[data-fact="telefono"]', card).textContent.trim();
      if (phone) row.append(el('span', 'text-muted', phone));
      tutors.append(row);
    });
    if (!tutors.children.length) tutors.append(el('li', 'text-muted', 'Sin tutores.'));
    blocks.push(reviewSection(3, 'users', 'Tutores', tutors));

    if (!isEdit) {
      const note = el('p', 'review__note');
      note.append(icon('key'), document.createTextNode(' Al registrar al estudiante verás sus credenciales de acceso una sola vez: tenlas a la mano para entregarlas.'));
      blocks.push(note);
    }
    review.replaceChildren(...blocks);
  }

  /* ============================================================ Envío y salida */
  let dirty = false;
  form.addEventListener('input', () => { dirty = true; });
  form.addEventListener('change', () => { dirty = true; });
  window.addEventListener('beforeunload', (event) => {
    if (!dirty || !form.isConnected) return;   /* en la ventana modal, el formulario se desecha al cerrarla */
    event.preventDefault();
    event.returnValue = '';
  });

  form.addEventListener('submit', (event) => {
    for (let index = 0; index < lastIndex; index += 1) {
      const invalid = validateStep(index);
      if (invalid) {
        event.preventDefault();
        show(index, { focus: true });
        invalid.focus();
        return;
      }
    }
    dirty = false;
    submitButton.disabled = true;
    submitButton.lastChild.textContent = ' Guardando…';
  });

  /* ============================================================== Arranque */
  items.forEach((item, index) => {
    if (panels[index].querySelector('.field__error, .is-invalid, .alert--error, .has-errors')) item.classList.add('has-error');
  });
  const firstError = items.findIndex((item) => item.classList.contains('has-error'));
  for (let index = 0; index < firstError; index += 1) done.add(index); /* los pasos previos al primer error ya estaban completos */
  show(firstError >= 0 ? firstError : Number(form.dataset.initialStep) || 0);
  refreshTutors();
  if (firstError >= 0) {
    const control = controlsOf(panels[firstError]).find((node) => node.closest('.is-invalid, .has-errors'));
    control?.focus({ preventScroll: false });
  }
})();
