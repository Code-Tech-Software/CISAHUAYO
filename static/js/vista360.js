/* CISAHUAYO · Vista 360 del estudiante (templates/alumnos/vista360.html)

   - Cada indicador del círculo (o tarjeta, en pantallas angostas) abre su panel de detalle sin recargar; un segundo
     clic, la «X» del panel o Escape lo cierran y el foco vuelve al indicador. Sin JavaScript son enlaces que abren la
     misma página con ?seccion=… (el servidor muestra ese panel).
   - Las flechas mueven el foco entre los indicadores en el orden del círculo; Enter o la barra espaciadora los abren.
   - La sección abierta queda en la dirección (?seccion=…) y en el formulario de filtros, para conservarla al cambiar
     de ciclo o de periodo.
   - Los filtros se aplican al cambiarlos, con un aviso de carga. Al cambiar de ciclo se usa el periodo predeterminado
     del ciclo nuevo (los periodos son de cada ciclo).
*/
(() => {
  'use strict';

  const raiz = document.querySelector('[data-vista360]');
  if (!raiz) return;

  const principal = raiz.querySelector('[data-v360-principal]');
  const botones = [...raiz.querySelectorAll('[data-v360-boton]')];
  const paneles = new Map([...raiz.querySelectorAll('[data-v360-panel]')].map((panel) => [panel.dataset.v360Panel, panel]));
  const trazos = new Map([...raiz.querySelectorAll('[data-v360-trazo]')].map((trazo) => [trazo.dataset.v360Trazo, trazo]));
  const filtros = raiz.querySelector('[data-v360-filtros]');
  const sinMovimiento = window.matchMedia('(prefers-reduced-motion: reduce)');

  const botonDe = (clave) => botones.find((boton) => boton.dataset.v360Boton === clave);

  const recordar = (clave) => {
    const url = new URL(window.location.href);
    if (clave) {
      url.searchParams.set('seccion', clave);
      url.hash = `panel-${clave}`;
    } else {
      url.searchParams.delete('seccion');
      url.hash = '';
    }
    window.history.replaceState(null, '', url);
    if (!filtros) return;
    let campo = filtros.querySelector('[data-v360-seccion-campo]');
    if (clave && !campo) {
      campo = document.createElement('input');
      campo.type = 'hidden';
      campo.name = 'seccion';
      campo.setAttribute('data-v360-seccion-campo', '');
      filtros.append(campo);
    }
    if (clave) campo.value = clave;
    else if (campo) campo.remove();
  };

  const mostrar = (clave, { enfocar = true } = {}) => {
    paneles.forEach((panel, otra) => {
      const abierta = otra === clave;
      panel.hidden = !abierta;
      trazos.get(otra)?.classList.toggle('is-abierta', abierta);
      botonDe(otra)?.setAttribute('aria-expanded', String(abierta));
    });
    recordar(clave);
    const panel = paneles.get(clave);
    if (panel && enfocar) {
      panel.focus({ preventScroll: true });
      panel.scrollIntoView({ behavior: sinMovimiento.matches ? 'auto' : 'smooth', block: 'nearest' });
    }
  };

  const cerrar = () => {
    const abierta = [...paneles].find(([, panel]) => !panel.hidden)?.[0];
    mostrar(null);
    botonDe(abierta)?.focus();
  };

  const alternar = (clave) => {
    if (paneles.get(clave)?.hidden === false) cerrar();
    else mostrar(clave);
  };

  botones.forEach((boton, indice) => {
    boton.addEventListener('click', (evento) => {
      if (evento.metaKey || evento.ctrlKey || evento.shiftKey || evento.button !== 0) return;   // abrir en otra pestaña
      evento.preventDefault();
      alternar(boton.dataset.v360Boton);
    });
    boton.addEventListener('keydown', (evento) => {
      const pasos = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
      if (evento.key === ' ') {
        evento.preventDefault();
        alternar(boton.dataset.v360Boton);
      } else if (evento.key in pasos) {
        evento.preventDefault();
        botones[(indice + pasos[evento.key] + botones.length) % botones.length].focus();
      } else if (evento.key === 'Home' || evento.key === 'End') {
        evento.preventDefault();
        botones[evento.key === 'Home' ? 0 : botones.length - 1].focus();
      }
    });
  });

  trazos.forEach((trazo, clave) => trazo.addEventListener('click', () => alternar(clave)));

  paneles.forEach((panel) => {
    panel.querySelector('[data-v360-cerrar]')?.addEventListener('click', cerrar);
    panel.addEventListener('keydown', (evento) => {
      if (evento.key === 'Escape' && !evento.defaultPrevented && !evento.target.closest('[data-menu], dialog')) {
        evento.preventDefault();
        cerrar();
      }
    });
  });

  // Sin ?seccion= pero con #panel-… (un enlace guardado): abre ese panel
  if (![...paneles.values()].some((panel) => !panel.hidden)) {
    const clave = window.location.hash.replace('#panel-', '');
    if (paneles.has(clave)) mostrar(clave, { enfocar: false });
  }

  // --- Que los textos del círculo quepan en su caja ------------------------------------------------------------
  // Cada indicador tiene la caja que cabe dentro de su segmento (y el centro, la que cabe en el hueco). Si con el
  // tamaño de letra normal no cabe (un nombre largo, una cifra ancha, otra fuente), se achica de 5 en 5 % hasta un
  // 60 %; lo que aún sobrara se recorta dentro de la caja, nunca sale del anillo. En tarjetas no hace falta.
  const circulo = raiz.querySelector('[data-v360-circulo]');
  const anillo = circulo?.querySelector('.v360-circulo__anillo');
  const ajustables = [...raiz.querySelectorAll('[data-v360-ajustable]')];
  const seDesborda = (el) => el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1;
  let pendiente = 0;

  const ajustar = () => {
    pendiente = 0;
    const enCirculo = anillo && getComputedStyle(anillo).display !== 'none';
    ajustables.forEach((el) => {
      el.style.removeProperty('--v360-ajuste');
      if (!enCirculo) return;
      for (let ajuste = 0.95; seDesborda(el) && ajuste >= 0.6; ajuste -= 0.05) {
        el.style.setProperty('--v360-ajuste', ajuste.toFixed(2));
      }
    });
  };
  const programar = () => {
    if (!pendiente) pendiente = window.requestAnimationFrame(ajustar);
  };

  if (circulo) {
    ajustar();
    document.fonts?.ready.then(programar);
    if ('ResizeObserver' in window) new ResizeObserver(programar).observe(circulo);
    else window.addEventListener('resize', programar);
  }

  // --- Filtros: se aplican al cambiarlos, con aviso de carga ---------------------------------------------------
  if (filtros) {
    const aplicar = filtros.querySelector('[data-v360-aplicar]');
    const aviso = raiz.querySelector('[data-v360-cargando]');
    const ciclo = filtros.querySelector('[name="ciclo"]');
    const periodo = filtros.querySelector('[name="periodo"]');
    if (aplicar) aplicar.hidden = true;

    const cargando = (si) => {
      principal?.classList.toggle('is-cargando', si);
      principal?.setAttribute('aria-busy', String(si));
      if (aviso) aviso.hidden = !si;
    };

    filtros.addEventListener('change', (evento) => {
      if (evento.target === ciclo && periodo) periodo.disabled = true;   // el periodo predeterminado del ciclo nuevo
      cargando(true);
      filtros.requestSubmit();
    });
    filtros.addEventListener('submit', () => cargando(true));
    // Al volver con «Atrás» la página puede salir de la memoria del navegador tal como se dejó
    window.addEventListener('pageshow', () => {
      if (periodo) periodo.disabled = false;
      cargando(false);
    });
  }
})();
