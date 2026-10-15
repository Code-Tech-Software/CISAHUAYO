/* CISAHUAYO · pantallas de acceso

   - Selector del tipo de acceso (Sistema · Estudiantes · Tutores): las pestañas son enlaces (?acceso=…) que funcionan
     sin JavaScript; aquí se cambian sin recargar, con flechas, Inicio y Fin, y se actualiza la dirección.
     Sin una pestaña pedida, se elige la última con la que se entró en este dispositivo.
   - En cada formulario: botón para mostrar u ocultar la contraseña, aviso de bloqueo de mayúsculas y botón
     «Entrando…» al enviar para evitar doble envío (se restablece si el navegador vuelve con «atrás»).
*/
(() => {
  'use strict';

  const ULTIMO_ACCESO = 'cisahuayo.acceso';
  const store = {
    get: (key) => { try { return localStorage.getItem(key); } catch (error) { return null; } },
    set: (key, value) => { try { localStorage.setItem(key, value); } catch (error) { /* modo privado */ } },
  };

  /* ---------------------------------------------------------------------- Pestañas */
  const tablist = document.querySelector('[data-access-tabs]');
  const tabs = tablist ? [...tablist.querySelectorAll('[data-access-tab]')] : [];
  const panelOf = (tab) => document.getElementById(tab.getAttribute('aria-controls'));

  const select = (tab, { focusTab = false, focusField = false, updateUrl = true } = {}) => {
    tabs.forEach((other) => {
      const selected = other === tab;
      other.setAttribute('aria-selected', String(selected));
      other.tabIndex = selected ? 0 : -1;
      const panel = panelOf(other);
      if (panel) panel.hidden = !selected;
    });
    if (focusTab) tab.focus();
    if (focusField) panelOf(tab)?.querySelector('input:not([type="hidden"])')?.focus();
    if (updateUrl) {
      const url = new URL(window.location.href);
      url.searchParams.set('acceso', tab.dataset.accessTab);
      window.history.replaceState(null, '', url);
    }
  };

  if (tabs.length) {
    tablist.addEventListener('click', (event) => {
      const tab = event.target.closest('[data-access-tab]');
      if (!tab || event.metaKey || event.ctrlKey || event.shiftKey) return;
      event.preventDefault();
      select(tab, { focusField: true });
    });

    tablist.addEventListener('keydown', (event) => {
      const current = tabs.indexOf(document.activeElement);
      if (current < 0) return;
      const next = {
        ArrowRight: (current + 1) % tabs.length,
        ArrowLeft: (current - 1 + tabs.length) % tabs.length,
        Home: 0,
        End: tabs.length - 1,
      }[event.key];
      if (next === undefined) return;
      event.preventDefault();
      select(tabs[next], { focusTab: true });
    });

    /* La última pestaña con la que se entró, si no se pidió una en particular */
    if (!tablist.hasAttribute('data-access-explicit')) {
      const remembered = tabs.find((tab) => tab.dataset.accessTab === store.get(ULTIMO_ACCESO));
      if (remembered && remembered.getAttribute('aria-selected') !== 'true') {
        select(remembered, { focusField: true, updateUrl: false });
      }
    }
  }

  /* ---------------------------------------------------------------------- Formularios */
  document.querySelectorAll('[data-access-form]').forEach((form) => {
    const password = form.querySelector('input[type="password"]');
    const toggle = form.querySelector('[data-password-toggle]');
    const capsNotice = form.querySelector('[data-caps-aviso]');
    const submit = form.querySelector('button[type="submit"]');

    /* Mostrar la contraseña */
    toggle?.addEventListener('click', () => {
      const visible = password.type === 'password';
      password.type = visible ? 'text' : 'password';
      toggle.setAttribute('aria-pressed', String(visible));
      toggle.setAttribute('aria-label', visible ? 'Ocultar la contraseña' : 'Mostrar la contraseña');
      password.focus();
    });

    /* Bloqueo de mayúsculas */
    const syncCaps = (event) => {
      if (!capsNotice || typeof event.getModifierState !== 'function') return;
      capsNotice.hidden = !event.getModifierState('CapsLock');
    };
    password?.addEventListener('keydown', syncCaps);
    password?.addEventListener('keyup', syncCaps);
    password?.addEventListener('blur', () => { if (capsNotice) capsNotice.hidden = true; });

    /* Envío */
    if (!submit) return;
    const label = submit.innerHTML;
    const restore = () => {
      submit.classList.remove('is-loading');
      submit.disabled = false;
      submit.innerHTML = label;
    };

    form.addEventListener('submit', (event) => {
      if (event.defaultPrevented || !form.checkValidity()) return;
      const tipo = form.querySelector('input[name="acceso"]')?.value;
      if (tipo) store.set(ULTIMO_ACCESO, tipo);
      /* Se deshabilita después del evento: un botón deshabilitado no manda su valor y el formulario aún no lo ha leído */
      window.setTimeout(() => {
        submit.classList.add('is-loading');
        submit.disabled = true;
        submit.firstChild.textContent = 'Entrando… ';
      }, 0);
    });

    window.addEventListener('pageshow', (event) => { if (event.persisted) restore(); });
  });
})();
