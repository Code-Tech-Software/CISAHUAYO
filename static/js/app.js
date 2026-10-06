/* CISAHUAYO · comportamiento de la interfaz base

   Cada función init* controla un componente y se engancha a atributos data-*
   del HTML (nunca a clases de estilo). Los estados se expresan con clases is-*
   en <html> o en el propio componente, y con atributos ARIA. Los módulos se
   comunican con eventos del documento (app:toggle-theme, app:toggle-sidebar).

     initSidebar   Menú lateral: superpuesto en móvil, contraíble en escritorio
     initNavGroups Grupos desplegables del menú (y su panel flotante con el menú contraído)
     initMenus     Menús desplegables (notificaciones, usuario)
     initPalette   Buscador de comandos (Ctrl+K / Cmd+K)
     initTheme     Tema claro/oscuro
     initToasts    Avisos flotantes de los mensajes de Django
     initAlerts    Cierre de avisos en línea (.alert)
     initTooltips  Tooltips de botones y del sidebar contraído
     initTabs      Pestañas accesibles ([data-tabs])
     initModals    Ventanas modales sobre <dialog data-modal>
     initSubmitFeedback  Botón «ocupado» y sin doble envío en los formularios POST
     initBack      Enlaces [data-back] que regresan a la página anterior
     initCopyAndPrint  Botones [data-copy] y [data-print]
     initAutosubmit    Filtros de listados que se envían solos ([data-autosubmit])

   Expone window.CISAHUAYO.icon(nombre), .liveSearch(opciones), .alumnoResult(alumno) y .forms (CURP, teléfonos,
   errores) a otros scripts.
*/
(() => {
  'use strict';

  /* Deben coincidir con static/js/preload.js y con los puntos de corte de app.css. */
  const SIDEBAR_KEY = 'cisahuayo.sidebar';
  const NAV_KEY = 'cisahuayo.menu';
  const THEME_KEY = 'cisahuayo.theme';
  const DESKTOP = window.matchMedia('(min-width: 64rem)');
  const MOTION_OK = window.matchMedia('(prefers-reduced-motion: no-preference)');

  const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
  const root = document.documentElement;

  const qs = (selector, scope = document) => scope.querySelector(selector);
  const qsa = (selector, scope = document) => [...scope.querySelectorAll(selector)];

  /* Crea un <svg> con un icono del sprite; reutiliza la URL del sprite que ya usa la página. */
  const SPRITE_URL = (qs('use')?.getAttribute('href') ?? '').split('#')[0];
  const icon = (name, classes = 'icon icon--sm') => {
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    const use = document.createElementNS(NS, 'use');
    svg.setAttribute('class', classes);
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    use.setAttribute('href', `${SPRITE_URL}#${name}`);
    svg.append(use);
    return svg;
  };

  /* Campo con una lista de resultados que llegan en vivo de una URL que responde { resultados: [...] }.
     Opciones: input (combobox), box (contenedor de los resultados), url, render(item) -> <button> con el
     contenido de cada resultado, onPick(item), isDisabled(item), emptyText, minChars, delay.
     Devuelve { close }. Accesible: roles combobox/listbox/option, flechas, Enter y Escape. */
  const liveSearch = ({
    input, box, url, render, onPick, isDisabled = () => false,
    emptyText = 'Sin resultados.', minChars = 2, delay = 250,
  }) => {
    let timer;
    let controller;
    let options = [];
    let active = -1;

    const close = () => {
      window.clearTimeout(timer);
      controller?.abort();
      box.hidden = true;
      box.replaceChildren();
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
      options = [];
      active = -1;
    };

    const setActive = (index) => {
      options.forEach(({ element }, i) => element.setAttribute('aria-selected', String(i === index)));
      active = index;
      if (options[index]) {
        input.setAttribute('aria-activedescendant', options[index].element.id);
        options[index].element.scrollIntoView({ block: 'nearest' });
      }
    };

    const pick = (index) => {
      const option = options[index];
      if (!option || option.element.getAttribute('aria-disabled') === 'true') return;
      close();
      onPick(option.item);
    };

    const message = (text) => {
      const note = document.createElement('p');
      note.className = 'live-search__empty';
      note.textContent = text;
      box.replaceChildren(note);
      box.hidden = false;
      input.setAttribute('aria-expanded', 'true');
    };

    const showResults = (items) => {
      if (!items.length) {
        options = [];
        message(emptyText);
        return;
      }
      options = items.map((item, index) => {
        const element = render(item);
        element.type = 'button';
        element.classList.add('live-result');
        element.id = `${box.id}-${index}`;
        element.setAttribute('role', 'option');
        element.setAttribute('aria-selected', 'false');
        if (isDisabled(item)) element.setAttribute('aria-disabled', 'true');
        element.addEventListener('click', () => pick(index));
        element.addEventListener('pointermove', () => { if (active !== index) setActive(index); });
        return { element, item };
      });
      box.replaceChildren(...options.map(({ element }) => element));
      box.hidden = false;
      input.setAttribute('aria-expanded', 'true');
      const first = options.findIndex(({ element }) => element.getAttribute('aria-disabled') !== 'true');
      if (first >= 0) setActive(first);
    };

    const search = async (query) => {
      controller?.abort();
      controller = new AbortController();
      try {
        const response = await fetch(`${url}${url.includes('?') ? '&' : '?'}q=${encodeURIComponent(query)}`, {
          headers: { Accept: 'application/json' },
          credentials: 'same-origin',
          signal: controller.signal,
        });
        if (!response.ok || !(response.headers.get('content-type') ?? '').includes('json')) throw new Error('respuesta no válida');
        showResults((await response.json()).resultados);
      } catch (error) {
        if (error.name !== 'AbortError') message('No se pudo buscar. Revisa tu conexión e intenta de nuevo.');
      }
    };

    input.addEventListener('input', () => {
      window.clearTimeout(timer);
      const query = input.value.trim();
      if (query.length < minChars) {
        close();
        return;
      }
      timer = window.setTimeout(() => search(query), delay);
    });

    input.addEventListener('keydown', (event) => {
      if (box.hidden) return;
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        if (!options.length) return;
        const step = event.key === 'ArrowDown' ? 1 : -1;
        setActive((active + step + options.length) % options.length);
      } else if (event.key === 'Enter' && options[active]) {
        event.preventDefault();
        pick(active);
      } else if (event.key === 'Escape') {
        event.stopPropagation();
        close();
      }
    });

    document.addEventListener('click', (event) => {
      if (!event.target.closest('.live-search')?.contains(input)) close();
    });

    return { close };
  };

  /* Resultado de la búsqueda de alumnos (JSON de alumnos:buscar): avatar con iniciales, nombre y datos. */
  const alumnoResult = (alumno) => {
    const option = document.createElement('button');
    const avatar = document.createElement('span');
    avatar.className = `avatar avatar--tone-${(Number(alumno.id) % 6) + 1}`;
    avatar.setAttribute('aria-hidden', 'true');
    avatar.textContent = alumno.iniciales;
    const text = document.createElement('span');
    text.className = 'live-result__text';
    const name = document.createElement('span');
    name.className = 'live-result__name';
    name.textContent = alumno.nombre;
    const meta = document.createElement('span');
    meta.className = 'live-result__meta';
    meta.textContent = [`Ref. ${alumno.referencia}`, alumno.grado || 'Sin inscripción actual', alumno.estatus].join(' · ');
    text.append(name, meta);
    option.append(avatar, text);
    return option;
  };

  /* Ayudantes que comparten los formularios de alumnos y tutores: CURP, teléfonos y errores en línea. */
  const forms = (() => {
    const CURP_RE = /^[A-Z][AEIOUX][A-Z]{2}\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[HM](AS|BC|BS|CC|CL|CM|CS|CH|DF|DG|GT|GR|HG|JC|MC|MN|MS|NT|NL|OC|PL|QT|QR|SP|SL|SR|TC|TS|TL|VZ|YN|ZS|NE)[B-DF-HJ-NP-TV-Z]{3}[0-9A-Z]\d$/;

    const normalizeCurp = (value) => value.replace(/\s+/g, '').toUpperCase();

    /* Fecha de nacimiento y sexo (códigos del modelo: M masculino, F femenino) que codifica una CURP. */
    const parseCurp = (curp) => {
      if (!CURP_RE.test(curp)) return null;
      const year = Number(curp.slice(4, 6)) + (/\d/.test(curp[16]) ? 1900 : 2000);
      const month = Number(curp.slice(6, 8));
      const day = Number(curp.slice(8, 10));
      const date = new Date(year, month - 1, day);
      if (date.getMonth() !== month - 1 || date.getDate() !== day) return null;
      const iso = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
      return { iso, date, sex: curp[10] === 'H' ? 'M' : 'F' };
    };

    const phoneDigits = (value) => {
      const digits = value.replace(/\D/g, '');
      if (digits.length === 13 && digits.startsWith('521')) return digits.slice(3);
      if (digits.length === 12 && digits.startsWith('52')) return digits.slice(2);
      return digits;
    };
    const formatPhone = (value) => {
      const digits = phoneDigits(value || '');
      return digits.length === 10 ? `${digits.slice(0, 3)} ${digits.slice(3, 6)} ${digits.slice(6)}` : (value || '');
    };

    const clearError = (field) => {
      qsa('.field__error', field).forEach((node) => node.remove());
      field.classList.remove('is-invalid');
      qsa('[aria-invalid]', field).forEach((control) => control.removeAttribute('aria-invalid'));
    };

    /* Muestra (o, con mensaje vacío, quita) el error de un control dentro de su .field. */
    const showError = (control, message) => {
      const field = control.closest('.field');
      if (!field) return;
      clearError(field);
      if (!message) return;
      field.classList.add('is-invalid');
      const error = document.createElement('p');
      error.className = 'field__error';
      error.textContent = message;
      field.append(error);
      const targets = control.type === 'radio' ? qsa(`input[name="${CSS.escape(control.name)}"]`) : [control];
      targets.forEach((target) => target.setAttribute('aria-invalid', 'true'));
    };

    return { CURP_RE, normalizeCurp, parseCurp, phoneDigits, formatPhone, clearError, showError };
  })();

  window.CISAHUAYO = Object.freeze({ icon, liveSearch, alumnoResult, forms });

  const store = {
    set(key, value) {
      try {
        if (value === null) {
          localStorage.removeItem(key);
        } else {
          localStorage.setItem(key, value);
        }
      } catch (error) {
        /* Sin almacenamiento: la preferencia solo dura mientras la página esté abierta. */
      }
    },
  };

  /* ------------------------------------------------------------------ Sidebar */
  function initSidebar() {
    const sidebar = qs('[data-sidebar]');
    const toggle = qs('[data-sidebar-toggle]');
    const main = qs('[data-app-main]');
    if (!sidebar || !toggle || !main) return;

    const closeButton = qs('[data-sidebar-close]', sidebar);
    const backdrop = qs('[data-sidebar-backdrop]');

    const isCollapsed = () => root.classList.contains('is-sidebar-collapsed');
    const isOpen = () => root.classList.contains('is-sidebar-open');

    /* aria-expanded: en escritorio indica sidebar expandido; en móvil, abierto. */
    const syncToggle = () => {
      toggle.setAttribute('aria-expanded', String(DESKTOP.matches ? !isCollapsed() : isOpen()));
    };

    const setCollapsed = (collapsed) => {
      root.classList.toggle('is-sidebar-collapsed', collapsed);
      store.set(SIDEBAR_KEY, collapsed ? 'collapsed' : null);
      syncToggle();
    };

    const open = () => {
      root.classList.add('is-sidebar-open', 'is-scroll-locked');
      main.inert = true; /* el foco y los lectores de pantalla quedan dentro del menú */
      syncToggle();
      closeButton?.focus();
    };

    const close = ({ restoreFocus = true } = {}) => {
      if (!isOpen()) return;
      root.classList.remove('is-sidebar-open', 'is-scroll-locked');
      main.inert = false;
      syncToggle();
      if (restoreFocus) toggle.focus();
    };

    const toggleSidebar = () => {
      if (DESKTOP.matches) {
        setCollapsed(!isCollapsed());
      } else if (isOpen()) {
        close();
      } else {
        open();
      }
    };

    toggle.addEventListener('click', toggleSidebar);
    document.addEventListener('app:toggle-sidebar', toggleSidebar);

    closeButton?.addEventListener('click', () => close());
    backdrop?.addEventListener('click', () => close({ restoreFocus: false }));

    /* Navegar desde el menú móvil lo cierra (también evita restaurarlo abierto con "Atrás"). */
    sidebar.addEventListener('click', (event) => {
      if (event.target.closest('a[href]') && !DESKTOP.matches) close({ restoreFocus: false });
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && isOpen()) {
        event.preventDefault();
        close();
      }
    });

    /* Con el menú móvil abierto, Tab no sale del sidebar. */
    sidebar.addEventListener('keydown', (event) => {
      if (event.key !== 'Tab' || !isOpen()) return;
      const items = qsa(FOCUSABLE, sidebar);
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });

    DESKTOP.addEventListener('change', () => {
      close({ restoreFocus: false });
      syncToggle();
    });
    window.addEventListener('pageshow', (event) => {
      if (event.persisted) close({ restoreFocus: false });
    });

    syncToggle();
  }

  /* -------------------------------------------------------- Grupos del menú */
  /* Cada grupo ([data-nav-group]) es un <details>: se abre y se cierra solo, aun sin este script. Aquí se recuerdan
     entre páginas los grupos que la persona deja abiertos (el de la página actual llega abierto desde el servidor) y, con
     el sidebar contraído (escritorio), el grupo se abre en un panel flotante junto a su icono. */
  function initNavGroups() {
    const nav = qs('[data-nav]');
    if (!nav) return;
    const groups = qsa('[data-nav-group]', nav);
    if (!groups.length) return;

    const leerAbiertos = () => {
      try {
        return new Set(JSON.parse(localStorage.getItem(NAV_KEY) || '[]'));
      } catch (error) {
        return new Set();
      }
    };
    const abiertos = leerAbiertos();
    const guardar = () => store.set(NAV_KEY, abiertos.size ? JSON.stringify([...abiertos]) : null);

    const detailsOf = (group) => qs('details', group);

    groups.forEach((group) => {
      const details = detailsOf(group);
      if (abiertos.has(group.dataset.navGroup)) details.open = true;
      details.addEventListener('toggle', () => {
        if (isRail()) return;
        if (details.open) {
          abiertos.add(group.dataset.navGroup);
        } else {
          abiertos.delete(group.dataset.navGroup);
        }
        guardar();
      });
    });

    /* --- Panel flotante (sidebar contraído) --- */
    let flyout = null;
    let flyoutOwner = null;
    const closeFlyout = ({ restoreFocus = false } = {}) => {
      if (!flyout) return;
      flyout.remove();
      flyout = null;
      if (restoreFocus) flyoutOwner?.focus();
      flyoutOwner = null;
    };
    const openFlyout = (group) => {
      const toggle = qs('[data-nav-toggle]', group);
      closeFlyout();
      flyout = document.createElement('div');
      flyout.className = 'nav-flyout';
      flyout.setAttribute('role', 'dialog');
      flyout.setAttribute('aria-label', qs('.nav__label--group', group).textContent.trim());
      const title = document.createElement('p');
      title.className = 'nav-flyout__title';
      title.textContent = flyout.getAttribute('aria-label');
      const list = document.createElement('ul');
      list.className = 'nav-flyout__list';
      qsa('.nav__sublink', group).forEach((link) => {
        const item = document.createElement('li');
        item.append(link.cloneNode(true));
        list.append(item);
      });
      flyout.append(title, list);
      document.body.append(flyout);

      const rect = toggle.getBoundingClientRect();
      const { height } = flyout.getBoundingClientRect();
      const top = Math.max(8, Math.min(rect.top - 8, window.innerHeight - height - 8));
      flyout.style.setProperty('left', `${Math.round(nav.getBoundingClientRect().right + 8)}px`);
      flyout.style.setProperty('top', `${Math.round(top)}px`);
      flyoutOwner = toggle;
      qs('a', flyout)?.focus();
    };

    const isRail = () => DESKTOP.matches && root.classList.contains('is-sidebar-collapsed');

    /* Contraído: el <summary> no despliega la lista (no cabe en el riel), abre el panel flotante */
    nav.addEventListener('click', (event) => {
      const toggle = event.target.closest('[data-nav-toggle]');
      if (!toggle || !isRail()) return;
      event.preventDefault();
      if (flyoutOwner === toggle) {
        closeFlyout();
      } else {
        openFlyout(toggle.closest('[data-nav-group]'));
      }
    });

    document.addEventListener('click', (event) => {
      if (flyout && !flyout.contains(event.target) && !event.target.closest('[data-nav-toggle]')) closeFlyout();
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && flyout) {
        event.preventDefault();
        closeFlyout({ restoreFocus: true });
      }
    });
    /* Al expandir o contraer el sidebar, o al cambiar de tamaño, el panel ya no corresponde */
    document.addEventListener('app:toggle-sidebar', () => closeFlyout());
    qs('[data-sidebar-toggle]')?.addEventListener('click', () => closeFlyout());
    window.addEventListener('resize', () => closeFlyout());
    nav.addEventListener('scroll', () => closeFlyout());
  }

  /* -------------------------------------------------------------------- Menús */
  function initMenus() {
    const menus = qsa('[data-menu]');
    if (!menus.length) return;

    const parts = (menu) => ({
      trigger: qs('[data-menu-trigger]', menu),
      panel: qs('[data-menu-panel]', menu),
    });
    const itemsOf = (panel) => qsa('a[href], button:not([disabled])', panel);
    const isOpen = (menu) => !parts(menu).panel.hidden;

    const setOpen = (menu, open, { focusFirst = false } = {}) => {
      const { trigger, panel } = parts(menu);
      panel.hidden = !open;
      trigger.setAttribute('aria-expanded', String(open));
      if (open && focusFirst) itemsOf(panel)[0]?.focus();
    };

    menus.forEach((menu) => {
      const { trigger, panel } = parts(menu);

      trigger.addEventListener('click', () => {
        const willOpen = !isOpen(menu);
        menus.forEach((other) => setOpen(other, false));
        setOpen(menu, willOpen);
      });

      trigger.addEventListener('keydown', (event) => {
        if (event.key !== 'ArrowDown') return;
        event.preventDefault();
        menus.forEach((other) => setOpen(other, false));
        setOpen(menu, true, { focusFirst: true });
      });

      panel.addEventListener('keydown', (event) => {
        const items = itemsOf(panel);
        const index = items.indexOf(document.activeElement);
        const moves = {
          ArrowDown: items[(index + 1) % items.length],
          ArrowUp: items[(index - 1 + items.length) % items.length],
          Home: items[0],
          End: items[items.length - 1],
        };
        if (!items.length || !(event.key in moves)) return;
        event.preventDefault();
        moves[event.key].focus();
      });

      /* Al salir del menú con Tab, se cierra. */
      menu.addEventListener('focusout', (event) => {
        if (event.relatedTarget && !menu.contains(event.relatedTarget)) setOpen(menu, false);
      });
    });

    document.addEventListener('click', (event) => {
      menus.forEach((menu) => {
        if (!menu.contains(event.target)) setOpen(menu, false);
      });
    });
    document.addEventListener('app:close-menus', () => menus.forEach((menu) => setOpen(menu, false)));

    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      const openMenu = menus.find(isOpen);
      if (!openMenu) return;
      const hadFocus = openMenu.contains(document.activeElement);
      setOpen(openMenu, false);
      if (hadFocus) parts(openMenu).trigger.focus();
    });
  }

  /* -------------------------------------------------------- Buscador de comandos */
  function initPalette() {
    const dialog = qs('[data-palette]');
    if (!dialog || typeof dialog.showModal !== 'function') return;

    const input = qs('[data-palette-input]', dialog);
    const list = qs('[data-palette-list]', dialog);
    const empty = qs('[data-palette-empty]', dialog);
    const emptyQuery = qs('[data-palette-empty-query]', dialog);
    const searchItem = qs('[data-palette-search]', dialog);
    const searchQuery = searchItem && qs('[data-palette-query]', searchItem);
    const searchBase = searchItem?.getAttribute('href');

    const normalize = (text) => text.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

    /* Orden original de grupos y opciones, para restaurarlo al borrar la búsqueda. */
    const nodes = [...list.children].filter((node) => node !== searchItem);
    const groups = nodes.filter((node) => node.matches('[data-palette-group]'));
    const entries = nodes
      .filter((node) => node.matches('[data-palette-item]'))
      .map((element) => ({
        element,
        order: nodes.indexOf(element),
        label: normalize(qs('.palette__label', element).textContent),
        keywords: normalize(element.dataset.keywords || ''),
      }));

    const visibleOptions = () => qsa('[role="option"]:not([hidden])', list);

    /* 0 = mejor coincidencia; -1 = no coincide. Cada palabra escrita debe coincidir. */
    const scoreOf = ({ label, keywords }, query) => {
      let total = 0;
      for (const token of query.split(/\s+/)) {
        let score = -1;
        if (label.startsWith(token)) score = 0;
        else if (label.split(/\s+/).some((word) => word.startsWith(token))) score = 1;
        else if (label.includes(token)) score = 2;
        else if (keywords.includes(token)) score = 3;
        if (score < 0) return -1;
        total += score;
      }
      return total;
    };

    let active = null;
    const setActive = (option) => {
      active?.setAttribute('aria-selected', 'false');
      active = option;
      if (option) {
        option.setAttribute('aria-selected', 'true');
        input.setAttribute('aria-activedescendant', option.id);
        option.scrollIntoView({ block: 'nearest' });
      } else {
        input.removeAttribute('aria-activedescendant');
      }
    };

    const filter = (rawQuery) => {
      const text = rawQuery.trim();
      const query = normalize(text);
      const scored = entries.map((entry) => ({ entry, score: query ? scoreOf(entry, query) : 0 }));
      scored.forEach(({ entry, score }) => { entry.element.hidden = score < 0; });

      if (query) {
        groups.forEach((group) => { group.hidden = true; });
        const sorted = scored
          .filter(({ score }) => score >= 0)
          .sort((a, b) => a.score - b.score || a.entry.order - b.entry.order)
          .map(({ entry }) => entry.element);
        list.prepend(...sorted);
      } else {
        groups.forEach((group) => { group.hidden = false; });
        list.prepend(...nodes);
      }

      if (searchItem) {
        searchItem.hidden = !query;
        searchQuery.textContent = text;
        searchItem.href = `${searchBase}${searchBase.includes('?') ? '&' : '?'}q=${encodeURIComponent(text)}`;
      }

      const options = visibleOptions();
      empty.hidden = options.length > 0;
      emptyQuery.textContent = text;
      setActive(options[0] ?? null);
    };

    const open = () => {
      if (dialog.open) return;
      dialog.showModal();
      root.classList.add('is-scroll-locked');
      input.value = '';
      filter('');
      input.focus();
    };

    const actions = {
      'toggle-theme': () => document.dispatchEvent(new CustomEvent('app:toggle-theme')),
      'toggle-sidebar': () => document.dispatchEvent(new CustomEvent('app:toggle-sidebar')),
    };

    document.addEventListener('click', (event) => {
      if (event.target.closest('[data-palette-open]')) open();
    });

    document.addEventListener('keydown', (event) => {
      const isShortcut = (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey
        && event.key.toLowerCase() === 'k';
      if (!isShortcut || root.classList.contains('is-sidebar-open')) return;
      event.preventDefault();
      if (dialog.open) {
        dialog.close();
      } else {
        open();
      }
    });

    dialog.addEventListener('close', () => root.classList.remove('is-scroll-locked'));
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) dialog.close(); /* clic fuera del panel */
    });

    input.addEventListener('input', () => filter(input.value));
    input.addEventListener('keydown', (event) => {
      if (event.isComposing) return;
      const options = visibleOptions();
      const index = options.indexOf(active);
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        if (!options.length) return;
        const step = event.key === 'ArrowDown' ? 1 : -1;
        setActive(options[(index + step + options.length) % options.length]);
      } else if (event.key === 'Enter') {
        event.preventDefault();
        active?.click();
      }
    });

    list.addEventListener('pointermove', (event) => {
      const option = event.target.closest('[role="option"]');
      if (option && option !== active) setActive(option);
    });

    list.addEventListener('click', (event) => {
      const option = event.target.closest('[role="option"]');
      if (!option) return;
      const action = actions[option.dataset.paletteAction];
      dialog.close(); /* antes de la acción, para que esta conserve el foco */
      action?.();
    });
  }

  /* --------------------------------------------------------------------- Tema */
  function initTheme() {
    const toggles = qsa('[data-theme-toggle]');
    const isDark = () => root.dataset.theme === 'dark';

    const apply = (dark) => {
      if (dark) {
        root.dataset.theme = 'dark';
      } else {
        delete root.dataset.theme;
      }
      store.set(THEME_KEY, dark ? 'dark' : null);
      toggles.forEach((button) => button.setAttribute('aria-pressed', String(dark)));
    };

    /* Revelado circular desde el botón con la API de View Transitions, si existe. */
    const toggleTheme = (origin) => {
      const dark = !isDark();
      if (!document.startViewTransition || !MOTION_OK.matches) {
        apply(dark);
        return;
      }

      const rect = origin?.getBoundingClientRect();
      const x = rect ? rect.left + rect.width / 2 : window.innerWidth / 2;
      const y = rect ? rect.top + rect.height / 2 : 0;
      const radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));

      root.classList.add('is-theme-transition');
      const transition = document.startViewTransition(() => apply(dark));
      transition.ready
        .then(() => root.animate(
          { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
          { duration: 520, easing: 'cubic-bezier(0.4, 0, 0.2, 1)', pseudoElement: '::view-transition-new(root)' },
        ))
        .catch(() => {});
      transition.finished.finally(() => root.classList.remove('is-theme-transition'));
    };

    toggles.forEach((button) => button.addEventListener('click', () => toggleTheme(button)));
    document.addEventListener('app:toggle-theme', () => toggleTheme(null));
    toggles.forEach((button) => button.setAttribute('aria-pressed', String(isDark())));
  }

  /* ------------------------------------------------------------ Avisos flotantes */
  function initToasts() {
    const region = qs('[data-toasts]');
    if (!region) return;

    const dismiss = (toast) => {
      if (!toast.isConnected || toast.classList.contains('is-leaving')) return;
      const remove = () => {
        if (!toast.isConnected) return;
        /* Si el foco estaba en el aviso, pasa al siguiente o al contenido para no perderse. */
        const hadFocus = toast.contains(document.activeElement);
        const next = toast.nextElementSibling ?? toast.previousElementSibling;
        toast.remove();
        if (hadFocus) (qs('[data-toast-dismiss]', next ?? document) ?? qs('main'))?.focus({ preventScroll: true });
        if (!region.children.length) region.remove();
      };
      toast.classList.add('is-leaving');
      toast.addEventListener('animationend', (event) => {
        if (event.animationName === 'toast-out') remove();
      });
      window.setTimeout(remove, 600); /* respaldo si no hay animación */
    };

    /* La barra de progreso es el temporizador: al terminar, el aviso se cierra. */
    qsa('[data-toast-progress]', region).forEach((bar) => {
      bar.addEventListener('animationend', () => dismiss(bar.closest('[data-toast]')));
    });

    region.addEventListener('click', (event) => {
      const button = event.target.closest('[data-toast-dismiss]');
      if (button) dismiss(button.closest('[data-toast]'));
    });
  }

  /* ----------------------------------------------------------- Avisos en línea */
  function initAlerts() {
    document.addEventListener('click', (event) => {
      const alert = event.target.closest('[data-alert-dismiss]')?.closest('[data-alert]');
      if (!alert) return;
      alert.remove();
      qs('main')?.focus({ preventScroll: true }); /* el foco no se pierde al borrar el botón */
    });
  }

  /* ----------------------------------------------------------------- Tooltips */
  function initTooltips() {
    const tooltip = document.createElement('div');
    tooltip.className = 'tooltip';
    tooltip.setAttribute('aria-hidden', 'true'); /* el nombre accesible ya está en el propio elemento */
    document.body.append(tooltip);

    const GAP = 8;

    /* Los de [data-tooltip-collapsed] solo aplican con el sidebar contraído. */
    const applies = (element) => !element.hasAttribute('data-tooltip-collapsed')
      || (DESKTOP.matches && root.classList.contains('is-sidebar-collapsed'));

    const hide = () => tooltip.classList.remove('is-visible');

    const show = (element) => {
      if (!applies(element)) {
        hide();
        return;
      }
      tooltip.textContent = element.dataset.tooltip;
      const anchor = element.getBoundingClientRect();
      const { width, height } = tooltip.getBoundingClientRect();
      let x;
      let y;
      if (element.dataset.tooltipPlacement === 'right') {
        x = anchor.right + GAP;
        y = anchor.top + (anchor.height - height) / 2;
      } else {
        x = anchor.left + (anchor.width - width) / 2;
        y = anchor.bottom + GAP;
      }
      x = Math.min(Math.max(x, GAP), window.innerWidth - width - GAP);
      tooltip.style.setProperty('--tooltip-x', `${x}px`);
      tooltip.style.setProperty('--tooltip-y', `${y}px`);
      tooltip.classList.add('is-visible');
    };

    document.addEventListener('pointerover', (event) => {
      if (event.pointerType !== 'mouse') return;
      const element = event.target.closest('[data-tooltip]');
      if (element) {
        show(element);
      } else {
        hide();
      }
    });
    document.addEventListener('pointerout', (event) => {
      if (!event.relatedTarget) hide();
    });
    document.addEventListener('focusin', (event) => {
      const element = event.target.closest('[data-tooltip]');
      if (element?.matches(':focus-visible')) show(element);
    });
    document.addEventListener('focusout', hide);
    document.addEventListener('click', hide);
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') hide();
    });
    window.addEventListener('scroll', hide, true);
    window.addEventListener('resize', hide);
  }

  /* ----------------------------------------------------------------- Pestañas */
  /* <div data-tabs> con [role=tablist] > [role=tab][aria-controls] y paneles [role=tabpanel] con ese id.
     Sin JavaScript todos los paneles se ven; con él, solo el activo. El hash de la URL (#id) abre un panel. */
  function initTabs() {
    qsa('[data-tabs]').forEach((tabs) => {
      const list = qs('[role="tablist"]', tabs);
      const items = qsa('[role="tab"]', list);
      if (!items.length) return;

      const panelOf = (tab) => document.getElementById(tab.getAttribute('aria-controls'));
      const fromHash = () => items.find((tab) => `#${tab.getAttribute('aria-controls')}` === window.location.hash);

      const select = (tab, { focus = false, updateHash = true } = {}) => {
        items.forEach((item) => {
          const active = item === tab;
          item.setAttribute('aria-selected', String(active));
          item.tabIndex = active ? 0 : -1;
          panelOf(item).hidden = !active;
        });
        if (focus) tab.focus();
        if (updateHash) window.history.replaceState(null, '', `#${tab.getAttribute('aria-controls')}`);
      };

      list.addEventListener('click', (event) => {
        const tab = event.target.closest('[role="tab"]');
        if (tab) select(tab);
      });

      list.addEventListener('keydown', (event) => {
        const index = items.indexOf(document.activeElement);
        const moves = {
          ArrowRight: items[(index + 1) % items.length],
          ArrowLeft: items[(index - 1 + items.length) % items.length],
          Home: items[0],
          End: items[items.length - 1],
        };
        if (index < 0 || !(event.key in moves)) return;
        event.preventDefault();
        select(moves[event.key], { focus: true });
      });

      window.addEventListener('hashchange', () => {
        const tab = fromHash();
        if (tab) select(tab, { updateHash: false });
      });

      const initial = fromHash() ?? items.find((tab) => tab.getAttribute('aria-selected') === 'true') ?? items[0];
      select(initial, { updateHash: false });
    });
  }

  /* ------------------------------------------------------------------ Modales */
  /* <dialog data-modal id="x"> abierto con [data-modal-open="x"] y cerrado con [data-modal-close],
     Escape o un clic fuera del panel. Todo es delegado: también sirve para los diálogos que llegan dentro de un
     formulario abierto en la ventana modal (modal-form.js), que no existían al cargar la página. */
  function initModals() {
    document.addEventListener('click', (event) => {
      const opener = event.target.closest('[data-modal-open]');
      if (opener) {
        /* Se busca primero dentro de la ventana donde está el botón: un formulario abierto en la ventana modal puede traer
           un diálogo con el mismo id que otro de la página de atrás (p. ej. «modal-eliminar») */
        const id = opener.dataset.modalOpen;
        const dialog = opener.closest('dialog')?.querySelector(`#${CSS.escape(id)}`) ?? document.getElementById(id);
        if (typeof dialog?.showModal !== 'function') return;
        document.dispatchEvent(new CustomEvent('app:close-menus'));
        dialog.showModal();
        root.classList.add('is-scroll-locked');
        return;
      }
      if (event.target.closest('[data-modal-close]')) {
        event.target.closest('dialog')?.close();
      } else if (event.target.matches('dialog[data-modal]')) {
        event.target.close(); /* clic en el velo, fuera del panel */
      }
    });

    /* «close» no burbujea: se escucha en la fase de captura para cubrir cualquier diálogo, presente o futuro */
    document.addEventListener('close', (event) => {
      if (event.target.matches?.('dialog') && !qs('dialog[open]')) root.classList.remove('is-scroll-locked');
    }, true);
  }

  /* ------------------------------------------------------ Envío de formularios */
  /* Al enviar un formulario por POST, el botón que lo envió muestra un anillo de «ocupado» y se bloquean los envíos
     repetidos: un doble clic ya no duplica un registro. Quedan fuera los formularios que cancelan el envío (los que
     validan o envían con fetch, como la ventana de modal-form.js) y los que llevan [data-no-busy]. */
  function initSubmitFeedback() {
    const BUTTONS = 'button[type="submit"], input[type="submit"]';

    document.addEventListener('submit', (event) => {
      const form = event.target;
      if (!(form instanceof HTMLFormElement) || form.method !== 'post' || form.hasAttribute('data-no-busy')) return;
      if (form.target && form.target !== '_self') return;   /* la página no se descarga: el botón no tendría cuándo volver */
      const submitter = event.submitter ?? qs(BUTTONS, form);

      /* Después de que el navegador lea los datos (un botón deshabilitado no manda su valor) y de que cualquier otro
         script haya podido cancelar el envío */
      window.setTimeout(() => {
        if (event.defaultPrevented || form.closest('[data-form-modal]')) return;
        qsa(BUTTONS, form).forEach((button) => { button.disabled = true; });
        submitter?.classList.add('is-loading');
        form.dataset.busy = 'true';
      }, 0);
    });

    /* Al volver con «atrás», el navegador puede mostrar la página tal como se quedó: se devuelve a su estado normal */
    window.addEventListener('pageshow', (event) => {
      if (!event.persisted) return;
      qsa('form[data-busy]').forEach((form) => {
        delete form.dataset.busy;
        qsa(BUTTONS, form).forEach((button) => {
          button.disabled = false;
          button.classList.remove('is-loading');
        });
      });
    });
  }

  /* ------------------------------------------------------------- Volver atrás */
  /* [data-back]: regresa a la página anterior (páginas de error); sin historial, el enlace conserva su destino. */
  function initBack() {
    document.addEventListener('click', (event) => {
      const link = event.target.closest('[data-back]');
      if (!link || window.history.length < 2 || !document.referrer.startsWith(window.location.origin)) return;
      event.preventDefault();
      window.history.back();
    });
  }

  /* ------------------------------------------------------- Copiar e imprimir */
  /* [data-copy="#selector"] copia el valor o texto del elemento; [data-print] abre el diálogo de impresión. */
  function initCopyAndPrint() {
    const copyText = async (text) => {
      try {
        await navigator.clipboard.writeText(text);
      } catch (error) {
        const area = document.createElement('textarea');
        area.value = text;
        area.setAttribute('readonly', '');
        area.className = 'visually-hidden';
        document.body.append(area);
        area.select();
        document.execCommand('copy');
        area.remove();
      }
    };

    document.addEventListener('click', async (event) => {
      const copyButton = event.target.closest('[data-copy]');
      if (copyButton) {
        const source = qs(copyButton.dataset.copy);
        await copyText((source?.value ?? source?.textContent ?? '').trim());
        if (copyButton.dataset.copied) return;
        const original = [...copyButton.childNodes];
        copyButton.dataset.copied = 'true';
        copyButton.replaceChildren(icon('check'), document.createTextNode(' Copiado'));
        window.setTimeout(() => {
          copyButton.replaceChildren(...original);
          delete copyButton.dataset.copied;
        }, 1600);
        return;
      }
      if (event.target.closest('[data-print]')) window.print();
    });
  }

  /* --------------------------------------------------------- Filtros en vivo */
  /* <form data-autosubmit>: envía al cambiar un select o al dejar de escribir; el botón queda de respaldo. */
  function initAutosubmit() {
    const FOCUS_KEY = 'cisahuayo.autosubmit-focus';

    qsa('form[data-autosubmit]').forEach((form) => {
      let timer;
      const submit = (field) => {
        window.clearTimeout(timer);
        try {
          sessionStorage.setItem(FOCUS_KEY, field?.name ?? '');
        } catch (error) {
          /* Sin almacenamiento: solo se pierde devolver el foco al campo. */
        }
        form.requestSubmit();
      };

      form.addEventListener('change', (event) => {
        if (event.target.matches('select')) submit(event.target);
      });
      form.addEventListener('input', (event) => {
        if (!event.target.matches('input[type="search"], input[type="text"]')) return;
        window.clearTimeout(timer);
        timer = window.setTimeout(() => submit(event.target), 450);
      });

      qs('[data-autosubmit-fallback]', form)?.setAttribute('hidden', '');

      /* Tras recargar con los resultados, el cursor vuelve al final del buscador. */
      try {
        const name = sessionStorage.getItem(FOCUS_KEY);
        sessionStorage.removeItem(FOCUS_KEY);
        const field = name ? form.elements[name] : null;
        if (field?.matches?.('input[type="search"], input[type="text"]')) {
          field.focus();
          field.setSelectionRange?.(field.value.length, field.value.length);
        }
      } catch (error) {
        /* Sin almacenamiento: no se restaura el foco. */
      }
    });
  }

  /* En Mac los atajos usan ⌘ en lugar de Ctrl. */
  const platform = navigator.userAgentData?.platform || navigator.platform || '';
  if (/mac|iphone|ipad/i.test(platform)) {
    qsa('[data-shortcut-kbd]').forEach((kbd) => { kbd.textContent = '⌘ K'; });
  }

  initSidebar();
  initNavGroups();
  initMenus();
  initPalette();
  initTheme();
  initToasts();
  initAlerts();
  initTooltips();
  initTabs();
  initModals();
  initSubmitFeedback();
  initBack();
  initCopyAndPrint();
  initAutosubmit();
})();
