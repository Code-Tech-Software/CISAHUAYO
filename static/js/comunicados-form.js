/* CISAHUAYO · crear (o corregir) un comunicado y elegir a sus destinatarios
   (templates/comunicados/_ventana_crear.html, _formulario.html, _selector.html, crear.html y editar.html)

   Ventana «Crear comunicado»
   - Se abre desde «Crear comunicado» (sin JavaScript, o con Ctrl/Cmd+clic, el enlace lleva a su página). Cerrarla con
     algo escrito pide confirmar; abrir y cerrar el selector de destinatarios no toca lo escrito.
   - La descripción se escribe con el editor con formato de la mensajería (static/js/editor-mensajes.js): negritas,
     listas, tablas, imágenes dentro del texto y enlaces; Intro hace un párrafo nuevo. Se manda su HTML (el servidor lo
     limpia) y su texto. Sin el editor queda el campo de texto de siempre.
   - Opciones (2026-10-27): pedir una respuesta (Enterado, autorización Sí / No o encuesta con sus opciones), programar
     el envío y la fecha de expiración, un evento para la agenda y la categoría (y fijarlo). Cada sección dice arriba lo
     que tiene elegido.
   - Antes de enviar revisa título, descripción, al menos un destinatario, las fechas, la encuesta, el evento y los
     archivos (hasta 5 contando los que se conservan o se copian, del tipo y tamaño que acepta el sistema). Luego muestra
     la revisión: «Se enviará a…», cuándo se publica y la vista previa como la verá quien lo reciba; «Enviar ahora» (o
     «Programar envío») lo manda. Al corregir no hay revisión: «Guardar cambios». El servidor vuelve a validar todo.
   - Envía con fetch: si falla, la ventana sigue abierta con todo y el aviso del problema. El botón se bloquea mientras
     se envía y la clave de envío del formulario hace que un reintento no cree un segundo comunicado.

   Selector de destinatarios
   - Pide al servidor las personas del alcance de quien envía (comunicados:destinatarios) la primera vez que se abre.
   - Las selecciones de cada pestaña (Tutores, Estudiantes, Profesores y, si puede enviarle, Personal) son
     independientes y se conservan al cambiar de pestaña, de nodo o de búsqueda. Marcar un nodo del árbol agrega a las
     personas de ese nodo en la pestaña activa (no en las otras) y muestra quiénes son; desmarcarlo las quita. Cada
     persona se puede desmarcar suelta. El personal está en su propia rama del árbol («Personal del colegio» → rol).
   - Las casillas del árbol reflejan la selección real de la pestaña activa: marcada (todos), a medias (algunos) o
     vacía; sin personas en esa pestaña, desactivada. Los contadores salen siempre de la selección real (sin repetidos:
     un tutor con varios hijos cuenta una vez).
   - «Marcar todos» y «Desmarcar todos» actúan sobre lo que se ve con el filtro actual (nodo y búsqueda) y lo dicen.
   - «Cancelar» (o Escape, o la X) descarta lo que se cambió en esta apertura; «Confirmar» lo guarda en el formulario.
*/
(() => {
  'use strict';

  const formulario = document.querySelector('[data-formulario-comunicado]');
  if (!formulario || !window.fetch) return;

  const qs = (selector, ambito = document) => ambito.querySelector(selector);
  const qsa = (selector, ambito = document) => [...ambito.querySelectorAll(selector)];
  const icono = (nombre, clase = 'icon icon--sm') => window.CISAHUAYO?.icon?.(nombre, clase) || document.createTextNode('');
  const sinAcentos = (texto) => (texto || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  const crear = (etiqueta, clase, texto) => {
    const nodo = document.createElement(etiqueta);
    if (clase) nodo.className = clase;
    if (texto !== undefined) nodo.textContent = texto;
    return nodo;
  };

  const editando = formulario.dataset.modo === 'editar';
  const TIPOS = ['tutores', 'estudiantes', 'profesores', 'personal'];
  const NOMBRES = {
    tutores: ['tutor', 'tutores'], estudiantes: ['estudiante', 'estudiantes'], profesores: ['profesor', 'profesores'],
    personal: ['persona del personal', 'personas del personal'],
  };
  const ROTULO = { tutores: 'Tutores', estudiantes: 'Estudiantes', profesores: 'Profesores', personal: 'Personal' };
  const cantidad = (n, tipo) => `${n} ${NOMBRES[tipo][n === 1 ? 0 : 1]}`;
  const LIMITE_DE_FILAS = 200;
  const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
  const fechaLegible = (iso, hora = '') => {
    const [anio, mes, dia] = (iso || '').split('-').map(Number);
    if (!anio) return '';
    return `${dia} de ${MESES[mes - 1]}${anio !== new Date().getFullYear() ? ` de ${anio}` : ''}${hora ? ` a las ${hora}` : ''}`;
  };
  const momento = (iso, hora) => {
    const [anio, mes, dia] = iso.split('-').map(Number);
    const [h, m] = (hora || '00:00').split(':').map(Number);
    return new Date(anio, mes - 1, dia, h, m);
  };

  /* =============================================================== Errores en pantalla */
  const errores = qs('[data-errores-generales]', formulario);
  const textoDeErrores = qs('[data-errores-texto]', formulario);
  const campo = (nombre) => qs(`[data-campo="${nombre}"]`, formulario);
  const CAMPOS_CON_ERROR = ['titulo', 'descripcion', 'expira', 'destinatarios', 'archivos', 'publicar', 'evento', 'respuesta'];

  const limpiarError = (nombre) => {
    const contenedor = campo(nombre);
    if (!contenedor) return;
    qsa(':scope > .field__error, :scope > .opcion-comunicado__cuerpo > .field__error', contenedor).forEach((nodo) => nodo.remove());
    contenedor.classList.remove('is-invalid');
    qsa('[aria-invalid]', contenedor).forEach((control) => control.removeAttribute('aria-invalid'));
  };

  const ponerError = (nombre, mensajes) => {
    const contenedor = campo(nombre);
    if (!contenedor) return;
    limpiarError(nombre);
    const lista = [].concat(mensajes || []).filter(Boolean);
    if (!lista.length) return;
    contenedor.classList.add('is-invalid');
    const destino = qs(':scope > .opcion-comunicado__cuerpo', contenedor) || contenedor;
    lista.forEach((mensaje) => destino.append(crear('p', 'field__error', mensaje)));
    qsa('input:not([type="hidden"]), textarea, button.campo-fecha', contenedor).forEach((control) => control.setAttribute('aria-invalid', 'true'));
    contenedor.closest('details')?.setAttribute('open', '');
  };

  const ponerErroresGenerales = (mensajes) => {
    const lista = [].concat(mensajes || []).filter(Boolean);
    textoDeErrores.replaceChildren(...lista.map((mensaje) => crear('p', '', mensaje)));
    errores.hidden = !lista.length;
  };

  const enfocarPrimerError = () => {
    const primero = qs('.is-invalid', formulario);
    const control = primero && (qs('input:not([type="hidden"]):not([hidden]), textarea:not([hidden]), [contenteditable="true"], button', primero));
    if (!errores.hidden) errores.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    control?.focus();
  };

  /* =============================================================== Campos */
  const titulo = qs('[name="titulo"]', formulario);
  const descripcion = qs('[data-descripcion-texto]', formulario);
  const cuenta = qs('[data-descripcion-cuenta]', formulario);
  const fecha = qs('[name="expira_fecha"]', formulario);
  const hora = qs('[name="expira_hora"]', formulario);
  const publicarFecha = qs('[data-publicar-fecha]', formulario);
  const publicarHora = qs('[data-publicar-hora]', formulario);
  const valorDestinatarios = qs('[data-destinatarios-valor]', formulario);
  const valorHtml = qs('[data-html-valor]', formulario);
  const clave = qs('[data-clave-envio]', formulario);
  const enviar = qs('[data-formulario-enviar]', formulario);
  const textoEnviar = qs('[data-formulario-enviar-texto]', formulario);
  const urgente = qs('[name="urgente"]', formulario);
  let modificado = false;

  /* --- El editor con formato ------------------------------------------------------------------------------------- */
  const raizEditor = qs('[data-editor]', formulario);
  const campoEditor = qs('[data-campo-editor]', formulario);
  let editor = null;
  const parrafos = (texto) => texto.split('\n').map((renglon) => {
    const parrafo = document.createElement('p');
    parrafo.textContent = renglon;
    return renglon.trim() ? parrafo.outerHTML : '<p><br></p>';
  }).join('');
  const textoDeLaDescripcion = () => (editor ? (editor.vacio() ? '' : editor.texto()) : descripcion.value.trim());

  const contarDescripcion = () => {
    if (!cuenta) return;
    const maximo = Number(cuenta.dataset.maximo) || 5000;
    const usados = textoDeLaDescripcion().length;
    cuenta.textContent = usados ? `${usados} / ${maximo} caracteres` : `Hasta ${maximo} caracteres · los enlaces que escribas se podrán tocar`;
    cuenta.classList.toggle('is-limite', usados > maximo * 0.9);
  };

  if (raizEditor && campoEditor && window.EditorEnriquecido) {
    campoEditor.hidden = false;
    descripcion.hidden = true;
    editor = new window.EditorEnriquecido(raizEditor, {
      alCambiar: () => {
        modificado = true;
        contarDescripcion();
        if (!editor?.vacio()) limpiarError('descripcion');
      },
    });
    const inicial = qs('[data-html-inicial]', formulario)?.innerHTML.trim();
    if (inicial) editor.poner(inicial);
    else if (descripcion.value.trim()) editor.poner(parrafos(descripcion.value));
    qs('label[for="comunicado-descripcion"]', formulario)?.addEventListener('click', (evento) => {
      evento.preventDefault();
      editor.enfocar();
    });
  } else {
    descripcion?.addEventListener('input', contarDescripcion);
  }
  contarDescripcion();

  formulario.addEventListener('input', (evento) => {
    modificado = true;
    const contenedor = evento.target.closest?.('[data-campo]');
    if (contenedor && evento.target.value) limpiarError(contenedor.dataset.campo);
  });
  formulario.addEventListener('change', (evento) => {
    modificado = true;
    if (evento.target === fecha || evento.target === hora) limpiarError('expira');
    if (evento.target === publicarFecha || evento.target === publicarHora) limpiarError('publicar');
    resumirOpciones();
  });

  /* =============================================================== Opciones */
  /* --- Pedir una respuesta --------------------------------------------------------------------------------------- */
  const tiposDeRespuesta = qsa('[data-respuesta-tipo]', formulario);
  const ayudaDeRespuesta = qs('[data-respuesta-ayuda]', formulario);
  const cajaPregunta = qs('[data-respuesta-pregunta]', formulario);
  const campoPregunta = qs('[data-respuesta-pregunta-campo]', formulario);
  const cajaOpciones = qs('[data-respuesta-opciones]', formulario);
  const listaOpciones = qs('[data-opciones-lista]', formulario);
  const agregarOpcion = qs('[data-opcion-agregar]', formulario);
  const MAXIMO_OPCIONES = Number(formulario.dataset.maximoOpciones) || 6;
  const AYUDAS = {
    '': 'Quien lo recibe solo lo lee. En el seguimiento verás quién lo abrió.',
    ENTERADO: 'Quien lo recibe confirma con un botón «Enterado». En el seguimiento verás quién confirmó.',
    AUTORIZACION: 'Quien lo recibe responde «Sí, autorizo» o «No autorizo» (por ejemplo, un permiso para una excursión). Puede cambiar su respuesta mientras el comunicado siga disponible.',
    ENCUESTA: 'Quien lo recibe elige una de las opciones. En el seguimiento verás cuántos eligieron cada una.',
  };
  const NOMBRE_DE_RESPUESTA = { '': '', ENTERADO: 'Confirmar de enterado', AUTORIZACION: 'Autorización (Sí / No)', ENCUESTA: 'Encuesta' };
  const respuestaElegida = () => tiposDeRespuesta.find((radio) => radio.checked)?.value || '';
  const opcionesEscritas = () => qsa('input[name="opciones"]', listaOpciones || formulario).map((entrada) => entrada.value.trim()).filter(Boolean);

  const renumerarOpciones = () => {
    if (!listaOpciones) return;
    const filas = qsa('.opciones-encuesta__fila', listaOpciones);
    filas.forEach((fila, indice) => {
      const entrada = qs('input', fila);
      entrada.placeholder = `Opción ${indice + 1}`;
      entrada.setAttribute('aria-label', `Opción ${indice + 1}`);
      qs('[data-opcion-quitar]', fila).disabled = filas.length <= 2;
    });
    if (agregarOpcion) agregarOpcion.disabled = filas.length >= MAXIMO_OPCIONES;
  };

  const pintarRespuesta = () => {
    if (!tiposDeRespuesta.length) return;
    const tipo = respuestaElegida();
    ayudaDeRespuesta.textContent = AYUDAS[tipo] || '';
    cajaPregunta.hidden = !['AUTORIZACION', 'ENCUESTA'].includes(tipo);
    campoPregunta.placeholder = tipo === 'ENCUESTA' ? '¿Qué día prefieren para la junta de familias?' : '¿Autoriza que su hijo o hija asista a la excursión?';
    cajaOpciones.hidden = tipo !== 'ENCUESTA';
    tiposDeRespuesta.forEach((radio) => radio.closest('label')?.classList.toggle('is-activo', radio.checked));
    renumerarOpciones();
  };
  tiposDeRespuesta.forEach((radio) => radio.addEventListener('change', () => {
    limpiarError('respuesta');
    pintarRespuesta();
  }));
  agregarOpcion?.addEventListener('click', () => {
    const filas = qsa('.opciones-encuesta__fila', listaOpciones);
    if (filas.length >= MAXIMO_OPCIONES) return;
    const nueva = filas[filas.length - 1].cloneNode(true);
    qs('input', nueva).value = '';
    listaOpciones.append(nueva);
    renumerarOpciones();
    qs('input', nueva).focus();
    modificado = true;
  });
  listaOpciones?.addEventListener('click', (evento) => {
    const quitar = evento.target.closest('[data-opcion-quitar]');
    if (!quitar || qsa('.opciones-encuesta__fila', listaOpciones).length <= 2) return;
    const fila = quitar.closest('.opciones-encuesta__fila');
    (fila.previousElementSibling || fila.nextElementSibling)?.querySelector('input')?.focus();
    fila.remove();
    renumerarOpciones();
    modificado = true;
    resumirOpciones();
  });
  pintarRespuesta();

  /* --- Lo que cada sección tiene elegido, en su encabezado ------------------------------------------------------- */
  const resumenRespuesta = qs('[data-resumen-respuesta]', formulario);
  const resumenPublicacion = qs('[data-resumen-publicacion]', formulario);
  const resumenEvento = qs('[data-resumen-evento]', formulario);
  const resumenCategoria = qs('[data-resumen-categoria]', formulario);
  const eventoFecha = qs('[name="evento_fecha"]', formulario);
  const eventoInicio = qs('[name="evento_hora_inicio"]', formulario);
  const eventoFin = qs('[name="evento_hora_fin"]', formulario);
  const eventoLugar = qs('[name="evento_lugar"]', formulario);
  const categoria = qs('[data-categoria]', formulario);
  const fijado = qs('[data-fijado]', formulario);

  const programado = () => Boolean(publicarFecha?.value && publicarHora?.value);
  const textoDelEvento = () => {
    if (!eventoFecha?.value) return '';
    const horas = eventoInicio.value ? (eventoFin.value ? `${eventoInicio.value} a ${eventoFin.value}` : eventoInicio.value) : 'todo el día';
    return [fechaLegible(eventoFecha.value), horas, eventoLugar.value.trim()].filter(Boolean).join(' · ');
  };
  function resumirOpciones() {
    if (resumenRespuesta) resumenRespuesta.textContent = NOMBRE_DE_RESPUESTA[respuestaElegida()] || '';
    if (resumenPublicacion) {
      const partes = [];
      if (programado()) partes.push(`Se publica el ${fechaLegible(publicarFecha.value, publicarHora.value)}`);
      if (fecha?.value) partes.push(`caduca el ${fechaLegible(fecha.value, hora.value)}`);
      resumenPublicacion.textContent = partes.join(' · ').replace(/^c/, 'C');
    }
    if (resumenEvento) resumenEvento.textContent = textoDelEvento();
    if (resumenCategoria) {
      resumenCategoria.textContent = [categoria?.value ? categoria.selectedOptions[0].textContent : '', fijado?.checked ? 'Fijado' : ''].filter(Boolean).join(' · ');
    }
  }
  resumirOpciones();

  /* =============================================================== Archivos */
  const entradaArchivos = qs('[data-archivos-entrada]', formulario);
  const zona = qs('[data-zona-archivos]', formulario);
  const listaArchivos = qs('[data-archivos-lista]', formulario);
  const cuentaArchivos = qs('[data-archivos-cuenta]', formulario);
  const MAXIMO_ARCHIVOS = Number(formulario.dataset.maximoArchivos) || 5;
  const MAXIMO_MB = Number(formulario.dataset.maximoMb) || 5;
  const EXTENSIONES = (formulario.dataset.acepta || '').split(',').map((e) => e.trim().replace(/^\./, '').toLowerCase()).filter(Boolean);
  const archivos = [];   /* { archivo, url } válidos, en orden */
  /* Los archivos del comunicado que se conservan (al corregir) o que se copian (al usar otro como base) */
  const previosMarcados = () => qsa('[data-adjunto-previo]:checked', formulario).length;
  const ocupados = () => archivos.length + previosMarcados();

  const tamano = (bytes) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1).replace('.', ',')} MB`;
  };

  const sincronizarEntrada = () => {
    try {
      const transferencia = new DataTransfer();
      archivos.forEach(({ archivo }) => transferencia.items.add(archivo));
      entradaArchivos.files = transferencia.files;
    } catch (error) {
      /* navegadores sin DataTransfer: se envía con fetch y la lista propia de todos modos */
    }
  };

  const pintarArchivos = () => {
    listaArchivos.replaceChildren(...archivos.map((elegido, indice) => {
      const fila = crear('li', 'archivo-elegido');
      const miniatura = crear('span', 'archivo-elegido__miniatura');
      miniatura.setAttribute('aria-hidden', 'true');
      if (elegido.url) {
        const imagen = document.createElement('img');
        imagen.src = elegido.url;
        imagen.alt = '';
        miniatura.append(imagen);
      } else {
        miniatura.append(icono('file-text', 'icon'));
      }
      const texto = crear('span', 'archivo-elegido__texto');
      texto.append(crear('span', 'archivo-elegido__nombre', elegido.archivo.name), crear('span', 'archivo-elegido__detalle', tamano(elegido.archivo.size)));
      const quitar = crear('button', 'btn btn--ghost btn--icon btn--sm');
      quitar.type = 'button';
      quitar.setAttribute('aria-label', `Quitar ${elegido.archivo.name}`);
      quitar.dataset.tooltip = 'Quitar';
      quitar.append(icono('x'));
      quitar.addEventListener('click', () => {
        const [quitado] = archivos.splice(indice, 1);
        if (quitado?.url) URL.revokeObjectURL(quitado.url);
        modificado = true;
        limpiarError('archivos');
        actualizarArchivos();
        (qsa('.archivo-elegido button', listaArchivos)[indice] || qsa('.archivo-elegido button', listaArchivos).at(-1) || entradaArchivos).focus();
      });
      fila.append(miniatura, texto, quitar);
      return fila;
    }));
  };

  const actualizarArchivos = () => {
    cuentaArchivos.textContent = String(ocupados());
    const lleno = ocupados() >= MAXIMO_ARCHIVOS;
    zona.classList.toggle('is-lleno', lleno);
    entradaArchivos.disabled = lleno;
    sincronizarEntrada();
    pintarArchivos();
  };

  const agregarArchivos = (nuevos) => {
    const rechazados = [];
    [...nuevos].forEach((archivo) => {
      const extension = archivo.name.includes('.') ? archivo.name.split('.').pop().toLowerCase() : '';
      if (archivos.some(({ archivo: otro }) => otro.name === archivo.name && otro.size === archivo.size && otro.lastModified === archivo.lastModified)) return;
      if (ocupados() >= MAXIMO_ARCHIVOS) {
        rechazados.push(`«${archivo.name}»: ya hay ${MAXIMO_ARCHIVOS} archivos (el máximo).`);
      } else if (!EXTENSIONES.includes(extension)) {
        rechazados.push(`«${archivo.name}»: solo se aceptan fotos (JPG, PNG o WEBP) y documentos PDF.`);
      } else if (archivo.size > MAXIMO_MB * 1024 * 1024) {
        rechazados.push(`«${archivo.name}» pesa ${tamano(archivo.size)}: el máximo es ${MAXIMO_MB} MB.`);
      } else if (!archivo.size) {
        rechazados.push(`«${archivo.name}» está vacío.`);
      } else {
        archivos.push({ archivo, url: archivo.type.startsWith('image/') ? URL.createObjectURL(archivo) : '' });
      }
    });
    modificado = true;
    ponerError('archivos', rechazados);
    actualizarArchivos();
  };

  entradaArchivos.addEventListener('change', () => {
    const elegidos = [...entradaArchivos.files].filter((archivo) => !archivos.some(({ archivo: otro }) => otro === archivo));
    agregarArchivos(elegidos);
  });
  ['dragenter', 'dragover'].forEach((tipo) => zona.addEventListener(tipo, (evento) => {
    if (![...(evento.dataTransfer?.types || [])].includes('Files')) return;
    evento.preventDefault();
    zona.classList.add('is-arrastrando');
  }));
  ['dragleave', 'dragend'].forEach((tipo) => zona.addEventListener(tipo, () => zona.classList.remove('is-arrastrando')));
  zona.addEventListener('drop', (evento) => {
    evento.preventDefault();
    zona.classList.remove('is-arrastrando');
    if (evento.dataTransfer?.files?.length) agregarArchivos(evento.dataTransfer.files);
  });
  qsa('[data-adjunto-previo]', formulario).forEach((casilla) => casilla.addEventListener('change', () => {
    if (casilla.checked && ocupados() > MAXIMO_ARCHIVOS) {
      casilla.checked = false;
      ponerError('archivos', `Ya hay ${MAXIMO_ARCHIVOS} archivos (el máximo).`);
    }
    actualizarArchivos();
  }));
  actualizarArchivos();

  /* =============================================================== Selector de destinatarios */
  const confirmado = { tutores: new Set(), estudiantes: new Set(), profesores: new Set(), personal: new Set() };
  const total = (seleccion) => TIPOS.reduce((suma, tipo) => suma + seleccion[tipo].size, 0);
  const resumenDe = (seleccion, prefijo = '') => {
    if (!total(seleccion)) return 'Nadie seleccionado todavía';
    return `${prefijo}${TIPOS.filter((tipo) => seleccion[tipo].size).map((tipo) => cantidad(seleccion[tipo].size, tipo)).join(' · ')}`;
  };
  let escribirSeleccion = () => {};
  const selector = qs('[data-selector]');

  if (!editando && selector && valorDestinatarios) {
    const panel = qs('.selector', selector);
    const abrirSelector = qs('[data-selector-abrir]', formulario);
    const resumenFormulario = qs('[data-destinatarios-resumen]', formulario);
    const filaDestinatarios = campo('destinatarios');
    const resumenInicial = resumenFormulario?.textContent || '';
    let borrador = null;
    let datos = null;
    let indices = null;
    let pestana = 'tutores';
    let enfocado = null;   /* clave del nodo cuyas personas se ven en la lista ('n:PRIMARIA', 'g:3', 'gr:7', 'm:31', 'p:todo', 'r:4') */
    let limite = LIMITE_DE_FILAS;
    let cargando = null;

    try {
      const previo = valorDestinatarios.value ? JSON.parse(valorDestinatarios.value) : null;
      if (previo) TIPOS.forEach((tipo) => (previo[tipo] || []).forEach((id) => confirmado[tipo].add(Number(id))));
    } catch (error) {
      /* sin selección previa */
    }

    escribirSeleccion = () => {
      const valor = {};
      TIPOS.forEach((tipo) => { valor[tipo] = [...confirmado[tipo]].sort((a, b) => a - b); });
      valorDestinatarios.value = total(confirmado) ? JSON.stringify(valor) : '';
      const hay = total(confirmado) > 0;
      resumenFormulario.textContent = hay ? resumenDe(confirmado) : resumenInicial;
      filaDestinatarios.classList.toggle('is-elegidos', hay);
      abrirSelector.textContent = hay ? 'Cambiar' : 'Abrir';
      if (hay) limpiarError('destinatarios');
    };
    if (total(confirmado)) escribirSeleccion();

    /* --- Datos e índices --------------------------------------------------------------------------------------- */
    const indexar = () => {
      datos.personal = datos.personal || [];
      datos.roles = datos.roles || [];
      const porId = { tutores: new Map(), estudiantes: new Map(), profesores: new Map(), personal: new Map() };
      TIPOS.forEach((tipo) => datos[tipo].forEach((persona) => porId[tipo].set(persona.id, persona)));
      const nodos = new Map();   /* clave -> { clave, tipo, nombre, padre, hijos, grupos: Set, materia } */
      const agregar = (nodo) => { nodos.set(nodo.clave, nodo); return nodo; };
      datos.arbol.forEach((nivel) => {
        const nodoNivel = agregar({ clave: `n:${nivel.clave}`, tipo: 'nivel', nivel: nivel.clave, nombre: nivel.nombre, padre: null, hijos: [], grupos: new Set() });
        nivel.grados.forEach((grado) => {
          const nodoGrado = agregar({ clave: `g:${grado.id}`, tipo: 'grado', nombre: grado.nombre, padre: nodoNivel, hijos: [], grupos: new Set() });
          nodoNivel.hijos.push(nodoGrado);
          grado.grupos.forEach((grupo) => {
            const nodoGrupo = agregar({ clave: `gr:${grupo.id}`, tipo: 'grupo', nombre: grupo.nombre, padre: nodoGrado, hijos: [], grupos: new Set([grupo.id]) });
            nodoGrado.hijos.push(nodoGrupo);
            nodoGrado.grupos.add(grupo.id);
            nodoNivel.grupos.add(grupo.id);
            grupo.materias.forEach((materia) => {
              nodoGrupo.hijos.push(agregar({
                clave: `m:${materia.id}`, tipo: 'materia', nombre: materia.nombre, padre: nodoGrupo, hijos: [],
                grupos: new Set([grupo.id]), materia: materia.id, profesor: materia.profesor,
              }));
            });
          });
        });
      });
      /* El personal: su propia rama, por rol */
      if (datos.personal.length) {
        const raiz = agregar({ clave: 'p:todo', tipo: 'personal', nombre: 'Personal del colegio', padre: null, hijos: [], grupos: new Set() });
        datos.roles.forEach((rol) => raiz.hijos.push(agregar({ clave: `r:${rol.id}`, tipo: 'rol', nombre: rol.nombre, padre: raiz, hijos: [], grupos: new Set(), rol: rol.id })));
      }
      const tutoresDe = new Map();   /* estudiante -> [tutores] */
      datos.tutores.forEach((tutor) => tutor.hijos.forEach((hijo) => {
        if (!tutoresDe.has(hijo)) tutoresDe.set(hijo, []);
        tutoresDe.get(hijo).push(tutor.id);
      }));
      indices = { porId, nodos, tutoresDe, miembros: new Map() };
    };

    /* Las personas de un nodo en una pestaña (sin repetidos), guardadas una vez calculadas */
    const miembros = (clave, tipo) => {
      const llave = `${tipo}|${clave}`;
      if (indices.miembros.has(llave)) return indices.miembros.get(llave);
      const nodo = indices.nodos.get(clave);
      const resultado = new Set();
      if (nodo && (nodo.tipo === 'personal' || nodo.tipo === 'rol')) {
        if (tipo === 'personal') datos.personal.forEach((persona) => { if (nodo.tipo === 'personal' || persona.rol === nodo.rol) resultado.add(persona.id); });
      } else if (nodo && tipo !== 'personal') {
        if (tipo === 'estudiantes' || tipo === 'tutores') {
          const alumnos = datos.estudiantes.filter((alumno) => alumno.grupo && nodo.grupos.has(alumno.grupo));
          if (tipo === 'estudiantes') alumnos.forEach((alumno) => resultado.add(alumno.id));
          else alumnos.forEach((alumno) => (indices.tutoresDe.get(alumno.id) || []).forEach((tutor) => resultado.add(tutor)));
        } else if (nodo.tipo === 'materia') {
          datos.profesores.forEach((profesor) => { if (profesor.materias.includes(nodo.materia)) resultado.add(profesor.id); });
        } else if (nodo.tipo === 'nivel') {
          datos.profesores.forEach((profesor) => {
            if (profesor.niveles.includes(nodo.nivel) || profesor.grupos.some((grupo) => nodo.grupos.has(grupo))) resultado.add(profesor.id);
          });
        } else {
          datos.profesores.forEach((profesor) => { if (profesor.grupos.some((grupo) => nodo.grupos.has(grupo))) resultado.add(profesor.id); });
        }
      }
      indices.miembros.set(llave, resultado);
      return resultado;
    };

    /* --- Elementos del selector -------------------------------------------------------------------------------- */
    const estado = qs('[data-selector-estado]', selector);
    const cargandoNodo = qs('[data-selector-cargando]', selector);
    const errorNodo = qs('[data-selector-error]', selector);
    const errorTexto = qs('[data-selector-error-texto]', selector);
    const cuerpo = qs('[data-selector-cuerpo]', selector);
    const arbol = qs('[data-arbol]', selector);
    const arbolVacio = qs('[data-arbol-vacio]', selector);
    const arbolBuscar = qs('[data-arbol-buscar]', selector);
    const arbolResumen = qs('[data-arbol-resumen]', selector);
    const lista = qs('[data-lista]', selector);
    const listaVacia = qs('[data-lista-vacia]', selector);
    const listaTitulo = qs('[data-lista-titulo]', selector);
    const listaContador = qs('[data-lista-contador]', selector);
    const listaAyuda = qs('[data-lista-ayuda]', selector);
    const listaAlcance = qs('[data-lista-alcance]', selector);
    const listaBuscar = qs('[data-lista-buscar]', selector);
    const listaFiltro = qs('[data-lista-filtro]', selector);
    const listaFiltroTexto = qs('[data-lista-filtro-texto]', selector);
    const masFilas = qs('[data-lista-mas]', selector);
    const marcarTodos = qs('[data-lista-marcar]', selector);
    const desmarcarTodos = qs('[data-lista-desmarcar]', selector);
    const resumenSelector = qs('[data-selector-resumen]', selector);
    const confirmar = qs('[data-selector-confirmar]', selector);
    const pasoCuenta = qs('[data-selector-paso-cuenta]', selector);
    const pestanas = qsa('[data-pestana]', selector);
    const filasDeNodo = new Map();   /* clave -> { li, fila, casilla, cuenta, plegar, sublista } */
    const tiposVisibles = () => TIPOS.filter((tipo) => tipo !== 'personal' || datos?.personal?.length || confirmado.personal.size);

    /* --- Árbol -------------------------------------------------------------------------------------------------- */
    const CHIP = { nivel: 'school', grado: 'layers', grupo: 'users', materia: 'book-open', personal: 'briefcase', rol: 'user-check' };
    const pocosGrupos = () => datos.arbol.reduce((suma, nivel) => suma + nivel.grados.reduce((s, grado) => s + grado.grupos.length, 0), 0);

    const construirArbol = () => {
      filasDeNodo.clear();
      const cuantos = pocosGrupos();
      const rama = (nodos, nivel = 0) => {
        const ul = crear('ul', 'arbol__lista');
        ul.setAttribute('role', 'list');
        nodos.forEach((nodo) => {
          const li = crear('li', `arbol__nodo arbol__nodo--${nodo.tipo}`);
          const fila = crear('div', 'arbol__nodo-fila');
          let plegar = null;
          let sublista = null;
          if (nodo.hijos.length) {
            plegar = crear('button', 'arbol__plegar');
            plegar.type = 'button';
            const abierto = nodo.tipo === 'nivel' || nodo.tipo === 'personal' || (nodo.tipo === 'grado' && cuantos <= 12) || (nodo.tipo === 'grupo' && cuantos <= 4);
            plegar.setAttribute('aria-expanded', String(abierto));
            plegar.setAttribute('aria-label', `${abierto ? 'Contraer' : 'Expandir'} ${nodo.nombre}`);
            plegar.append(icono('chevron-down'));
            fila.append(plegar);
          } else {
            fila.append(crear('span', 'arbol__plegar-espacio'));
          }
          const casilla = document.createElement('input');
          casilla.type = 'checkbox';
          casilla.className = 'arbol__casilla';
          casilla.dataset.nodo = nodo.clave;
          const chip = crear('span', `arbol__chip arbol__chip--${nodo.tipo}`);
          chip.setAttribute('aria-hidden', 'true');
          chip.append(icono(CHIP[nodo.tipo]));
          const etiqueta = crear('button', 'arbol__etiqueta', nodo.nombre);
          etiqueta.type = 'button';
          etiqueta.dataset.enfocar = nodo.clave;
          const cuentaNodo = crear('span', 'arbol__cuenta');
          fila.append(casilla, chip, etiqueta, cuentaNodo);
          li.append(fila);
          if (nodo.hijos.length) {
            sublista = rama(nodo.hijos, nivel + 1);
            sublista.hidden = plegar.getAttribute('aria-expanded') !== 'true';
            li.append(sublista);
            plegar.addEventListener('click', () => {
              const abrir = plegar.getAttribute('aria-expanded') !== 'true';
              plegar.setAttribute('aria-expanded', String(abrir));
              plegar.setAttribute('aria-label', `${abrir ? 'Contraer' : 'Expandir'} ${nodo.nombre}`);
              sublista.hidden = !abrir;
            });
          }
          filasDeNodo.set(nodo.clave, { li, fila, casilla, cuenta: cuentaNodo, etiqueta, plegar, sublista, nodo });
          ul.append(li);
        });
        return ul;
      };
      const raices = datos.arbol.map((nivel) => indices.nodos.get(`n:${nivel.clave}`));
      if (indices.nodos.has('p:todo')) raices.push(indices.nodos.get('p:todo'));
      arbol.replaceChildren(raices.length ? rama(raices) : crear('p', 'selector__nada', 'No hay grupos con estudiantes o profesores en el ciclo actual. Busca y marca personas en la lista.'));
    };

    const nombreDelNodo = (nodo) => (nodo.tipo === 'materia' ? `${nodo.nombre} · ${nodo.padre.nombre}` : nodo.nombre);

    const actualizarArbol = () => {
      const elegidos = borrador[pestana];
      let marcadosArriba = 0;
      filasDeNodo.forEach(({ fila, casilla, cuenta: cuentaNodo, etiqueta, nodo }) => {
        const personas = miembros(nodo.clave, pestana);
        let dentro = 0;
        personas.forEach((id) => { if (elegidos.has(id)) dentro += 1; });
        const todos = personas.size > 0 && dentro === personas.size;
        casilla.checked = todos;
        casilla.indeterminate = dentro > 0 && !todos;
        casilla.disabled = personas.size === 0;
        casilla.setAttribute('aria-label', personas.size
          ? `${todos ? 'Quitar' : 'Incluir'} a ${personas.size === 1 ? 'la persona' : `las ${personas.size} personas`} (${ROTULO[pestana].toLowerCase()}) de ${nombreDelNodo(nodo)}`
          : `${nombreDelNodo(nodo)}: sin ${ROTULO[pestana].toLowerCase()}`);
        cuentaNodo.textContent = String(personas.size);
        cuentaNodo.title = `${cantidad(personas.size, pestana)}${dentro ? ` · ${dentro} seleccionado${dentro === 1 ? '' : 's'}` : ''}`;
        fila.classList.toggle('is-marcado', todos);
        fila.classList.toggle('is-vacio', personas.size === 0);
        fila.classList.toggle('is-enfocado', enfocado === nodo.clave);
        etiqueta.setAttribute('aria-pressed', String(enfocado === nodo.clave));
      });
      /* Los marcados «de más arriba» (un grupo dentro de un grado marcado no cuenta otra vez), ya con los padres al día */
      filasDeNodo.forEach(({ casilla, nodo }) => {
        if (casilla.checked && !(nodo.padre && filasDeNodo.get(nodo.padre.clave)?.casilla.checked)) marcadosArriba += 1;
      });
      arbolResumen.textContent = marcadosArriba
        ? `${marcadosArriba} ${marcadosArriba === 1 ? 'grupo completo marcado' : 'grupos completos marcados'} en ${ROTULO[pestana].toLowerCase()}`
        : `Ningún grupo completo marcado en ${ROTULO[pestana].toLowerCase()}`;
    };

    const filtrarArbol = () => {
      const texto = sinAcentos(arbolBuscar.value.trim());
      let visibles = 0;
      const visible = (nodo) => {
        const propio = !texto || sinAcentos(nombreDelNodo(nodo)).includes(texto);
        const deHijos = nodo.hijos.map(visible).some(Boolean);
        return propio || deHijos;
      };
      const coincideArriba = (nodo) => Boolean(nodo) && (sinAcentos(nombreDelNodo(nodo)).includes(texto) || coincideArriba(nodo.padre));
      filasDeNodo.forEach(({ li, nodo, plegar, sublista }) => {
        const ver = !texto || visible(nodo) || coincideArriba(nodo.padre);
        li.hidden = !ver;
        if (ver) visibles += 1;
        if (texto && sublista && ver) {
          sublista.hidden = false;
          plegar?.setAttribute('aria-expanded', 'true');
        }
      });
      arbolVacio.hidden = Boolean(visibles) || !filasDeNodo.size;
    };

    /* --- Lista de personas ------------------------------------------------------------------------------------- */
    const textoDeBusqueda = (persona) => {
      if (persona._busqueda) return persona._busqueda;
      const partes = [persona.nombre, persona.detalle || ''];
      if (pestana === 'tutores') partes.push(...persona.hijos.map((hijo) => indices.porId.estudiantes.get(hijo)?.corto || ''));
      persona._busqueda = sinAcentos(partes.join(' '));
      return persona._busqueda;
    };

    const filtradas = () => {
      const texto = sinAcentos(listaBuscar.value.trim());
      const delNodo = enfocado ? miembros(enfocado, pestana) : null;
      return datos[pestana].filter((persona) => (!delNodo || delNodo.has(persona.id))
        && (!texto || texto.split(/\s+/).every((palabra) => textoDeBusqueda(persona).includes(palabra))));
    };

    const filaDePersona = (persona) => {
      const li = document.createElement('li');
      const fila = crear('label', 'persona-fila');
      const casilla = document.createElement('input');
      casilla.type = 'checkbox';
      casilla.className = 'persona-fila__casilla';
      casilla.value = String(persona.id);
      casilla.checked = borrador[pestana].has(persona.id);
      const texto = crear('span', 'persona-fila__texto');
      texto.append(crear('span', 'persona-fila__nombre', persona.nombre));
      if (pestana === 'tutores') {
        const nodo = enfocado ? indices.nodos.get(enfocado) : null;
        const hijos = persona.hijos.map((hijo) => indices.porId.estudiantes.get(hijo)).filter((hijo) => hijo && (!nodo || (hijo.grupo && nodo.grupos.has(hijo.grupo))));
        const visibles = hijos.length ? hijos : persona.hijos.map((hijo) => indices.porId.estudiantes.get(hijo)).filter(Boolean);
        if (visibles.length) {
          const caja = crear('span', 'persona-fila__hijos');
          caja.append(crear('span', '', visibles.length === 1 ? 'Hijo/a:' : 'Hijos/as:'));
          visibles.forEach((hijo) => caja.append(crear('span', 'persona-fila__hijo', hijo.corto)));
          texto.append(caja);
        } else {
          texto.append(crear('span', 'persona-fila__detalle', 'Sin estudiantes vinculados que reciban avisos'));
        }
      } else if (persona.detalle) {
        texto.append(crear('span', 'persona-fila__detalle', persona.detalle));
      }
      if (persona.sin_acceso) texto.append(crear('span', 'persona-fila__aviso', 'Aún sin acceso al portal'));
      fila.append(casilla, texto);
      li.append(fila);
      return li;
    };

    const pintarLista = (reiniciar = false) => {
      if (reiniciar) {
        limite = LIMITE_DE_FILAS;
        lista.scrollTop = 0;
      }
      const personas = filtradas();
      const elegidos = borrador[pestana];
      const marcadas = personas.reduce((suma, persona) => suma + elegidos.has(persona.id), 0);
      const nodo = enfocado ? indices.nodos.get(enfocado) : null;
      listaTitulo.textContent = nodo ? `${nombreDelNodo(nodo)} · ${ROTULO[pestana]}` : `Todos · ${ROTULO[pestana]}`;
      listaContador.textContent = `${marcadas} de ${personas.length} seleccionado${personas.length === 1 ? '' : 's'}`;
      listaFiltro.hidden = !nodo;
      if (nodo) listaFiltroTexto.textContent = `Se ven los ${ROTULO[pestana].toLowerCase()} de ${nombreDelNodo(nodo)}.`;
      let ayuda = nodo ? '' : 'Busca y marca personas concretas, o elige un nivel, grupo o materia a la izquierda para incluir a todo el grupo.';
      if (pestana === 'tutores') ayuda = `${ayuda} Solo aparecen los tutores con «Recibe notificaciones» activo en su vínculo con el estudiante; un tutor con varios hijos recibe una sola copia.`.trim();
      if (pestana === 'profesores') ayuda = `${ayuda} Aparecen los profesores con cuenta que pueden consultar comunicados.`.trim();
      if (pestana === 'personal') ayuda = 'El personal no docente cuya cuenta puede consultar comunicados (Roles y permisos › Comunicados recibidos). Elige «Personal del colegio» o un rol a la izquierda para incluirlos a todos.';
      listaAyuda.textContent = ayuda;
      const filtrado = Boolean(nodo || listaBuscar.value.trim());
      listaAlcance.textContent = personas.length
        ? `«Marcar todos» ${filtrado ? `marca a los ${personas.length} que se ven con este filtro` : `marca a ${personas.length === 1 ? 'la persona' : `las ${personas.length} personas`} de ${ROTULO[pestana].toLowerCase()} a las que puedes enviar`}.`
        : '';
      marcarTodos.disabled = !personas.length || marcadas === personas.length;
      desmarcarTodos.disabled = !marcadas;
      lista.replaceChildren(...personas.slice(0, limite).map(filaDePersona));
      masFilas.hidden = personas.length <= limite;
      if (!masFilas.hidden) masFilas.textContent = `Mostrar más (${personas.length - limite} restantes)`;
      listaVacia.hidden = Boolean(personas.length);
      if (!personas.length) {
        listaVacia.textContent = listaBuscar.value.trim()
          ? 'Nadie coincide con la búsqueda.'
          : nodo ? `${nombreDelNodo(nodo)} no tiene ${ROTULO[pestana].toLowerCase()} a quienes enviar.` : `No hay ${ROTULO[pestana].toLowerCase()} a quienes puedas enviar.`;
      }
    };

    const actualizarResumen = () => {
      const n = total(borrador);
      resumenSelector.replaceChildren();
      if (n) {
        resumenSelector.append(document.createTextNode('Seleccionados: '));
        tiposVisibles().forEach((tipo, indice) => {
          if (indice) resumenSelector.append(document.createTextNode(' · '));
          resumenSelector.append(crear('strong', '', cantidad(borrador[tipo].size, tipo)));
        });
      } else {
        resumenSelector.textContent = 'Nadie seleccionado todavía';
      }
      confirmar.disabled = !n;
      pasoCuenta.hidden = !n;
      pasoCuenta.textContent = String(n);
      TIPOS.forEach((tipo) => {
        const insignia = qs(`[data-pestana-cuenta="${tipo}"]`, selector);
        if (!insignia) return;
        insignia.textContent = borrador[tipo].size ? String(borrador[tipo].size) : '';
        qs(`[data-pestana="${tipo}"]`, selector).setAttribute('aria-label', `${ROTULO[tipo]}${borrador[tipo].size ? `, ${cantidad(borrador[tipo].size, tipo)} seleccionados` : ''}`);
      });
    };

    const refrescar = (reiniciarLista = false) => {
      actualizarArbol();
      pintarLista(reiniciarLista);
      actualizarResumen();
    };

    /* --- Interacción ------------------------------------------------------------------------------------------- */
    arbol.addEventListener('change', (evento) => {
      const casilla = evento.target.closest('.arbol__casilla');
      if (!casilla) return;
      const personas = miembros(casilla.dataset.nodo, pestana);
      const elegidos = borrador[pestana];
      const todos = [...personas].every((id) => elegidos.has(id));
      personas.forEach((id) => (todos ? elegidos.delete(id) : elegidos.add(id)));
      enfocado = todos && enfocado === casilla.dataset.nodo ? enfocado : casilla.dataset.nodo;   /* se ve a quién se incluyó */
      refrescar(true);
    });
    arbol.addEventListener('click', (evento) => {
      const etiqueta = evento.target.closest('[data-enfocar]');
      if (!etiqueta) return;
      enfocado = enfocado === etiqueta.dataset.enfocar ? null : etiqueta.dataset.enfocar;
      const nodo = indices.nodos.get(enfocado);
      if (nodo && (nodo.tipo === 'personal' || nodo.tipo === 'rol') && pestana !== 'personal') elegirPestana('personal');   /* su rama: su pestaña */
      else refrescar(true);
      if (window.matchMedia('(max-width: 63.99rem)').matches && enfocado) cambiarPaso('personas');
    });
    arbolBuscar.addEventListener('input', filtrarArbol);
    qs('[data-arbol-limpiar]', selector).addEventListener('click', () => {
      borrador[pestana].clear();
      enfocado = null;
      refrescar(true);
    });

    lista.addEventListener('change', (evento) => {
      const casilla = evento.target.closest('.persona-fila__casilla');
      if (!casilla) return;
      const id = Number(casilla.value);
      if (casilla.checked) borrador[pestana].add(id);
      else borrador[pestana].delete(id);
      actualizarArbol();
      const personas = filtradas();
      const marcadas = personas.reduce((suma, persona) => suma + borrador[pestana].has(persona.id), 0);
      listaContador.textContent = `${marcadas} de ${personas.length} seleccionado${personas.length === 1 ? '' : 's'}`;
      marcarTodos.disabled = !personas.length || marcadas === personas.length;
      desmarcarTodos.disabled = !marcadas;
      actualizarResumen();
    });
    let espera = null;
    listaBuscar.addEventListener('input', () => {
      window.clearTimeout(espera);
      espera = window.setTimeout(() => pintarLista(true), 120);
    });
    qs('[data-lista-filtro-quitar]', selector).addEventListener('click', () => {
      enfocado = null;
      refrescar(true);
    });
    marcarTodos.addEventListener('click', () => {
      filtradas().forEach((persona) => borrador[pestana].add(persona.id));
      refrescar();
    });
    desmarcarTodos.addEventListener('click', () => {
      filtradas().forEach((persona) => borrador[pestana].delete(persona.id));
      refrescar();
    });
    masFilas.addEventListener('click', () => {
      limite += LIMITE_DE_FILAS;
      pintarLista();
    });

    function elegirPestana(tipo, enfocar = false) {
      pestana = tipo;
      pestanas.forEach((boton) => {
        const activa = boton.dataset.pestana === tipo;
        boton.setAttribute('aria-selected', String(activa));
        boton.tabIndex = activa ? 0 : -1;
        if (activa && enfocar) boton.focus();
      });
      qsa('[data-pestana-movil]', selector).forEach((boton) => {
        const activa = boton.dataset.pestanaMovil === tipo;
        boton.classList.toggle('is-activo', activa);
        boton.setAttribute('aria-pressed', String(activa));
      });
      refrescar(true);
    }
    pestanas.forEach((boton) => {
      boton.addEventListener('click', () => elegirPestana(boton.dataset.pestana));
      boton.addEventListener('keydown', (evento) => {
        const paso = { ArrowRight: 1, ArrowLeft: -1 }[evento.key];
        if (!paso) return;
        evento.preventDefault();
        const visibles = tiposVisibles();
        const indice = (visibles.indexOf(pestana) + paso + visibles.length) % visibles.length;
        elegirPestana(visibles[indice], true);
      });
    });

    qsa('[data-pestana-movil]', selector).forEach((boton) => boton.addEventListener('click', () => elegirPestana(boton.dataset.pestanaMovil)));

    /* En el móvil: «Grupos y materias» o «Personas» */
    const pasos = qsa('[data-selector-paso]', selector);
    const cambiarPaso = (paso) => {
      panel.dataset.paso = paso;
      pasos.forEach((boton) => boton.setAttribute('aria-selected', String(boton.dataset.selectorPaso === paso)));
    };
    pasos.forEach((boton) => boton.addEventListener('click', () => cambiarPaso(boton.dataset.selectorPaso)));

    /* --- Cargar, abrir, confirmar y cancelar ------------------------------------------------------------------- */
    const mostrarEstado = (cual) => {
      estado.hidden = cual === 'listo';
      cargandoNodo.hidden = cual !== 'cargando';
      errorNodo.hidden = cual !== 'error';
      cuerpo.hidden = cual !== 'listo';
    };

    const cargar = () => {
      if (datos) return Promise.resolve(datos);
      if (cargando) return cargando;
      mostrarEstado('cargando');
      cargando = fetch(formulario.dataset.destinatariosUrl, { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
        .then(async (respuesta) => {
          const contenido = await respuesta.json().catch(() => ({}));
          if (!respuesta.ok) throw new Error(contenido.error || 'No se pudo cargar la lista de personas.');
          datos = contenido;
          indexar();
          /* La pestaña «Personal», solo para quien puede enviarle */
          qsa('[data-solo-personal]', selector).forEach((boton) => { boton.hidden = !datos.personal.length; });
          /* Lo que ya estaba elegido y ya no está en el alcance (p. ej. tras cambiar sus niveles) se descarta */
          TIPOS.forEach((tipo) => [...confirmado[tipo]].forEach((id) => { if (!indices.porId[tipo].has(id)) confirmado[tipo].delete(id); }));
          escribirSeleccion();
          construirArbol();
          return datos;
        })
        .catch((error) => {
          errorTexto.textContent = error.message && !/fetch|network/i.test(error.message) ? error.message : 'Revisa tu conexión e inténtalo de nuevo.';
          mostrarEstado('error');
          throw error;
        })
        .finally(() => { cargando = null; });
      return cargando;
    };

    const abrir = () => {
      if (typeof selector.showModal !== 'function') return;
      borrador = Object.fromEntries(TIPOS.map((tipo) => [tipo, new Set(confirmado[tipo])]));
      enfocado = null;
      listaBuscar.value = '';
      arbolBuscar.value = '';
      cambiarPaso('grupos');
      selector.showModal();
      cargar().then(() => {
        mostrarEstado('listo');
        filtrarArbol();
        elegirPestana(pestana);
        (qs('.arbol__casilla:not(:disabled)', arbol) || listaBuscar).focus();
      }).catch(() => qs('[data-selector-reintentar]', selector)?.focus());
    };

    const cerrar = () => {
      borrador = null;
      if (selector.open) selector.close();
      abrirSelector.focus();
    };

    abrirSelector.addEventListener('click', abrir);
    qs('[data-selector-reintentar]', selector)?.addEventListener('click', () => {
      cargar().then(() => {
        mostrarEstado('listo');
        filtrarArbol();
        elegirPestana(pestana);
      }).catch(() => {});
    });
    qsa('[data-selector-cancelar]', selector).forEach((boton) => boton.addEventListener('click', cerrar));
    selector.addEventListener('cancel', (evento) => {   /* Escape: lo mismo que «Cancelar» */
      evento.preventDefault();
      cerrar();
    });
    confirmar.addEventListener('click', () => {
      if (!borrador || !total(borrador)) return;
      TIPOS.forEach((tipo) => { confirmado[tipo] = new Set(borrador[tipo]); });
      modificado = true;
      escribirSeleccion();
      cerrar();
    });

    /* Usado como base: los destinatarios del original, ya revisados contra el alcance al cargar la lista */
    if (total(confirmado)) cargar().catch(() => {});
  }

  /* =============================================================== Validar */
  const validar = () => {
    let bien = true;
    ponerErroresGenerales([]);
    const ahora = new Date();
    if (!titulo.value.trim()) {
      ponerError('titulo', 'Escribe un título para el comunicado.');
      bien = false;
    }
    if (!textoDeLaDescripcion()) {
      ponerError('descripcion', 'Escribe la descripción del comunicado.');
      bien = false;
    } else if (editor?.subiendo()) {
      ponerError('descripcion', 'Espera a que termine de subirse la imagen.');
      bien = false;
    }
    if (!editando && !total(confirmado)) {
      ponerError('destinatarios', 'Elige al menos un destinatario.');
      bien = false;
    }
    let publicacion = ahora;
    if (publicarFecha && (publicarFecha.value || publicarHora.value)) {
      if (!publicarFecha.value || !publicarHora.value) {
        ponerError('publicar', 'Elige la fecha y la hora de publicación (o bórralas para enviarlo ya).');
        bien = false;
      } else {
        publicacion = momento(publicarFecha.value, publicarHora.value);
        if (publicacion <= ahora) {
          ponerError('publicar', 'La fecha de publicación debe ser posterior a este momento.');
          bien = false;
        }
      }
    }
    if (hora.value && !fecha.value) {
      ponerError('expira', 'Elige también la fecha de expiración (o borra la hora).');
      bien = false;
    } else if (fecha.value) {
      const expira = momento(fecha.value, hora.value || '23:59');
      if (expira <= ahora) {
        ponerError('expira', 'La fecha de expiración debe ser posterior al momento del envío.');
        bien = false;
      } else if (expira <= publicacion) {
        ponerError('expira', 'La fecha de expiración debe ser posterior a la publicación.');
        bien = false;
      }
    }
    const tipo = respuestaElegida();
    if (tipo === 'ENCUESTA') {
      const opciones = opcionesEscritas();
      const distintas = new Set(opciones.map((opcion) => sinAcentos(opcion)));
      if (!campoPregunta.value.trim()) {
        ponerError('respuesta', 'Escribe la pregunta de la encuesta.');
        bien = false;
      } else if (distintas.size < 2) {
        ponerError('respuesta', 'La encuesta necesita al menos 2 opciones distintas.');
        bien = false;
      }
    }
    if (eventoFecha) {
      if (!eventoFecha.value && (eventoInicio.value || eventoFin.value || eventoLugar.value.trim())) {
        ponerError('evento', 'Elige la fecha del evento (o borra su hora y su lugar).');
        bien = false;
      } else if (eventoFin.value && !eventoInicio.value) {
        ponerError('evento', 'Elige también la hora de inicio del evento.');
        bien = false;
      } else if (eventoInicio.value && eventoFin.value && eventoFin.value <= eventoInicio.value) {
        ponerError('evento', 'La hora de fin del evento debe ser después de la de inicio.');
        bien = false;
      }
    }
    return bien;
  };

  /* =============================================================== Revisión antes de enviar */
  const pasoEditar = qs('[data-paso-editar]', formulario);
  const pasoRevisar = qs('[data-paso-revisar]', formulario);
  const revisionResumen = qs('[data-revision-resumen]', formulario);
  const revisionVista = qs('[data-revision-vista]', formulario);
  const revisionTitulo = qs('[data-revision-titulo]', formulario);
  const volverAEditar = qs('[data-formulario-volver]', formulario);
  const TEXTO_DEL_BOTON = editando ? 'Guardar cambios' : 'Revisar y enviar';
  let revisando = false;

  /* El contenido para la vista previa: lo del editor, sin scripts ni atributos de eventos */
  const contenidoSeguro = () => {
    if (!editor) {
      const caja = document.createElement('div');
      caja.innerHTML = parrafos(descripcion.value);
      return caja;
    }
    const documento = new DOMParser().parseFromString(editor.html(), 'text/html');
    qsa('script,style,iframe,object,embed,form,input,button', documento.body).forEach((nodo) => nodo.remove());
    qsa('*', documento.body).forEach((nodo) => [...nodo.attributes].forEach((atributo) => {
      if (/^on/i.test(atributo.name)) nodo.removeAttribute(atributo.name);
    }));
    const caja = document.createElement('div');
    caja.append(...documento.body.childNodes);
    return caja;
  };

  const vistaPrevia = () => {
    const tarjeta = crear('article', `revision-comunicado__tarjeta${urgente?.checked ? ' revision-comunicado__tarjeta--urgente' : ''}`);
    const etiquetas = crear('div', 'detalle-comunicado__etiquetas');
    if (urgente?.checked) {
      const etiqueta = crear('span', 'etiqueta-urgente etiqueta-urgente--suave');
      etiqueta.append(icono('triangle-alert'), document.createTextNode(' Urgente'));
      etiquetas.append(etiqueta);
    }
    if (categoria?.value) etiquetas.append(crear('span', 'tag', categoria.selectedOptions[0].textContent));
    if (fijado?.checked) etiquetas.append(crear('span', 'tag', 'Fijado'));
    if (etiquetas.childNodes.length) tarjeta.append(etiquetas);
    tarjeta.append(crear('h4', 'revision-comunicado__titulo-vista', titulo.value.trim()));
    const contenido = contenidoSeguro();
    contenido.className = 'contenido-comunicado';
    tarjeta.append(contenido);
    if (textoDelEvento()) {
      const evento = crear('p', 'revision-comunicado__linea');
      evento.append(icono('calendar-range'), document.createTextNode(` Evento: ${textoDelEvento()}`));
      tarjeta.append(evento);
    }
    const nombres = [
      ...qsa('[data-adjunto-previo]:checked', formulario).map((casilla) => qs('.archivo-previo__nombre', casilla.closest('label'))?.textContent || ''),
      ...archivos.map(({ archivo }) => archivo.name),
    ].filter(Boolean);
    if (nombres.length) {
      const linea = crear('p', 'revision-comunicado__linea');
      linea.append(icono('paperclip'), document.createTextNode(` ${nombres.join(' · ')}`));
      tarjeta.append(linea);
    }
    const tipo = respuestaElegida();
    if (tipo) {
      const caja = crear('div', 'respuesta-comunicado');
      const pregunta = tipo === 'ENTERADO' ? 'Confirma que lo leíste' : (campoPregunta.value.trim() || '¿Das tu autorización?');
      caja.append(crear('p', 'respuesta-comunicado__titulo', pregunta));
      const botones = crear('div', 'respuesta-comunicado__botones');
      const opciones = tipo === 'ENTERADO' ? ['Enterado'] : (tipo === 'AUTORIZACION' ? ['Sí, autorizo', 'No autorizo'] : opcionesEscritas());
      opciones.forEach((texto) => {
        const boton = crear('button', 'btn btn--sm', texto);
        boton.type = 'button';
        boton.disabled = true;
        botones.append(boton);
      });
      caja.append(botones);
      tarjeta.append(caja);
    }
    return tarjeta;
  };

  const mostrarRevision = () => {
    revisando = true;
    const n = total(confirmado);
    const partes = [`Se enviará a ${n} ${n === 1 ? 'persona' : 'personas'}: ${resumenDe(confirmado)}.`];
    partes.push(programado() ? `Se publicará el ${fechaLegible(publicarFecha.value, publicarHora.value)}: hasta entonces nadie lo ve.` : 'Se publicará en cuanto lo envíes.');
    if (urgente?.checked) partes.push('Va como urgente.');
    if (fecha.value) partes.push(`Dejará de mostrarse el ${fechaLegible(fecha.value, hora.value || '23:59')}.`);
    revisionResumen.textContent = partes.join(' ');
    revisionVista.replaceChildren(vistaPrevia());
    pasoEditar.hidden = true;
    pasoRevisar.hidden = false;
    volverAEditar.hidden = false;
    textoEnviar.textContent = programado() ? 'Programar envío' : 'Enviar ahora';
    formulario.closest('.crear-comunicado__cuerpo, .modal__panel')?.scrollTo?.({ top: 0 });
    revisionTitulo.focus();
  };

  const ocultarRevision = (enfocar = true) => {
    revisando = false;
    pasoEditar.hidden = false;
    pasoRevisar.hidden = true;
    volverAEditar.hidden = true;
    textoEnviar.textContent = TEXTO_DEL_BOTON;
    if (enfocar) titulo.focus();
  };
  volverAEditar?.addEventListener('click', () => ocultarRevision());

  /* =============================================================== Enviar */
  let enviando = false;
  const ocupado = (valor) => {
    enviando = valor;
    enviar.disabled = valor;
    volverAEditar.disabled = valor;
    enviar.classList.toggle('is-loading', valor);
    if (valor) textoEnviar.textContent = editando ? 'Guardando…' : 'Enviando…';
    formulario.setAttribute('aria-busy', String(valor));
  };

  formulario.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    if (enviando) return;   /* doble clic o Intro repetido */
    if (!revisando) {
      if (!validar()) {
        enfocarPrimerError();
        return;
      }
      if (!editando) {   /* primero la revisión; el segundo clic envía */
        mostrarRevision();
        return;
      }
    }
    if (editor) {
      descripcion.value = editor.vacio() ? '' : editor.texto();
      valorHtml.value = editor.vacio() ? '' : editor.html();
    }
    const datosDelFormulario = new FormData(formulario);
    datosDelFormulario.delete('archivos');
    archivos.forEach(({ archivo }) => datosDelFormulario.append('archivos', archivo, archivo.name));
    ocupado(true);
    try {
      const respuesta = await fetch(formulario.action, {
        method: 'POST', body: datosDelFormulario, credentials: 'same-origin',
        headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      });
      const contenido = await respuesta.json().catch(() => null);
      if (respuesta.ok && contenido?.redirect) {
        modificado = false;
        window.location.assign(contenido.redirect);
        return;
      }
      ocupado(false);
      ocultarRevision(false);
      const lista = contenido?.errores || { __all__: ['No se pudo enviar el comunicado. Inténtalo de nuevo.'] };
      CAMPOS_CON_ERROR.forEach((nombre) => ponerError(nombre, lista[nombre]));
      ponerErroresGenerales([...(lista.__all__ || []), ...(lista.clave_envio || []), ...(lista.categoria || [])]);
      if (respuesta.status === 403 && !lista.__all__) ponerErroresGenerales(['No tienes permiso para enviar comunicados.']);
      enfocarPrimerError();
    } catch (error) {
      ocupado(false);
      ocultarRevision(false);
      ponerErroresGenerales(['No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo: no se enviará dos veces.']);
      enfocarPrimerError();
    }
  });

  /* Todo lo de arriba marcó «modificado» al preparar lo que ya venía escrito */
  modificado = false;

  /* =============================================================== La ventana «Crear comunicado» */
  const ventana = qs('[data-crear-modal]');
  if (!ventana || typeof ventana.showModal !== 'function') {
    window.addEventListener('beforeunload', (evento) => {
      if (modificado && !enviando) evento.preventDefault();
    });
    qs('[data-formulario-salir]', formulario)?.addEventListener('click', () => { modificado = false; });
    return;
  }
  const aviso = qs('[data-crear-confirmar]', ventana);
  const raizDocumento = document.documentElement;
  let abridor = null;

  const reiniciar = () => {
    formulario.reset();
    editor?.vaciar();
    archivos.splice(0).forEach(({ url }) => url && URL.revokeObjectURL(url));
    actualizarArchivos();
    TIPOS.forEach((tipo) => confirmado[tipo].clear());
    escribirSeleccion();
    CAMPOS_CON_ERROR.forEach(limpiarError);
    ponerErroresGenerales([]);
    ocultarRevision(false);
    qsa('.opciones-encuesta__fila', listaOpciones || formulario).slice(2).forEach((fila) => fila.remove());
    qsa('details.opcion-comunicado', formulario).forEach((seccion) => seccion.removeAttribute('open'));
    pintarRespuesta();
    resumirOpciones();
    contarDescripcion();
    if (window.crypto?.randomUUID) clave.value = window.crypto.randomUUID();
    modificado = false;
  };

  const abrirVentana = (desde) => {
    abridor = desde;
    aviso.hidden = true;
    ventana.showModal();
    raizDocumento.classList.add('is-scroll-locked');
    window.setTimeout(() => titulo.focus(), 30);
  };

  const pedirCierre = () => {
    if (enviando) return;
    if (!modificado) {
      ventana.close();
      return;
    }
    aviso.hidden = false;
    qs('[data-crear-seguir]', aviso).focus();
  };

  document.addEventListener('click', (evento) => {
    const enlace = evento.target.closest('[data-crear-comunicado]');
    if (!enlace || evento.button !== 0 || evento.metaKey || evento.ctrlKey || evento.shiftKey || evento.altKey) return;
    evento.preventDefault();
    abrirVentana(enlace);
  });
  qs('[data-crear-cerrar]', ventana).addEventListener('click', pedirCierre);
  qs('[data-formulario-cancelar]', formulario)?.addEventListener('click', pedirCierre);
  ventana.addEventListener('cancel', (evento) => {
    evento.preventDefault();
    if (!aviso.hidden) {
      aviso.hidden = true;
      return;
    }
    pedirCierre();
  });
  ventana.addEventListener('click', (evento) => {
    if (evento.target === ventana) pedirCierre();   /* clic en el velo */
  });
  qs('[data-crear-seguir]', aviso).addEventListener('click', () => {
    aviso.hidden = true;
    titulo.focus();
  });
  qs('[data-crear-descartar]', aviso).addEventListener('click', () => {
    reiniciar();
    ventana.close();
  });
  ventana.addEventListener('close', () => {
    aviso.hidden = true;
    if (!qs('dialog[open]')) raizDocumento.classList.remove('is-scroll-locked');
    abridor?.focus();
  });
  window.addEventListener('beforeunload', (evento) => {
    if (ventana.open && modificado && !enviando) evento.preventDefault();
  });
})();
