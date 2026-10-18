/* CISAHUAYO · Agenda / Calendario (templates/agenda/calendario.html)

   - Al tocar un evento se abre su ventana de detalle con los datos que ya trae la página (#agenda-eventos). Sin
     JavaScript, o con Ctrl/Cmd+clic, el enlace lleva a la página del evento.
   - Editar y Eliminar (solo quien gestiona) cierran el detalle y abren su formulario en la ventana de modal-form.js.
   - Cambiar de mes o de nivel trae el mes nuevo sin recargar toda la página: mientras llega, lo actual se atenúa con
     «Cargando…»; si falla, queda un aviso con «Reintentar». La dirección cambia, así que Atrás y Adelante funcionan.
   - «+N eventos» se cierra al tocar fuera o con Escape, y solo uno queda abierto a la vez.
*/
(() => {
  'use strict';

  const raiz = document.querySelector('[data-agenda]');
  if (!raiz) return;

  const qs = (selector, ambito = raiz) => ambito.querySelector(selector);
  let origen = null;
  let turno = 0;

  /* --------------------------------------------------------------------------- Detalle */
  const eventos = () => {
    try {
      return JSON.parse(document.getElementById('agenda-eventos')?.textContent || '[]');
    } catch (error) {
      return [];
    }
  };

  const abrirDetalle = (enlace) => {
    const dialogo = qs('[data-agenda-detalle]');
    if (typeof dialogo?.showModal !== 'function') return false;
    const evento = eventos().find((dato) => String(dato.id) === enlace.dataset.agendaEvento);
    if (!evento) return false;

    const poner = (nombre, texto) => {
      const nodo = qs(`[data-agenda-detalle-${nombre}]`, dialogo);
      if (nodo) nodo.textContent = texto || '';
    };
    dialogo.style.setProperty('--color', evento.color);
    dialogo.style.setProperty('--texto', evento.colorTexto);
    poner('alcance', evento.alcance);
    poner('titulo', evento.titulo);
    poner('fechas', evento.fechas);
    poner('horario', evento.horario);
    poner('lugar', evento.lugar);
    poner('descripcion', evento.descripcion);
    const conLugar = qs('[data-agenda-detalle-con-lugar]', dialogo);
    if (conLugar) conLugar.hidden = !evento.lugar;
    const editar = qs('[data-agenda-detalle-editar]', dialogo);
    const eliminar = qs('[data-agenda-detalle-eliminar]', dialogo);
    if (editar && evento.editar) editar.href = evento.editar;
    if (eliminar && evento.eliminar) eliminar.href = evento.eliminar;

    origen = enlace;
    document.dispatchEvent(new CustomEvent('app:close-menus'));
    dialogo.showModal();
    document.documentElement.classList.add('is-scroll-locked');
    return true;
  };

  /* Al cerrar, el foco vuelve al evento que se tocó (si sigue en la página) */
  raiz.addEventListener('close', (evento) => {
    if (!evento.target.matches?.('[data-agenda-detalle]')) return;
    const volver = origen;
    origen = null;
    if (volver?.isConnected) volver.focus({ preventScroll: true });
  }, true);

  /* --------------------------------------------------------------------------- «+N eventos» */
  const cerrarMas = (excepto = null) => {
    raiz.querySelectorAll('details.agenda-mas[open]').forEach((mas) => {
      if (mas !== excepto) mas.open = false;
    });
  };

  /* «toggle» no burbujea: se escucha en la captura. Si la lista no cabe abajo y sí arriba, se abre hacia arriba */
  raiz.addEventListener('toggle', (evento) => {
    const mas = evento.target;
    if (!mas.matches?.('details.agenda-mas') || !mas.open) return;
    cerrarMas(mas);
    mas.classList.remove('is-arriba');
    const panel = qs('.agenda-mas__panel', mas);
    const caja = panel?.getBoundingClientRect();
    if (caja && caja.bottom > window.innerHeight && caja.height + 8 < mas.getBoundingClientRect().top) {
      mas.classList.add('is-arriba');
    }
  }, true);

  document.addEventListener('click', (evento) => {
    if (evento.target.closest('dialog')) return;
    cerrarMas(evento.target.closest('details.agenda-mas'));
  });

  document.addEventListener('keydown', (evento) => {
    if (evento.key !== 'Escape' || document.querySelector('dialog[open]')) return;
    const abierto = qs('details.agenda-mas[open]');
    if (!abierto) return;
    abierto.open = false;
    qs('summary', abierto)?.focus();
  });

  /* --------------------------------------------------------------------------- Cambiar de mes o de nivel */
  const quitarError = () => qs('[data-agenda-error]')?.remove();

  const mostrarError = (destino) => {
    quitarError();
    const aviso = document.createElement('p');
    aviso.className = 'agenda-aviso agenda-aviso--error';
    aviso.setAttribute('role', 'alert');
    aviso.dataset.agendaError = '';
    const reintentar = document.createElement('a');
    reintentar.href = destino;
    reintentar.textContent = 'Reintentar';
    aviso.append('No se pudo cargar el calendario. Revisa tu conexión. ', reintentar);
    qs('[data-agenda-cargando]')?.after(aviso);
  };

  const cargando = (activo) => {
    const cuerpo = qs('[data-agenda-cuerpo]');
    const aviso = qs('[data-agenda-cargando]');
    cuerpo?.classList.toggle('is-cargando', activo);
    if (activo) cuerpo?.setAttribute('aria-busy', 'true');
    else cuerpo?.removeAttribute('aria-busy');
    if (aviso) aviso.hidden = !activo;
  };

  /* Tras cambiar el contenido, el foco vuelve al mismo control (mes anterior, Hoy, mes siguiente o el nivel) */
  const enfocar = (foco) => {
    if (foco === 'nivel') qs('[data-agenda-nivel]')?.focus();
    else if (Number.isInteger(foco)) raiz.querySelectorAll('[data-agenda-navegar]')[foco]?.focus();
  };

  const cargar = async (destino, { historial = true, foco = null } = {}) => {
    const mio = ++turno;
    quitarError();
    cerrarMas();
    cargando(true);
    try {
      const respuesta = await fetch(destino, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' });
      if (mio !== turno) return;
      if (!respuesta.ok) throw new Error(String(respuesta.status));
      const pagina = new DOMParser().parseFromString(await respuesta.text(), 'text/html');
      if (mio !== turno) return;
      const nuevo = pagina.querySelector('[data-agenda]');
      if (!nuevo) throw new Error('sin agenda');              /* p. ej. la sesión venció y llegó la página de acceso */
      raiz.replaceChildren(...nuevo.childNodes);
      if (pagina.title) document.title = pagina.title;
      if (historial) history.pushState({ agenda: true }, '', destino);
      enfocar(foco);
    } catch (error) {
      if (mio !== turno) return;
      cargando(false);
      mostrarError(destino);
    }
  };

  const sinModificadores = (evento) => evento.button === 0 && !evento.metaKey && !evento.ctrlKey && !evento.shiftKey && !evento.altKey;

  raiz.addEventListener('click', (evento) => {
    /* Editar o eliminar desde el detalle: se cierra el detalle y modal-form.js abre el formulario */
    const accion = evento.target.closest('[data-agenda-detalle-editar], [data-agenda-detalle-eliminar]');
    if (accion) {
      origen = null;
      accion.closest('dialog')?.close();
      return;
    }

    if (evento.defaultPrevented || !sinModificadores(evento)) return;

    const navegar = evento.target.closest('a[data-agenda-navegar]');
    if (navegar && window.fetch && window.DOMParser) {
      evento.preventDefault();
      const foco = [...raiz.querySelectorAll('[data-agenda-navegar]')].indexOf(navegar);
      cargar(navegar.href, { foco });
      return;
    }

    const enlace = evento.target.closest('a[data-agenda-evento]');
    if (enlace && abrirDetalle(enlace)) evento.preventDefault();
  });

  /* El nivel se aplica al elegirlo (sin JavaScript queda el botón «Filtrar») */
  raiz.addEventListener('change', (evento) => {
    const nivel = evento.target.closest('[data-agenda-nivel]');
    if (!nivel) return;
    const formulario = nivel.form;
    if (!window.fetch || !window.DOMParser) {
      formulario.submit();
      return;
    }
    const destino = new URL(formulario.action, location.href);
    destino.search = new URLSearchParams(new FormData(formulario)).toString();
    if (!nivel.value) destino.searchParams.delete('nivel');
    cargar(destino.href, { foco: 'nivel' });
  });

  /* Atrás y Adelante entre meses ya vistos */
  history.replaceState({ ...(history.state || {}), agenda: true }, '');
  window.addEventListener('popstate', (evento) => {
    if (evento.state?.agenda) cargar(location.href, { historial: false });
  });
})();
