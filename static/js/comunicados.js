/* CISAHUAYO · pantalla de comunicados (templates/comunicados/inicio.html y detalle.html)

   - Detalle en ventana: cada tarjeta abre su comunicado en una ventana (lo pide con ?parcial=1); sin JavaScript, o con
     Ctrl/Cmd+clic, el enlace lleva a su página. Si quien lo abre es un destinatario, el servidor guarda ahí su primera
     lectura: la tarjeta deja de verse «Sin leer» y se avisa a los contadores (static/js/comunicados-avisos.js).
   - Filtro por fecha de creación: calendario con «Hoy», «Ayer», «Hace 7 días» (exactamente esa fecha, no un rango) y
     «Limpiar». Los atajos parten del día del colegio que manda el servidor (zona horaria del proyecto), no del reloj
     del navegador. Se combina con la búsqueda y el estado (van en el mismo formulario).
   - Papelera: entra al modo de selección; se marcan las tarjetas (solo las que se pueden eliminar) y se confirma.
   - En el detalle de quien envió: búsqueda y filtro de la lista de destinatarios y confirmación para eliminar.
*/
(() => {
  'use strict';

  const qs = (selector, ambito = document) => ambito.querySelector(selector);
  const qsa = (selector, ambito = document) => [...ambito.querySelectorAll(selector)];
  const icono = (nombre, clase) => window.CISAHUAYO?.icon?.(nombre, clase) || document.createTextNode('');
  const raiz = qs('[data-comunicados]');

  /* =============================================================== Detalle: lista de destinatarios y eliminar */
  const prepararDetalle = (detalle) => {
    if (!detalle || detalle.dataset.listo) return;
    detalle.dataset.listo = '1';

    const buscar = qs('[data-destinatarios-buscar]', detalle);
    const filas = qsa('.destinatario-fila', detalle);
    const vacio = qs('[data-destinatarios-vacio]', detalle);
    let estado = '';
    const filtrar = () => {
      const texto = (buscar?.value || '').trim().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
      let visibles = 0;
      filas.forEach((fila) => {
        const nombre = fila.dataset.nombre.normalize('NFD').replace(/[̀-ͯ]/g, '');
        const delEstado = !estado || (estado === 'sin-responder' ? fila.hasAttribute('data-sin-responder') : fila.dataset.estado === estado);
        const ver = (!texto || nombre.includes(texto)) && delEstado;
        fila.hidden = !ver;
        visibles += ver;
      });
      if (vacio) {
        vacio.hidden = Boolean(visibles);
        vacio.textContent = estado === 'leido' && !texto ? 'Nadie lo ha leído todavía.' : estado === 'pendiente' && !texto ? 'Todos lo han leído.'
          : estado === 'sin-responder' && !texto ? 'Todos han respondido.' : 'Nadie coincide con la búsqueda.';
      }
    };
    buscar?.addEventListener('input', filtrar);
    qsa('[data-destinatarios-estado]', detalle).forEach((boton) => boton.addEventListener('click', () => {
      estado = boton.dataset.destinatariosEstado;
      qsa('[data-destinatarios-estado]', detalle).forEach((otro) => {
        otro.classList.toggle('is-activo', otro === boton);
        otro.setAttribute('aria-pressed', String(otro === boton));
      });
      filtrar();
    }));

    /* Eliminar: se confirma ahí mismo (sin JavaScript, el enlace lleva a la página de confirmación) */
    const eliminar = qs('[data-detalle-eliminar]', detalle);
    const confirmar = qs('[data-detalle-confirmar]', detalle);
    const vista = qs('[data-comunicados]')?.dataset.vista;
    if (confirmar && vista && !qs('input[name="vista"]', confirmar)) {   /* al terminar, se vuelve a la misma bandeja */
      const campo = document.createElement('input');
      campo.type = 'hidden';
      campo.name = 'vista';
      campo.value = vista;
      confirmar.append(campo);
    }
    if (eliminar && confirmar) {
      eliminar.addEventListener('click', (evento) => {
        evento.preventDefault();
        confirmar.hidden = false;
        eliminar.hidden = true;
        qs('[data-detalle-confirmar-si]', confirmar)?.focus();
      });
      qs('[data-detalle-confirmar-no]', confirmar)?.addEventListener('click', () => {
        confirmar.hidden = true;
        eliminar.hidden = false;
        eliminar.focus();
      });
    }

    /* Responder y recordar sin salir de la ventana (en su propia página, el formulario normal recarga la página) */
    if (!detalle.closest('[data-detalle-modal]')) return;
    qsa('[data-responder], [data-recordar]', detalle).forEach((formulario) => formulario.addEventListener('submit', async (evento) => {
      evento.preventDefault();
      const datos = new FormData(formulario);
      if (evento.submitter?.name) datos.set(evento.submitter.name, evento.submitter.value);
      const botones = qsa('button[type="submit"]', formulario);
      botones.forEach((boton) => { boton.disabled = true; });
      try {
        const respuesta = await fetch(formulario.action, {
          method: 'POST', body: datos, credentials: 'same-origin', headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        });
        const resultado = await respuesta.json().catch(() => ({}));
        if (!respuesta.ok) throw new Error(resultado.error || 'No se pudo guardar. Inténtalo de nuevo.');
        if (formulario.matches('[data-responder]')) {
          /* La tarjeta deja de pedir respuesta y la ventana se vuelve a pedir con la respuesta ya guardada */
          qs(`[data-tarjeta="${detalle.dataset.comunicado}"] [data-tarjeta-responder]`)?.remove();
          if (origen) abrirDetalle(origen);
        } else {
          const nota = qs('.recordar-comunicado__nota', detalle);
          if (nota) nota.textContent = resultado.mensaje || 'Se recordó el comunicado.';
        }
      } catch (problema) {
        botones.forEach((boton) => { boton.disabled = false; });
        const error = qs('[data-responder-error]', formulario);
        if (error) {
          error.textContent = problema.message;
          error.hidden = false;
        } else {
          window.alert(problema.message);
        }
      }
    }));
  };
  qsa('[data-detalle-comunicado]').forEach(prepararDetalle);

  if (!raiz) return;

  /* =============================================================== Detalle en ventana */
  const ventana = qs('[data-detalle-modal]');
  const contenido = qs('[data-detalle-contenido]', ventana || document);
  let origen = null;
  let turno = 0;

  const esqueleto = () => {
    const bloque = document.createElement('div');
    bloque.className = 'form-skeleton';
    bloque.setAttribute('aria-hidden', 'true');
    ['skeleton skeleton--title', 'skeleton', 'skeleton', 'skeleton skeleton--short', 'skeleton skeleton--field', 'skeleton skeleton--field'].forEach((clases) => {
      const linea = document.createElement('span');
      linea.className = clases;
      bloque.append(linea);
    });
    return bloque;
  };

  const marcarLeida = (tarjeta) => {
    if (!tarjeta || !tarjeta.classList.contains('is-pendiente')) return false;
    tarjeta.classList.remove('is-pendiente');
    const nuevo = qs('[data-tarjeta-nuevo]', tarjeta);
    if (nuevo) nuevo.hidden = true;
    const lectura = qs('[data-tarjeta-lectura]', tarjeta);
    if (lectura) {
      lectura.replaceChildren(icono('check-check', 'icon icon--sm'), document.createTextNode(' Leído hoy'));
    }
    return true;
  };

  const abrirDetalle = async (enlace) => {
    if (!ventana || typeof ventana.showModal !== 'function') {
      window.location.href = enlace.href;
      return;
    }
    origen = enlace;
    const miTurno = ++turno;
    contenido.replaceChildren(esqueleto());
    ventana.setAttribute('aria-busy', 'true');
    if (!ventana.open) {
      ventana.showModal();
      document.documentElement.classList.add('is-scroll-locked');
    }
    try {
      const respuesta = await fetch(enlace.dataset.abrirDetalle, {
        headers: { Accept: 'text/html', 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin',
      });
      if (miTurno !== turno) return;
      if (!respuesta.ok) throw new Error(String(respuesta.status));
      const html = await respuesta.text();
      const documento = new DOMParser().parseFromString(html, 'text/html');
      const detalle = qs('[data-detalle-comunicado]', documento);
      if (!detalle) throw new Error('sin detalle');
      contenido.replaceChildren(document.adoptNode(detalle));
      ventana.setAttribute('aria-labelledby', qs('[data-detalle-titulo]', detalle)?.id || '');
      prepararDetalle(detalle);
      qs('[data-detalle-titulo]', detalle)?.focus();
      if (detalle.dataset.pendientes !== undefined) {
        const tarjeta = enlace.closest('[data-tarjeta]');
        const urgente = tarjeta?.classList.contains('tarjeta-comunicado--urgente');
        const eraPendiente = marcarLeida(tarjeta);   /* la primera lectura ya la guardó el servidor */
        document.dispatchEvent(new CustomEvent('comunicados:pendientes', {
          detail: { pendientes: Number(detalle.dataset.pendientes), urgente: Boolean(eraPendiente && urgente) },
        }));
      }
    } catch (error) {
      if (miTurno !== turno) return;
      const aviso = document.createElement('div');
      aviso.className = 'empty-state';
      aviso.setAttribute('role', 'alert');
      const titulo = document.createElement('p');
      titulo.className = 'empty-state__title';
      titulo.textContent = error.message === '404' ? 'Este comunicado ya no está disponible' : 'No se pudo abrir el comunicado';
      const texto = document.createElement('p');
      texto.className = 'empty-state__text';
      texto.textContent = error.message === '404'
        ? 'Puede que haya caducado o que se haya eliminado.'
        : 'Revisa tu conexión e inténtalo de nuevo.';
      const acciones = document.createElement('div');
      acciones.className = 'empty-state__actions';
      const reintentar = document.createElement('button');
      reintentar.type = 'button';
      reintentar.className = 'btn btn--sm';
      reintentar.textContent = 'Reintentar';
      reintentar.addEventListener('click', () => abrirDetalle(enlace));
      acciones.append(reintentar);
      aviso.append(icono('triangle-alert', 'icon icon--lg empty-state__icon'), titulo, texto, acciones);
      contenido.replaceChildren(aviso);
      reintentar.focus();
    } finally {
      if (miTurno === turno) ventana.removeAttribute('aria-busy');
    }
  };

  const cerrarDetalle = () => {
    if (ventana?.open) ventana.close();
  };

  ventana?.addEventListener('close', () => {
    turno += 1;
    contenido.replaceChildren();
    if (!qs('dialog[open]')) document.documentElement.classList.remove('is-scroll-locked');
    origen?.focus();
  });
  ventana?.addEventListener('click', (evento) => {
    if (evento.target === ventana) cerrarDetalle();   /* clic en el velo */
  });
  qs('[data-detalle-cerrar]', ventana || document)?.addEventListener('click', cerrarDetalle);

  /* =============================================================== Modo selección (papelera) */
  const barra = qs('[data-seleccion-barra]');
  const confirmarVarios = qs('[data-seleccion-confirmar]');
  const botonEliminar = qs('[data-seleccion-eliminar]');
  const papelera = qs('.comunicados__papelera[data-seleccion-alternar]');
  let seleccionando = false;

  const casillas = () => qsa('[data-seleccion-casilla]');
  const contarSeleccion = () => {
    const elegidas = casillas().filter((casilla) => casilla.checked);
    const n = elegidas.length;
    const texto = n ? `${n} comunicado${n === 1 ? '' : 's'} seleccionado${n === 1 ? '' : 's'}` : 'Ningún comunicado seleccionado';
    qsa('[data-seleccion-cuenta]').forEach((nodo) => { nodo.textContent = texto; });
    qsa('[data-seleccion-cuenta-confirmar]').forEach((nodo) => { nodo.textContent = n === 1 ? '1 comunicado' : `${n} comunicados`; });
    if (botonEliminar) botonEliminar.disabled = !n;
    casillas().forEach((casilla) => casilla.closest('[data-tarjeta]')?.classList.toggle('is-elegida', casilla.checked));
  };

  const alternarSeleccion = (activar = !seleccionando) => {
    seleccionando = activar;
    raiz.classList.toggle('is-seleccionando', activar);
    papelera?.setAttribute('aria-pressed', String(activar));
    if (barra) barra.hidden = !activar;
    qsa('[data-seleccion-marca]').forEach((marca) => { marca.hidden = !activar; });
    if (!activar) casillas().forEach((casilla) => { casilla.checked = false; });
    contarSeleccion();
    if (activar) casillas()[0]?.focus();
    else papelera?.focus();
  };

  qsa('[data-seleccion-alternar]').forEach((boton) => boton.addEventListener('click', () => alternarSeleccion()));
  raiz.addEventListener('change', (evento) => {
    if (evento.target.matches('[data-seleccion-casilla]')) contarSeleccion();
  });
  botonEliminar?.addEventListener('click', () => {
    if (!casillas().some((casilla) => casilla.checked)) return;
    if (typeof confirmarVarios?.showModal === 'function') {
      confirmarVarios.showModal();
      document.documentElement.classList.add('is-scroll-locked');
    } else if (window.confirm('¿Eliminar los comunicados seleccionados? Dejarán de verse para sus destinatarios.')) {
      barra.submit();
    }
  });

  /* Un clic en la tarjeta: con la selección activa la marca; si no, abre el detalle en la ventana */
  raiz.addEventListener('click', (evento) => {
    const enlace = evento.target.closest('[data-abrir-detalle]');
    if (!enlace || evento.defaultPrevented || evento.button !== 0 || evento.metaKey || evento.ctrlKey || evento.shiftKey || evento.altKey) return;
    evento.preventDefault();
    if (seleccionando) {
      const casilla = qs('[data-seleccion-casilla]', enlace.closest('[data-tarjeta]'));
      if (casilla) {
        casilla.checked = !casilla.checked;
        contarSeleccion();
      }
      return;
    }
    abrirDetalle(enlace);
  });

  document.addEventListener('keydown', (evento) => {
    if (evento.key === 'Escape' && seleccionando && !qs('dialog[open]')) alternarSeleccion(false);
  });

  /* =============================================================== Calendario del filtro por fecha */
  const formulario = qs('[data-comunicados-filtros]');
  /* La categoría se aplica al elegirla */
  qs('[data-comunicados-categoria]', formulario || document)?.addEventListener('change', () => formulario?.requestSubmit());
  const entrada = qs('[data-fecha-filtro]');
  const botonCalendario = qs('[data-calendario-abrir]');
  const calendario = qs('[data-calendario-filtro]');
  if (!formulario || !entrada || !botonCalendario || !calendario || !HTMLElement.prototype.showPopover) return;

  const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
  const DIAS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
  const leer = (texto) => {
    const partes = /^(\d{4})-(\d{2})-(\d{2})$/.exec(texto || '');
    return partes ? new Date(Number(partes[1]), Number(partes[2]) - 1, Number(partes[3])) : null;
  };
  const iso = (fecha) => `${fecha.getFullYear()}-${String(fecha.getMonth() + 1).padStart(2, '0')}-${String(fecha.getDate()).padStart(2, '0')}`;
  const sumarDias = (fecha, dias) => new Date(fecha.getFullYear(), fecha.getMonth(), fecha.getDate() + dias);
  const mismoDia = (a, b) => Boolean(a && b) && a.getTime() === b.getTime();
  /* «Hoy» es el del colegio (lo manda el servidor con su zona horaria), no el del reloj de este equipo */
  const hoy = leer(entrada.dataset.hoy) || (() => { const a = new Date(); return new Date(a.getFullYear(), a.getMonth(), a.getDate()); })();

  const titulo = qs('[data-calendario-mes]', calendario);
  const cuerpo = qs('[data-calendario-dias]', calendario);
  const [anterior, siguiente] = qsa('[data-calendario-paso]', calendario);
  const limpiar = qs('[data-calendario-limpiar]', calendario);
  calendario.hidden = false;
  calendario.removeAttribute('hidden');
  document.body.append(calendario);

  const elegida = leer(entrada.value);
  let mes = new Date((elegida || hoy).getFullYear(), (elegida || hoy).getMonth(), 1);
  let foco = elegida || hoy;

  qsa('[data-calendario-atajo]', calendario).forEach((atajo) => {
    atajo.classList.toggle('is-elegido', mismoDia(sumarDias(hoy, -Number(atajo.dataset.calendarioAtajo)), elegida));
  });

  const pintar = () => {
    titulo.textContent = `${MESES[mes.getMonth()]} ${mes.getFullYear()}`;
    siguiente.disabled = mes.getFullYear() > hoy.getFullYear() || (mes.getFullYear() === hoy.getFullYear() && mes.getMonth() >= hoy.getMonth());
    const inicio = sumarDias(mes, -((mes.getDay() + 6) % 7));   /* el lunes de la primera semana */
    const filas = [];
    for (let semana = 0; semana < 6; semana += 1) {
      const fila = document.createElement('tr');
      for (let dia = 0; dia < 7; dia += 1) {
        const fecha = sumarDias(inicio, semana * 7 + dia);
        const celda = document.createElement('td');
        const boton = document.createElement('button');
        boton.type = 'button';
        boton.className = 'calendario__dia';
        boton.textContent = String(fecha.getDate());
        boton.dataset.fecha = iso(fecha);
        boton.setAttribute('aria-label', `${DIAS[fecha.getDay()]} ${fecha.getDate()} de ${MESES[fecha.getMonth()]} de ${fecha.getFullYear()}`);
        if (fecha.getMonth() !== mes.getMonth()) boton.classList.add('is-otro-mes');
        if (fecha > hoy) {
          boton.disabled = true;
          boton.classList.add('is-futuro');
        }
        if (mismoDia(fecha, hoy)) {
          boton.classList.add('is-hoy');
          boton.setAttribute('aria-current', 'date');
        }
        if (mismoDia(fecha, elegida)) {
          boton.classList.add('is-elegido');
          boton.setAttribute('aria-pressed', 'true');
        }
        boton.tabIndex = mismoDia(fecha, foco) ? 0 : -1;
        celda.append(boton);
        fila.append(celda);
      }
      filas.push(fila);
      if (sumarDias(inicio, (semana + 1) * 7).getMonth() !== mes.getMonth() && semana >= 3) break;
    }
    cuerpo.replaceChildren(...filas);
  };

  const colocar = () => {
    if (window.CISAHUAYO?.pickers?.place) {
      window.CISAHUAYO.pickers.place(calendario, botonCalendario);
      return;
    }
    const ancla = botonCalendario.getBoundingClientRect();
    calendario.style.top = `${ancla.bottom + 6}px`;
    calendario.style.left = `${Math.max(8, Math.min(ancla.left, window.innerWidth - calendario.offsetWidth - 8))}px`;
  };

  const abierto = () => calendario.matches(':popover-open');
  const abrir = () => {
    mes = new Date((elegida || hoy).getFullYear(), (elegida || hoy).getMonth(), 1);
    foco = elegida || hoy;
    pintar();
    calendario.showPopover();
    colocar();
    botonCalendario.setAttribute('aria-expanded', 'true');
    qs('.calendario__dia[tabindex="0"]', calendario)?.focus();
  };
  const cerrar = (devolverFoco = true) => {
    if (abierto()) calendario.hidePopover();
    botonCalendario.setAttribute('aria-expanded', 'false');
    if (devolverFoco) botonCalendario.focus();
  };
  const aplicar = (fecha) => {
    entrada.value = fecha ? iso(fecha) : '';
    qsa('input[name="page"]', formulario).forEach((campo) => campo.remove());
    qsa('input[name="q"]', formulario).forEach((campo) => { campo.disabled = !campo.value.trim(); });   /* sin «q=» vacío */
    cerrar(false);
    formulario.requestSubmit ? formulario.requestSubmit() : formulario.submit();
  };

  botonCalendario.addEventListener('click', () => (abierto() ? cerrar() : abrir()));
  anterior.addEventListener('click', () => {
    mes = new Date(mes.getFullYear(), mes.getMonth() - 1, 1);
    foco = mes;
    pintar();
  });
  siguiente.addEventListener('click', () => {
    mes = new Date(mes.getFullYear(), mes.getMonth() + 1, 1);
    foco = mes > hoy ? hoy : mes;
    pintar();
  });
  cuerpo.addEventListener('click', (evento) => {
    const boton = evento.target.closest('.calendario__dia');
    if (boton && !boton.disabled) aplicar(leer(boton.dataset.fecha));
  });
  cuerpo.addEventListener('keydown', (evento) => {
    const pasos = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
    if (!(evento.key in pasos)) return;
    evento.preventDefault();
    const nueva = sumarDias(foco, pasos[evento.key]);
    if (nueva > hoy) return;
    foco = nueva;
    if (foco.getMonth() !== mes.getMonth() || foco.getFullYear() !== mes.getFullYear()) mes = new Date(foco.getFullYear(), foco.getMonth(), 1);
    pintar();
    qs('.calendario__dia[tabindex="0"]', calendario)?.focus();
  });
  qsa('[data-calendario-atajo]', calendario).forEach((atajo) => atajo.addEventListener('click', () => {
    aplicar(sumarDias(hoy, -Number(atajo.dataset.calendarioAtajo)));
  }));
  limpiar?.addEventListener('click', () => aplicar(null));
  calendario.addEventListener('keydown', (evento) => {
    if (evento.key === 'Escape') {
      evento.preventDefault();
      cerrar();
    }
  });
  document.addEventListener('pointerdown', (evento) => {
    if (abierto() && !calendario.contains(evento.target) && !botonCalendario.contains(evento.target)) cerrar(false);
  });
  window.addEventListener('resize', () => { if (abierto()) colocar(); });
  window.addEventListener('scroll', () => { if (abierto()) colocar(); }, { passive: true });
})();
