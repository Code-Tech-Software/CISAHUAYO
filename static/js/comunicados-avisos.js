/* CISAHUAYO · avisos de comunicados (en todas las páginas del sistema y de los portales)

   - static/js/avisos.js reenvía a la página cada evento del canal de avisos como «mensajeria:evento»; los de tipo
     «comunicado» (Comunicados/tiempo_real.py) llegan aquí: se suma uno a los contadores de comunicados sin leer (menú
     lateral, campana y pestaña «Recibidos») y se muestra un aviso en pantalla o, si la página no está a la vista y se
     permitió desde la campana, un aviso del navegador. Los urgentes se distinguen en naranja y no se cierran solos.
   - Al abrir un comunicado (static/js/comunicados.js) llega «comunicados:pendientes» con el total nuevo.
   El aviso solo dice que llegó: no lo marca como leído ni confirma que la persona lo vio.
*/
(() => {
  'use strict';

  const insignias = () => document.querySelectorAll('[data-comunicados-pendientes]');
  const campana = document.querySelector('[data-comunicados-campana]');
  const sprite = document.querySelector('svg use')?.getAttribute('href')?.split('#')[0] || '';
  const logo = document.querySelector('link[rel="icon"]')?.href;

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

  const actual = () => Number(insignias()[0]?.textContent || campana?.dataset.pendientes || 0) || 0;
  let urgentes = Number(campana?.dataset.urgentes) || 0;

  const ponerPendientes = (total, urgentesNuevos = urgentes) => {
    total = Math.max(0, Number(total) || 0);
    urgentes = Math.max(0, Math.min(total, Number(urgentesNuevos) || 0));
    insignias().forEach((insignia) => {
      insignia.textContent = String(total);
      insignia.hidden = !total;
      insignia.setAttribute('aria-label', `${total} sin leer`);
    });
    document.querySelectorAll('[data-comunicados-vista-cuenta]').forEach((cuenta) => {
      cuenta.textContent = String(total);
      cuenta.hidden = !total;
    });
    if (campana) {
      campana.hidden = !total;
      campana.dataset.pendientes = String(total);
      campana.dataset.urgentes = String(urgentes);
      campana.classList.toggle('is-urgente', urgentes > 0);
      const texto = campana.querySelector('[data-comunicados-campana-texto]');
      if (texto) texto.textContent = `${total} comunicado${total === 1 ? '' : 's'} sin leer`;
      const nota = campana.querySelector('[data-comunicados-campana-urgentes]');
      if (nota) nota.textContent = `${urgentes ? `${urgentes} urgente${urgentes === 1 ? '' : 's'} · ` : ''}Ver comunicados`;
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

  document.addEventListener('mensajeria:evento', (evento) => {
    const datos = evento.detail || {};
    if (datos.evento !== 'comunicado') return;
    ponerPendientes(actual() + 1, urgentes + (datos.urgente ? 1 : 0));
    if (document.visibilityState === 'visible') mostrarFlotante(datos);
    else avisarNavegador(datos);
    document.dispatchEvent(new CustomEvent('comunicados:nuevo', { detail: datos }));
  });

  document.addEventListener('comunicados:pendientes', (evento) => {
    const { pendientes, urgente } = evento.detail || {};
    if (pendientes === undefined) return;
    ponerPendientes(pendientes, urgente ? urgentes - 1 : urgentes);
  });
})();
