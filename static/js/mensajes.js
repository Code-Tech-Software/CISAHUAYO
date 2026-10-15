/* CISAHUAYO · pantalla de mensajes (templates/mensajes/bandeja.html)

   - Envía sin recargar (Intro envía, Mayús+Intro hace un salto de línea) y muestra el mensaje al momento.
   - Con los eventos en tiempo real (static/js/avisos.js → «mensajeria:evento»): agrega los mensajes que llegan a la
     conversación abierta y la marca como leída (si la pestaña está a la vista), pone «Leído» en los propios cuando la
     otra persona los lee y mantiene la lista de conversaciones (orden, vista previa, hora y no leídos).
   - Búsqueda: filtra las conversaciones y busca personas a las que se puede escribir.
   Sin JavaScript la pantalla funciona con formularios normales.
*/
(() => {
  'use strict';

  const chat = document.querySelector('[data-chat]');
  if (!chat) return;

  const conversacion = Number(chat.dataset.conversacion || 0);
  const mensajes = chat.querySelector('[data-chat-mensajes]');
  const formulario = chat.querySelector('[data-chat-formulario]');
  const campo = chat.querySelector('[data-chat-campo]');
  const error = chat.querySelector('[data-chat-error]');
  const conversaciones = chat.querySelector('[data-chat-conversaciones]');
  const sinConversaciones = chat.querySelector('[data-chat-sin-conversaciones]');
  const buscar = chat.querySelector('[data-chat-buscar]');
  const personas = chat.querySelector('[data-chat-personas]');
  const personasLista = chat.querySelector('[data-chat-personas-lista]');
  const csrf = chat.querySelector('input[name="csrfmiddlewaretoken"]')?.value || '';
  const sprite = document.querySelector('svg use')?.getAttribute('href')?.split('#')[0] || '';

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
  const post = (url, cuerpo) => fetch(url, {
    method: 'POST', body: cuerpo, credentials: 'same-origin',
    headers: { 'X-CSRFToken': csrf, Accept: 'application/json' },
  });

  /* ------------------------------------------------------------------ mensajes de la conversación */
  const cercaDelFinal = () => !mensajes || mensajes.scrollHeight - mensajes.scrollTop - mensajes.clientHeight < 120;
  const alFinal = () => {
    if (mensajes) mensajes.scrollTop = mensajes.scrollHeight;
  };
  if (window.location.hash.startsWith('#mensaje-')) {
    document.querySelector(window.location.hash)?.scrollIntoView({ block: 'end' });
  } else {
    alFinal();
  }

  const estado = (leido) => {
    const marca = elemento('span', `burbuja__estado${leido ? ' is-leido' : ''}`);
    marca.dataset.estado = '';
    marca.append(icono(leido ? 'check-check' : 'check'), elemento('span', 'visually-hidden', leido ? 'Leído' : 'Enviado'));
    return marca;
  };

  const agregar = (datos) => {
    if (!mensajes || document.getElementById(`mensaje-${datos.id}`)) return;
    const seguir = datos.mio || cercaDelFinal();
    mensajes.querySelector('[data-chat-sin-mensajes]')?.remove();
    const dias = mensajes.querySelectorAll('[data-chat-dia]');
    if (!dias.length || dias[dias.length - 1].dataset.chatDia !== datos.fecha) {
      const dia = elemento('p', 'chat__dia');
      dia.dataset.chatDia = datos.fecha;
      dia.append(elemento('span', '', 'Hoy'));
      mensajes.append(dia);
    }
    const burbuja = elemento('div', `burbuja is-nueva${datos.mio ? ' burbuja--mia' : ''}`);
    burbuja.id = `mensaje-${datos.id}`;
    burbuja.dataset.mensaje = String(datos.id);
    burbuja.append(elemento('p', 'burbuja__texto', datos.texto));
    const pie = elemento('p', 'burbuja__pie');
    const hora = elemento('time', '', datos.hora);
    pie.append(hora);
    if (datos.mio) pie.append(estado(false));
    burbuja.append(pie);
    mensajes.append(burbuja);
    if (seguir) alFinal();
  };

  const marcarLeidosHasta = (hasta) => {
    mensajes?.querySelectorAll('.burbuja--mia').forEach((burbuja) => {
      if (Number(burbuja.dataset.mensaje) > hasta) return;
      const marca = burbuja.querySelector('[data-estado]');
      if (marca && !marca.classList.contains('is-leido')) marca.replaceWith(estado(true));
    });
  };

  let porLeer = false;
  const marcarLeida = () => {
    if (!chat.dataset.leidaUrl) return;
    post(chat.dataset.leidaUrl).catch(() => {});
  };
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && porLeer) {
      porLeer = false;
      marcarLeida();
    }
  });

  /* ------------------------------------------------------------------ lista de conversaciones */
  const actualizarItem = (datos) => {
    if (!conversaciones) return;
    let fila = conversaciones.querySelector(`[data-conversacion-item="${datos.conversacion}"]`);
    if (!fila) {
      if (datos.mio) return;   /* la propia conversación nueva aparece al recargar */
      fila = elemento('li');
      fila.dataset.conversacionItem = String(datos.conversacion);
      fila.dataset.texto = datos.autor.toLowerCase();
      const enlace = elemento('a', 'chat-item');
      enlace.href = datos.url;
      const avatar = elemento('span', 'avatar chat-item__avatar', datos.iniciales);
      avatar.setAttribute('aria-hidden', 'true');
      const texto = elemento('span', 'chat-item__texto');
      const arriba = elemento('span', 'chat-item__fila');
      const hora = elemento('time', 'chat-item__hora');
      hora.dataset.chatItemHora = '';
      arriba.append(elemento('span', 'chat-item__nombre', datos.autor), hora);
      const abajo = elemento('span', 'chat-item__fila');
      const vista = elemento('span', 'chat-item__vista');
      vista.dataset.chatItemVista = '';
      const conteo = elemento('span', 'chat-item__conteo', '0');
      conteo.dataset.chatItemConteo = '';
      conteo.hidden = true;
      abajo.append(vista, conteo);
      texto.append(arriba, abajo);
      enlace.append(avatar, texto);
      fila.append(enlace);
    }
    fila.querySelector('[data-chat-item-vista]').textContent = `${datos.mio ? 'Tú: ' : ''}${datos.vista_previa}`;
    fila.querySelector('[data-chat-item-hora]').textContent = datos.hora;
    const conteo = fila.querySelector('[data-chat-item-conteo]');
    const enlace = fila.querySelector('.chat-item');
    if (!datos.mio && datos.conversacion !== conversacion) {
      conteo.textContent = String((Number(conteo.textContent) || 0) + 1);
      conteo.hidden = false;
      enlace.classList.add('is-sin-leer');
    }
    conversaciones.prepend(fila);
    if (sinConversaciones) sinConversaciones.hidden = true;
  };

  const limpiarConteo = (id) => {
    const fila = conversaciones?.querySelector(`[data-conversacion-item="${id}"]`);
    if (!fila) return;
    const conteo = fila.querySelector('[data-chat-item-conteo]');
    conteo.textContent = '0';
    conteo.hidden = true;
    fila.querySelector('.chat-item')?.classList.remove('is-sin-leer');
  };

  /* ------------------------------------------------------------------ eventos en tiempo real */
  document.addEventListener('mensajeria:evento', ({ detail: datos }) => {
    if (datos.evento === 'mensaje') {
      actualizarItem(datos);
      if (datos.conversacion !== conversacion) return;
      agregar(datos);
      if (!datos.mio) {
        if (document.visibilityState === 'visible') marcarLeida();
        else porLeer = true;
      }
    } else if (datos.evento === 'leido' && datos.conversacion === conversacion) {
      marcarLeidosHasta(datos.hasta);
    } else if (datos.evento === 'resumen') {
      limpiarConteo(datos.conversacion);
    }
  });

  /* ------------------------------------------------------------------ escribir */
  const ajustarAltura = () => {
    if (!campo) return;
    campo.style.height = 'auto';
    campo.style.height = `${Math.min(campo.scrollHeight + 2, 144)}px`;
  };
  campo?.addEventListener('input', ajustarAltura);
  campo?.addEventListener('keydown', (evento) => {
    if (evento.key === 'Enter' && !evento.shiftKey && !evento.isComposing) {
      evento.preventDefault();
      formulario?.requestSubmit();
    }
  });

  let enviando = false;
  formulario?.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    if (enviando || !campo.value.trim()) return;
    enviando = true;
    const boton = formulario.querySelector('button[type="submit"]');
    boton.disabled = true;
    if (error) error.hidden = true;
    try {
      const respuesta = await post(formulario.action, new FormData(formulario));
      const datos = await respuesta.json().catch(() => ({}));
      if (!respuesta.ok) throw new Error(datos.error || 'No se pudo enviar el mensaje.');
      agregar(datos);
      actualizarItem(datos);
      campo.value = '';
      ajustarAltura();
    } catch (problema) {
      if (error) {
        error.textContent = problema.message || 'No se pudo enviar el mensaje. Revisa tu conexión e inténtalo de nuevo.';
        error.hidden = false;
      }
    } finally {
      enviando = false;
      boton.disabled = false;
      campo.focus();
    }
  });
  if (campo && window.matchMedia('(min-width: 48rem)').matches) campo.focus({ preventScroll: true });

  /* ------------------------------------------------------------------ buscar */
  const normal = (texto) => texto.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();

  const pintarPersonas = (contactos, consulta) => {
    if (!personas || !personasLista) return;
    personasLista.replaceChildren();
    if (!contactos.length) {
      personasLista.append(elemento('li', 'chat__nadie', `Nadie coincide con «${consulta}» entre las personas a las que puedes escribir.`));
    }
    contactos.forEach((contacto) => {
      const fila = elemento('li');
      const forma = elemento('form');
      forma.method = 'post';
      forma.action = chat.dataset.nuevaUrl;
      const token = elemento('input');
      Object.assign(token, { type: 'hidden', name: 'csrfmiddlewaretoken', value: csrf });
      const boton = elemento('button', 'chat-persona');
      Object.assign(boton, { type: 'submit', name: 'destinatario', value: contacto.clave });
      const avatar = elemento('span', `avatar avatar--sm chat-persona__avatar--${contacto.tipo.toLowerCase()}`, contacto.iniciales);
      avatar.setAttribute('aria-hidden', 'true');
      const texto = elemento('span', 'chat-persona__texto');
      texto.append(elemento('span', 'chat-persona__nombre', contacto.nombre), elemento('span', 'chat-persona__detalle', contacto.detalle));
      boton.append(avatar, texto);
      forma.append(token, boton);
      fila.append(forma);
      personasLista.append(fila);
    });
    personas.hidden = false;
  };

  let pedido = null;
  let pausa = null;
  buscar?.addEventListener('input', () => {
    const consulta = buscar.value.trim();
    const filtro = normal(consulta);
    conversaciones?.querySelectorAll('[data-conversacion-item]').forEach((fila) => {
      fila.hidden = Boolean(filtro) && !normal(fila.dataset.texto || '').includes(filtro);
    });
    window.clearTimeout(pausa);
    if (consulta.length < 2) {
      if (personas) personas.hidden = true;
      return;
    }
    pausa = window.setTimeout(async () => {
      pedido?.abort();
      pedido = new AbortController();
      try {
        const respuesta = await fetch(`${chat.dataset.contactosUrl}?q=${encodeURIComponent(consulta)}`, {
          headers: { Accept: 'application/json' }, credentials: 'same-origin', signal: pedido.signal,
        });
        if (respuesta.ok) pintarPersonas((await respuesta.json()).contactos, consulta);
      } catch (problema) {
        /* búsqueda cancelada o sin conexión */
      }
    }, 250);
  });
})();
