/* Matriz de asistencia por materia (templates/asistencias/_matriz.html): la del docente (docente.html) y la de la
   administración (materias.html), que además elige el grupo y justifica faltas.

   - La matriz es una sola parada del tabulador: las flechas mueven el foco entre celdas (Inicio y Fin van al primer y
     último día; con Ctrl, a la primera y última fila) y Enter o Espacio abre el menú de estados de una celda editable.
     En el menú: flechas, P / F / R para elegir directo y Escape para cerrar. Falta y retardo piden la observación
     (por qué) antes de guardar: Enter la guarda, Mayús+Enter es nueva línea, «Volver» regresa a los estados.
   - Al elegir un estado se guarda al momento, una solicitud por celda a la vez. Si el servidor no lo acepta (o no hay
     conexión) la celda vuelve a lo último guardado y se avisa por qué. El servidor valida todo de nuevo.
   - El buscador filtra estudiantes por nombre; al cargar, la columna de hoy queda a la vista.
   - Las fechas que se ven (por omisión el mes en curso) se eligen arriba, siempre dentro del periodo.
   - Solo en la administración: una falta [data-justificable] ofrece «Justificar falta» (J) y una J con su justificación
     [data-justificacion] se abre al tocarla. Esto lo resuelve asistencia-justificar.js, que escucha los eventos
     «asistencia:justificar» y «asistencia:ver-justificacion» de la matriz (detail: la celda y cómo repintarla). */
(() => {
  const aviso = document.querySelector('[data-aviso]');
  let ocultarAviso = null;

  const avisar = (texto, tipo = 'info') => {
    if (!aviso) return;
    clearTimeout(ocultarAviso);
    if (!texto) {
      aviso.hidden = true;
      return;
    }
    aviso.className = `alert alert--${tipo} asistencia-docente__aviso`;
    const cuerpo = document.createElement('div');
    cuerpo.className = 'alert__body';
    const parrafo = document.createElement('p');
    parrafo.textContent = texto;
    cuerpo.append(parrafo);
    aviso.replaceChildren(cuerpo);
    aviso.hidden = false;
    if (tipo === 'success') ocultarAviso = setTimeout(() => { aviso.hidden = true; }, 5000);
  };

  /* Filtros. Al cambiar de materia se envía solo y sin fechas (la otra materia abre en su mes en curso, y su periodo
     puede ser otro); las fechas se aplican con «Ver», y antes se revisa que el inicio no vaya después del fin. */
  const filtros = document.querySelector('[data-filtros-docente]');
  const selector = filtros?.querySelector('[data-elegir-materia]');
  selector?.addEventListener('change', () => {
    filtros.querySelectorAll('input[type="date"]').forEach((campo) => campo.remove());
    avisar(`Cargando la asistencia de ${selector.selectedOptions[0]?.textContent.trim() || 'la materia'}…`);
    filtros.requestSubmit();
  });
  /* Administración: otro grupo abre en su primera materia (la materia elegida no se envía) */
  const selectorGrupo = filtros?.querySelector('[data-elegir-grupo]');
  selectorGrupo?.addEventListener('change', () => {
    filtros.querySelectorAll('input[type="date"]').forEach((campo) => campo.remove());
    if (selector) selector.disabled = true;
    avisar(`Cargando las materias de ${selectorGrupo.selectedOptions[0]?.textContent.trim() || 'el grupo'}…`);
    filtros.requestSubmit();
  });
  filtros?.addEventListener('submit', (evento) => {
    const desde = filtros.elements.desde?.value;
    const hasta = filtros.elements.hasta?.value;
    if (desde && hasta && desde > hasta) {
      evento.preventDefault();
      avisar('La fecha de inicio va después de la de fin: corrígela para ver ese rango.', 'error');
      filtros.elements.desde.focus();
    }
  });

  const raiz = document.querySelector('[data-asistencia-docente]');
  if (!raiz) return;

  const marco = raiz.querySelector('[data-marco]');
  const tabla = raiz.querySelector('table');
  const cuerpo = tabla.tBodies[0];
  const urlGuardar = raiz.dataset.guardar;
  const token = raiz.querySelector('input[name="csrfmiddlewaretoken"]')?.value || '';
  const encabezados = [...tabla.querySelectorAll('thead th[data-fecha]')];
  const menu = document.querySelector('[data-menu-asistencia]');
  const tituloMenu = menu?.querySelector('[data-menu-titulo]');
  const opciones = menu ? [...menu.querySelectorAll('[data-estado]')] : [];
  const justificar = menu?.querySelector('[data-justificar]');   // solo en la administración
  const separador = menu?.querySelector('[data-justificar-separador]');
  const visibles = () => [...opciones, justificar].filter((opcion) => opcion && !opcion.hidden);
  const pendientes = new WeakSet();

  const filasVisibles = () => [...cuerpo.rows].filter((fila) => !fila.hidden);
  const celdasDe = (fila) => [...fila.querySelectorAll('.indicador-asistencia')];
  const posicion = (boton) => {
    const celda = boton.parentElement;
    return { fila: celda.parentElement, columna: celda.cellIndex - 1 };
  };
  const nombreDe = (fila) => fila.querySelector('th').textContent.trim();
  const claseDe = (boton) => (boton.className.match(/indicador-asistencia--([a-z]+)/) || [])[1] || 'nada';
  const justificacionDe = (boton) => {
    try {
      return boton.dataset.justificacion ? JSON.parse(boton.dataset.justificacion) : null;
    } catch (error) {
      return null;
    }
  };

  /* La celda para asistencia-justificar.js: quién, qué día, su versión y cómo repintarla con lo que responda el servidor */
  const avisarDeLaCelda = (evento, boton) => {
    const { fila, columna } = posicion(boton);
    raiz.dispatchEvent(new CustomEvent(evento, {
      detail: {
        boton,
        alumno: nombreDe(fila),
        inscripcion: fila.dataset.inscripcion,
        fecha: encabezados[columna].dataset.fecha,
        titulo: encabezados[columna].dataset.titulo,
        version: boton.dataset.version || '',
        observaciones: boton.dataset.observaciones || '',
        justificacion: justificacionDe(boton),
        pintar: (datos) => pintar(boton, datos),
        avisar,
        ocupada: (si) => {
          if (si) {
            pendientes.add(boton);
          } else {
            pendientes.delete(boton);
          }
          boton.classList.toggle('is-guardando', si);
          if (si) {
            boton.setAttribute('aria-busy', 'true');
          } else {
            boton.removeAttribute('aria-busy');
          }
        },
      },
    }));
  };

  /* --- Foco itinerante: una sola celda con tabindex 0 ------------------------------------------------- */
  let activo = null;
  const activar = (boton, enfocar = true) => {
    if (!boton) return;
    if (activo && activo !== boton) activo.tabIndex = -1;
    activo = boton;
    boton.tabIndex = 0;
    if (enfocar) boton.focus();
  };

  const columnaDeHoy = encabezados.findIndex((th) => th.classList.contains('is-hoy'));
  const primeraFila = filasVisibles()[0];
  if (primeraFila) activar(celdasDe(primeraFila)[Math.max(columnaDeHoy, 0)], false);

  /* La columna de hoy, a la vista (a la derecha de la columna fija de nombres) */
  if (columnaDeHoy >= 0) {
    const th = encabezados[columnaDeHoy];
    const fija = tabla.querySelector('thead th')?.offsetWidth || 0;
    marco.scrollLeft = Math.max(0, th.offsetLeft - fija - (marco.clientWidth - fija) / 2 + th.offsetWidth / 2);
  }

  /* Lo que dice un lector de pantalla al llegar a una celda: estudiante, día y estado */
  tabla.addEventListener('focusin', (evento) => {
    const boton = evento.target.closest('.indicador-asistencia');
    if (!boton) return;
    const { fila, columna } = posicion(boton);
    boton.setAttribute('aria-label', `${nombreDe(fila)}, ${encabezados[columna].dataset.titulo}: ${boton.dataset.tooltip}`);
    if (activo !== boton) activar(boton, false);
  });

  tabla.addEventListener('keydown', (evento) => {
    const boton = evento.target.closest('.indicador-asistencia');
    if (!boton) return;
    const filas = filasVisibles();
    const { fila, columna } = posicion(boton);
    let renglon = filas.indexOf(fila);
    let columnaNueva = columna;
    const ultima = encabezados.length - 1;
    switch (evento.key) {
      case 'ArrowRight': columnaNueva = Math.min(columna + 1, ultima); break;
      case 'ArrowLeft': columnaNueva = Math.max(columna - 1, 0); break;
      case 'ArrowDown': renglon = Math.min(renglon + 1, filas.length - 1); break;
      case 'ArrowUp': renglon = Math.max(renglon - 1, 0); break;
      case 'Home': columnaNueva = 0; if (evento.ctrlKey) renglon = 0; break;
      case 'End': columnaNueva = ultima; if (evento.ctrlKey) renglon = filas.length - 1; break;
      case 'Enter':
      case ' ':
        evento.preventDefault();
        abrir(boton);
        return;
      default:
        return;
    }
    evento.preventDefault();
    activar(celdasDe(filas[renglon])[columnaNueva]);
  });

  tabla.addEventListener('click', (evento) => {
    const boton = evento.target.closest('.indicador-asistencia');
    if (!boton) return;
    activar(boton);
    abrir(boton);
  });

  /* --- Ventana de la celda: primero el estado; en falta o retardo, la observación con el porqué -------- */
  const pasoOpciones = menu?.querySelector('[data-menu-opciones]');
  const pasoObservacion = menu?.querySelector('[data-menu-observacion]');
  const texto = menu?.querySelector('[data-observacion-texto]');
  const etiqueta = menu?.querySelector('[data-observacion-etiqueta]');
  const cuenta = menu?.querySelector('[data-observacion-cuenta]');
  const errorObservacion = menu?.querySelector('[data-observacion-error]');
  const indicadorElegido = menu?.querySelector('[data-observacion-indicador]');
  const estadoElegido = menu?.querySelector('[data-observacion-estado]');
  const volver = menu?.querySelector('[data-observacion-volver]');
  const MINIMO = 3;
  const PIDEN_OBSERVACION = new Set(['FALTA', 'RETARDO']);
  let celdaDelMenu = null;
  let opcionElegida = null;

  const escribiendo = () => Boolean(pasoObservacion && !pasoObservacion.hidden);

  const colocar = (boton) => {
    const celda = boton.getBoundingClientRect();
    const caja = menu.getBoundingClientRect();
    let arriba = celda.bottom + 6;
    if (arriba + caja.height > window.innerHeight - 8) arriba = Math.max(8, celda.top - caja.height - 6);
    const izquierda = Math.max(8, Math.min(celda.left + celda.width / 2 - caja.width / 2, window.innerWidth - caja.width - 8));
    menu.style.top = `${arriba}px`;
    menu.style.left = `${izquierda}px`;
  };

  const cerrar = (devolverFoco = true) => {
    if (!menu || menu.hidden) return;
    menu.hidden = true;
    const boton = celdaDelMenu;
    celdaDelMenu = null;
    opcionElegida = null;
    if (devolverFoco && boton) boton.focus();
  };

  const mostrarOpciones = () => {
    pasoObservacion.hidden = true;
    pasoOpciones.hidden = false;
  };

  function abrir(boton) {
    if (pendientes.has(boton)) return;
    if (boton.hasAttribute('data-justificacion')) {   // una J: su justificación y su comprobante (administración)
      avisarDeLaCelda('asistencia:ver-justificacion', boton);
      return;
    }
    const editable = boton.hasAttribute('data-editable');
    const justificable = Boolean(justificar) && boton.hasAttribute('data-justificable');
    if (!editable && !justificable) {
      avisar(boton.dataset.tooltip || 'Esta celda no se puede cambiar.');
      return;
    }
    if (!menu) return;
    celdaDelMenu = boton;
    const { fila, columna } = posicion(boton);
    tituloMenu.textContent = `${nombreDe(fila)} · ${encabezados[columna].dataset.titulo}`;
    const letra = boton.textContent.trim();
    /* Los estados, si la celda se puede cambiar; «Justificar falta», si es una falta que se puede justificar */
    opciones.forEach((opcion) => {
      opcion.hidden = !editable;
      opcion.setAttribute('aria-checked', String(opcion.dataset.letra === letra));
    });
    if (justificar) {
      justificar.hidden = !justificable;
      if (separador) separador.hidden = !(editable && justificable);
    }
    mostrarOpciones();
    menu.hidden = false;
    colocar(boton);
    const items = visibles();
    (items.find((opcion) => opcion.dataset.estado && opcion.dataset.letra === letra) || items[0]).focus();
  }

  const actualizarCuenta = () => {
    cuenta.textContent = String(texto.value.length);
  };

  const marcarError = (mensaje) => {
    errorObservacion.textContent = mensaje;
    errorObservacion.hidden = !mensaje;
    if (mensaje) {
      texto.setAttribute('aria-invalid', 'true');
    } else {
      texto.removeAttribute('aria-invalid');
    }
  };

  /* Falta o retardo: se pide el porqué (con la observación que ya tenía, si es el mismo estado) */
  const pedirObservacion = (opcion) => {
    opcionElegida = opcion;
    const falta = opcion.dataset.estado === 'FALTA';
    indicadorElegido.className = `indicador-asistencia indicador-asistencia--${falta ? 'falta' : 'retardo'}`;
    indicadorElegido.textContent = opcion.dataset.letra;
    estadoElegido.textContent = falta ? 'Falta' : 'Retardo';
    etiqueta.textContent = falta ? '¿Por qué la falta?' : '¿Por qué el retardo?';
    texto.placeholder = falta ? 'Ej.: no se presentó a la clase' : 'Ej.: llegó 15 minutos tarde';
    const mismoEstado = celdaDelMenu.textContent.trim() === opcion.dataset.letra;
    texto.value = mismoEstado ? (celdaDelMenu.dataset.observaciones || '') : '';
    actualizarCuenta();
    marcarError('');
    pasoOpciones.hidden = true;
    pasoObservacion.hidden = false;
    colocar(celdaDelMenu);
    texto.focus();
  };

  const elegir = (opcion) => {
    if (!celdaDelMenu) return;
    if (opcion === justificar) {
      /* El foco vuelve antes a la celda: al cerrarse la ventana «Justificar falta» (asistencia-justificar.js), el
         navegador lo regresa ahí */
      const boton = celdaDelMenu;
      cerrar();
      avisarDeLaCelda('asistencia:justificar', boton);
      return;
    }
    if (PIDEN_OBSERVACION.has(opcion.dataset.estado)) {
      pedirObservacion(opcion);
      return;
    }
    const boton = celdaDelMenu;
    cerrar();
    guardar(boton, opcion.dataset.estado, opcion.dataset.letra, '');
  };

  texto?.addEventListener('input', () => {
    actualizarCuenta();
    if (!errorObservacion.hidden && texto.value.trim().length >= MINIMO) marcarError('');
  });

  volver?.addEventListener('click', () => {
    mostrarOpciones();
    colocar(celdaDelMenu);
    opcionElegida?.focus();
  });

  pasoObservacion?.addEventListener('submit', (evento) => {
    evento.preventDefault();
    const observacion = texto.value.trim().replace(/\s+/g, ' ');
    if (observacion.length < MINIMO) {
      const que = opcionElegida.dataset.estado === 'FALTA' ? 'la falta' : 'el retardo';
      marcarError(`Escribe por qué ${que} (al menos ${MINIMO} letras).`);
      texto.focus();
      return;
    }
    const boton = celdaDelMenu;
    const opcion = opcionElegida;
    cerrar();
    guardar(boton, opcion.dataset.estado, opcion.dataset.letra, observacion);
  });

  menu?.addEventListener('keydown', (evento) => {
    if (escribiendo()) {
      if (evento.key === 'Escape') {
        evento.preventDefault();
        cerrar();
      } else if (evento.key === 'Enter' && !evento.shiftKey && evento.target === texto) {
        evento.preventDefault();
        pasoObservacion.requestSubmit();
      } else if (evento.key === 'Tab') {
        /* El foco se queda dentro de la ventana mientras se escribe */
        const enfocables = [texto, ...pasoObservacion.querySelectorAll('button')];
        const indice = enfocables.indexOf(document.activeElement);
        evento.preventDefault();
        const siguiente = evento.shiftKey ? indice - 1 : indice + 1;
        enfocables[(siguiente + enfocables.length) % enfocables.length].focus();
      }
      return;
    }
    const items = visibles();
    const indice = items.indexOf(document.activeElement);
    if (evento.key === 'ArrowDown') {
      evento.preventDefault();
      items[(indice + 1) % items.length].focus();
    } else if (evento.key === 'ArrowUp') {
      evento.preventDefault();
      items[(indice - 1 + items.length) % items.length].focus();
    } else if (evento.key === 'Escape' || evento.key === 'Tab') {
      evento.preventDefault();
      cerrar();
    } else {
      const atajo = items.find((opcion) => opcion.dataset.letra === evento.key.toUpperCase());
      if (atajo) {
        evento.preventDefault();
        elegir(atajo);
      }
    }
  });

  pasoOpciones?.addEventListener('click', (evento) => {
    const opcion = evento.target.closest('[data-estado], [data-justificar]');
    if (opcion) elegir(opcion);
  });

  document.addEventListener('pointerdown', (evento) => {
    if (menu && !menu.hidden && !menu.contains(evento.target) && evento.target !== celdaDelMenu) cerrar(false);
  });
  /* Al desplazarse: mientras se escribe, la ventana sigue a su celda; si no, se cierra */
  const alMover = () => {
    if (escribiendo() && celdaDelMenu) {
      colocar(celdaDelMenu);
    } else {
      cerrar(false);
    }
  };
  marco.addEventListener('scroll', alMover, { passive: true });
  window.addEventListener('resize', alMover);

  /* --- Guardar una celda ------------------------------------------------------------------------------- */
  const pintar = (boton, datos) => {
    boton.textContent = datos.letra;
    boton.className = `indicador-asistencia indicador-asistencia--${datos.clase}`;
    boton.dataset.tooltip = datos.nombre;
    boton.dataset.version = datos.version || '';
    if (datos.observaciones) {
      boton.dataset.observaciones = datos.observaciones;
    } else {
      delete boton.dataset.observaciones;
    }
    if (datos.editable) {
      boton.setAttribute('data-editable', '');
      boton.removeAttribute('aria-disabled');
    } else {
      boton.removeAttribute('data-editable');
      boton.setAttribute('aria-disabled', 'true');
    }
    /* Administración: si la falta se puede justificar y, en una J, su justificación */
    boton.toggleAttribute('data-justificable', Boolean(datos.justificable));
    if ('justificacion' in datos) {
      if (datos.justificacion) {
        boton.dataset.justificacion = JSON.stringify(datos.justificacion);
      } else {
        delete boton.dataset.justificacion;
      }
    }
    if (boton === activo) boton.tabIndex = 0;
  };

  async function guardar(boton, estado, letra, observaciones) {
    if (pendientes.has(boton)) return;
    if (boton.textContent.trim() === letra && (boton.dataset.observaciones || '') === observaciones) return;   // nada cambió
    const { fila, columna } = posicion(boton);
    const anterior = {
      letra: boton.textContent, clase: claseDe(boton), nombre: boton.dataset.tooltip, version: boton.dataset.version,
      editable: boton.hasAttribute('data-editable'), observaciones: boton.dataset.observaciones || '',
      justificable: boton.hasAttribute('data-justificable'), justificacion: justificacionDe(boton),
    };
    const datos = new FormData();
    datos.append('csrfmiddlewaretoken', token);
    datos.append('inscripcion', fila.dataset.inscripcion);
    datos.append('fecha', encabezados[columna].dataset.fecha);
    datos.append('estado', estado);
    datos.append('observaciones', observaciones);
    datos.append('version', boton.dataset.version || '');

    pendientes.add(boton);
    boton.classList.add('is-guardando');
    boton.setAttribute('aria-busy', 'true');
    avisar('Guardando…');
    try {
      const respuesta = await fetch(urlGuardar, {
        method: 'POST', body: datos, credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });
      const json = await respuesta.json().catch(() => null);
      if (!json) throw new Error('sin respuesta');
      pintar(boton, json.letra !== undefined ? json : anterior);   // lo que de verdad quedó guardado
      if (json.ok) {
        avisar(json.mensaje, 'success');
      } else {
        avisar(`No se guardó el cambio: ${json.mensaje}`, 'error');
      }
    } catch (error) {
      pintar(boton, anterior);
      avisar('No se guardó el cambio: revisa tu conexión e inténtalo de nuevo.', 'error');
    } finally {
      pendientes.delete(boton);
      boton.classList.remove('is-guardando');
      boton.removeAttribute('aria-busy');
    }
  }

  /* --- Buscar estudiante ------------------------------------------------------------------------------- */
  const buscar = document.querySelector('[data-buscar-estudiante]');
  /* Está dentro del formulario de materia y fechas: Enter no lo envía, solo filtra */
  buscar?.addEventListener('keydown', (evento) => {
    if (evento.key === 'Enter') evento.preventDefault();
  });
  const normalizar = (texto) => texto.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  buscar?.addEventListener('input', () => {
    const consulta = normalizar(buscar.value.trim());
    let visibles = 0;
    [...cuerpo.rows].forEach((fila) => {
      const coincide = !consulta || normalizar(fila.dataset.nombre).includes(consulta);
      fila.hidden = !coincide;
      if (coincide) visibles += 1;
    });
    if (activo?.closest('tr').hidden) {
      const fila = filasVisibles()[0];
      if (fila) activar(celdasDe(fila)[posicion(activo).columna], false);
    }
    avisar(visibles ? '' : 'Ningún estudiante coincide con la búsqueda.');
  });
})();
