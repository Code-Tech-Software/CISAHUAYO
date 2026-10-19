/* CISAHUAYO · avisos de reuniones con familias (en las páginas del personal del módulo y en el portal de tutores)

   - static/js/avisos.js reenvía cada evento del canal de avisos como «mensajeria:evento»; los de tipo «reunion»
     (Reuniones/tiempo_real.py) llegan aquí: se pide el resumen al servidor y se vuelven a pintar la lista de la campana
     y su número (avisos.js suma data-reuniones-sin-leer con «avisos:repintar»). Si la página no está a la vista y se
     permitió desde la campana, también un aviso del navegador.
   - Al reconectarse el canal («avisos:reconectado») y al volver a la pestaña se vuelve a pedir el resumen. Al cargar la
     página también, a lo más cada cinco minutos: esa petición es la que genera los recordatorios previos y los avisos de
     acuerdos por vencer (Reuniones/context_processors.py), sin sumarle consultas a cada página.
   Los avisos solo dicen cuándo y dónde: nunca el motivo ni las notas.
*/
(() => {
  'use strict';

  const raiz = document.querySelector('[data-notificaciones]');
  const lista = raiz?.querySelector('[data-reuniones-lista]');
  const mas = raiz?.querySelector('[data-reuniones-mas]');
  const urlResumen = raiz?.dataset.reunionesResumenUrl;
  if (!raiz || !lista || !urlResumen) return;
  const sprite = document.querySelector('svg use')?.getAttribute('href')?.split('#')[0] || '';
  const logo = document.querySelector('link[rel="icon"]')?.href;

  const elemento = (etiqueta, clase, texto) => {
    const nodo = document.createElement(etiqueta);
    if (clase) nodo.className = clase;
    if (texto !== undefined) nodo.textContent = texto;
    return nodo;
  };
  const icono = (nombre) => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'icon icon--sm');
    svg.setAttribute('aria-hidden', 'true');
    const uso = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    uso.setAttribute('href', `${sprite}#${nombre}`);
    svg.append(uso);
    return svg;
  };

  const fila = (aviso) => {
    const item = elemento('li');
    item.dataset.avisoReunion = String(aviso.id);
    const enlace = elemento('a', 'aviso aviso--reunion');
    enlace.href = aviso.url;
    const avatar = elemento('span', 'avatar avatar--sm aviso__avatar aviso__avatar--reunion');
    avatar.setAttribute('aria-hidden', 'true');
    avatar.append(icono('users'));
    const texto = elemento('span', 'aviso__texto');
    const cabeza = elemento('span', 'aviso__fila');
    cabeza.append(elemento('span', 'aviso__nombre', aviso.titulo), elemento('span', 'aviso__hora', aviso.hora || ''));
    texto.append(cabeza, elemento('span', 'aviso__vista', aviso.texto));
    enlace.append(avatar, texto);
    item.append(enlace);
    return item;
  };

  const pintar = (datos) => {
    const pendientes = Math.max(0, Number(datos.pendientes) || 0);
    lista.replaceChildren(...(datos.avisos || []).map(fila));
    lista.hidden = !lista.children.length;
    raiz.dataset.reunionesSinLeer = String(pendientes);
    if (mas) {
      mas.hidden = pendientes <= lista.children.length;
      mas.textContent = `Ver las reuniones (${pendientes} avisos sin leer)`;
    }
    document.dispatchEvent(new CustomEvent('avisos:repintar'));
  };

  let turno = 0;
  const actualizar = async () => {
    const mio = ++turno;
    try {
      const respuesta = await fetch(urlResumen, { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
      if (!respuesta.ok || mio !== turno) return;
      pintar(await respuesta.json());
    } catch (error) {
      /* sin conexión: se reintenta al reconectarse el canal o al volver a la pestaña */
    }
  };

  document.addEventListener('mensajeria:evento', (evento) => {
    const datos = evento.detail || {};
    if (datos.evento !== 'reunion') return;
    actualizar();
    if (document.visibilityState !== 'visible' && 'Notification' in window && Notification.permission === 'granted') {
      try {
        const aviso = new Notification(datos.titulo || 'Reuniones con familias', { body: datos.texto || '', icon: logo, tag: `reunion-${datos.id}` });
        aviso.onclick = () => { window.focus(); window.location.href = datos.url; };
      } catch (error) { /* el navegador no permite avisos desde aquí */ }
    }
  });
  document.addEventListener('avisos:reconectado', actualizar);

  const LLAVE = 'cisahuayo.reuniones-avisos';
  let ultima = 0;
  try { ultima = Number(sessionStorage.getItem(LLAVE)) || 0; } catch (error) { /* sin almacenamiento: se pide siempre */ }
  if (Date.now() - ultima > 5 * 60 * 1000) {
    try { sessionStorage.setItem(LLAVE, String(Date.now())); } catch (error) { /* sin almacenamiento */ }
    actualizar();
  }
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') actualizar(); });
})();
