/* CISAHUAYO · avisos de retiros anticipados (en las páginas del personal que los atiende y en el portal de tutores)

   - static/js/avisos.js reenvía cada evento del canal de avisos como «mensajeria:evento»; los de tipo «retiro»
     (Retiros/tiempo_real.py) llegan aquí: un aviso nuevo o una cancelación para el personal; la salida confirmada, una
     cancelación o una corrección para el tutor. Se suma uno a los contadores y aparece arriba en la campana; después
     se pide el resumen al servidor para dejar la lista y los números exactos. Se muestra un aviso en pantalla o, si la
     página no está a la vista y se permitió desde la campana, un aviso del navegador.
   - Contadores: el número de la campana (lo pinta avisos.js con data-retiros-sin-leer y «avisos:repintar») y el de
     «Retiros anticipados» del menú lateral.
   - Si la página abierta es la de retiros, se avisa con «retiros:nuevo» (la lista del día se puede recargar).
   - Al reconectarse el canal («avisos:reconectado») y al volver a la pestaña se vuelve a pedir el resumen.
*/
(() => {
  'use strict';

  const raiz = document.querySelector('[data-notificaciones]');
  const lista = raiz?.querySelector('[data-retiros-lista]');
  const mas = raiz?.querySelector('[data-retiros-mas]');
  const urlResumen = raiz?.dataset.retirosResumenUrl;
  const sprite = document.querySelector('svg use')?.getAttribute('href')?.split('#')[0] || '';
  const logo = document.querySelector('link[rel="icon"]')?.href;
  const MAXIMO_EN_LA_CAMPANA = 5;

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
  const pendientesActuales = () => Number(raiz?.dataset.retirosSinLeer
    ?? document.querySelector('[data-retiros-pendientes]')?.textContent) || 0;

  const ponerPendientes = (total) => {
    total = Math.max(0, Number(total) || 0);
    document.querySelectorAll('[data-retiros-pendientes]').forEach((insignia) => {
      insignia.textContent = String(total);
      insignia.hidden = !total;
      insignia.setAttribute('aria-label', `${total} sin leer`);
    });
    if (raiz) raiz.dataset.retirosSinLeer = String(total);
    if (mas) {
      const enLista = lista ? lista.children.length : 0;
      mas.hidden = total <= enLista;
      mas.textContent = `Ver los retiros (${total} avisos sin leer)`;
    }
    document.dispatchEvent(new CustomEvent('avisos:repintar'));   /* avisos.js: el número de la campana */
  };

  /* ------------------------------------------------------------------ lista de la campana */
  const itemDe = (aviso) => {
    const fila = elemento('li');
    fila.dataset.avisoRetiro = String(aviso.id);
    const enlace = elemento('a', 'aviso aviso--retiro');
    enlace.href = aviso.url;
    const avatar = elemento('span', 'avatar avatar--sm aviso__avatar aviso__avatar--retiro');
    avatar.setAttribute('aria-hidden', 'true');
    avatar.append(icono('log-out'));
    const texto = elemento('span', 'aviso__texto');
    const arriba = elemento('span', 'aviso__fila');
    arriba.append(elemento('span', 'aviso__nombre', aviso.titulo), elemento('span', 'aviso__hora', aviso.hora || ''));
    texto.append(arriba, elemento('span', 'aviso__vista', aviso.texto));
    enlace.append(avatar, texto);
    fila.append(enlace);
    return fila;
  };

  const ponerLista = (avisos) => {
    if (!lista) return;
    lista.replaceChildren(...avisos.slice(0, MAXIMO_EN_LA_CAMPANA).map(itemDe));
    lista.hidden = !lista.children.length;
  };

  const agregarALista = (datos) => {
    if (!lista || lista.querySelector(`[data-aviso-retiro="${datos.id}"]`)) return;
    const hora = new Date();
    lista.prepend(itemDe({ ...datos, hora: `${String(hora.getHours()).padStart(2, '0')}:${String(hora.getMinutes()).padStart(2, '0')}` }));
    while (lista.children.length > MAXIMO_EN_LA_CAMPANA) lista.lastElementChild.remove();
    lista.hidden = false;
  };

  let turno = 0;
  const refrescar = async () => {
    if (!urlResumen) return;
    const miTurno = ++turno;
    try {
      const respuesta = await fetch(urlResumen, { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
      if (!respuesta.ok || miTurno !== turno) return;
      const datos = await respuesta.json();
      ponerLista(datos.avisos || []);
      ponerPendientes(datos.pendientes);
    } catch (error) {
      /* sin conexión: se intentará al reconectar */
    }
  };

  /* ------------------------------------------------------------------ aviso en pantalla */
  let flotante = null;
  let cierre = null;
  const mostrarFlotante = (datos) => {
    flotante?.remove();
    window.clearTimeout(cierre);
    flotante = elemento('a', 'aviso-flotante aviso-flotante--retiro');
    flotante.href = datos.url;
    flotante.setAttribute('role', 'status');
    const texto = elemento('span', 'aviso-flotante__texto');
    texto.append(
      elemento('span', 'aviso-flotante__titulo', 'Retiros anticipados'),
      elemento('span', 'aviso-flotante__nombre', datos.titulo),
      elemento('span', 'aviso-flotante__vista', datos.texto),
    );
    const cerrar = elemento('button', 'aviso-flotante__cerrar');
    cerrar.type = 'button';
    cerrar.setAttribute('aria-label', 'Cerrar aviso');
    cerrar.append(icono('x'));
    cerrar.addEventListener('click', (evento) => {
      evento.preventDefault();
      flotante?.remove();
    });
    const avatar = elemento('span', 'avatar aviso__avatar');
    avatar.setAttribute('aria-hidden', 'true');
    avatar.append(icono('log-out'));
    flotante.append(avatar, texto, cerrar);
    document.body.append(flotante);
    const este = flotante;
    cierre = window.setTimeout(() => este.remove(), 9000);
  };

  const avisarNavegador = (datos) => {
    if (!('Notification' in window) || !window.isSecureContext || Notification.permission !== 'granted') return;
    try {
      const aviso = new Notification(datos.titulo, { body: datos.texto, tag: `retiro-${datos.id}`, icon: logo });
      aviso.addEventListener('click', () => {
        window.focus();
        window.location.href = datos.url;
        aviso.close();
      });
    } catch (error) {
      /* algunos navegadores móviles solo permiten avisos desde un service worker */
    }
  };

  /* ------------------------------------------------------------------ eventos */
  document.addEventListener('mensajeria:evento', (evento) => {
    const datos = evento.detail || {};
    if (datos.evento !== 'retiro') return;
    agregarALista(datos);
    ponerPendientes(pendientesActuales() + 1);
    refrescar();
    if (document.visibilityState === 'visible') mostrarFlotante(datos);
    else avisarNavegador(datos);
    document.dispatchEvent(new CustomEvent('retiros:nuevo', { detail: datos }));
  });

  document.addEventListener('avisos:reconectado', refrescar);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') refrescar();
  });
})();
