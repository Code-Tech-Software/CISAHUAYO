/* CISAHUAYO · pantalla de comunicados (templates/comunicados/inicio.html y detalle.html)

   - Detalle en ventana: cada tarjeta abre su comunicado en una ventana (lo pide con ?parcial=1); sin JavaScript, o con
     Ctrl/Cmd+clic, el enlace lleva a su página. Si quien lo abre es un destinatario, el servidor guarda ahí su primera
     lectura: la tarjeta deja de verse «Sin leer» y se avisa a los contadores (static/js/comunicados-avisos.js).
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

    /* Las listas del seguimiento (destinatarios y autorización por estudiante) vienen del servidor por páginas: buscar,
       filtrar y «Ver más» piden la que toca */
    qsa('[data-lista-destinatarios]', detalle).forEach((caja) => {
      const filas = qs('[data-destinatarios-filas]', caja);
      const buscar = qs('[data-destinatarios-buscar]', caja);
      let estado = '';
      let pausa = null;
      let pedido = null;
      const pedirFilas = async (pagina = 1) => {
        pedido?.abort();
        const este = new AbortController();
        pedido = este;
        const url = new URL(caja.dataset.destinatariosUrl, window.location.href);
        url.searchParams.set('pagina', pagina);
        if (estado) url.searchParams.set('estado', estado);
        if (buscar?.value.trim()) url.searchParams.set('q', buscar.value.trim());
        filas.setAttribute('aria-busy', 'true');
        try {
          const respuesta = await fetch(url, { credentials: 'same-origin', signal: este.signal });
          if (!respuesta.ok) throw new Error(String(respuesta.status));
          const plantilla = document.createElement('template');
          plantilla.innerHTML = await respuesta.text();
          if (pagina === 1) filas.replaceChildren(plantilla.content);
          else {
            qs('.lista-destinatarios__mas', filas)?.remove();
            filas.append(plantilla.content);
          }
        } catch (problema) {
          if (problema.name === 'AbortError') return;
          const aviso = document.createElement('li');
          aviso.className = 'lista-destinatarios__vacio';
          aviso.textContent = 'No se pudo cargar la lista. Inténtalo de nuevo.';
          filas.replaceChildren(aviso);
        } finally {
          if (pedido === este) filas.removeAttribute('aria-busy');
        }
      };
      buscar?.addEventListener('input', () => {
        window.clearTimeout(pausa);
        pausa = window.setTimeout(() => pedirFilas(), 250);
      });
      qsa('[data-destinatarios-estado]', caja).forEach((boton) => boton.addEventListener('click', () => {
        estado = boton.dataset.destinatariosEstado;
        qsa('[data-destinatarios-estado]', caja).forEach((otro) => {
          otro.classList.toggle('is-activo', otro === boton);
          otro.setAttribute('aria-pressed', String(otro === boton));
        });
        pedirFilas();
      }));
      filas.addEventListener('click', (evento) => {
        const mas = evento.target.closest('[data-destinatarios-mas]');
        if (!mas) return;
        mas.disabled = true;
        pedirFilas(Number(mas.dataset.destinatariosMas));
      });
    });

    /* «Ir a tu respuesta»: sin cambiar la dirección */
    qs('[data-ir-a-respuesta]', detalle)?.addEventListener('click', (evento) => {
      evento.preventDefault();
      qs('[data-respuesta-comunicado]', detalle)?.scrollIntoView({ block: 'center' });
      qs('[data-respuesta-comunicado] button, [data-respuesta-comunicado] input', detalle)?.focus();
    });

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
          /* La ventana se vuelve a pedir con la respuesta ya guardada; al llegar, la fila toma su estado nuevo */
          if (origen) abrirDetalle(origen, { historia: false });
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

  /* La fila dice lo que dice el servidor: su estado, con icono y texto */
  const ponerEstado = (fila, detalle) => {
    if (!fila || !detalle.dataset.estadoClave) return false;
    const eraPendiente = fila.classList.contains('is-pendiente');
    fila.className = fila.className.replace(/fila-comunicado--\S+/, `fila-comunicado--${detalle.dataset.estadoClave}`);
    fila.classList.remove('is-pendiente');
    const estado = qs('[data-fila-estado]', fila);
    if (estado) estado.textContent = detalle.dataset.estadoTexto;
    qs('[data-fila-icono]', fila)?.replaceChildren(icono(detalle.dataset.estadoIcono, 'icon icon--sm'));
    return eraPendiente;
  };

  const abrirDetalle = async (enlace, { historia = true } = {}) => {
    if (!ventana || typeof ventana.showModal !== 'function') {
      window.location.href = enlace.href;
      return;
    }
    origen = enlace;
    const miTurno = ++turno;
    contenido.replaceChildren(esqueleto());
    ventana.setAttribute('aria-busy', 'true');
    if (!ventana.open) {
      /* Cada comunicado abierto tiene su dirección: se puede compartir y «Atrás» regresa a la lista */
      if (historia) window.history.pushState({ comunicado: enlace.getAttribute('href') }, '', enlace.href);
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
        const fila = enlace.closest('[data-fila]');
        const urgente = fila?.classList.contains('fila-comunicado--urgente');
        const eraPendiente = ponerEstado(fila, detalle);   /* la primera apertura ya la guardó el servidor */
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
      if (error.message !== '404') acciones.append(reintentar);
      aviso.append(icono('triangle-alert', 'icon icon--lg empty-state__icon'), titulo, texto, acciones);
      contenido.replaceChildren(aviso);
      (reintentar.isConnected ? reintentar : qs('[data-detalle-cerrar]', ventana))?.focus();
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
    if (window.history.state?.comunicado) window.history.back();
  });
  window.addEventListener('popstate', (evento) => {
    if (!evento.state?.comunicado) {
      cerrarDetalle();
      return;
    }
    const enlace = qsa('[data-abrir-detalle]').find((candidato) => candidato.getAttribute('href') === evento.state.comunicado);
    if (enlace) abrirDetalle(enlace, { historia: false });
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
    casillas().forEach((casilla) => casilla.closest('[data-fila]')?.classList.toggle('is-elegida', casilla.checked));
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
      const casilla = qs('[data-seleccion-casilla]', enlace.closest('[data-fila]'));
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
})();
