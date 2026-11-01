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
   - Citas, correcciones y «escribiendo…» (2026-10-23): cada mensaje tiene «Responder» (la cita queda arriba de la caja y
     se envía con su id) y, los propios en sus primeros 2 minutos, «Corregir» (en el lugar; queda «editado» para los
     dos). Mientras se escribe se avisa a la otra persona, a lo más cada 3 segundos, por el WebSocket de avisos.js; su
     «está escribiendo…» se quita a los 5 segundos sin avisos o cuando llega su mensaje.
   - Borradores (2026-10-27): lo que se está escribiendo (con su cita y sus documentos) se guarda en el navegador por
     conversación y vuelve al abrirla otra vez. El filtro «Sin leer» de la lista se conserva en sus enlaces, y el
     resumen de una conversación dejada «no leída» le pone su conteo.
   - Sin recargar (2026-10-31): cada conversación se abre reemplazando solo el panel de la derecha (?panel=1,
     templates/mensajes/_hilo.html), así que la lista se queda donde estaba; la dirección y el botón «atrás» siguen
     funcionando. montarHilo() vuelve a tomar los elementos del panel nuevo; casi todas las escuchas están delegadas en
     la pantalla y sirven para cualquier panel. Si algo falla, se abre la dirección normal.
   - Los mensajes anteriores llegan al subir por la conversación. «Nuevo mensaje» abre el directorio de personas, la
     búsqueda tiene filtros (y también hay una dentro de la conversación), y una ventana lista los archivos enviados.
   - Destacar, archivar (con «Deshacer»), marcar todo como leído y la vista compacta se hacen sin recargar. Cerca del
     límite aparece un contador de caracteres, y un aviso dice si se cortó el tiempo real (avisos.js → «avisos:conexion»).
   Sin JavaScript la pantalla funciona con formularios normales.
*/
(() => {
  'use strict';

  const chat = document.querySelector('[data-chat]');
  if (!chat) return;

  /* Lo de la conversación abierta: cambia al abrir otra sin recargar la página (montarHilo) */
  let hilo = null;
  let conversacion = 0;
  let hayPosteriores = false;
  let mensajes = null;
  let formulario = null;
  let campo = null;
  let error = null;
  let caja = null;
  let campoHtml = null;
  let raizEditor = null;
  let archivoAdjunto = null;
  let listaAdjuntos = null;
  let barraRespuesta = null;
  let respondeA = null;
  let escribiendo = null;
  let contador = null;

  const filtroDeLista = chat.dataset.filtro || '';   /* la bandeja elegida («?sin_leer=1»): sus enlaces la conservan */
  const lista = chat.querySelector('.chat__lista');
  const conversaciones = chat.querySelector('[data-chat-conversaciones]');
  const sinConversaciones = chat.querySelector('[data-chat-sin-conversaciones]');
  const formaBuscar = chat.querySelector('[data-chat-buscar-forma]');
  const buscar = chat.querySelector('[data-chat-buscar]');
  const personas = chat.querySelector('[data-chat-personas]');
  const personasLista = chat.querySelector('[data-chat-personas-lista]');
  const encontrados = chat.querySelector('[data-chat-encontrados]');
  const encontradosLista = chat.querySelector('[data-chat-encontrados-lista]');
  const buscando = chat.querySelector('[data-chat-buscando]');
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
  /* Al abrir la conversación: en el mensaje de la dirección (#mensaje-N) o al final */
  const colocar = () => {
    const destino = window.location.hash.startsWith('#mensaje-') ? document.querySelector(window.location.hash) : null;
    if (destino && mensajes) {
      if ('scrollRestoration' in window.history) window.history.scrollRestoration = 'manual';   /* al recargar, tampoco */
      irAlMensaje(destino);
      if (document.readyState !== 'complete') window.addEventListener('load', () => irAlMensaje(destino), { once: true });   /* ya con las imágenes cargadas */
    } else {
      alFinal();
    }
  };

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
      const descargar = elemento('a', 'documento-adjunto__descargar');
      descargar.href = `${documento.url}?descargar=1`;
      descargar.setAttribute('aria-label', `Descargar ${documento.nombre}`);
      descargar.dataset.tooltip = 'Descargar';
      descargar.append(icono('download'));
      fila.append(enlace, descargar);
      contenedor.append(fila);
    });
    return contenedor;
  };

  /* ------------------------------------------------------------------ citas y correcciones */
  const citaDe = (cita) => {
    const enlace = elemento('a', 'burbuja__cita');
    enlace.href = `${hilo?.dataset.conversacionUrl || ''}?mensaje=${cita.id}#mensaje-${cita.id}`;
    enlace.dataset.chatIrA = String(cita.id);
    enlace.append(elemento('span', 'burbuja__cita-autor', cita.autor), elemento('span', 'burbuja__cita-texto', cita.texto));
    return enlace;
  };

  const editableHasta = (burbuja) => Date.parse(burbuja.dataset.editableHasta || '') || 0;

  /* «Responder» en todos (si se puede escribir), «Corregir» en los propios mientras dure el plazo y «Reportar» en los
     de la otra persona (también si la conversación ya no admite mensajes) */
  const ponerAcciones = (burbuja) => {
    if (burbuja.querySelector('.burbuja__acciones')) return;
    const acciones = elemento('div', 'burbuja__acciones');
    const boton = (nombre, etiqueta, accion) => {
      const nodo = elemento('button', 'burbuja__accion');
      nodo.type = 'button';
      nodo.dataset.chatAccion = accion;
      nodo.setAttribute('aria-label', etiqueta);
      nodo.dataset.tooltip = etiqueta;
      nodo.append(icono(nombre));
      return nodo;
    };
    if (formulario) acciones.append(boton('reply', 'Responder', 'responder'));
    const restante = editableHasta(burbuja) - Date.now();
    if (formulario && restante > 0) {
      const corregir = boton('pencil', 'Corregir', 'corregir');
      acciones.append(corregir);
      window.setTimeout(() => corregir.remove(), restante);
    }
    if (hilo?.dataset.reportarUrl && !burbuja.classList.contains('burbuja--mia') && !burbuja.hasAttribute('data-reportado')) {
      acciones.append(boton('flag', 'Reportar al administrador', 'reportar'));
    }
    if (acciones.children.length) burbuja.append(acciones);
  };

  /* Reportar un mensaje recibido al administrador: un motivo opcional y listo (quien lo escribió no se entera) */
  const reportar = (burbuja) => {
    if (burbuja.querySelector('.burbuja__reporte')) return;
    const forma = elemento('form', 'burbuja__edicion burbuja__reporte');
    const etiqueta = elemento('label', 'burbuja__reporte-titulo', '¿Por qué es inapropiado? (opcional)');
    const motivo = elemento('textarea', 'field__control');
    motivo.maxLength = 300;
    motivo.rows = 2;
    motivo.id = `motivo-reporte-${burbuja.dataset.mensaje}`;
    etiqueta.htmlFor = motivo.id;
    const nota = elemento('p', 'burbuja__reporte-nota', 'Lo revisará el administrador del colegio. La otra persona no se entera.');
    const botones = elemento('div', 'burbuja__edicion-botones');
    const cancelar = elemento('button', 'btn btn--ghost btn--sm', 'Cancelar');
    cancelar.type = 'button';
    const enviarReporte = elemento('button', 'btn btn--danger btn--sm', 'Reportar');
    enviarReporte.type = 'submit';
    botones.append(cancelar, enviarReporte);
    forma.append(etiqueta, motivo, nota, botones);
    burbuja.querySelector('.burbuja__pie').before(forma);
    motivo.focus();
    cancelar.addEventListener('click', () => forma.remove());
    motivo.addEventListener('keydown', (evento) => {
      if (evento.key === 'Escape') forma.remove();
    });
    forma.addEventListener('submit', async (evento) => {
      evento.preventDefault();
      enviarReporte.disabled = true;
      try {
        const cuerpo = new FormData();
        cuerpo.append('motivo', motivo.value);
        const url = hilo.dataset.reportarUrl.replace(/\/0\/reportar\/$/, `/${burbuja.dataset.mensaje}/reportar/`);
        const respuesta = await post(url, cuerpo);
        const datos = await respuesta.json().catch(() => ({}));
        if (!respuesta.ok) throw new Error(datos.error || 'No se pudo reportar el mensaje.');
        forma.remove();
        burbuja.dataset.reportado = '';
        burbuja.querySelector('[data-chat-accion="reportar"]')?.remove();
        const marca = elemento('span', 'burbuja__reportado', 'Reportado');
        marca.dataset.tooltip = 'Lo reportaste al administrador del colegio';
        burbuja.querySelector('.burbuja__pie')?.append(marca);
        mostrarError('');
        if (estadoDelReporte) estadoDelReporte.textContent = datos.mensaje || 'Se reportó el mensaje.';
      } catch (problema) {
        enviarReporte.disabled = false;
        mostrarError(problema.message);
      }
    });
  };
  /* Para lectores de pantalla: la confirmación del reporte */
  const estadoDelReporte = elemento('p', 'visually-hidden');
  estadoDelReporte.setAttribute('role', 'status');
  chat.append(estadoDelReporte);

  /* El texto nuevo de un mensaje corregido (aquí, en otra pestaña o por la otra persona), con su formato si lo tiene */
  const ponerCorreccion = (datos) => {
    const burbuja = document.getElementById(`mensaje-${datos.id}`);
    if (!burbuja) return;
    burbuja.querySelector('.burbuja__edicion')?.remove();
    burbuja.querySelectorAll('.burbuja__texto').forEach((nodo) => nodo.remove());
    let texto;
    if (datos.html) {
      texto = elemento('div', 'burbuja__texto burbuja__texto--rico');
      texto.innerHTML = datos.html;   /* ya limpio en el servidor (Mensajes/enriquecido.py) */
    } else {
      texto = elemento('p', 'burbuja__texto', datos.texto);
    }
    const cita = burbuja.querySelector('.burbuja__cita');
    if (cita) cita.after(texto);
    else burbuja.prepend(texto);
    const pie = burbuja.querySelector('.burbuja__pie');
    if (pie && !pie.querySelector('.burbuja__editado')) pie.querySelector('time')?.after(elemento('span', 'burbuja__editado', 'editado'));
    /* Si es el último de la conversación, también cambia la vista previa de la lista */
    const fila = conversaciones?.querySelector(`[data-conversacion-item="${datos.conversacion}"]`);
    const todas = mensajes?.querySelectorAll('.burbuja');
    if (fila && todas?.length && todas[todas.length - 1] === burbuja) {
      fila.querySelector('[data-chat-item-vista]').textContent = `${datos.mio ? 'Tú: ' : ''}${datos.vista_previa}`;
    }
  };

  /* Un mensaje con formato se corrige en el lugar con su formato (negritas, listas, tablas…): el servidor lo vuelve a
     limpiar. Lo que se pega entra como texto. */
  const areaConFormato = (original) => {
    const area = elemento('div', 'field__control burbuja__edicion-rico burbuja__texto--rico');
    area.contentEditable = 'true';
    area.setAttribute('role', 'textbox');
    area.setAttribute('aria-multiline', 'true');
    area.innerHTML = original.innerHTML;   /* el HTML que ya se muestra, limpio en el servidor */
    area.addEventListener('paste', (evento) => {
      evento.preventDefault();
      document.execCommand('insertText', false, evento.clipboardData?.getData('text/plain') || '');
    });
    return area;
  };

  const corregir = (burbuja) => {
    if (burbuja.querySelector('.burbuja__edicion')) return;
    const original = burbuja.querySelector('.burbuja__texto');
    const conFormato = Boolean(original?.classList.contains('burbuja__texto--rico'));
    const forma = elemento('form', 'burbuja__edicion');
    const area = conFormato ? areaConFormato(original) : elemento('textarea', 'field__control');
    if (!conFormato) {
      area.value = original ? original.innerText.trim() : '';
      area.maxLength = Number(campo?.maxLength) > 0 ? Number(campo.maxLength) : 2000;
    }
    const contenido = () => (conFormato ? area.innerText : area.value);
    area.setAttribute('aria-label', 'Corregir el mensaje');
    const botones = elemento('div', 'burbuja__edicion-botones');
    const cancelar = elemento('button', 'btn btn--ghost btn--sm', 'Cancelar');
    cancelar.type = 'button';
    const guardar = elemento('button', 'btn btn--sm', 'Guardar');
    guardar.type = 'submit';
    botones.append(cancelar, guardar);
    forma.append(area, botones);
    if (original) original.hidden = true;
    (original || burbuja.querySelector('.burbuja__pie')).before(forma);
    area.focus();
    const cerrar = () => {
      forma.remove();
      if (original) original.hidden = false;
    };
    cancelar.addEventListener('click', cerrar);
    area.addEventListener('keydown', (evento) => {
      if (evento.key === 'Escape') cerrar();
      /* Como en la caja de escribir: Intro guarda; en listas y tablas, hace un renglón nuevo */
      const nodo = conFormato ? window.getSelection()?.anchorNode : null;
      const lugar = nodo?.nodeType === Node.ELEMENT_NODE ? nodo : nodo?.parentElement;
      const enListaOTabla = Boolean(lugar && area.contains(lugar) && lugar.closest('li, td, th'));
      if (evento.key === 'Enter' && !evento.shiftKey && !evento.isComposing && !enListaOTabla) {
        evento.preventDefault();
        forma.requestSubmit();
      }
    });
    forma.addEventListener('submit', async (evento) => {
      evento.preventDefault();
      if (!contenido().trim()) return;
      guardar.disabled = true;
      try {
        const cuerpo = new FormData();
        cuerpo.append('texto', contenido());
        if (conFormato) cuerpo.append('html', area.innerHTML);
        const respuesta = await post(burbuja.dataset.urlEditar, cuerpo);
        const datos = await respuesta.json().catch(() => ({}));
        if (!respuesta.ok) throw new Error(datos.error || 'No se pudo corregir el mensaje.');
        ponerCorreccion(datos);
      } catch (problema) {
        mostrarError(problema.message);
        cerrar();
      }
    });
  };

  /* Respondiendo a un mensaje: su cita arriba de la caja, hasta enviar o quitarla */
  const quitarRespuesta = () => {
    if (!barraRespuesta) return;
    barraRespuesta.hidden = true;
    respondeA.value = '';
    guardarBorradorLuego();
  };
  const ponerRespuesta = (id, autor, cita) => {
    respondeA.value = id;
    barraRespuesta.querySelector('[data-chat-respuesta-autor]').textContent = autor;
    barraRespuesta.querySelector('[data-chat-respuesta-cita]').textContent = cita;
    barraRespuesta.hidden = false;
  };
  const responder = (burbuja) => {
    if (!barraRespuesta) return;
    const texto = (burbuja.querySelector('.burbuja__texto') || burbuja.querySelector('.burbuja__documentos'))?.innerText.trim() || '';
    ponerRespuesta(burbuja.dataset.mensaje, burbuja.classList.contains('burbuja--mia') ? 'Tú' : (burbuja.dataset.autor || ''),
      texto.length > 120 ? `${texto.slice(0, 119)}…` : texto);
    guardarBorradorLuego();
    if (editor) editor.enfocar();
    else campo?.focus();
  };

  chat.addEventListener('click', (evento) => {
    if (evento.target.closest('[data-chat-respuesta-quitar]')) {
      quitarRespuesta();
      return;
    }
    if (evento.target.closest('[data-chat-adjuntar]')) {
      archivoAdjunto?.click();
      return;
    }
    const accion = evento.target.closest('[data-chat-accion]');
    if (accion) {
      const burbuja = accion.closest('.burbuja');
      if (accion.dataset.chatAccion === 'responder') responder(burbuja);
      else if (accion.dataset.chatAccion === 'reportar') reportar(burbuja);
      else if (editableHasta(burbuja) > Date.now()) corregir(burbuja);
      else accion.remove();
      return;
    }
    const cita = evento.target.closest('[data-chat-ir-a]');
    if (!cita) return;
    evento.preventDefault();
    const citado = document.getElementById(`mensaje-${cita.dataset.chatIrA}`);
    if (citado) {
      citado.scrollIntoView({ block: 'center', behavior: 'smooth' });
      citado.classList.add('is-destacado');
      window.setTimeout(() => citado.classList.remove('is-destacado'), 1600);
    } else {   /* no está a la vista: se abre la conversación en ese mensaje */
      abrir(cita.href);
    }
  });

  /* ------------------------------------------------------------------ «escribiendo…» */
  let finEscribiendo = null;
  const ocultarEscribiendo = () => {
    if (escribiendo) escribiendo.hidden = true;
    window.clearTimeout(finEscribiendo);
  };
  const mostrarEscribiendo = () => {
    if (!escribiendo) return;
    escribiendo.hidden = false;
    window.clearTimeout(finEscribiendo);
    finEscribiendo = window.setTimeout(ocultarEscribiendo, 5000);
  };
  let ultimoAviso = 0;
  const avisarQueEscribo = () => {
    if (!conversacion || Date.now() - ultimoAviso < 3000) return;
    ultimoAviso = Date.now();
    document.dispatchEvent(new CustomEvent('mensajeria:enviar', { detail: { evento: 'escribiendo', conversacion } }));
  };

  const agregar = (datos) => {
    if (!mensajes || document.getElementById(`mensaje-${datos.id}`)) return;
    const seguir = datos.mio || cercaDelFinal();
    mensajes.querySelector('[data-chat-sin-mensajes]')?.remove();
    const dias = mensajes.querySelectorAll('[data-chat-dia]');
    if (!dias.length || dias[dias.length - 1].dataset.chatDia !== datos.fecha) {
      const dia = elemento('p', 'chat__dia');
      dia.dataset.chatDia = datos.fecha;
      dia.append(elemento('span', ''));
      mensajes.append(dia);
    }
    /* Normalmente acaba de llegar (su día es hoy); al ponerse al día después de una desconexión puede ser de antes */
    renombrarDias(datos.fecha > hoyAhora() ? datos.fecha : hoyAhora());
    const burbuja = elemento('div', `burbuja is-nueva${datos.mio ? ' burbuja--mia' : ''}`);
    burbuja.id = `mensaje-${datos.id}`;
    burbuja.dataset.mensaje = String(datos.id);
    burbuja.dataset.autor = datos.autor;
    if (datos.editable_hasta) {
      burbuja.dataset.editableHasta = datos.editable_hasta;
      burbuja.dataset.urlEditar = datos.url_editar;
    }
    if (datos.cita) burbuja.append(citaDe(datos.cita));
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
    if (datos.editado) pie.append(elemento('span', 'burbuja__editado', 'editado'));
    if (datos.mio) pie.append(estado(false));
    burbuja.append(pie);
    ponerAcciones(burbuja);
    mensajes.append(burbuja);
    if (!datos.mio) ocultarEscribiendo();
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
    if (!hilo?.dataset.leidaUrl) return;
    post(hilo.dataset.leidaUrl).catch(() => {});
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

  /* Si la conversación de un mensaje que llegó sigue en la bandeja que se está viendo */
  const entraEnLaLista = (datos, fila) => {
    if (datos.conversacion === conversacion) return true;
    if (chat.dataset.vista === 'archivadas') return false;   /* un mensaje nuevo la regresa a la bandeja */
    if (chat.dataset.vista === 'destacadas' && !fila) return false;
    const tipo = (datos.con?.tipo || '').toUpperCase();
    return !chat.dataset.tipo || !tipo || chat.dataset.tipo === tipo;
  };

  const actualizarItem = (datos) => {
    if (!conversaciones) return;
    let fila = conversaciones.querySelector(`[data-conversacion-item="${datos.conversacion}"]`);
    if (!entraEnLaLista(datos, fila)) {
      fila?.remove();
      return;
    }
    if (!fila) {
      /* Una conversación que aún no está en la lista: también la propia recién empezada (con quién: datos.con) */
      const con = datos.con || { nombre: datos.autor, iniciales: datos.iniciales, tipo: '' };
      const actual = datos.conversacion === conversacion;
      fila = elemento('li');
      fila.dataset.conversacionItem = String(datos.conversacion);
      fila.dataset.texto = con.nombre.toLowerCase();
      const enlace = elemento('a', `chat-item${actual ? ' is-actual' : ''}`);
      enlace.href = `${datos.url}${filtroDeLista}`;
      if (actual) enlace.setAttribute('aria-current', 'page');
      const avatar = elemento('span', `avatar chat-item__avatar${con.tipo ? ` chat-persona__avatar--${con.tipo}` : ''}`, con.iniciales);
      avatar.setAttribute('aria-hidden', 'true');
      const texto = elemento('span', 'chat-item__texto');
      const arriba = elemento('span', 'chat-item__fila');
      const hora = elemento('time', 'chat-item__hora');
      hora.dataset.chatItemHora = '';
      const estrella = elemento('span', 'chat-item__marca');
      estrella.dataset.chatItemEstrella = '';
      estrella.hidden = true;
      estrella.append(icono('star'), elemento('span', 'visually-hidden', 'Destacada'));
      arriba.append(elemento('span', 'chat-item__nombre', con.nombre), estrella, hora);
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
    } else if (datos.mio) {   /* quien escribe ya leyó todo lo anterior (también desde otra pestaña) */
      conteo.textContent = '0';
      conteo.hidden = true;
      enlace.classList.remove('is-sin-leer');
    }
    conversaciones.prepend(fila);
    filtrarConversaciones();
    if (sinConversaciones) sinConversaciones.hidden = true;
  };

  /* Lo que queda pendiente en una conversación (0 al leerla; 1 o más si se dejó «no leída») */
  const ponerConteo = (id, pendientes) => {
    const fila = conversaciones?.querySelector(`[data-conversacion-item="${id}"]`);
    if (!fila) return;
    const conteo = fila.querySelector('[data-chat-item-conteo]');
    conteo.textContent = String(pendientes);
    conteo.setAttribute('aria-label', `${pendientes} sin leer`);
    conteo.hidden = !pendientes;
    fila.querySelector('.chat-item')?.classList.toggle('is-sin-leer', Boolean(pendientes));
  };

  /* La dirección de la lista de conversaciones (siguientes o toda), en la bandeja elegida */
  const urlDeLista = (despues) => {
    const url = new URL(chat.dataset.conversacionesUrl, window.location.href);
    new URLSearchParams(filtroDeLista).forEach((valor, clave) => url.searchParams.set(clave, valor));
    if (despues) url.searchParams.set('despues', despues);
    if (conversacion) url.searchParams.set('actual', String(conversacion));
    return url;
  };
  const enlaceDeSiguientes = (despues) => `${filtroDeLista ? `${filtroDeLista}&` : '?'}despues=${encodeURIComponent(despues)}`;

  /* «Ver más conversaciones»: las siguientes, sin recargar (sin JavaScript, el enlace lleva a la página siguiente) */
  chat.addEventListener('click', async (evento) => {
    const enlace = evento.target.closest('[data-chat-mas]');
    if (!enlace || !conversaciones) return;
    evento.preventDefault();
    if (enlace.classList.contains('is-loading')) return;
    enlace.classList.add('is-loading');
    try {
      const respuesta = await fetch(urlDeLista(enlace.dataset.siguientes), { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
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
        enlace.href = enlaceDeSiguientes(datos.siguientes);
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
    } else if (datos.evento === 'editado') {
      if (datos.conversacion === conversacion) ponerCorreccion(datos);
    } else if (datos.evento === 'escribiendo') {
      if (datos.conversacion === conversacion) mostrarEscribiendo();
    } else if (datos.evento === 'retirado') {
      quitarMensaje(datos);
      retirarDeLaLista(datos);
    } else if (datos.evento === 'leido' && datos.conversacion === conversacion) {
      marcarLeidosHasta(datos.hasta, datos.leido);
    } else if (datos.evento === 'resumen') {
      ponerConteo(datos.conversacion, Number(datos.pendientes) || 0);
      if (datos.organizada) refrescarLista().catch(() => {});   /* la destacó o la archivó en esta u otra pestaña */
    }
  });

  /* ------------------------------------------------------------------ ponerse al día al reconectarse */
  /* Mientras la pestaña estuvo desconectada (celular bloqueado, cambio de red, servidor reiniciado) no llegaron los
     eventos: al reconectarse (avisos.js → «avisos:reconectado») se vuelve a pedir la lista de conversaciones y, en la
     conversación abierta, los mensajes nuevos, los que se retiraron y hasta dónde leyó la otra persona. */
  const pedirJsonDe = async (url) => {
    const respuesta = await fetch(url, { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
    return respuesta.ok ? respuesta.json() : null;
  };

  const refrescarLista = async () => {
    if (!conversaciones || !chat.dataset.conversacionesUrl) return;
    const datos = await pedirJsonDe(urlDeLista());
    if (!datos) return;
    const plantilla = document.createElement('template');
    plantilla.innerHTML = datos.html;   /* lo pinta el servidor (templates/mensajes/_conversaciones.html) */
    conversaciones.replaceChildren(...plantilla.content.querySelectorAll('[data-conversacion-item]'));
    let fila = chat.querySelector('[data-chat-mas-fila]');
    if (datos.siguientes && !fila) {
      fila = elemento('p', 'chat__mas');
      fila.dataset.chatMasFila = '';
      const enlace = elemento('a', 'btn btn--ghost btn--sm', 'Ver más conversaciones');
      enlace.dataset.chatMas = '';
      fila.append(enlace);
      conversaciones.after(fila);
    }
    if (datos.siguientes) {
      const enlace = fila.querySelector('[data-chat-mas]');
      enlace.dataset.siguientes = datos.siguientes;
      enlace.href = enlaceDeSiguientes(datos.siguientes);
    } else {
      fila?.remove();
    }
    filtrarConversaciones();
    if (sinConversaciones) sinConversaciones.hidden = Boolean(conversaciones.querySelector('[data-conversacion-item]'));
  };

  const ponerAlDiaLaConversacion = async () => {
    /* Abierta en una parte anterior, lo nuevo se ve con «Ver mensajes más recientes» */
    if (!conversacion || hayPosteriores || !mensajes || !hilo?.dataset.nuevosUrl) return;
    const ids = [...mensajes.querySelectorAll('.burbuja[data-mensaje]')].map((burbuja) => Number(burbuja.dataset.mensaje));
    let despues = ids.length ? Math.max(...ids) : 0;
    let datos = null;
    let llegaron = false;
    for (let vuelta = 0; vuelta < 10; vuelta += 1) {   /* de 50 en 50, por si fueron muchos */
      const url = new URL(hilo.dataset.nuevosUrl, window.location.href);
      url.searchParams.set('despues', String(despues));
      if (vuelta === 0 && ids.length) url.searchParams.set('desde', String(Math.min(...ids)));
      datos = await pedirJsonDe(url);
      if (!datos) return;
      if (vuelta === 0 && ids.length) {
        const siguen = new Set(datos.existentes);
        ids.filter((id) => !siguen.has(id)).forEach((id) => quitarMensaje({ conversacion, id }));
      }
      datos.mensajes.forEach((mensaje) => {
        agregar(mensaje);
        if (!mensaje.mio) llegaron = true;
        despues = Math.max(despues, mensaje.id);
      });
      if (datos.completos) break;
    }
    marcarLeidosHasta(datos.leido_hasta, datos.leido);
    if (llegaron) {
      ocultarEscribiendo();
      if (document.visibilityState === 'visible') marcarLeida();
      else porLeer = true;
    }
  };

  document.addEventListener('avisos:reconectado', async () => {
    try {
      await Promise.all([refrescarLista(), ponerAlDiaLaConversacion()]);
    } catch (problema) {
      /* sin conexión otra vez: se intentará en la siguiente reconexión */
    }
  });

  /* ------------------------------------------------------------------ documentos adjuntos (PDF) */
  const adjuntos = [];   /* {id, nombre, tamano, subido}: los ya subidos, en el orden en que se agregaron */
  let subiendoAdjuntos = 0;
  let editor = null;

  /* Cuántos caracteres lleva, cerca del límite (quien decide es el servidor: reglas.preparar_contenido) */
  const actualizarContador = () => {
    if (!contador) return;
    const maximo = Number(contador.dataset.maximo) || 2000;
    const largo = (editor ? (editor.vacio() ? '' : editor.texto()) : campo?.value || '').length;
    contador.hidden = largo < maximo * 0.8;
    contador.textContent = `${largo} / ${maximo}`;
    contador.classList.toggle('is-excedido', largo > maximo);
  };

  const actualizarCaja = () => {
    const vacia = editor ? editor.vacio() : !campo?.value.trim();
    caja?.classList.toggle('is-vacia', (vacia && !adjuntos.length) || Boolean(editor?.subiendo()) || subiendoAdjuntos > 0);
    if (campo && !editor) campo.required = !adjuntos.length;
    actualizarContador();
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

  /* Un documento ya subido: su ficha lista para quitarse (al terminar de subir, o al recuperar el borrador) */
  const listoParaEnviar = (adjunto, { ficha, detalle, quitar }) => {
    adjuntos.push(adjunto);
    ficha.classList.remove('is-subiendo');
    detalle.textContent = adjunto.tamano;
    quitar.disabled = false;
    quitar.addEventListener('click', () => {
      adjuntos.splice(adjuntos.indexOf(adjunto), 1);
      ficha.remove();
      listaAdjuntos.hidden = !listaAdjuntos.children.length;
      actualizarCaja();
      guardarBorradorLuego();
      if (editor) editor.enfocar();
      else campo?.focus();
    });
  };

  const subirAdjuntos = async (archivos) => {
    if (!archivoAdjunto || !listaAdjuntos) return;
    const maximo = Number(archivoAdjunto.dataset.maximo) || 10;
    const maximoMb = Number(archivoAdjunto.dataset.maximoMb) || 5;
    const deEsta = conversacion;   /* si mientras sube se abre otra, el archivo no le toca a esa */
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
      const piezas = fichaDeAdjunto(archivo.name);
      const { ficha } = piezas;
      listaAdjuntos.append(ficha);
      listaAdjuntos.hidden = false;
      subiendoAdjuntos += 1;
      actualizarCaja();
      try {
        const datos = new FormData();
        datos.append('documento', archivo, archivo.name);
        const respuesta = await post(archivoAdjunto.dataset.url, datos);
        const resultado = await respuesta.json().catch(() => ({}));
        if (conversacion !== deEsta) return;
        if (!respuesta.ok) throw new Error(resultado.error || 'No se pudo adjuntar el documento.');
        listoParaEnviar({ id: resultado.id, nombre: resultado.nombre, tamano: resultado.tamano, subido: Date.now() }, piezas);
        guardarBorradorLuego();
      } catch (problema) {
        if (conversacion !== deEsta) return;
        ficha.remove();
        mostrarError(problema.message || 'No se pudo adjuntar el documento. Revisa tu conexión e inténtalo de nuevo.');
      } finally {
        if (conversacion === deEsta) {
          subiendoAdjuntos -= 1;
          listaAdjuntos.hidden = !listaAdjuntos.children.length;
          actualizarCaja();
        }
      }
    }
  };

  const vaciarAdjuntos = () => {
    adjuntos.length = 0;
    listaAdjuntos?.replaceChildren();
    if (listaAdjuntos) listaAdjuntos.hidden = true;
  };

  /* ------------------------------------------------------------------ borradores (2026-10-27) */
  /* Lo que se está escribiendo se guarda en este navegador, por cuenta y conversación: cambiar de conversación o
     recargar la página ya no lo pierde. Se borra al enviar, a los 7 días, al cerrar sesión (static/js/app.js) y cuando
     otra cuenta abre los mensajes en este navegador. Los documentos adjuntos vuelven solo mientras siguen en el servidor
     (los que no se envían se borran al día siguiente: Mensajes/limpieza.py). */
  const PREFIJO_BORRADOR = 'cisahuayo.borrador.';
  const VIGENCIA_BORRADOR = 7 * 24 * 3600 * 1000;
  const VIGENCIA_ADJUNTO = 20 * 3600 * 1000;
  const prefijoPropio = `${PREFIJO_BORRADOR}${chat.dataset.yo || ''}.`;
  let llaveBorrador = '';
  const almacen = (() => {
    try {
      return window.localStorage;
    } catch (problema) {
      return null;   /* sin almacenamiento (navegación privada estricta, permisos): sin borradores */
    }
  })();
  let restaurando = false;

  const leerBorrador = (llave) => {
    try {
      const borrador = JSON.parse(almacen.getItem(llave) || 'null');
      return borrador && typeof borrador === 'object' ? borrador : null;
    } catch (problema) {
      return null;
    }
  };

  /* Los de otras cuentas y los viejos se van en cuanto se abren los mensajes */
  const limpiarBorradores = () => {
    if (!almacen) return;
    try {
      for (let indice = almacen.length - 1; indice >= 0; indice -= 1) {
        const llave = almacen.key(indice);
        if (!llave?.startsWith(PREFIJO_BORRADOR)) continue;
        const guardado = Number(leerBorrador(llave)?.guardado) || 0;
        if (!llave.startsWith(prefijoPropio) || Date.now() - guardado > VIGENCIA_BORRADOR) almacen.removeItem(llave);
      }
    } catch (problema) {
      /* sin almacenamiento */
    }
  };

  let pausaBorrador = null;
  const guardarBorrador = () => {
    window.clearTimeout(pausaBorrador);
    pausaBorrador = null;
    if (!llaveBorrador || !almacen || restaurando) return;
    const html = editor && !editor.vacio() ? editor.html() : '';
    const texto = editor ? (editor.vacio() ? '' : editor.texto()) : (campo?.value || '');
    const responde = respondeA?.value ? {
      id: respondeA.value,
      autor: barraRespuesta.querySelector('[data-chat-respuesta-autor]').textContent,
      cita: barraRespuesta.querySelector('[data-chat-respuesta-cita]').textContent,
    } : null;
    try {
      if (!texto.trim() && !html && !adjuntos.length && !responde) almacen.removeItem(llaveBorrador);
      else almacen.setItem(llaveBorrador, JSON.stringify({ texto, html, responde, adjuntos, guardado: Date.now() }));
    } catch (problema) {
      /* lleno o sin permiso: se sigue sin borrador */
    }
  };
  function guardarBorradorLuego() {   /* declarada como función: la usan las citas y los adjuntos, definidos antes */
    window.clearTimeout(pausaBorrador);
    pausaBorrador = window.setTimeout(guardarBorrador, 400);
  }
  const borrarBorrador = () => {
    window.clearTimeout(pausaBorrador);
    pausaBorrador = null;
    try {
      if (llaveBorrador) almacen?.removeItem(llaveBorrador);
    } catch (problema) {
      /* sin almacenamiento */
    }
  };
  /* Al salir de la página con un cambio aún sin guardar (salvo al cerrar sesión: app.js acaba de borrar los borradores) */
  window.addEventListener('pagehide', () => {
    if (pausaBorrador) guardarBorrador();
  });
  document.addEventListener('submit', (evento) => {
    if (!evento.target.matches?.('form[data-cerrar-sesion]')) return;
    window.clearTimeout(pausaBorrador);
    pausaBorrador = null;
  }, true);

  const parrafos = (texto) => texto.split('\n').map((renglon) => {
    const parrafo = document.createElement('p');
    parrafo.textContent = renglon;
    return renglon ? parrafo.outerHTML : '<p><br></p>';
  }).join('');

  /* Devuelve true si había un borrador */
  const restaurarBorrador = () => {
    if (!llaveBorrador || !almacen) return false;
    const borrador = leerBorrador(llaveBorrador);
    if (!borrador) return false;
    restaurando = true;
    try {
      const texto = typeof borrador.texto === 'string' ? borrador.texto : '';
      const html = typeof borrador.html === 'string' ? borrador.html : '';
      if (editor && (html || texto)) editor.poner(html || parrafos(texto));
      else if (campo && texto) {
        campo.value = texto;
        ajustarAltura();
      }
      const responde = borrador.responde;
      if (responde?.id && barraRespuesta && /^\d+$/.test(String(responde.id))) {
        ponerRespuesta(String(responde.id), String(responde.autor || ''), String(responde.cita || ''));
      }
      if (archivoAdjunto && listaAdjuntos && Array.isArray(borrador.adjuntos)) {
        const maximo = Number(archivoAdjunto.dataset.maximo) || 10;
        borrador.adjuntos
          .filter((adjunto) => Number.isInteger(adjunto?.id) && Date.now() - (Number(adjunto.subido) || 0) < VIGENCIA_ADJUNTO)
          .slice(0, maximo)
          .forEach((adjunto) => {
            const piezas = fichaDeAdjunto(String(adjunto.nombre || 'documento.pdf'));
            listaAdjuntos.append(piezas.ficha);
            listoParaEnviar({ id: adjunto.id, nombre: String(adjunto.nombre || ''), tamano: String(adjunto.tamano || ''), subido: Number(adjunto.subido) }, piezas);
          });
        listaAdjuntos.hidden = !listaAdjuntos.children.length;
      }
      actualizarCaja();
    } finally {
      restaurando = false;
    }
    return true;
  };

  chat.addEventListener('change', (evento) => {
    if (evento.target !== archivoAdjunto) return;
    if (archivoAdjunto.files.length) subirAdjuntos(archivoAdjunto.files);
    archivoAdjunto.value = '';
  });
  /* Soltar documentos sobre la caja de escribir (las imágenes las inserta el editor) */
  const soloDocumentos = (archivos) => [...(archivos || [])].filter((archivo) => /\.pdf$/i.test(archivo.name) || archivo.type === 'application/pdf');
  chat.addEventListener('dragover', (evento) => {
    if (evento.target.closest('[data-chat-caja]') && archivoAdjunto && [...(evento.dataTransfer?.types || [])].includes('Files')) evento.preventDefault();
  });
  chat.addEventListener('drop', (evento) => {
    if (!evento.target.closest('[data-chat-caja]')) return;
    const documentos = soloDocumentos(evento.dataTransfer?.files);
    if (!documentos.length || !archivoAdjunto) return;
    evento.preventDefault();
    subirAdjuntos(documentos);
  });

  /* ------------------------------------------------------------------ escribir */
  const ajustarAltura = () => {
    if (!campo) return;
    campo.style.height = 'auto';
    campo.style.height = `${Math.min(campo.scrollHeight + 2, 144)}px`;
  };
  chat.addEventListener('input', (evento) => {
    if (!campo || evento.target !== campo) return;
    ajustarAltura();
    actualizarContador();
    if (campo.value.trim()) avisarQueEscribo();
    if (!editor) guardarBorradorLuego();
  });
  chat.addEventListener('keydown', (evento) => {
    if (!campo || evento.target !== campo) return;
    if (evento.key === 'Enter' && !evento.shiftKey && !evento.isComposing) {
      evento.preventDefault();
      formulario?.requestSubmit();
    }
  });

  let enviando = false;
  const enviarMensaje = async () => {
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
    const deEsta = conversacion;   /* si mientras se envía se abre otra, el mensaje no se muestra en esa */
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
      if (conversacion !== deEsta) {
        almacen?.removeItem(`${prefijoPropio}${deEsta}`);
        actualizarItem(datos);
        return;
      }
      if (hayPosteriores) {   /* se estaba viendo una parte anterior: a los más recientes, con el nuevo */
        borrarBorrador();
        abrir(`${hilo.dataset.conversacionUrl}#mensaje-${datos.id}`);
        return;
      }
      agregar(datos);
      actualizarItem(datos);
      quitarRespuesta();
      ultimoAviso = 0;
      campo.value = '';
      if (campoHtml) campoHtml.value = '';
      editor?.vaciar();
      vaciarAdjuntos();
      borrarBorrador();
      ajustarAltura();
      actualizarCaja();
    } catch (problema) {
      if (error && conversacion === deEsta) {
        error.textContent = problema.message || 'No se pudo enviar el mensaje. Revisa tu conexión e inténtalo de nuevo.';
        error.hidden = false;
      }
    } finally {
      enviando = false;
      boton.disabled = false;
      boton.classList.remove('is-loading');
      if (conversacion === deEsta) {
        if (editor) editor.enfocar();
        else campo?.focus();
      }
    }
  };

  /* ------------------------------------------------------------------ buscar */
  function normal(texto) {
    return texto.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();
  }

  /* Una persona a la que se puede escribir: al elegirla se abre (o se retoma) la conversación */
  const filaDePersona = (contacto) => {
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
    return fila;
  };

  const pintarPersonas = (contactos, consulta) => {
    if (!personas || !personasLista) return;
    personasLista.replaceChildren();
    if (!contactos.length) {
      personasLista.append(elemento('li', 'chat__nadie', `Nadie coincide con «${consulta}» entre las personas a las que puedes escribir.`));
    }
    contactos.forEach((contacto) => personasLista.append(filaDePersona(contacto)));
    personas.hidden = false;
  };

  /* Un mensaje encontrado: al tocarlo, se abre la conversación en ese mensaje */
  const filaDeResultado = (resultado) => {
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
    return fila;
  };

  const masEncontrados = chat.querySelector('[data-chat-encontrados-mas]');
  const filaDeMasEncontrados = chat.querySelector('[data-chat-encontrados-mas-fila]');
  const ponerSiguienteEncontrado = (siguiente) => {
    if (!masEncontrados) return;
    masEncontrados.dataset.siguiente = siguiente || '';
    filaDeMasEncontrados.hidden = !siguiente;
  };

  const pintarEncontrados = (resultados, siguiente, { agregar: alFinalDeLaLista = false } = {}) => {
    if (!encontrados || !encontradosLista) return;
    if (!alFinalDeLaLista) encontradosLista.replaceChildren();
    if (!resultados.length && !alFinalDeLaLista) encontradosLista.append(elemento('li', 'chat__nadie', 'Ningún mensaje coincide con la búsqueda.'));
    resultados.forEach((resultado) => encontradosLista.append(filaDeResultado(resultado)));
    ponerSiguienteEncontrado(siguiente);
    encontrados.hidden = false;
  };

  const pedirJson = async (url, parametros, senal) => {
    const respuesta = await fetch(`${url}?${parametros}`, {
      headers: { Accept: 'application/json' }, credentials: 'same-origin', signal: senal,
    });
    return respuesta.ok ? respuesta.json() : null;
  };

  /* Lo escrito y lo elegido en los filtros, sin lo vacío */
  const parametrosDeBusqueda = () => {
    const parametros = new URLSearchParams();
    if (formaBuscar) {
      new FormData(formaBuscar).forEach((valor, clave) => {
        if (String(valor).trim()) parametros.set(clave, String(valor).trim());
      });
    }
    return parametros;
  };

  /* Mientras se busca, los resultados ocupan el lugar de las conversaciones */
  const ponerBuscando = (activa) => lista?.classList.toggle('is-buscando', activa);

  const botonDeFiltros = chat.querySelector('.chat__filtros-boton');
  let pedido = null;
  let pausa = null;
  const buscarAhora = async () => {
    window.clearTimeout(pausa);
    const parametros = parametrosDeBusqueda();
    const consulta = parametros.get('q') || '';
    const conFiltros = [...parametros.keys()].some((clave) => clave !== 'q');
    botonDeFiltros?.classList.toggle('is-activo', conFiltros);
    pedido?.abort();
    if (consulta.length < 2 && !conFiltros) {
      if (buscando) buscando.hidden = true;
      if (personas) personas.hidden = true;
      if (encontrados) encontrados.hidden = true;
      ponerBuscando(false);
      return;
    }
    const este = new AbortController();
    pedido = este;
    if (buscando) buscando.hidden = false;
    try {
      const [deContactos, deMensajes] = await Promise.all([
        consulta.length >= 2 ? pedirJson(chat.dataset.contactosUrl, new URLSearchParams({ q: consulta }), este.signal) : null,
        pedirJson(chat.dataset.buscarUrl, parametros, este.signal),
      ]);
      if (deContactos) pintarPersonas(deContactos.contactos, consulta);
      else if (personas) personas.hidden = true;
      if (deMensajes) pintarEncontrados(deMensajes.mensajes, deMensajes.siguiente);
      ponerBuscando(true);
    } catch (problema) {
      /* búsqueda cancelada o sin conexión */
    } finally {
      if (pedido === este && buscando) buscando.hidden = true;
    }
  };

  formaBuscar?.addEventListener('input', () => {
    filtrarConversaciones();
    window.clearTimeout(pausa);
    pausa = window.setTimeout(buscarAhora, 250);
  });
  formaBuscar?.addEventListener('submit', (evento) => {
    evento.preventDefault();
    /* El panel ocupa casi toda la columna: al aplicar se cierra para dejar ver los resultados */
    const panelDeFiltros = chat.querySelector('[data-chat-filtros]');
    if (panelDeFiltros) panelDeFiltros.open = false;
    buscarAhora();
  });
  chat.querySelector('[data-chat-filtros-limpiar]')?.addEventListener('click', (evento) => {
    evento.preventDefault();
    [...formaBuscar.elements].forEach((campoDeFiltro) => {
      if (campoDeFiltro.name === 'q' || !campoDeFiltro.name) return;
      if (campoDeFiltro.type === 'checkbox') campoDeFiltro.checked = false;
      else campoDeFiltro.value = '';
    });
    buscarAhora();
  });
  masEncontrados?.addEventListener('click', async () => {
    const parametros = parametrosDeBusqueda();
    parametros.set('antes', masEncontrados.dataset.siguiente || '');
    masEncontrados.disabled = true;
    try {
      const datos = await pedirJson(chat.dataset.buscarUrl, parametros);
      if (datos) pintarEncontrados(datos.mensajes, datos.siguiente, { agregar: true });
    } catch (problema) {
      /* sin conexión: se puede volver a intentar */
    } finally {
      masEncontrados.disabled = false;
    }
  });

  /* ------------------------------------------------------------------ buscar en la conversación */
  const cerrarBusquedaDelHilo = () => {
    const panel = hilo?.querySelector('[data-chat-busqueda-hilo]');
    if (!panel) return;
    panel.hidden = true;
    hilo.querySelector('[data-chat-abrir-busqueda]')?.setAttribute('aria-expanded', 'false');
  };

  let pausaEnHilo = null;
  let pedidoEnHilo = null;
  const buscarEnElHilo = async (consulta) => {
    const listaEnHilo = hilo.querySelector('[data-chat-busqueda-hilo-lista]');
    const estado = hilo.querySelector('[data-chat-busqueda-hilo-estado]');
    pedidoEnHilo?.abort();
    if (consulta.length < 2) {
      listaEnHilo.replaceChildren();
      estado.hidden = true;
      return;
    }
    const este = new AbortController();
    pedidoEnHilo = este;
    estado.hidden = false;
    try {
      const datos = await pedirJson(chat.dataset.buscarUrl, new URLSearchParams({ q: consulta, conversacion: String(conversacion) }), este.signal);
      if (!datos) return;
      listaEnHilo.replaceChildren(...datos.mensajes.map(filaDeResultado));
      if (!datos.mensajes.length) listaEnHilo.append(elemento('li', 'chat__nadie', 'Ningún mensaje coincide en esta conversación.'));
    } catch (problema) {
      /* búsqueda cancelada o sin conexión */
    } finally {
      if (pedidoEnHilo === este) estado.hidden = true;
    }
  };

  chat.addEventListener('click', (evento) => {
    const abrirla = evento.target.closest('[data-chat-abrir-busqueda]');
    if (abrirla) {
      const panel = hilo.querySelector('[data-chat-busqueda-hilo]');
      panel.hidden = !panel.hidden;
      abrirla.setAttribute('aria-expanded', String(!panel.hidden));
      if (!panel.hidden) panel.querySelector('input')?.focus();
    } else if (evento.target.closest('[data-chat-cerrar-busqueda]')) {
      cerrarBusquedaDelHilo();
    }
  });
  chat.addEventListener('input', (evento) => {
    if (!evento.target.matches('[data-chat-busqueda-hilo-campo]')) return;
    window.clearTimeout(pausaEnHilo);
    const consulta = evento.target.value.trim();
    pausaEnHilo = window.setTimeout(() => buscarEnElHilo(consulta), 250);
  });
  chat.addEventListener('keydown', (evento) => {
    if (evento.key === 'Escape' && evento.target.matches('[data-chat-busqueda-hilo-campo]')) cerrarBusquedaDelHilo();
  });

  /* ------------------------------------------------------------------ nuevo mensaje */
  const directorio = chat.querySelector('[data-chat-directorio]');
  const buscarEnDirectorio = chat.querySelector('[data-chat-directorio-buscar]');
  const gruposDelDirectorio = chat.querySelector('[data-chat-directorio-grupos]');
  const estadoDelDirectorio = chat.querySelector('[data-chat-directorio-estado]');

  const pintarDirectorio = (grupos, consulta) => {
    gruposDelDirectorio.replaceChildren();
    if (!grupos.length) {
      gruposDelDirectorio.append(elemento('p', 'chat__nadie', consulta
        ? `Nadie coincide con «${consulta}» entre las personas a las que puedes escribir.`
        : 'Por ahora no hay personas a las que puedas escribir.'));
    }
    grupos.forEach((grupo) => {
      const seccion = elemento('section', 'chat-ventana__grupo');
      const personasDelGrupo = elemento('ul', 'chat-ventana__lista');
      grupo.contactos.forEach((contacto) => personasDelGrupo.append(filaDePersona(contacto)));
      seccion.append(elemento('h3', 'chat__subtitulo', grupo.titulo), personasDelGrupo);
      if (grupo.hay_mas) seccion.append(elemento('p', 'chat-ventana__mas', 'Hay más personas: escribe un nombre para encontrarlas.'));
      gruposDelDirectorio.append(seccion);
    });
  };

  let pedidoDeDirectorio = null;
  let pausaDeDirectorio = null;
  const cargarDirectorio = async (consulta = '') => {
    pedidoDeDirectorio?.abort();
    const este = new AbortController();
    pedidoDeDirectorio = este;
    estadoDelDirectorio.hidden = false;
    try {
      const datos = await pedirJson(chat.dataset.directorioUrl, new URLSearchParams(consulta ? { q: consulta } : {}), este.signal);
      if (!datos) throw new Error('sin respuesta');
      pintarDirectorio(datos.grupos, consulta);
    } catch (problema) {
      if (problema.name === 'AbortError') return;
      gruposDelDirectorio.replaceChildren(elemento('p', 'chat__nadie', 'No se pudo cargar la lista de personas. Revisa tu conexión e inténtalo de nuevo.'));
    } finally {
      if (pedidoDeDirectorio === este) estadoDelDirectorio.hidden = true;
    }
  };

  chat.addEventListener('click', (evento) => {
    if (evento.target.closest('[data-chat-nuevo]') && directorio) {
      buscarEnDirectorio.value = '';
      cargarDirectorio();
    }
  });
  buscarEnDirectorio?.addEventListener('input', () => {
    window.clearTimeout(pausaDeDirectorio);
    pausaDeDirectorio = window.setTimeout(() => cargarDirectorio(buscarEnDirectorio.value.trim()), 250);
  });

  /* ------------------------------------------------------------------ archivos de la conversación */
  const ventanaDeArchivos = chat.querySelector('[data-chat-archivos]');
  const listaDeArchivos = chat.querySelector('[data-chat-archivos-lista]');
  const estadoDeArchivos = chat.querySelector('[data-chat-archivos-estado]');

  const filaDeArchivo = (archivo) => {
    const fila = elemento('li', 'chat-archivo');
    const marca = elemento('span', 'documento-adjunto__icono');
    marca.setAttribute('aria-hidden', 'true');
    marca.append(icono(archivo.documento ? 'file-text' : 'image'));
    const texto = elemento('span', 'chat-archivo__texto');
    const enlace = elemento('a', 'chat-archivo__nombre', archivo.nombre);
    Object.assign(enlace, { href: archivo.url, target: '_blank', rel: 'noopener' });
    texto.append(enlace, elemento('span', 'chat-archivo__detalle', `${archivo.autor} · ${archivo.fecha} · ${archivo.tamano}`));
    const ver = elemento('a', 'btn btn--ghost btn--icon btn--sm');
    ver.href = archivo.mensaje;
    ver.dataset.chatVerMensaje = '';
    ver.dataset.tooltip = 'Ver en la conversación';
    ver.setAttribute('aria-label', `Ver ${archivo.nombre} en la conversación`);
    ver.append(icono('message-circle'));
    const descargar = elemento('a', 'btn btn--ghost btn--icon btn--sm');
    descargar.href = archivo.descargar;
    descargar.dataset.tooltip = 'Descargar';
    descargar.setAttribute('aria-label', `Descargar ${archivo.nombre}`);
    descargar.append(icono('download'));
    fila.append(marca, texto, ver, descargar);
    return fila;
  };

  const cargarArchivos = async () => {
    listaDeArchivos.replaceChildren();
    estadoDeArchivos.hidden = false;
    try {
      const datos = await pedirJson(hilo.dataset.archivosUrl, new URLSearchParams());
      if (!datos) throw new Error('sin respuesta');
      listaDeArchivos.replaceChildren(...datos.archivos.map(filaDeArchivo));
      if (!datos.archivos.length) listaDeArchivos.append(elemento('li', 'chat__nadie', 'Todavía no se han enviado archivos en esta conversación.'));
    } catch (problema) {
      listaDeArchivos.replaceChildren(elemento('li', 'chat__nadie', 'No se pudieron cargar los archivos. Revisa tu conexión e inténtalo de nuevo.'));
    } finally {
      estadoDeArchivos.hidden = true;
    }
  };

  chat.addEventListener('click', (evento) => {
    if (evento.target.closest('[data-chat-abrir-archivos]')) cargarArchivos();
    const ver = evento.target.closest('[data-chat-ver-mensaje]');
    if (ver) {
      evento.preventDefault();
      ventanaDeArchivos?.close();
      abrir(ver.href);
    }
  });

  /* ------------------------------------------------------------------ organizar */
  const avisoDeDeshacer = chat.querySelector('[data-chat-deshacer]');
  let accionDeDeshacer = null;
  let finDeDeshacer = null;
  const ocultarDeshacer = () => {
    window.clearTimeout(finDeDeshacer);
    accionDeDeshacer = null;
    if (avisoDeDeshacer) avisoDeDeshacer.hidden = true;
  };
  const ofrecerDeshacer = (texto, accion) => {
    if (!avisoDeDeshacer) return;
    avisoDeDeshacer.querySelector('[data-chat-deshacer-texto]').textContent = texto;
    avisoDeDeshacer.hidden = false;
    accionDeDeshacer = accion;
    window.clearTimeout(finDeDeshacer);
    finDeDeshacer = window.setTimeout(ocultarDeshacer, 7000);
  };
  chat.querySelector('[data-chat-deshacer-boton]')?.addEventListener('click', () => {
    const accion = accionDeDeshacer;
    ocultarDeshacer();
    accion?.();
  });

  const destacar = async (forma) => {
    try {
      const respuesta = await post(forma.action, new FormData(forma));
      if (!respuesta.ok) throw new Error('sin respuesta');
      const activa = forma.elements.valor.value === '1';
      forma.elements.valor.value = activa ? '0' : '1';
      const boton = forma.querySelector('button');
      boton.classList.toggle('is-activa', activa);
      boton.setAttribute('aria-pressed', String(activa));
      boton.dataset.tooltip = activa ? 'Quitar de destacadas' : 'Destacar';
      const marca = conversaciones?.querySelector(`[data-conversacion-item="${conversacion}"] [data-chat-item-estrella]`);
      if (marca) marca.hidden = !activa;
    } catch (problema) {
      mostrarError('No se pudo cambiar. Revisa tu conexión e inténtalo de nuevo.');
    }
  };

  const archivar = async (forma) => {
    const accion = forma.action;
    const datos = new FormData(forma);
    const archivada = datos.get('valor') === '1';
    const abierta = hilo.dataset.conversacionUrl;
    try {
      const respuesta = await post(accion, datos);
      if (!respuesta.ok) throw new Error('sin respuesta');
      await abrir(`${chat.dataset.inicioUrl}${filtroDeLista}`);
      await refrescarLista();
      ofrecerDeshacer(archivada ? 'Se archivó la conversación.' : 'La conversación regresó a la bandeja.', async () => {
        const contraria = new FormData();
        contraria.append('valor', archivada ? '0' : '1');
        await post(accion, contraria).catch(() => {});
        await abrir(abierta);
        await refrescarLista();
      });
    } catch (problema) {
      mostrarError('No se pudo archivar. Revisa tu conexión e inténtalo de nuevo.');
    }
  };

  const marcarTodo = async (forma) => {
    document.dispatchEvent(new CustomEvent('app:close-menus'));
    try {
      const respuesta = await post(forma.action, new FormData(forma));
      if (!respuesta.ok) throw new Error('sin respuesta');
      await refrescarLista();
      document.dispatchEvent(new CustomEvent('avisos:actualizar'));
    } catch (problema) {
      /* sin conexión: la lista sigue como estaba */
    }
  };

  const cambiarDensidad = (forma) => {
    document.dispatchEvent(new CustomEvent('app:close-menus'));
    const compacta = forma.elements.compacta.value === '1';
    post(forma.action, new FormData(forma)).catch(() => {});
    chat.classList.toggle('chat--compacta', compacta);
    forma.elements.compacta.value = compacta ? '0' : '1';
    forma.querySelector('[data-chat-compacta]')?.setAttribute('aria-pressed', String(compacta));
    forma.querySelector('[data-chat-compacta-texto]').textContent = compacta ? 'Vista normal' : 'Vista compacta';
  };

  chat.addEventListener('submit', (evento) => {
    const forma = evento.target;
    const accion = [['[data-chat-formulario]', enviarMensaje], ['[data-chat-destacar]', destacar], ['[data-chat-archivar]', archivar],
      ['[data-chat-marcar-todo]', marcarTodo], ['[data-chat-compacta-forma]', cambiarDensidad]].find(([selector]) => forma.matches(selector));
    if (!accion) return;
    evento.preventDefault();
    accion[1](forma);
  });

  /* ------------------------------------------------------------------ mensajes anteriores, al subir */
  let cargandoAnteriores = false;
  const cargarAnteriores = async () => {
    const fila = mensajes?.querySelector('[data-chat-anteriores]');
    if (!fila || cargandoAnteriores) return;
    const deEsta = conversacion;
    cargandoAnteriores = true;
    fila.classList.add('is-cargando');
    try {
      const datos = await pedirJson(hilo.dataset.anterioresUrl, new URLSearchParams({ antes: fila.dataset.primero }));
      if (!datos || conversacion !== deEsta) return;
      const plantilla = document.createElement('template');
      plantilla.innerHTML = datos.html;   /* lo pinta el servidor (templates/mensajes/_mensajes.html) */
      const altura = mensajes.scrollHeight;
      const arriba = mensajes.scrollTop;
      const primerDia = mensajes.querySelector('[data-chat-dia]');
      const dias = [...plantilla.content.querySelectorAll('[data-chat-dia]')];
      const burbujas = [...plantilla.content.querySelectorAll('.burbuja')];
      mensajes.setAttribute('aria-busy', 'true');   /* lo que llega del historial no se lee en voz alta */
      fila.after(plantilla.content);
      burbujas.forEach(ponerAcciones);
      /* El día en que terminan los anteriores puede ser el mismo en que empezaban los que ya estaban */
      if (primerDia && dias[dias.length - 1]?.dataset.chatDia === primerDia.dataset.chatDia) primerDia.remove();
      mensajes.scrollTop = arriba + mensajes.scrollHeight - altura;
      mensajes.removeAttribute('aria-busy');
      ponerLectura();
      if (datos.hay_anteriores) {
        fila.dataset.primero = String(datos.primero);
        fila.querySelector('a').href = `?antes=${datos.primero}`;
      } else {
        fila.remove();
      }
    } catch (problema) {
      /* sin conexión: queda el enlace para volver a intentar */
    } finally {
      cargandoAnteriores = false;
      fila.classList.remove('is-cargando');
    }
  };
  const alDesplazar = () => {
    if (mensajes.scrollTop < 200) cargarAnteriores();
  };
  chat.addEventListener('click', (evento) => {
    if (!evento.target.closest('[data-chat-anteriores] a')) return;
    evento.preventDefault();
    cargarAnteriores();
  });

  /* ------------------------------------------------------------------ abrir sin recargar */
  /* Toma los elementos del panel que está en la página y lo deja listo: al cargar y al abrir otra conversación */
  const montarHilo = () => {
    hilo = chat.querySelector('[data-chat-hilo]');
    conversacion = Number(hilo?.dataset.conversacion || 0);
    hayPosteriores = Boolean(hilo?.hasAttribute('data-hay-posteriores'));
    mensajes = hilo?.querySelector('[data-chat-mensajes]') || null;
    formulario = hilo?.querySelector('[data-chat-formulario]') || null;
    campo = hilo?.querySelector('[data-chat-campo]') || null;
    error = hilo?.querySelector('[data-chat-error]') || null;
    caja = hilo?.querySelector('[data-chat-caja]') || null;
    campoHtml = hilo?.querySelector('[data-chat-html]') || null;
    raizEditor = hilo?.querySelector('[data-editor]') || null;
    archivoAdjunto = hilo?.querySelector('[data-chat-adjuntar-archivo]') || null;
    listaAdjuntos = hilo?.querySelector('[data-chat-adjuntos]') || null;
    barraRespuesta = hilo?.querySelector('[data-chat-respuesta]') || null;
    respondeA = hilo?.querySelector('[data-chat-responde-a]') || null;
    escribiendo = hilo?.querySelector('[data-chat-escribiendo]') || null;
    contador = hilo?.querySelector('[data-chat-contador]') || null;

    chat.dataset.conversacion = conversacion || '';
    chat.classList.toggle('chat--abierta', Boolean(conversacion));
    adjuntos.length = 0;
    subiendoAdjuntos = 0;
    porLeer = false;
    enviando = false;
    ultimoAviso = 0;
    editor = null;
    llaveBorrador = conversacion && formulario ? `${prefijoPropio}${conversacion}` : '';

    hilo?.querySelectorAll('[data-chat-abrir-busqueda], [data-chat-abrir-archivos]').forEach((boton) => { boton.hidden = false; });
    mensajes?.querySelectorAll('.burbuja').forEach((burbuja) => ponerAcciones(burbuja));
    mensajes?.addEventListener('scroll', alDesplazar, { passive: true });

    if (raizEditor && window.EditorEnriquecido && campo) {
      editor = new window.EditorEnriquecido(raizEditor, {
        alEnviar: () => formulario?.requestSubmit(),
        alCambiar: () => {
          actualizarCaja();
          if (restaurando) return;   /* el borrador recuperado al abrir: nadie está escribiendo */
          if (!editor?.vacio()) avisarQueEscribo();
          guardarBorradorLuego();
        },
      });
      campo.hidden = true;
      campo.required = false;
      caja?.classList.add('chat__caja--editor', 'is-vacia');
      hilo.querySelector('[data-chat-atajos-editor]')?.removeAttribute('hidden');
    }

    const conBorrador = restaurarBorrador();
    /* Abierta desde otro lugar con un asunto (p. ej. una cita del portal): si no había borrador, ya viene escrito */
    if (!conBorrador && hilo?.dataset.asunto) {
      if (editor) editor.poner(parrafos(`${hilo.dataset.asunto}: `));
      else if (campo) campo.value = `${hilo.dataset.asunto}: `;
    }
    actualizarCaja();
    colocar();
    if (formulario && window.matchMedia('(min-width: 48rem)').matches) {
      if (editor) {
        editor.enfocar();
        if (conBorrador) editor.ponerCursorAlFinal();   /* para seguir escribiendo donde se quedó */
      } else {
        campo?.focus({ preventScroll: true });
      }
    }
  };

  let scrollDeLaLista = 0;
  const desmontarHilo = () => {
    if (pausaBorrador) guardarBorrador();
    mensajes?.removeEventListener('scroll', alDesplazar);
    editor?.destruir();
    ocultarEscribiendo();
    scrollDeLaLista = conversaciones?.scrollTop || scrollDeLaLista;   /* en el celular, la lista se oculta */
  };

  /* Lo que está fuera del panel: el título, la ruta de arriba y la lista */
  const alCambiarDeHilo = () => {
    document.dispatchEvent(new CustomEvent('avisos:titulo', { detail: hilo.dataset.titulo }));
    const actual = document.querySelector('[data-chat-miga-actual]');
    if (actual) actual.textContent = conversacion ? hilo.dataset.nombre : 'Mensajes';
    const miga = document.querySelector('[data-chat-miga-mensajes]');
    if (miga) miga.hidden = !conversacion;
    chat.querySelectorAll('[data-chat-filtro]').forEach((enlace) => { enlace.pathname = window.location.pathname; });
    conversaciones?.querySelectorAll('.chat-item.is-actual').forEach((enlace) => {
      enlace.classList.remove('is-actual');
      enlace.removeAttribute('aria-current');
    });
    const fila = conversaciones?.querySelector(`[data-conversacion-item="${conversacion}"]`);
    if (fila) {
      const enlace = fila.querySelector('.chat-item');
      enlace.classList.add('is-actual');
      enlace.setAttribute('aria-current', 'page');
      if (!hayPosteriores) ponerConteo(conversacion, 0);
    } else if (conversacion) {
      refrescarLista().catch(() => {});   /* abierta desde un resultado: se agrega a la lista */
    }
    if (!conversacion && conversaciones) conversaciones.scrollTop = scrollDeLaLista;
    if (!conectado) document.dispatchEvent(new CustomEvent('avisos:actualizar'));
  };

  let pedidoDeHilo = null;
  async function abrir(direccion, { apilar = true } = {}) {
    const destino = new URL(direccion, window.location.href);
    if (apilar && destino.href === window.location.href) return;
    const panel = new URL(destino);
    panel.hash = '';
    panel.searchParams.set('panel', '1');
    pedidoDeHilo?.abort();
    const este = new AbortController();
    pedidoDeHilo = este;
    hilo?.setAttribute('aria-busy', 'true');
    try {
      const respuesta = await fetch(panel, { credentials: 'same-origin', headers: { Accept: 'text/html' }, signal: este.signal });
      if (!respuesta.ok || respuesta.redirected) throw new Error('sin panel');
      const plantilla = document.createElement('template');
      plantilla.innerHTML = await respuesta.text();
      const nuevo = plantilla.content.querySelector('[data-chat-hilo]');
      if (!nuevo) throw new Error('sin panel');
      if (pedidoDeHilo !== este) return;
      if (apilar) window.history.pushState({}, '', destino);
      desmontarHilo();
      hilo.replaceWith(nuevo);
      montarHilo();
      alCambiarDeHilo();
    } catch (problema) {
      if (problema.name !== 'AbortError') window.location.href = destino.href;
    }
  }

  chat.addEventListener('click', (evento) => {
    if (evento.defaultPrevented || evento.button || evento.metaKey || evento.ctrlKey || evento.shiftKey || evento.altKey) return;
    const enlace = evento.target.closest('.chat-item, .chat-resultado, [data-chat-volver], [data-chat-recientes]');
    if (!enlace) return;
    evento.preventDefault();
    abrir(enlace.href);
  });
  window.addEventListener('popstate', () => abrir(window.location.href, { apilar: false }));

  /* ------------------------------------------------------------------ conexión */
  const avisoDeConexion = chat.querySelector('[data-chat-conexion]');
  let conectado = true;
  let pausaDeConexion = null;
  document.addEventListener('avisos:conexion', ({ detail }) => {
    conectado = detail.conectado;
    window.clearTimeout(pausaDeConexion);
    if (conectado) {
      if (avisoDeConexion) avisoDeConexion.hidden = true;
    } else {   /* un corte de unos segundos se arregla solo: no vale la pena avisarlo */
      pausaDeConexion = window.setTimeout(() => {
        if (avisoDeConexion) avisoDeConexion.hidden = false;
      }, 4000);
    }
  });

  limpiarBorradores();
  ponerSiguienteEncontrado(masEncontrados?.dataset.siguiente);
  montarHilo();
})();
