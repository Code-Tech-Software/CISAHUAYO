/* CISAHUAYO · avisos de la mensajería en tiempo real (en todas las páginas del sistema y de los portales)

   - Se conecta al WebSocket de avisos (Mensajes/consumers.py) y se reconecta solo si se corta (con espera creciente);
     al reconectarse pide el resumen para ponerse al día con lo que llegó mientras tanto.
   - Mantiene al día la campana de notificaciones (lista de quién escribió y vista previa), el contador de «Mensajes»
     del menú lateral y el título de la pestaña. El número de la campana suma los mensajes, los comunicados y los avisos
     de retiros sin leer: static/js/comunicados-avisos.js y static/js/retiros-avisos.js ponen los suyos en
     data-comunicados-sin-leer y data-retiros-sin-leer, y avisan con «avisos:repintar».
   - Una cuenta que solo recibe comunicados (sin mensajería) también se conecta: aquí solo se le pinta la campana.
   - Mensaje nuevo: si la página está a la vista, un aviso en pantalla (al tocarlo se abre la conversación); si no,
     un aviso del navegador (si se permitió desde la campana).
   - Mensaje retirado por moderación: la campana se queda con lo que sigue sin leer de esa conversación, y se quitan el
     aviso en pantalla y el del navegador si eran de ese mensaje.
   - Reenvía cada evento a la página como «mensajeria:evento» (la pantalla de mensajes lo usa: static/js/mensajes.js;
     los comunicados, static/js/comunicados-avisos.js) y, al reconectarse, avisa con «avisos:reconectado».
*/
(() => {
  'use strict';

  const raiz = document.querySelector('[data-notificaciones]');
  if (!raiz || !('WebSocket' in window)) return;
  const conMensajes = Boolean(raiz.dataset.resumenUrl);
  let mensajes = Number(raiz.dataset.mensajesSinLeer) || 0;

  const boton = raiz.querySelector('[data-notificaciones-boton]');
  const total = raiz.querySelector('[data-notificaciones-total]');
  const lista = raiz.querySelector('[data-notificaciones-lista]');
  const vacio = raiz.querySelector('[data-notificaciones-vacio]');
  const permiso = raiz.querySelector('[data-notificaciones-permiso]');
  const activar = raiz.querySelector('[data-notificaciones-activar]');
  const logo = document.querySelector('link[rel="icon"]')?.href;
  const sprite = document.querySelector('svg use')?.getAttribute('href')?.split('#')[0] || '';
  const tituloBase = document.title.replace(/^\(\d+\)\s*/, '');

  const conversacionAbierta = () => Number(document.querySelector('[data-chat]')?.dataset.conversacion || 0);
  const aLaVista = () => document.visibilityState === 'visible';

  const icono = (nombre, clase = 'icon icon--sm') => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', clase);
    svg.setAttribute('aria-hidden', 'true');
    const uso = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    uso.setAttribute('href', `${sprite}#${nombre}`);
    svg.append(uso);
    return svg;
  };
  const elemento = (etiqueta, clase, texto) => {
    const nodo = document.createElement(etiqueta);
    if (clase) nodo.className = clase;
    if (texto !== undefined) nodo.textContent = texto;
    return nodo;
  };

  /* ------------------------------------------------------------------ contadores */
  /* El número de la campana: mensajes, comunicados, avisos de retiros y de reuniones sin leer (static/js/reuniones-avisos.js
     pone los suyos en data-reuniones-sin-leer) */
  const pintarCampana = () => {
    const comunicados = Number(raiz.dataset.comunicadosSinLeer) || 0;
    const retiros = Number(raiz.dataset.retirosSinLeer) || 0;
    const reuniones = Number(raiz.dataset.reunionesSinLeer) || 0;
    const n = mensajes + comunicados + retiros + reuniones;
    if (total) {
      total.textContent = String(n);
      total.hidden = !n;
    }
    const partes = [];
    if (mensajes) partes.push(`${mensajes} mensaje${mensajes === 1 ? '' : 's'} sin leer`);
    if (comunicados) partes.push(`${comunicados} comunicado${comunicados === 1 ? '' : 's'} sin leer`);
    if (retiros) partes.push(`${retiros} aviso${retiros === 1 ? '' : 's'} de retiro sin leer`);
    if (reuniones) partes.push(`${reuniones} aviso${reuniones === 1 ? '' : 's'} de reuniones sin leer`);
    boton?.setAttribute('aria-label', ['Notificaciones', ...partes].join(', '));
    document.title = n ? `(${n}) ${tituloBase}` : tituloBase;
  };

  const ponerTotal = (n) => {
    mensajes = Number(n) || 0;
    document.querySelectorAll('[data-mensajes-no-leidos]').forEach((insignia) => {
      insignia.textContent = String(mensajes);
      insignia.hidden = !mensajes;
      insignia.setAttribute('aria-label', `${mensajes} sin leer`);
    });
    pintarCampana();
  };

  /* ------------------------------------------------------------------ lista de la campana */
  const sincronizarLista = () => {
    if (!lista || !vacio) return;
    lista.hidden = !lista.children.length;
    const deComunicados = raiz.querySelector('[data-comunicados-lista]');
    const deRetiros = raiz.querySelector('[data-retiros-lista]');
    const deReuniones = raiz.querySelector('[data-reuniones-lista]');
    vacio.hidden = Boolean(lista.children.length || deComunicados?.children.length || deRetiros?.children.length || deReuniones?.children.length);
  };

  /* Los comunicados cambiaron (static/js/comunicados-avisos.js): se vuelve a pintar el número y el estado vacío */
  document.addEventListener('avisos:repintar', () => {
    pintarCampana();
    sincronizarLista();
  });

  const itemDe = (aviso) => {
    const fila = elemento('li');
    fila.dataset.avisoConversacion = String(aviso.conversacion);
    const enlace = elemento('a', 'aviso');
    enlace.href = aviso.url;
    const avatar = elemento('span', 'avatar avatar--sm aviso__avatar', aviso.iniciales);
    avatar.setAttribute('aria-hidden', 'true');
    const texto = elemento('span', 'aviso__texto');
    const arriba = elemento('span', 'aviso__fila');
    arriba.append(elemento('span', 'aviso__nombre', aviso.nombre), elemento('span', 'aviso__hora', aviso.hora));
    texto.append(arriba, elemento('span', 'aviso__vista', aviso.vista_previa));
    const conteo = elemento('span', 'aviso__conteo', String(aviso.no_leidos));
    conteo.setAttribute('aria-label', `${aviso.no_leidos} sin leer`);
    enlace.append(avatar, texto, conteo);
    fila.append(enlace);
    return fila;
  };

  const ponerAviso = (datos) => {
    if (!lista) return;
    const anterior = lista.querySelector(`[data-aviso-conversacion="${datos.conversacion}"]`);
    const previos = anterior ? Number(anterior.querySelector('.aviso__conteo')?.textContent) || 0 : 0;
    anterior?.remove();
    lista.prepend(itemDe({
      conversacion: datos.conversacion, url: datos.url, nombre: datos.autor, iniciales: datos.iniciales,
      vista_previa: datos.vista_previa, hora: datos.hora, no_leidos: previos + 1,
    }));
    sincronizarLista();
  };

  const quitarAviso = (conversacion) => {
    lista?.querySelector(`[data-aviso-conversacion="${conversacion}"]`)?.remove();
    sincronizarLista();
  };

  /* ------------------------------------------------------------------ aviso en pantalla */
  let flotante = null;
  let cierre = null;
  const mostrarFlotante = (datos) => {
    flotante?.remove();
    window.clearTimeout(cierre);
    flotante = elemento('a', 'aviso-flotante');
    flotante.href = datos.url;
    flotante.dataset.mensaje = String(datos.id);
    flotante.setAttribute('role', 'status');
    const texto = elemento('span', 'aviso-flotante__texto');
    texto.append(
      elemento('span', 'aviso-flotante__titulo', 'Mensaje nuevo'),
      elemento('span', 'aviso-flotante__nombre', datos.autor),
      elemento('span', 'aviso-flotante__vista', datos.vista_previa),
    );
    const cerrar = elemento('button', 'aviso-flotante__cerrar');
    cerrar.type = 'button';
    cerrar.setAttribute('aria-label', 'Cerrar aviso');
    cerrar.append(icono('x'));
    cerrar.addEventListener('click', (evento) => {
      evento.preventDefault();
      flotante?.remove();
    });
    const avatar = elemento('span', 'avatar aviso__avatar', datos.iniciales);
    avatar.setAttribute('aria-hidden', 'true');
    flotante.append(avatar, texto, cerrar);
    document.body.append(flotante);
    const actual = flotante;
    cierre = window.setTimeout(() => actual.remove(), 8000);
  };

  /* ------------------------------------------------------------------ avisos del navegador */
  const soporta = 'Notification' in window && window.isSecureContext;
  const enNavegador = new Map();   /* conversación -> {mensaje, aviso}: el último aviso del navegador de cada una */
  const sincronizarPermiso = () => {
    if (permiso) permiso.hidden = !(soporta && Notification.permission === 'default');
  };
  activar?.addEventListener('click', async () => {
    try {
      await Notification.requestPermission();
    } catch (error) {
      /* el navegador no lo permite aquí */
    }
    sincronizarPermiso();
  });
  sincronizarPermiso();

  const avisarNavegador = (datos) => {
    if (!soporta || Notification.permission !== 'granted') return;
    try {
      const aviso = new Notification(datos.autor, { body: datos.vista_previa, tag: `conversacion-${datos.conversacion}`, icon: logo });
      enNavegador.set(datos.conversacion, { mensaje: datos.id, aviso });
      aviso.addEventListener('click', () => {
        window.focus();
        window.location.href = datos.url;
        aviso.close();
      });
    } catch (error) {
      /* algunos navegadores móviles solo permiten avisos desde un service worker */
    }
  };

  /* ------------------------------------------------------------------ mensajes retirados (moderación) */
  const retirarAviso = (datos) => {
    const pendientes = Number(datos.pendientes) || 0;
    const fila = lista?.querySelector(`[data-aviso-conversacion="${datos.conversacion}"]`);
    if (fila && !pendientes) {
      quitarAviso(datos.conversacion);
    } else if (fila) {
      fila.querySelector('.aviso__vista').textContent = datos.vista_previa;
      fila.querySelector('.aviso__hora').textContent = datos.hora;
      const conteo = fila.querySelector('.aviso__conteo');
      conteo.textContent = String(pendientes);
      conteo.setAttribute('aria-label', `${pendientes} sin leer`);
    }
    if (flotante?.dataset.mensaje === String(datos.id)) flotante.remove();
    const delNavegador = enNavegador.get(datos.conversacion);
    if (delNavegador?.mensaje === datos.id) {
      delNavegador.aviso.close();
      enNavegador.delete(datos.conversacion);
    }
  };

  /* ------------------------------------------------------------------ eventos */
  const recibir = (datos) => {
    document.dispatchEvent(new CustomEvent('mensajeria:evento', { detail: datos }));
    if (datos.evento === 'mensaje') {
      if (datos.mio) return;
      if (conversacionAbierta() === datos.conversacion && aLaVista()) return;   /* se marca leído: llega el resumen */
      ponerTotal(datos.no_leidos);
      ponerAviso(datos);
      if (aLaVista()) mostrarFlotante(datos);
      else avisarNavegador(datos);
    } else if (datos.evento === 'resumen') {
      ponerTotal(datos.no_leidos);
      quitarAviso(datos.conversacion);
    } else if (datos.evento === 'retirado') {
      ponerTotal(datos.no_leidos);
      retirarAviso(datos);
    }
  };

  const ponerseAlDia = async () => {
    document.dispatchEvent(new CustomEvent('avisos:reconectado'));
    if (!conMensajes) return;
    try {
      const respuesta = await fetch(raiz.dataset.resumenUrl, { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
      if (!respuesta.ok) return;
      const datos = await respuesta.json();
      ponerTotal(datos.no_leidos);
      if (lista) {
        lista.replaceChildren(...datos.avisos.map(itemDe));
        sincronizarLista();
      }
      document.dispatchEvent(new CustomEvent('mensajeria:al-dia', { detail: datos }));
    } catch (error) {
      /* sin conexión: se intentará al reconectar */
    }
  };

  /* ------------------------------------------------------------------ conexión */
  const direccion = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}${raiz.dataset.ws}`;
  let espera = 1000;
  let latido = null;
  let reconexion = false;

  const conectar = () => {
    let socket;
    try {
      socket = new WebSocket(direccion);
    } catch (error) {
      return;
    }
    socket.addEventListener('open', () => {
      espera = 1000;
      if (reconexion) ponerseAlDia();
      latido = window.setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ evento: 'ping' }));
      }, 30000);
    });
    socket.addEventListener('message', (evento) => {
      try {
        recibir(JSON.parse(evento.data));
      } catch (error) {
        /* evento que no se entiende: se ignora */
      }
    });
    socket.addEventListener('close', (evento) => {
      window.clearInterval(latido);
      if (evento.code === 4403) return;   /* la sesión ya no tiene mensajería: no insistir */
      reconexion = true;
      window.setTimeout(conectar, espera);
      espera = Math.min(espera * 2, 30000);
    });
  };

  conectar();
})();
