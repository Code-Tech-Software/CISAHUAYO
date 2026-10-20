/* CISAHUAYO · pantalla de mensajes (templates/mensajes/bandeja.html)

   - Envía sin recargar (Intro envía, Mayús+Intro hace un salto de línea) y muestra el mensaje al momento.
   - Con el editor con formato (static/js/editor-mensajes.js) se manda el HTML (el servidor lo limpia) y su texto; no se
     envía un mensaje vacío (solo etiquetas de formato) ni mientras se sube una imagen o un documento. Los mensajes con
     formato se muestran con el HTML que ya viene limpio del servidor.
   - Documentos PDF (pedido del 2026-10-20): el clip de la barra (o soltarlos sobre la caja) los sube y los deja en fichas
     arriba de la caja; se envían con el mensaje (también solos, sin texto) y se muestran debajo del texto.
   - Con los eventos en tiempo real (static/js/avisos.js → «mensajeria:evento»): agrega los mensajes que llegan a la
     conversación abierta y la marca como leída (si la pestaña está a la vista), pone «Leído a las 10:42» en los propios
     cuando la otra persona los lee (a la vista en el último leído; en los demás, al pasar el puntero) y mantiene la lista
     de conversaciones (orden, vista previa, hora y no leídos; también la conversación recién empezada). Los separadores
     de día se vuelven a nombrar (Hoy, Ayer, Lunes 19 de octubre…) cuando cambia el día con la pantalla abierta.
   - Abierta en un mensaje encontrado (o en mensajes anteriores), los nuevos no se agregan al final: se ven con «Ver
     mensajes más recientes»; al enviar, se pasa a los más recientes.
   - Un mensaje retirado por moderación (evento «retirado») sale de la conversación abierta y la lista se queda con la
     vista previa del mensaje anterior (o sin la conversación, si ya no tiene mensajes).
   - Búsqueda: filtra las conversaciones, busca personas a las que se puede escribir y busca en el texto de los mensajes
     (y en los nombres de los documentos); «Ver más conversaciones» trae las siguientes sin recargar.
   Sin JavaScript la pantalla funciona con formularios normales.
*/
(() => {
  'use strict';

  const chat = document.querySelector('[data-chat]');
  if (!chat) return;

  const conversacion = Number(chat.dataset.conversacion || 0);
  const hayPosteriores = chat.hasAttribute('data-hay-posteriores');
  const mensajes = chat.querySelector('[data-chat-mensajes]');
  const formulario = chat.querySelector('[data-chat-formulario]');
  const campo = chat.querySelector('[data-chat-campo]');
  const error = chat.querySelector('[data-chat-error]');
  const conversaciones = chat.querySelector('[data-chat-conversaciones]');
  const sinConversaciones = chat.querySelector('[data-chat-sin-conversaciones]');
  const buscar = chat.querySelector('[data-chat-buscar]');
  const personas = chat.querySelector('[data-chat-personas]');
  const personasLista = chat.querySelector('[data-chat-personas-lista]');
  const encontrados = chat.querySelector('[data-chat-encontrados]');
  const encontradosLista = chat.querySelector('[data-chat-encontrados-lista]');
  const buscando = chat.querySelector('[data-chat-buscando]');
  const csrf = chat.querySelector('input[name="csrfmiddlewaretoken"]')?.value || '';
  const caja = chat.querySelector('[data-chat-caja]');
  const campoHtml = chat.querySelector('[data-chat-html]');
  const raizEditor = chat.querySelector('[data-editor]');
  const archivoAdjunto = chat.querySelector('[data-chat-adjuntar-archivo]');
  const listaAdjuntos = chat.querySelector('[data-chat-adjuntos]');
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

  /* ------------------------------------------------------------------ días */
  /* Como Mensajes/views._dia: Hoy, Ayer, «Lunes 19 de octubre» o, de otro año, «19 de octubre de 2025» */
  const DIAS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
  const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
  const fechaDe = (iso) => {
    const [anio, mes, dia] = iso.split('-').map(Number);
    return new Date(anio, mes - 1, dia);
  };
  const isoDe = (fecha) => `${fecha.getFullYear()}-${String(fecha.getMonth() + 1).padStart(2, '0')}-${String(fecha.getDate()).padStart(2, '0')}`;
  const etiquetaDeDia = (iso, hoyIso) => {
    if (iso === hoyIso) return 'Hoy';
    const hoy = fechaDe(hoyIso);
    const ayer = new Date(hoy);
    ayer.setDate(hoy.getDate() - 1);
    if (iso === isoDe(ayer)) return 'Ayer';
    const fecha = fechaDe(iso);
    const texto = fecha.getFullYear() === hoy.getFullYear()
      ? `${DIAS[fecha.getDay()]} ${fecha.getDate()} de ${MESES[fecha.getMonth()]}`
      : `${fecha.getDate()} de ${MESES[fecha.getMonth()]} de ${fecha.getFullYear()}`;
    return texto.charAt(0).toUpperCase() + texto.slice(1);
  };
  /* El «hoy» del colegio: el del servidor al cargar, más los días que han pasado desde entonces en este equipo */
  const hoyAlCargar = chat.dataset.hoy || isoDe(new Date());
  const cargadoEl = isoDe(new Date());
  const hoyAhora = () => {
    const pasados = Math.round((fechaDe(isoDe(new Date())) - fechaDe(cargadoEl)) / 86400000);
    const hoy = fechaDe(hoyAlCargar);
    hoy.setDate(hoy.getDate() + pasados);
    return isoDe(hoy);
  };
  const renombrarDias = (hoyIso) => {
    mensajes?.querySelectorAll('[data-chat-dia]').forEach((dia) => {
      const etiqueta = dia.querySelector('span');
      if (etiqueta) etiqueta.textContent = etiquetaDeDia(dia.dataset.chatDia, hoyIso);
    });
  };

  /* ------------------------------------------------------------------ mensajes de la conversación */
  const cercaDelFinal = () => !mensajes || mensajes.scrollHeight - mensajes.scrollTop - mensajes.clientHeight < 120;
  const alFinal = () => {
    if (mensajes) mensajes.scrollTop = mensajes.scrollHeight;
  };
  /* A un mensaje (#mensaje-N): se desplaza solo la conversación, no la página (el navegador, al seguir el ancla, mueve
     también la página y esconde el encabezado del chat). El encontrado al buscar, al centro; los demás, abajo. */
  const irAlMensaje = (destino) => {
    window.scrollTo(0, 0);
    const caja = mensajes.getBoundingClientRect();
    const lugar = destino.getBoundingClientRect();
    const margen = destino.classList.contains('is-destacado') ? (mensajes.clientHeight - lugar.height) / 2 : mensajes.clientHeight - lugar.height;
    mensajes.scrollTop += lugar.top - caja.top - Math.max(0, margen);
  };
  const destino = window.location.hash.startsWith('#mensaje-') ? document.querySelector(window.location.hash) : null;
  if (destino && mensajes) {
    if ('scrollRestoration' in window.history) window.history.scrollRestoration = 'manual';   /* al recargar, tampoco */
    irAlMensaje(destino);
    window.addEventListener('load', () => irAlMensaje(destino), { once: true });   /* ya con las imágenes cargadas */
  } else {
    alFinal();
  }

  /* Enviado (✓) o leído (✓✓, con la hora de lectura) */
  const estado = (leido, texto = 'Leído') => {
    const marca = elemento('span', `burbuja__estado${leido ? ' is-leido' : ''}`);
    marca.dataset.estado = '';
    const etiqueta = elemento('span', 'visually-hidden', leido ? texto : 'Enviado');
    if (leido) {
      marca.dataset.leidoTexto = texto;
      etiqueta.dataset.leido = '';
    }
    marca.append(icono(leido ? 'check-check' : 'check'), etiqueta);
    return marca;
  };

  /* La hora de lectura a la vista solo en el último mensaje propio leído; en los demás, al pasar el puntero */
  const ponerLectura = () => {
    const leidos = [...(mensajes?.querySelectorAll('.burbuja--mia [data-estado].is-leido') || [])];
    leidos.forEach((marca, posicion) => {
      const ultimo = posicion === leidos.length - 1;
      const etiqueta = marca.querySelector('[data-leido]');
      if (etiqueta) etiqueta.className = ultimo ? 'burbuja__leido' : 'visually-hidden';
      if (ultimo) marca.removeAttribute('data-tooltip');
      else marca.dataset.tooltip = marca.dataset.leidoTexto || 'Leído';
    });
  };

  const documentosDe = (lista) => {
    const contenedor = elemento('ul', 'burbuja__documentos');
    lista.forEach((documento) => {
      const fila = elemento('li');
      const enlace = elemento('a', 'documento-adjunto');
      Object.assign(enlace, { href: documento.url, target: '_blank', rel: 'noopener' });
      const marca = elemento('span', 'documento-adjunto__icono');
      marca.setAttribute('aria-hidden', 'true');
      marca.append(icono('file-text'));
      const texto = elemento('span', 'documento-adjunto__texto');
      texto.append(elemento('span', 'documento-adjunto__nombre', documento.nombre), elemento('span', 'documento-adjunto__tamano', documento.tamano));
      enlace.append(marca, texto);
      fila.append(enlace);
      contenedor.append(fila);
    });
    return contenedor;
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
    renombrarDias(datos.fecha);   /* el mensaje acaba de llegar: su día es hoy */
    const burbuja = elemento('div', `burbuja is-nueva${datos.mio ? ' burbuja--mia' : ''}`);
    burbuja.id = `mensaje-${datos.id}`;
    burbuja.dataset.mensaje = String(datos.id);
    if (datos.html) {
      /* Ya limpio en el servidor (Mensajes/enriquecido.py) */
      const contenido = elemento('div', 'burbuja__texto burbuja__texto--rico');
      contenido.innerHTML = datos.html;
      burbuja.append(contenido);
    } else if (datos.texto) {
      burbuja.append(elemento('p', 'burbuja__texto', datos.texto));
    }
    if (datos.documentos?.length) burbuja.append(documentosDe(datos.documentos));
    const pie = elemento('p', 'burbuja__pie');
    const hora = elemento('time', '', datos.hora);
    pie.append(hora);
    if (datos.mio) pie.append(estado(false));
    burbuja.append(pie);
    mensajes.append(burbuja);
    if (seguir) alFinal();
  };

  const marcarLeidosHasta = (hasta, texto) => {
    mensajes?.querySelectorAll('.burbuja--mia').forEach((burbuja) => {
      if (Number(burbuja.dataset.mensaje) > hasta) return;
      const marca = burbuja.querySelector('[data-estado]');
      if (marca && !marca.classList.contains('is-leido')) marca.replaceWith(estado(true, texto || 'Leído'));
    });
    ponerLectura();
  };

  let porLeer = false;
  const marcarLeida = () => {
    if (!chat.dataset.leidaUrl) return;
    post(chat.dataset.leidaUrl).catch(() => {});
  };
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') return;
    renombrarDias(hoyAhora());   /* por si cambió el día con la pantalla abierta */
    if (porLeer) {
      porLeer = false;
      marcarLeida();
    }
  });

  /* ------------------------------------------------------------------ lista de conversaciones */
  const filtrarConversaciones = () => {
    const filtro = normal(buscar?.value || '');
    conversaciones?.querySelectorAll('[data-conversacion-item]').forEach((fila) => {
      fila.hidden = Boolean(filtro) && !normal(fila.dataset.texto || '').includes(filtro);
    });
  };

  const actualizarItem = (datos) => {
    if (!conversaciones) return;
    let fila = conversaciones.querySelector(`[data-conversacion-item="${datos.conversacion}"]`);
    if (!fila) {
      /* Una conversación que aún no está en la lista: también la propia recién empezada (con quién: datos.con) */
      const con = datos.con || { nombre: datos.autor, iniciales: datos.iniciales, tipo: '' };
      const actual = datos.conversacion === conversacion;
      fila = elemento('li');
      fila.dataset.conversacionItem = String(datos.conversacion);
      fila.dataset.texto = con.nombre.toLowerCase();
      const enlace = elemento('a', `chat-item${actual ? ' is-actual' : ''}`);
      enlace.href = datos.url;
      if (actual) enlace.setAttribute('aria-current', 'page');
      const avatar = elemento('span', `avatar chat-item__avatar${con.tipo ? ` chat-persona__avatar--${con.tipo}` : ''}`, con.iniciales);
      avatar.setAttribute('aria-hidden', 'true');
      const texto = elemento('span', 'chat-item__texto');
      const arriba = elemento('span', 'chat-item__fila');
      const hora = elemento('time', 'chat-item__hora');
      hora.dataset.chatItemHora = '';
      arriba.append(elemento('span', 'chat-item__nombre', con.nombre), hora);
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
    if (!datos.mio && (datos.conversacion !== conversacion || hayPosteriores)) {
      conteo.textContent = String((Number(conteo.textContent) || 0) + 1);
      conteo.hidden = false;
      enlace.classList.add('is-sin-leer');
    }
    conversaciones.prepend(fila);
    filtrarConversaciones();
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

  /* «Ver más conversaciones»: las siguientes, sin recargar (sin JavaScript, el enlace lleva a la página siguiente) */
  chat.addEventListener('click', async (evento) => {
    const enlace = evento.target.closest('[data-chat-mas]');
    if (!enlace || !conversaciones) return;
    evento.preventDefault();
    if (enlace.classList.contains('is-loading')) return;
    enlace.classList.add('is-loading');
    try {
      const url = new URL(chat.dataset.conversacionesUrl, window.location.href);
      url.searchParams.set('despues', enlace.dataset.siguientes);
      if (conversacion) url.searchParams.set('actual', String(conversacion));
      const respuesta = await fetch(url, { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
      if (!respuesta.ok) throw new Error('sin respuesta');
      const datos = await respuesta.json();
      const plantilla = document.createElement('template');
      plantilla.innerHTML = datos.html;   /* lo pinta el servidor (templates/mensajes/_conversaciones.html) */
      plantilla.content.querySelectorAll('[data-conversacion-item]').forEach((fila) => {
        if (!conversaciones.querySelector(`[data-conversacion-item="${fila.dataset.conversacionItem}"]`)) conversaciones.append(fila);
      });
      filtrarConversaciones();
      if (datos.siguientes) {
        enlace.dataset.siguientes = datos.siguientes;
        enlace.href = `?despues=${encodeURIComponent(datos.siguientes)}`;
      } else {
        enlace.closest('[data-chat-mas-fila]')?.remove();
      }
    } catch (problema) {
      window.location.href = enlace.href;
    } finally {
      enlace.classList.remove('is-loading');
    }
  });

  /* ------------------------------------------------------------------ mensajes retirados (moderación) */
  /* Sale de la conversación abierta, con su día si se queda sin mensajes */
  const quitarMensaje = (datos) => {
    if (datos.conversacion !== conversacion || !mensajes) return;
    const burbuja = document.getElementById(`mensaje-${datos.id}`);
    if (!burbuja) return;
    const antes = burbuja.previousElementSibling;
    burbuja.remove();
    const despues = antes?.nextElementSibling;
    if (antes?.matches('[data-chat-dia]') && (!despues || despues.matches('[data-chat-dia]'))) antes.remove();
    if (!mensajes.querySelector('.burbuja')) {
      const vacio = elemento('p', 'chat__inicio-conversacion');
      vacio.dataset.chatSinMensajes = '';
      const marca = elemento('span', 'chat__icono-vacio');
      marca.setAttribute('aria-hidden', 'true');
      marca.append(icono('message-circle'));
      vacio.append(marca, 'Aún no hay mensajes.');
      mensajes.append(vacio);
    }
    ponerLectura();
  };

  /* La lista se queda con lo que sigue en la conversación: el mensaje anterior y lo que falta por leer */
  const retirarDeLaLista = (datos) => {
    const fila = conversaciones?.querySelector(`[data-conversacion-item="${datos.conversacion}"]`);
    if (!fila) return;
    if (datos.vacia) {
      fila.remove();
      if (sinConversaciones) sinConversaciones.hidden = Boolean(conversaciones.querySelector('[data-conversacion-item]'));
      return;
    }
    fila.querySelector('[data-chat-item-vista]').textContent = `${datos.mio ? 'Tú: ' : ''}${datos.vista_previa}`;
    fila.querySelector('[data-chat-item-hora]').textContent = datos.hora;
    const pendientes = datos.conversacion === conversacion ? 0 : Number(datos.pendientes) || 0;
    const conteo = fila.querySelector('[data-chat-item-conteo]');
    conteo.textContent = String(pendientes);
    conteo.hidden = !pendientes;
    fila.querySelector('.chat-item')?.classList.toggle('is-sin-leer', Boolean(pendientes));
  };

  /* ------------------------------------------------------------------ eventos en tiempo real */
  document.addEventListener('mensajeria:evento', ({ detail: datos }) => {
    if (datos.evento === 'mensaje') {
      actualizarItem(datos);
      /* Abierta en mensajes anteriores: el nuevo se ve en «Ver mensajes más recientes» (y queda sin leer) */
      if (datos.conversacion !== conversacion || hayPosteriores) return;
      agregar(datos);
      if (!datos.mio) {
        if (document.visibilityState === 'visible') marcarLeida();
        else porLeer = true;
      }
    } else if (datos.evento === 'retirado') {
      quitarMensaje(datos);
      retirarDeLaLista(datos);
    } else if (datos.evento === 'leido' && datos.conversacion === conversacion) {
      marcarLeidosHasta(datos.hasta, datos.leido);
    } else if (datos.evento === 'resumen') {
      limpiarConteo(datos.conversacion);
    }
  });

  /* ------------------------------------------------------------------ documentos adjuntos (PDF) */
  const adjuntos = [];   /* {id, nombre}: los ya subidos, en el orden en que se agregaron */
  let subiendoAdjuntos = 0;
  let editor = null;

  const actualizarCaja = () => {
    const vacia = editor ? editor.vacio() : !campo?.value.trim();
    caja?.classList.toggle('is-vacia', (vacia && !adjuntos.length) || Boolean(editor?.subiendo()) || subiendoAdjuntos > 0);
    if (campo && !editor) campo.required = !adjuntos.length;
  };

  const mostrarError = (texto) => {
    if (!error) return;
    error.textContent = texto;
    error.hidden = !texto;
  };

  const fichaDeAdjunto = (nombre) => {
    const ficha = elemento('li', 'chat-adjunto is-subiendo');
    const marca = elemento('span', 'chat-adjunto__icono');
    marca.setAttribute('aria-hidden', 'true');
    marca.append(icono('file-text'));
    const texto = elemento('span', 'chat-adjunto__texto');
    const detalle = elemento('span', 'chat-adjunto__detalle', 'Subiendo…');
    texto.append(elemento('span', 'chat-adjunto__nombre', nombre), detalle);
    const quitar = elemento('button', 'btn btn--ghost btn--icon btn--sm chat-adjunto__quitar');
    quitar.type = 'button';
    quitar.disabled = true;
    quitar.setAttribute('aria-label', `Quitar «${nombre}»`);
    quitar.append(icono('x'));
    ficha.append(marca, texto, quitar);
    return { ficha, detalle, quitar };
  };

  const subirAdjuntos = async (archivos) => {
    if (!archivoAdjunto || !listaAdjuntos) return;
    const maximo = Number(archivoAdjunto.dataset.maximo) || 10;
    const maximoMb = Number(archivoAdjunto.dataset.maximoMb) || 5;
    mostrarError('');
    for (const archivo of [...archivos]) {
      if (adjuntos.length + subiendoAdjuntos >= maximo) {
        mostrarError(`Se pueden adjuntar hasta ${maximo} documentos por mensaje.`);
        break;
      }
      if (!/\.pdf$/i.test(archivo.name)) {
        mostrarError(`«${archivo.name}»: solo se pueden adjuntar documentos PDF.`);
        continue;
      }
      if (archivo.size > maximoMb * 1024 * 1024) {
        mostrarError(`«${archivo.name}» pesa más de ${maximoMb} MB.`);
        continue;
      }
      const { ficha, detalle, quitar } = fichaDeAdjunto(archivo.name);
      listaAdjuntos.append(ficha);
      listaAdjuntos.hidden = false;
      subiendoAdjuntos += 1;
      actualizarCaja();
      try {
        const datos = new FormData();
        datos.append('documento', archivo, archivo.name);
        const respuesta = await post(archivoAdjunto.dataset.url, datos);
        const resultado = await respuesta.json().catch(() => ({}));
        if (!respuesta.ok) throw new Error(resultado.error || 'No se pudo adjuntar el documento.');
        const adjunto = { id: resultado.id, nombre: resultado.nombre };
        adjuntos.push(adjunto);
        ficha.classList.remove('is-subiendo');
        detalle.textContent = resultado.tamano;
        quitar.disabled = false;
        quitar.addEventListener('click', () => {
          adjuntos.splice(adjuntos.indexOf(adjunto), 1);
          ficha.remove();
          listaAdjuntos.hidden = !listaAdjuntos.children.length;
          actualizarCaja();
          if (editor) editor.enfocar();
          else campo?.focus();
        });
      } catch (problema) {
        ficha.remove();
        mostrarError(problema.message || 'No se pudo adjuntar el documento. Revisa tu conexión e inténtalo de nuevo.');
      } finally {
        subiendoAdjuntos -= 1;
        listaAdjuntos.hidden = !listaAdjuntos.children.length;
        actualizarCaja();
      }
    }
  };

  const vaciarAdjuntos = () => {
    adjuntos.length = 0;
    listaAdjuntos?.replaceChildren();
    if (listaAdjuntos) listaAdjuntos.hidden = true;
  };

  chat.querySelector('[data-chat-adjuntar]')?.addEventListener('click', () => archivoAdjunto?.click());
  archivoAdjunto?.addEventListener('change', () => {
    if (archivoAdjunto.files.length) subirAdjuntos(archivoAdjunto.files);
    archivoAdjunto.value = '';
  });
  /* Soltar documentos sobre la caja de escribir (las imágenes las inserta el editor) */
  const soloDocumentos = (lista) => [...(lista || [])].filter((archivo) => /\.pdf$/i.test(archivo.name) || archivo.type === 'application/pdf');
  caja?.addEventListener('dragover', (evento) => {
    if (archivoAdjunto && [...(evento.dataTransfer?.types || [])].includes('Files')) evento.preventDefault();
  });
  caja?.addEventListener('drop', (evento) => {
    const documentos = soloDocumentos(evento.dataTransfer?.files);
    if (!documentos.length || !archivoAdjunto) return;
    evento.preventDefault();
    subirAdjuntos(documentos);
  });

  /* ------------------------------------------------------------------ escribir */
  const enviarAhora = () => formulario?.requestSubmit();
  if (raizEditor && window.EditorEnriquecido && campo) {
    editor = new window.EditorEnriquecido(raizEditor, {
      alEnviar: enviarAhora,
      alCambiar: () => actualizarCaja(),
    });
    campo.hidden = true;
    campo.required = false;
    caja?.classList.add('chat__caja--editor', 'is-vacia');
    chat.querySelector('[data-chat-atajos-editor]')?.removeAttribute('hidden');
  }

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
    if (enviando) return;
    if (subiendoAdjuntos) {
      mostrarError('Espera a que termine de subirse el documento.');
      return;
    }
    if (editor) {
      if (editor.subiendo()) {
        mostrarError('Espera a que termine de subirse la imagen.');
        return;
      }
      if (editor.vacio() && !adjuntos.length) return;   /* solo etiquetas de formato: nada que enviar */
      campo.value = editor.vacio() ? '' : editor.texto();
      campoHtml.value = editor.vacio() ? '' : editor.html();
    } else if (!campo.value.trim() && !adjuntos.length) {
      return;
    }
    enviando = true;
    const boton = formulario.querySelector('button[type="submit"]');
    boton.disabled = true;
    boton.classList.add('is-loading');
    if (error) error.hidden = true;
    try {
      const cuerpo = new FormData(formulario);
      adjuntos.forEach((adjunto) => cuerpo.append('documentos', String(adjunto.id)));
      const respuesta = await post(formulario.action, cuerpo);
      const datos = await respuesta.json().catch(() => ({}));
      if (!respuesta.ok) throw new Error(datos.error || 'No se pudo enviar el mensaje.');
      if (hayPosteriores) {   /* se estaba viendo una parte anterior: a los más recientes, con el nuevo */
        window.location.href = `${chat.dataset.conversacionUrl}#mensaje-${datos.id}`;
        return;
      }
      agregar(datos);
      actualizarItem(datos);
      campo.value = '';
      if (campoHtml) campoHtml.value = '';
      editor?.vaciar();
      vaciarAdjuntos();
      ajustarAltura();
      actualizarCaja();
    } catch (problema) {
      if (error) {
        error.textContent = problema.message || 'No se pudo enviar el mensaje. Revisa tu conexión e inténtalo de nuevo.';
        error.hidden = false;
      }
    } finally {
      enviando = false;
      boton.disabled = false;
      boton.classList.remove('is-loading');
      if (editor) editor.enfocar();
      else campo.focus();
    }
  });
  if (window.matchMedia('(min-width: 48rem)').matches) {
    if (editor) editor.enfocar();
    else campo?.focus({ preventScroll: true });
  }

  /* ------------------------------------------------------------------ buscar */
  function normal(texto) {
    return texto.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();
  }

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

  /* Los mensajes que tienen lo buscado: al tocar uno, se abre la conversación en ese mensaje */
  const pintarEncontrados = (lista, consulta) => {
    if (!encontrados || !encontradosLista) return;
    encontradosLista.replaceChildren();
    if (!lista.length) encontradosLista.append(elemento('li', 'chat__nadie', `Ningún mensaje tiene «${consulta}».`));
    lista.forEach((resultado) => {
      const fila = elemento('li');
      const enlace = elemento('a', 'chat-resultado');
      enlace.href = resultado.url;
      const avatar = elemento('span', `avatar avatar--sm chat-persona__avatar--${resultado.tipo}`, resultado.iniciales);
      avatar.setAttribute('aria-hidden', 'true');
      const texto = elemento('span', 'chat-resultado__texto');
      const arriba = elemento('span', 'chat-resultado__fila');
      arriba.append(elemento('span', 'chat-resultado__nombre', resultado.nombre), elemento('span', 'chat-resultado__hora', resultado.hora));
      const fragmento = elemento('span', 'chat-resultado__fragmento');
      /* Escapado en el servidor (Mensajes/reglas.resaltar): solo agrega <mark> en lo que coincide */
      fragmento.innerHTML = `${resultado.mio ? 'Tú: ' : ''}${resultado.fragmento}`;
      texto.append(arriba, fragmento);
      enlace.append(avatar, texto);
      fila.append(enlace);
      encontradosLista.append(fila);
    });
    encontrados.hidden = false;
  };

  const pedirJson = async (url, consulta, senal) => {
    const respuesta = await fetch(`${url}?q=${encodeURIComponent(consulta)}`, {
      headers: { Accept: 'application/json' }, credentials: 'same-origin', signal: senal,
    });
    return respuesta.ok ? respuesta.json() : null;
  };

  let pedido = null;
  let pausa = null;
  buscar?.addEventListener('input', () => {
    const consulta = buscar.value.trim();
    filtrarConversaciones();
    window.clearTimeout(pausa);
    if (consulta.length < 2) {
      pedido?.abort();
      if (buscando) buscando.hidden = true;
      if (personas) personas.hidden = true;
      if (encontrados) encontrados.hidden = true;
      return;
    }
    pausa = window.setTimeout(async () => {
      pedido?.abort();
      const este = new AbortController();
      pedido = este;
      if (buscando) buscando.hidden = false;
      try {
        const [deContactos, deMensajes] = await Promise.all([
          pedirJson(chat.dataset.contactosUrl, consulta, este.signal),
          chat.dataset.buscarUrl ? pedirJson(chat.dataset.buscarUrl, consulta, este.signal) : null,
        ]);
        if (deContactos) pintarPersonas(deContactos.contactos, consulta);
        if (deMensajes) pintarEncontrados(deMensajes.mensajes, consulta);
      } catch (problema) {
        /* búsqueda cancelada o sin conexión */
      } finally {
        if (pedido === este && buscando) buscando.hidden = true;
      }
    }, 250);
  });
})();
