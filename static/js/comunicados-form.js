/* CISAHUAYO · crear un comunicado y elegir a sus destinatarios
   (templates/comunicados/_ventana_crear.html, _formulario.html y _selector.html)

   Ventana «Crear comunicado»
   - Se abre desde «Crear comunicado» (sin JavaScript, o con Ctrl/Cmd+clic, el enlace lleva a su página). Cerrarla con
     algo escrito pide confirmar; abrir y cerrar el selector de destinatarios no toca lo escrito.
   - Antes de enviar revisa título, descripción, al menos un destinatario, que la expiración sea futura y los archivos
     (hasta 5, del tipo y tamaño que acepta el sistema). El servidor vuelve a validar todo.
   - Envía con fetch: si falla, la ventana sigue abierta con todo y el aviso del problema. El botón se bloquea mientras
     se envía y la clave de envío del formulario hace que un reintento no cree un segundo comunicado.

   Selector de destinatarios
   - Pide al servidor las personas del alcance de quien envía (comunicados:destinatarios) la primera vez que se abre.
   - Las selecciones de cada pestaña (Tutores, Estudiantes, Profesores) son independientes y se conservan al cambiar de
     pestaña, de nodo o de búsqueda. Marcar un nodo del árbol agrega a las personas de ese nodo en la pestaña activa (no
     en las otras) y muestra quiénes son; desmarcarlo las quita. Cada persona se puede desmarcar suelta.
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
  const ayudantes = window.CISAHUAYO?.forms;
  const sinAcentos = (texto) => (texto || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  const crear = (etiqueta, clase, texto) => {
    const nodo = document.createElement(etiqueta);
    if (clase) nodo.className = clase;
    if (texto !== undefined) nodo.textContent = texto;
    return nodo;
  };

  const TIPOS = ['tutores', 'estudiantes', 'profesores'];
  const NOMBRES = { tutores: ['tutor', 'tutores'], estudiantes: ['estudiante', 'estudiantes'], profesores: ['profesor', 'profesores'] };
  const ROTULO = { tutores: 'Tutores', estudiantes: 'Estudiantes', profesores: 'Profesores' };
  const cantidad = (n, tipo) => `${n} ${NOMBRES[tipo][n === 1 ? 0 : 1]}`;
  const LIMITE_DE_FILAS = 200;

  /* =============================================================== Errores en pantalla */
  const errores = qs('[data-errores-generales]', formulario);
  const textoDeErrores = qs('[data-errores-texto]', formulario);
  const campo = (nombre) => qs(`[data-campo="${nombre}"]`, formulario);

  const limpiarError = (nombre) => {
    const contenedor = campo(nombre);
    if (!contenedor) return;
    qsa('.field__error', contenedor).forEach((nodo) => nodo.remove());
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
    lista.forEach((mensaje) => contenedor.append(crear('p', 'field__error', mensaje)));
    qsa('input:not([type="hidden"]), textarea, button.campo-fecha', contenedor).forEach((control) => control.setAttribute('aria-invalid', 'true'));
  };

  const ponerErroresGenerales = (mensajes) => {
    const lista = [].concat(mensajes || []).filter(Boolean);
    textoDeErrores.replaceChildren(...lista.map((mensaje) => crear('p', '', mensaje)));
    errores.hidden = !lista.length;
  };

  const enfocarPrimerError = () => {
    const primero = qs('.is-invalid', formulario);
    const control = primero && (qs('input:not([type="hidden"]):not([hidden]), textarea, button', primero));
    if (!errores.hidden) errores.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    control?.focus();
  };

  /* =============================================================== Campos */
  const titulo = qs('[name="titulo"]', formulario);
  const descripcion = qs('[name="descripcion"]', formulario);
  const cuenta = qs('[data-descripcion-cuenta]', formulario);
  const fecha = qs('[name="expira_fecha"]', formulario);
  const hora = qs('[name="expira_hora"]', formulario);
  const valorDestinatarios = qs('[data-destinatarios-valor]', formulario);
  const clave = qs('[data-clave-envio]', formulario);
  const enviar = qs('[data-formulario-enviar]', formulario);
  const textoEnviar = qs('[data-formulario-enviar-texto]', formulario);
  let modificado = false;

  const contarDescripcion = () => {
    if (!cuenta) return;
    const maximo = Number(cuenta.dataset.maximo) || 5000;
    const usados = descripcion.value.length;
    cuenta.textContent = usados ? `${usados} / ${maximo} caracteres` : `Hasta ${maximo} caracteres`;
    cuenta.classList.toggle('is-limite', usados > maximo * 0.9);
  };
  descripcion?.addEventListener('input', contarDescripcion);
  contarDescripcion();

  formulario.addEventListener('input', (evento) => {
    modificado = true;
    const contenedor = evento.target.closest('[data-campo]');
    if (contenedor && evento.target.value) limpiarError(contenedor.dataset.campo);
  });
  formulario.addEventListener('change', (evento) => {
    modificado = true;
    if (evento.target === fecha || evento.target === hora) limpiarError('expira');
  });

  /* =============================================================== Archivos */
  const entradaArchivos = qs('[data-archivos-entrada]', formulario);
  const zona = qs('[data-zona-archivos]', formulario);
  const listaArchivos = qs('[data-archivos-lista]', formulario);
  const cuentaArchivos = qs('[data-archivos-cuenta]', formulario);
  const MAXIMO_ARCHIVOS = Number(formulario.dataset.maximoArchivos) || 5;
  const MAXIMO_MB = Number(formulario.dataset.maximoMb) || 5;
  const EXTENSIONES = (formulario.dataset.acepta || '').split(',').map((e) => e.trim().replace(/^\./, '').toLowerCase()).filter(Boolean);
  const archivos = [];   /* { archivo, url } válidos, en orden */

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
    cuentaArchivos.textContent = String(archivos.length);
    const lleno = archivos.length >= MAXIMO_ARCHIVOS;
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
      if (archivos.length >= MAXIMO_ARCHIVOS) {
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
  actualizarArchivos();

  /* =============================================================== Selector de destinatarios */
  const selector = qs('[data-selector]');
  const panel = qs('.selector', selector || document);
  const abrirSelector = qs('[data-selector-abrir]', formulario);
  const resumenFormulario = qs('[data-destinatarios-resumen]', formulario);
  const filaDestinatarios = campo('destinatarios');
  const resumenInicial = resumenFormulario?.textContent || '';
  const confirmado = { tutores: new Set(), estudiantes: new Set(), profesores: new Set() };
  let borrador = null;
  let datos = null;
  let indices = null;
  let pestana = 'tutores';
  let enfocado = null;   /* clave del nodo cuyas personas se ven en la lista ('n:PRIMARIA', 'g:3', 'gr:7', 'm:31') */
  let limite = LIMITE_DE_FILAS;
  let cargando = null;

  try {
    const previo = valorDestinatarios.value ? JSON.parse(valorDestinatarios.value) : null;
    if (previo) TIPOS.forEach((tipo) => (previo[tipo] || []).forEach((id) => confirmado[tipo].add(Number(id))));
  } catch (error) {
    /* sin selección previa */
  }

  const total = (seleccion) => TIPOS.reduce((suma, tipo) => suma + seleccion[tipo].size, 0);
  const resumenDe = (seleccion, prefijo = '') => {
    if (!total(seleccion)) return 'Nadie seleccionado todavía';
    return `${prefijo}${TIPOS.filter((tipo) => seleccion[tipo].size).map((tipo) => cantidad(seleccion[tipo].size, tipo)).join(' · ')}`;
  };

  const escribirSeleccion = () => {
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

  /* --- Datos e índices ----------------------------------------------------------------------------------------- */
  const indexar = () => {
    const porId = { tutores: new Map(), estudiantes: new Map(), profesores: new Map() };
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
    if (nodo) {
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

  /* --- Elementos del selector ------------------------------------------------------------------------------------ */
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

  /* --- Árbol ------------------------------------------------------------------------------------------------------ */
  const CHIP = { nivel: 'school', grado: 'layers', grupo: 'users', materia: 'book-open' };
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
          const abierto = nodo.tipo === 'nivel' || (nodo.tipo === 'grado' && cuantos <= 12) || (nodo.tipo === 'grupo' && cuantos <= 4);
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
        const etiqueta = crear('button', 'arbol__etiqueta', nodo.tipo === 'materia' ? nodo.nombre : nodo.nombre);
        etiqueta.type = 'button';
        etiqueta.dataset.enfocar = nodo.clave;
        const cuenta = crear('span', 'arbol__cuenta');
        fila.append(casilla, chip, etiqueta, cuenta);
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
        filasDeNodo.set(nodo.clave, { li, fila, casilla, cuenta, etiqueta, plegar, sublista, nodo });
        ul.append(li);
      });
      return ul;
    };
    const raices = datos.arbol.map((nivel) => indices.nodos.get(`n:${nivel.clave}`));
    arbol.replaceChildren(raices.length ? rama(raices) : crear('p', 'selector__nada', 'No hay grupos con estudiantes o profesores en el ciclo actual. Busca y marca personas en la lista.'));
  };

  const nombreDelNodo = (nodo) => (nodo.tipo === 'materia' ? `${nodo.nombre} · ${nodo.padre.nombre}` : nodo.nombre);

  const actualizarArbol = () => {
    const elegidos = borrador[pestana];
    let marcadosArriba = 0;
    filasDeNodo.forEach(({ fila, casilla, cuenta, etiqueta, nodo }) => {
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
      cuenta.textContent = String(personas.size);
      cuenta.title = `${cantidad(personas.size, pestana)}${dentro ? ` · ${dentro} seleccionado${dentro === 1 ? '' : 's'}` : ''}`;
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

  /* --- Lista de personas ------------------------------------------------------------------------------------------ */
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
      TIPOS.forEach((tipo, indice) => {
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
      insignia.textContent = borrador[tipo].size ? String(borrador[tipo].size) : '';
      qs(`[data-pestana="${tipo}"]`, selector).setAttribute('aria-label', `${ROTULO[tipo]}${borrador[tipo].size ? `, ${cantidad(borrador[tipo].size, tipo)} seleccionados` : ''}`);
    });
  };

  const refrescar = (reiniciarLista = false) => {
    actualizarArbol();
    pintarLista(reiniciarLista);
    actualizarResumen();
  };

  /* --- Interacción ---------------------------------------------------------------------------------------------- */
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
    refrescar(true);
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

  const elegirPestana = (tipo, enfocar = false) => {
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
  };
  pestanas.forEach((boton) => {
    boton.addEventListener('click', () => elegirPestana(boton.dataset.pestana));
    boton.addEventListener('keydown', (evento) => {
      const paso = { ArrowRight: 1, ArrowLeft: -1 }[evento.key];
      if (!paso) return;
      evento.preventDefault();
      const indice = (TIPOS.indexOf(pestana) + paso + TIPOS.length) % TIPOS.length;
      elegirPestana(TIPOS[indice], true);
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

  /* --- Cargar, abrir, confirmar y cancelar ---------------------------------------------------------------------- */
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
    if (!selector || typeof selector.showModal !== 'function') return;
    borrador = { tutores: new Set(confirmado.tutores), estudiantes: new Set(confirmado.estudiantes), profesores: new Set(confirmado.profesores) };
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

  /* =============================================================== Validar y enviar */
  const validar = () => {
    let bien = true;
    ponerErroresGenerales([]);
    if (!titulo.value.trim()) {
      ponerError('titulo', 'Escribe un título para el comunicado.');
      bien = false;
    }
    if (!descripcion.value.trim()) {
      ponerError('descripcion', 'Escribe la descripción del comunicado.');
      bien = false;
    }
    if (!total(confirmado)) {
      ponerError('destinatarios', 'Elige al menos un destinatario.');
      bien = false;
    }
    if (hora.value && !fecha.value) {
      ponerError('expira', 'Elige también la fecha de expiración (o borra la hora).');
      bien = false;
    } else if (fecha.value) {
      const [anio, mes, dia] = fecha.value.split('-').map(Number);
      const [h, m] = (hora.value || '23:59').split(':').map(Number);
      if (new Date(anio, mes - 1, dia, h, m) <= new Date()) {
        ponerError('expira', 'La fecha de expiración debe ser posterior al momento del envío.');
        bien = false;
      }
    }
    return bien;
  };

  let enviando = false;
  const ocupado = (valor) => {
    enviando = valor;
    enviar.disabled = valor;
    enviar.classList.toggle('is-loading', valor);
    textoEnviar.textContent = valor ? 'Enviando…' : 'Enviar comunicado';
    formulario.setAttribute('aria-busy', String(valor));
  };

  formulario.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    if (enviando) return;   /* doble clic o Enter repetido */
    if (!validar()) {
      enfocarPrimerError();
      return;
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
      const lista = contenido?.errores || { __all__: ['No se pudo enviar el comunicado. Inténtalo de nuevo.'] };
      ['titulo', 'descripcion', 'expira', 'destinatarios', 'archivos'].forEach((nombre) => ponerError(nombre, lista[nombre]));
      ponerErroresGenerales(lista.__all__ || lista.clave_envio || []);
      if (respuesta.status === 403 && !lista.__all__) ponerErroresGenerales(['No tienes permiso para enviar comunicados.']);
      ocupado(false);
      enfocarPrimerError();
    } catch (error) {
      ocupado(false);
      ponerErroresGenerales(['No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo: no se enviará dos veces.']);
      enfocarPrimerError();
    }
  });

  /* =============================================================== La ventana «Crear comunicado» */
  const ventana = qs('[data-crear-modal]');
  if (!ventana || typeof ventana.showModal !== 'function') {
    window.addEventListener('beforeunload', (evento) => {
      if (modificado && !enviando) evento.preventDefault();
    });
    return;
  }
  const aviso = qs('[data-crear-confirmar]', ventana);
  const raizDocumento = document.documentElement;
  let abridor = null;

  const reiniciar = () => {
    formulario.reset();
    archivos.splice(0).forEach(({ url }) => url && URL.revokeObjectURL(url));
    actualizarArchivos();
    TIPOS.forEach((tipo) => confirmado[tipo].clear());
    escribirSeleccion();
    ['titulo', 'descripcion', 'expira', 'destinatarios', 'archivos'].forEach(limpiarError);
    ponerErroresGenerales([]);
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
