/* CISAHUAYO · avisos de comunicados (en todas las páginas del sistema y de los portales de quien recibe comunicados)

   - static/js/avisos.js reenvía a la página cada evento del canal de avisos como «mensajeria:evento»; los de tipo
     «comunicado» (Comunicados/tiempo_real.py) llegan aquí. Al momento se suma uno a los contadores y el comunicado
     aparece arriba en la campana; después se pide el resumen al servidor (comunicados:resumen) para dejar la lista y los
     números exactos. Se muestra un aviso en pantalla o, si la página no está a la vista y se permitió desde la campana,
     un aviso del navegador. Los urgentes se distinguen en naranja y su aviso no se cierra solo.
   - Contadores: el número de la campana (lo pinta avisos.js con data-comunicados-sin-leer y «avisos:repintar»), el de
     «Comunicados» del menú lateral y el de la pestaña «Recibidos».
   - Al abrir un comunicado (static/js/comunicados.js llega «comunicados:pendientes») y al reconectarse el canal
     («avisos:reconectado») se vuelve a pedir el resumen.
   El aviso solo dice que llegó: no lo marca como leído ni confirma que la persona lo vio.
*/
(() => {
  'use strict';

  const raiz = document.querySelector('[data-notificaciones]');
  const lista = raiz?.querySelector('[data-comunicados-lista]');
  const mas = raiz?.querySelector('[data-comunicados-mas]');
  const urlResumen = raiz?.dataset.comunicadosResumenUrl;
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
  const pendientesActuales = () => Number(raiz?.dataset.comunicadosSinLeer
    ?? document.querySelector('[data-comunicados-pendientes]')?.textContent) || 0;

  const ponerPendientes = (total) => {
    total = Math.max(0, Number(total) || 0);
    document.querySelectorAll('[data-comunicados-pendientes]').forEach((insignia) => {
      insignia.textContent = String(total);
      insignia.hidden = !total;
      insignia.setAttribute('aria-label', `${total} sin leer`);
    });
    document.querySelectorAll('[data-comunicados-vista-cuenta]').forEach((cuenta) => {
      cuenta.textContent = String(total);
      cuenta.hidden = !total;
    });
    if (raiz) raiz.dataset.comunicadosSinLeer = String(total);
    if (mas) {
      const enLista = lista ? lista.children.length : 0;
      mas.hidden = total <= enLista;
      mas.textContent = `Ver los ${total} comunicados sin leer`;
    }
    document.dispatchEvent(new CustomEvent('avisos:repintar'));   /* avisos.js: el número de la campana */
  };

  /* ------------------------------------------------------------------ lista de la campana */
  const itemDe = (aviso) => {
    const fila = elemento('li');
    fila.dataset.avisoComunicado = String(aviso.id);
    const enlace = elemento('a', `aviso aviso--comunicado${aviso.urgente ? ' is-urgente' : ''}`);
    enlace.href = aviso.url;
    const avatar = elemento('span', 'avatar avatar--sm aviso__avatar aviso__avatar--comunicado');
    avatar.setAttribute('aria-hidden', 'true');
    avatar.append(icono(aviso.urgente ? 'triangle-alert' : 'megaphone'));
    const texto = elemento('span', 'aviso__texto');
    const arriba = elemento('span', 'aviso__fila');
    arriba.append(elemento('span', 'aviso__nombre', aviso.titulo), elemento('span', 'aviso__hora', aviso.hora || ''));
    texto.append(arriba, elemento('span', 'aviso__vista', `${aviso.urgente ? 'Urgente · ' : ''}Comunicado de ${aviso.autor}`));
    enlace.append(avatar, texto);
    fila.append(enlace);
    return fila;
  };

  const ponerLista = (avisos) => {
    if (!lista) return;
    lista.replaceChildren(...avisos.slice(0, MAXIMO_EN_LA_CAMPANA).map(itemDe));
    lista.hidden = !lista.children.length;
  };

  /* Lo que llegó por el canal, al momento (después se confirma con el resumen) */
  const agregarALista = (datos) => {
    if (!lista || lista.querySelector(`[data-aviso-comunicado="${datos.id}"]`)) return;
    const hora = new Date();
    lista.prepend(itemDe({ ...datos, hora: `${String(hora.getHours()).padStart(2, '0')}:${String(hora.getMinutes()).padStart(2, '0')}` }));
    while (lista.children.length > MAXIMO_EN_LA_CAMPANA) lista.lastElementChild.remove();
    lista.hidden = false;
  };

  /* El resumen del servidor: los números y la lista exactos */
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
    flotante = elemento('a', `aviso-flotante aviso-flotante--comunicado${datos.urgente ? ' aviso-flotante--urgente' : ''}`);
    flotante.href = datos.url;
    flotante.setAttribute('role', datos.urgente ? 'alert' : 'status');
    const texto = elemento('span', 'aviso-flotante__texto');
    texto.append(
      elemento('span', 'aviso-flotante__titulo', datos.urgente ? 'Comunicado urgente' : 'Comunicado nuevo'),
      elemento('span', 'aviso-flotante__nombre', datos.titulo),
      elemento('span', 'aviso-flotante__vista', `${datos.autor} · ${datos.vista_previa}`),
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
    avatar.append(icono(datos.urgente ? 'triangle-alert' : 'megaphone'));
    flotante.append(avatar, texto, cerrar);
    document.body.append(flotante);
    if (!datos.urgente) {   /* el urgente se queda hasta que se cierre o se abra */
      const este = flotante;
      cierre = window.setTimeout(() => este.remove(), 9000);
    }
  };

  const avisarNavegador = (datos) => {
    if (!('Notification' in window) || !window.isSecureContext || Notification.permission !== 'granted') return;
    try {
      const aviso = new Notification(datos.urgente ? `Urgente: ${datos.titulo}` : datos.titulo, {
        body: `${datos.autor} · ${datos.vista_previa}`, tag: `comunicado-${datos.id}`, icon: logo, requireInteraction: Boolean(datos.urgente),
      });
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
    if (datos.evento !== 'comunicado') return;
    agregarALista(datos);
    ponerPendientes(pendientesActuales() + 1);
    refrescar();
    if (document.visibilityState === 'visible') mostrarFlotante(datos);
    else avisarNavegador(datos);
    document.dispatchEvent(new CustomEvent('comunicados:nuevo', { detail: datos }));
  });

  /* Se abrió un comunicado (ya quedó leído en el servidor) */
  document.addEventListener('comunicados:pendientes', (evento) => {
    const { pendientes } = evento.detail || {};
    if (pendientes !== undefined) ponerPendientes(pendientes);
    refrescar();
  });

  document.addEventListener('avisos:reconectado', refrescar);

  /* Al volver a la pestaña tras un rato, por si algo cambió mientras tanto (otra pestaña lo leyó) */
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') refrescar();
  });
})();
