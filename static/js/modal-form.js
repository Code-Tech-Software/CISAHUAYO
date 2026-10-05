/* CISAHUAYO · formularios en ventanas modales

   Los enlaces con data-modal-form (Nuevo…, Editar…) abren su formulario dentro de una ventana, sin salir de la página:
   - Se pide la página del formulario con fetch y se muestra su título, su descripción y su formulario. Las páginas
     siguen existiendo tal cual: sin JavaScript, o con Ctrl/Cmd+clic, el enlace lleva a la página completa.
   - El formulario se envía con fetch a su misma dirección. Si el servidor lo acepta responde con una redirección, que
     el middleware CISAHUAYO.modal convierte en JSON {"redirect": url}: la página navega ahí (al listado, con su mensaje).
     Si hay errores, el servidor devuelve la página con el formulario corregido y aquí se vuelve a pintar con sus avisos.
   - Los estilos y scripts propios de cada formulario (asistente de alumnos, búsquedas en vivo...) se cargan al vuelo y los
     scripts se vuelven a ejecutar cada vez que se abre: cada uno se engancha a su formulario recién puesto en la ventana.
   - Calidad: esqueleto mientras carga, foco en el primer campo (o en el primero con error), botón «Guardando…», cierre con
     Escape, con la X o al tocar fuera, y confirmación antes de descartar lo que se escribió.
*/
(() => {
  'use strict';

  const dialogo = document.querySelector('[data-form-modal]');
  if (!dialogo || typeof dialogo.showModal !== 'function' || !window.fetch || !window.DOMParser) return;

  const raiz = document.documentElement;
  const qs = (selector, ambito = dialogo) => ambito.querySelector(selector);
  const titulo = qs('[data-form-modal-title]');
  const descripcion = qs('[data-form-modal-description]');
  const cuerpo = qs('[data-form-modal-body]');
  const confirmacion = qs('[data-form-modal-confirm]');

  const ENCABEZADOS = { 'X-Requested-With': 'XMLHttpRequest', 'X-Modal-Form': '1' };
  const DE_LA_BASE = new Set(['app.js', 'preload.js', 'modal-form.js']);   /* los de la plantilla base no se recargan */
  const FORMULARIO = 'form.form-page, form.wizard';

  let direccion = '';
  let origen = null;
  let modificado = false;
  let ocupado = false;
  let navegando = false;
  let turno = 0;

  /* --------------------------------------------------------------------------- Ayudantes */
  const nombreDe = (ruta) => new URL(ruta, location.href).pathname.split('/').pop().replace(/\.[0-9a-f]{12}(?=\.\w+$)/, '');

  const esperar = (nodo) => new Promise((resuelto) => {
    nodo.addEventListener('load', resuelto, { once: true });
    nodo.addEventListener('error', resuelto, { once: true });
  });

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

  /* Con la confirmación a la vista, lo de atrás queda inerte: ni el teclado ni los lectores de pantalla llegan al formulario */
  const fondoInerte = (valor) => {
    dialogo.querySelectorAll('.modal__header, .modal__body').forEach((zona) => { zona.inert = valor; });
  };
  let campoPrevio = null;
  const mostrarConfirmacion = () => {
    campoPrevio = cuerpo.contains(document.activeElement) ? document.activeElement : null;
    confirmacion.hidden = false;
    fondoInerte(true);
    qs('[data-form-modal-seguir]').focus();
  };
  const ocultarConfirmacion = () => {
    const habiaConfirmacion = !confirmacion.hidden;
    confirmacion.hidden = true;
    fondoInerte(false);
    if (habiaConfirmacion && campoPrevio?.isConnected) campoPrevio.focus({ preventScroll: true });
    campoPrevio = null;
  };

  /* Estilos que la página del formulario necesita y la página actual no tiene */
  const asegurarEstilos = async (documento, destino) => {
    const cargados = new Set([...document.querySelectorAll('link[rel="stylesheet"]')].map((enlace) => new URL(enlace.href, location.href).pathname));
    const pendientes = [];
    documento.querySelectorAll('link[rel="stylesheet"]').forEach((enlace) => {
      const href = new URL(enlace.getAttribute('href'), destino).href;
      const ruta = new URL(href).pathname;
      if (cargados.has(ruta)) return;
      const nuevo = document.createElement('link');
      nuevo.rel = 'stylesheet';
      nuevo.href = href;
      document.head.append(nuevo);
      cargados.add(ruta);
      pendientes.push(esperar(nuevo));
    });
    await Promise.all(pendientes);
  };

  /* Scripts propios del formulario: se insertan de nuevo (y por tanto se ejecutan) cada vez, uno tras otro */
  const ejecutarScripts = async (documento, destino) => {
    const fuentes = [...documento.querySelectorAll('script[src]')]
      .map((script) => new URL(script.getAttribute('src'), destino).href)
      .filter((fuente) => !DE_LA_BASE.has(nombreDe(fuente)));
    for (const fuente of fuentes) {
      const nodo = document.createElement('script');
      nodo.src = fuente;
      nodo.async = false;
      document.body.append(nodo);
      await esperar(nodo);
      nodo.remove();
    }
  };

  /* El formulario trae sus propios ids y la página de atrás también tiene los suyos: si alguno se repite (por ejemplo
     «modal-eliminar» en un horario), se renombra con sus referencias. Así las etiquetas, los lectores de pantalla y los
     botones que abren diálogos apuntan siempre al elemento de la ventana. */
  const REFERENCIAS_A_IDS = ['for', 'aria-labelledby', 'aria-describedby', 'aria-controls', 'aria-owns', 'data-modal-open', 'list', 'form'];
  const evitarIdsRepetidos = (contenedor) => {
    const nuevos = new Map();
    contenedor.querySelectorAll('[id]').forEach((elemento) => {
      if (document.getElementById(elemento.id) !== elemento) nuevos.set(elemento.id, `${elemento.id}-modal`);
    });
    if (!nuevos.size) return;
    contenedor.querySelectorAll('[id]').forEach((elemento) => {
      if (nuevos.has(elemento.id)) elemento.id = nuevos.get(elemento.id);
    });
    contenedor.querySelectorAll('*').forEach((elemento) => {
      REFERENCIAS_A_IDS.forEach((atributo) => {
        const valor = elemento.getAttribute(atributo);
        if (valor) elemento.setAttribute(atributo, valor.split(/\s+/).map((id) => nuevos.get(id) ?? id).join(' '));
      });
      const enlace = elemento.getAttribute('href');
      if (enlace?.startsWith('#') && nuevos.has(enlace.slice(1))) elemento.setAttribute('href', `#${nuevos.get(enlace.slice(1))}`);
    });
  };

  /* «Cancelar» era un enlace a la página anterior: dentro de la ventana solo cierra */
  const adaptarCancelar = (formulario) => {
    formulario.querySelectorAll('.action-bar > a.btn, .wizard__footer > a.btn').forEach((enlace) => {
      const boton = document.createElement('button');
      boton.type = 'button';
      boton.className = enlace.className;
      boton.textContent = enlace.textContent.trim();
      boton.setAttribute('data-form-modal-close', '');
      enlace.replaceWith(boton);
    });
  };

  const enfocarPrimero = (formulario) => {
    const invalido = formulario.querySelector('.field.is-invalid .field__control, .field.is-invalid input');
    const campo = invalido
      ?? formulario.querySelector('[autofocus]')
      ?? formulario.querySelector('.field__control:not([disabled]):not([type="hidden"]), input:not([type="hidden"]):not([disabled])');
    if (!campo) return;
    campo.focus({ preventScroll: true });
    if (invalido) campo.scrollIntoView({ block: 'center' });
  };

  const mostrarError = (mensaje, reintentar) => {
    titulo.textContent = 'No se pudo abrir el formulario';
    descripcion.hidden = true;
    const aviso = document.createElement('div');
    aviso.className = 'alert alert--error';
    aviso.setAttribute('role', 'alert');
    const texto = document.createElement('p');
    texto.className = 'alert__body';
    texto.textContent = mensaje;
    aviso.append(texto);
    cuerpo.replaceChildren(aviso);
    if (reintentar) {
      const boton = document.createElement('button');
      boton.type = 'button';
      boton.className = 'btn btn--sm';
      boton.textContent = 'Reintentar';
      boton.addEventListener('click', () => {
        cuerpo.replaceChildren(esqueleto());
        cargar(direccion);
      });
      cuerpo.append(boton);
    }
  };

  const irA = (destino) => {
    navegando = true;
    window.location.assign(destino);
  };

  /* --------------------------------------------------------------------------- Pintar el formulario */
  const pintar = async (html, destino) => {
    const documento = new DOMParser().parseFromString(html, 'text/html');
    const pagina = documento.querySelector('#contenido .page') ?? documento.querySelector('main .page');
    if (!pagina?.querySelector(FORMULARIO)) return false;

    await asegurarEstilos(documento, destino);

    const encabezado = pagina.querySelector(':scope > .page-header');
    titulo.textContent = encabezado?.querySelector('.page-header__title')?.textContent.trim() || 'Formulario';
    descripcion.textContent = encabezado?.querySelector('.page-header__description')?.textContent.trim() || '';
    descripcion.hidden = !descripcion.textContent;
    encabezado?.remove();

    cuerpo.replaceChildren(...[...pagina.childNodes].map((nodo) => document.importNode(nodo, true)));
    const formulario = qs(FORMULARIO, cuerpo);
    formulario.action = destino;       /* sin action enviaría a la página donde está abierta la ventana */
    /* El formulario pide su tamaño con data-modal-tam (la matriz de permisos); el asistente de alumnos siempre es ancho */
    dialogo.dataset.tam = formulario.dataset.modalTam || (formulario.classList.contains('wizard') ? 'lg' : 'md');
    evitarIdsRepetidos(cuerpo);
    adaptarCancelar(formulario);

    await ejecutarScripts(documento, destino);
    enfocarPrimero(formulario);
    cuerpo.scrollTop = 0;
    window.setTimeout(() => { modificado = formulario.querySelector('.field.is-invalid') !== null; }, 0);
    return true;
  };

  /* Respuesta del servidor, a un GET o a un envío */
  const tratar = async (respuesta, destino, mio) => {
    if ((respuesta.headers.get('content-type') || '').includes('application/json')) {
      const datos = await respuesta.json();
      if (datos.redirect) irA(datos.redirect);
      return;
    }
    if (mio !== turno) return;
    if (respuesta.status === 403) return mostrarError('No tienes permiso para hacer esto.', false);
    if (respuesta.status === 404) return mostrarError('Ese registro ya no existe.', false);
    if (!respuesta.ok) return mostrarError('El servidor tuvo un problema. Inténtalo de nuevo en un momento.', false);
    if (!(await pintar(await respuesta.text(), destino))) {
      mostrarError('No se pudo mostrar el formulario. Abre la página completa para continuar.', false);
    }
  };

  async function cargar(destino) {
    const mio = ++turno;
    try {
      await tratar(await fetch(destino, { headers: ENCABEZADOS, credentials: 'same-origin' }), destino, mio);
    } catch (error) {
      if (mio === turno) mostrarError('No se pudo cargar el formulario. Revisa tu conexión.', true);
    }
  }

  /* --------------------------------------------------------------------------- Abrir y cerrar */
  const abrir = (enlace) => {
    direccion = new URL(enlace.getAttribute('href'), location.href).href;
    origen = enlace;
    modificado = false;
    ocupado = false;
    navegando = false;
    titulo.textContent = 'Cargando…';
    descripcion.hidden = true;
    dialogo.dataset.tam = 'md';
    ocultarConfirmacion();
    cuerpo.replaceChildren(esqueleto());
    dialogo.showModal();
    raiz.classList.add('is-scroll-locked');
    cargar(direccion);
  };

  /* Deja la ventana lista para la próxima vez. Se hace al cerrar y no solo al evento «close», que el navegador puede
     entregar tarde, cuando la ventana ya se volvió a abrir con otro formulario */
  const limpiar = () => {
    turno += 1;
    cuerpo.replaceChildren();
    modificado = false;
    ocupado = false;
    ocultarConfirmacion();
    const volver = origen;
    origen = null;
    if (!document.querySelector('dialog[open]')) raiz.classList.remove('is-scroll-locked');
    volver?.focus?.({ preventScroll: true });
  };

  const cerrar = (forzar = false) => {
    if (!dialogo.open) return;
    if (!forzar && modificado && !ocupado && !navegando) {
      mostrarConfirmacion();
      return;
    }
    dialogo.close();
    limpiar();
  };

  document.addEventListener('click', (evento) => {
    const enlace = evento.target.closest('a[data-modal-form]');
    if (!enlace || evento.defaultPrevented || evento.button !== 0) return;
    if (evento.metaKey || evento.ctrlKey || evento.shiftKey || evento.altKey || enlace.target === '_blank') return;
    evento.preventDefault();
    abrir(enlace);
  });

  dialogo.addEventListener('click', (evento) => {
    if (evento.target === dialogo) cerrar();                                            /* toque fuera de la ventana */
    else if (evento.target.closest('[data-form-modal-close]')) cerrar();
    else if (evento.target.closest('[data-form-modal-seguir]')) ocultarConfirmacion();
    else if (evento.target.closest('[data-form-modal-descartar]')) cerrar(true);
  });

  dialogo.addEventListener('cancel', (evento) => {                                       /* Escape */
    evento.preventDefault();
    if (!confirmacion.hidden) ocultarConfirmacion();
    else cerrar();
  });

  dialogo.addEventListener('close', () => {
    if (!dialogo.open) limpiar();
  });

  /* Lo escrito se da por modificado (también lo que cambian los propios scripts del formulario al reaccionar al usuario) */
  cuerpo.addEventListener('input', () => { modificado = true; });
  cuerpo.addEventListener('change', () => { modificado = true; });

  /* --------------------------------------------------------------------------- Enviar */
  const guardando = (formulario, activo) => {
    formulario.querySelectorAll('button[type="submit"]').forEach((boton) => {
      boton.classList.toggle('is-loading', activo);
      if (activo) {
        boton.disabled = true;
      } else {
        boton.disabled = false;
        if (boton.dataset.etiqueta !== undefined) boton.innerHTML = boton.dataset.etiqueta;   /* los scripts del formulario ponen «Guardando…» */
      }
    });
  };

  /* Antes de que los scripts del formulario cambien el texto del botón al enviar, se guarda para poder devolverlo */
  cuerpo.addEventListener('submit', (evento) => {
    evento.target.querySelectorAll?.('button[type="submit"]').forEach((boton) => {
      boton.dataset.etiqueta = boton.innerHTML;
    });
  }, true);

  cuerpo.addEventListener('submit', async (evento) => {
    const formulario = evento.target;
    /* Los scripts del formulario validan antes (y cancelan el envío si algo está mal); aquí llega ya lo que sí se envía */
    if (!(formulario instanceof HTMLFormElement) || !formulario.matches(FORMULARIO) || evento.defaultPrevented) return;
    evento.preventDefault();
    if (ocupado) return;

    ocupado = true;
    guardando(formulario, true);
    const mio = ++turno;
    try {
      const respuesta = await fetch(formulario.action, {
        method: 'POST', body: new FormData(formulario), headers: ENCABEZADOS, credentials: 'same-origin',
      });
      await tratar(respuesta, formulario.action, mio);
    } catch (error) {
      if (mio === turno) {
        guardando(formulario, false);
        const aviso = document.createElement('div');
        aviso.className = 'alert alert--error';
        aviso.setAttribute('role', 'alert');
        const texto = document.createElement('p');
        texto.className = 'alert__body';
        texto.textContent = 'No se pudo guardar: revisa tu conexión e inténtalo de nuevo. Lo que escribiste sigue aquí.';
        aviso.append(texto);
        formulario.prepend(aviso);
        aviso.scrollIntoView({ block: 'nearest' });
      }
    } finally {
      if (!navegando) ocupado = false;
    }
  });
})();
