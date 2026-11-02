/* CISAHUAYO · Agenda / Calendario (templates/agenda/calendario.html)

   - Al tocar un evento se abre su ventana de detalle con los datos que ya trae la página (#agenda-eventos). Sin
     JavaScript, o con Ctrl/Cmd+clic, el enlace lleva a la página del evento (o al mes, si es de otro módulo sin página).
     Un comunicado o una reunión llevan a su propia página. La ventana solo muestra lo que ese evento tiene: para quién
     es, sus archivos, si está cancelado (con su motivo), «Confirmar asistencia» (familias) y las acciones (agregar a mi
     calendario; para quien lo gestiona: detalle, duplicar, cancelar o reactivar, eliminar y editar).
   - Editar, Duplicar, Cancelar y Eliminar cierran el detalle y abren su formulario en la ventana de modal-form.js.
   - La vista (mes, semana, próximos, ciclo), el nivel, el grado o grupo, el tipo y la búsqueda también se cambian sin
     recargar: mientras llega, lo actual se atenúa con «Cargando…»; si falla, queda un aviso con «Reintentar». La
     dirección cambia, así que Atrás y Adelante funcionan; tras cambiar, el foco vuelve al mismo control.
   - En el teléfono, el mes actual se abre en el día de hoy (o el siguiente con eventos) y el mes en miniatura lleva a
     cada día de la lista.
   - «+N eventos» se cierra al tocar fuera o con Escape, y solo uno queda abierto a la vez.
*/
(() => {
  'use strict';

  const raiz = document.querySelector('[data-agenda]');
  if (!raiz) return;

  const qs = (selector, ambito = raiz) => ambito.querySelector(selector);
  const telefono = window.matchMedia('(max-width: 47.99rem)');
  const sinMovimiento = window.matchMedia('(prefers-reduced-motion: reduce)');
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

  const ponerAdjuntos = (lista, adjuntos) => {
    if (!lista) return;
    lista.replaceChildren(...(adjuntos || []).map((adjunto) => {
      const elemento = document.createElement('li');
      const enlace = document.createElement('a');
      enlace.className = 'agenda-adjuntos__archivo';
      enlace.href = adjunto.url;
      enlace.target = '_blank';
      enlace.rel = 'noopener';
      const icono = window.CISAHUAYO?.icon?.('paperclip');
      if (icono) enlace.append(icono);
      enlace.append(` ${adjunto.nombre}`);
      elemento.append(enlace);
      return elemento;
    }));
    lista.hidden = !(adjuntos || []).length;
  };

  const abrirDetalle = (enlace) => {
    const dialogo = qs('[data-agenda-detalle]');
    if (typeof dialogo?.showModal !== 'function') return false;
    const evento = eventos().find((dato) => String(dato.id) === enlace.dataset.agendaEvento);
    if (!evento || evento.navega) return false;   /* un comunicado o una reunión: el enlace lleva a su página */

    const poner = (nombre, texto) => {
      const nodo = qs(`[data-agenda-detalle-${nombre}]`, dialogo);
      if (nodo) nodo.textContent = texto || '';
    };
    const mostrar = (nombre, visible) => {
      const nodo = qs(`[data-agenda-detalle-${nombre}]`, dialogo);
      if (nodo) nodo.hidden = !visible;
    };
    dialogo.style.setProperty('--color', evento.color);
    dialogo.style.setProperty('--texto', evento.colorTexto);
    dialogo.classList.toggle('is-cancelado', Boolean(evento.cancelado));
    poner('alcance', evento.alcance);
    poner('titulo', evento.titulo);
    poner('fechas', evento.fechas);
    poner('horario', evento.horario);
    poner('lugar', evento.lugar);
    poner('publico', evento.publico);
    poner('repeticion', evento.repeticion);
    poner('tipo', evento.tipo);
    poner('motivo', evento.cancelado ? `Se canceló.${evento.motivo ? ` ${evento.motivo}` : ''}` : '');
    /* La descripción ya viene escapada del servidor, con sus direcciones como enlaces (Agenda/reglas.descripcion_html) */
    const descripcion = qs('[data-agenda-detalle-descripcion]', dialogo);
    if (descripcion) descripcion.innerHTML = evento.descripcionHtml || '';
    ponerAdjuntos(qs('[data-agenda-detalle-adjuntos]', dialogo), evento.adjuntos);
    mostrar('con-lugar', evento.lugar);
    mostrar('con-publico', evento.publico);
    mostrar('con-repeticion', evento.repeticion);
    mostrar('tipo', evento.tipo);
    mostrar('cancelado', evento.cancelado);
    mostrar('motivo', evento.cancelado);
    mostrar('importante', evento.importante && !evento.cancelado);
    mostrar('con-confirmar', evento.confirmar);
    /* Cada acción, solo si ese evento la tiene (los días sin clases o las fechas de calificaciones no se editan aquí) */
    ['editar', 'eliminar', 'duplicar', 'calendario', 'cancelar', 'confirmar', 'resumen'].forEach((accion) => {
      const boton = qs(`[data-agenda-detalle-${accion}]`, dialogo);
      if (!boton) return;
      boton.hidden = !evento[accion];
      if (evento[accion]) boton.href = evento[accion];
    });
    const reactivar = qs('[data-agenda-detalle-reactivar]', dialogo);
    if (reactivar) {
      reactivar.hidden = !evento.reactivar;
      if (evento.reactivar) reactivar.action = evento.reactivar;
    }

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

  /* --------------------------------------------------------------------------- El teléfono: ir a un día */
  const irA = (seccion) => {
    seccion?.scrollIntoView({ block: 'start', behavior: sinMovimiento.matches ? 'auto' : 'smooth' });
  };

  /* El mes actual se abre en hoy (o el siguiente día con eventos); si es el primero de la lista, no se mueve nada */
  const irAHoy = () => {
    if (!telefono.matches || raiz.dataset.modo !== 'mes' || !('esActual' in raiz.dataset)) return;
    const secciones = [...raiz.querySelectorAll('.agenda-lista [data-fecha]')];
    const destino = secciones.find((seccion) => seccion.dataset.fecha >= raiz.dataset.hoy);
    if (destino && destino !== secciones[0]) irA(destino);
  };

  /* --------------------------------------------------------------------------- Cambiar de mes, de vista o de filtro */
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

  /* Tras cambiar el contenido, el foco vuelve al mismo control (mes anterior, Hoy, mes siguiente, una vista o un filtro) */
  const enfocar = (foco) => {
    if (typeof foco === 'string' && foco.startsWith('filtro:')) qs(`[data-agenda-filtrar="${foco.slice(7)}"]`)?.focus();
    else if (foco === 'buscar') qs('[data-agenda-buscar]')?.focus();
    else if (Number.isInteger(foco)) raiz.querySelectorAll('[data-agenda-navegar]')[foco]?.focus();
  };

  const copiarDatos = (nuevo) => {
    ['hoy', 'modo'].forEach((clave) => { raiz.dataset[clave] = nuevo.dataset[clave] || ''; });
    if ('esActual' in nuevo.dataset) raiz.dataset.esActual = '';
    else delete raiz.dataset.esActual;
  };

  const cargar = async (destino, { historial = true, foco = null, hoy = false } = {}) => {
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
      copiarDatos(nuevo);
      if (pagina.title) document.title = pagina.title;
      if (historial) history.pushState({ agenda: true }, '', destino);
      enfocar(foco);
      if (hoy) irAHoy();
    } catch (error) {
      if (mio !== turno) return;
      cargando(false);
      mostrarError(destino);
    }
  };

  const sinModificadores = (evento) => evento.button === 0 && !evento.metaKey && !evento.ctrlKey && !evento.shiftKey && !evento.altKey;

  raiz.addEventListener('click', (evento) => {
    /* Editar, duplicar, cancelar o eliminar desde el detalle: se cierra el detalle y modal-form.js abre el formulario */
    const accion = evento.target.closest('[data-agenda-detalle-editar], [data-agenda-detalle-eliminar], [data-agenda-detalle-duplicar], [data-agenda-detalle-cancelar]');
    if (accion) {
      origen = null;
      accion.closest('dialog')?.close();
      return;
    }

    if (evento.defaultPrevented || !sinModificadores(evento)) return;

    const dia = evento.target.closest('a[data-agenda-ir-al-dia]');
    if (dia) {
      const seccion = document.getElementById(dia.getAttribute('href').slice(1));
      if (seccion) {
        evento.preventDefault();
        irA(seccion);
      }
      return;
    }

    const navegar = evento.target.closest('a[data-agenda-navegar]');
    if (navegar && window.fetch && window.DOMParser) {
      evento.preventDefault();
      const foco = [...raiz.querySelectorAll('[data-agenda-navegar]')].indexOf(navegar);
      cargar(navegar.href, { foco, hoy: 'agendaHoy' in navegar.dataset });
      return;
    }

    const enlace = evento.target.closest('a[data-agenda-evento]');
    if (enlace && abrirDetalle(enlace)) evento.preventDefault();
  });

  /* El nivel, el grado o grupo y el tipo se aplican al elegirlos; la búsqueda, al enviarla (sin JavaScript queda el
     botón «Filtrar»). La fecha que se está viendo va en el formulario (campos ocultos). */
  const destinoDe = (formulario) => {
    const destino = new URL(formulario.action, location.href);
    const datos = new URLSearchParams();
    new FormData(formulario).forEach((valor, nombre) => { if (String(valor).trim()) datos.set(nombre, String(valor).trim()); });
    destino.search = datos.toString();
    return destino.href;
  };
  raiz.addEventListener('change', (evento) => {
    const filtro = evento.target.closest('[data-agenda-filtrar]');
    if (!filtro) return;
    const formulario = filtro.form;
    if (!window.fetch || !window.DOMParser) {
      formulario.submit();
      return;
    }
    cargar(destinoDe(formulario), { foco: `filtro:${filtro.dataset.agendaFiltrar}` });
  });
  raiz.addEventListener('submit', (evento) => {
    const formulario = evento.target.closest('[data-agenda-filtro]');
    if (!formulario || !window.fetch || !window.DOMParser) return;
    evento.preventDefault();
    cargar(destinoDe(formulario), { foco: 'buscar' });
  });

  /* Atrás y Adelante entre meses ya vistos */
  history.replaceState({ ...(history.state || {}), agenda: true }, '');
  window.addEventListener('popstate', (evento) => {
    if (evento.state?.agenda) cargar(location.href, { historial: false });
  });

  irAHoy();
})();
