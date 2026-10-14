/* CISAHUAYO · conducta (registro, pendientes, reportes, ajustes y las páginas de cada acción).

   - Filtros [data-filtros-conducta]: las listas que dependen de otra solo muestran lo que corresponde (periodos del
     ciclo, grados y catálogos del nivel, grupos del grado, categorías del tipo, motivos de la categoría). El servidor
     aplica igual cualquier combinación.
   - Reportes [data-varios-estudiantes]: elegir uno o varios estudiantes con la búsqueda en vivo.
   - Formularios con [data-confirmar]: piden confirmación en la ventana [data-confirmacion] antes de enviarse.
   - Campos de archivos [data-evidencias]: lista lo elegido con su tamaño y avisa lo que no se aceptará (el servidor
     lo revisa de nuevo).
   - Contacto con la familia: el nombre de «otra persona» solo se pide cuando se elige esa opción.
   Se vuelve a ejecutar cada vez que una de estas páginas se abre en la ventana modal: por eso escucha en los propios
   elementos (nuevos en cada apertura) y no en document. */
(() => {
  'use strict';

  const MB = 1024 * 1024;
  const TIPOS = ['image/jpeg', 'image/png', 'image/webp', 'application/pdf'];
  const peso = (bytes) => (bytes < MB ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / MB).toFixed(1)} MB`);

  /* ------------------------------------------------------------------ Filtros dependientes */
  document.querySelectorAll('[data-filtros-conducta]').forEach((filtros) => {
    if (filtros.dataset.listo) return;
    filtros.dataset.listo = '1';
    const valor = (nombre) => filtros.elements[nombre]?.value || '';

    /* Deja visibles las opciones cuyos data-* coinciden (un criterio vacío no filtra) */
    const limitar = (select, criterios) => {
      if (!select) return;
      [...select.options].forEach((opcion) => {
        if (!opcion.value) return;
        const queda = Object.entries(criterios).every(([clave, buscado]) => !buscado || !opcion.dataset[clave] || opcion.dataset[clave] === buscado);
        opcion.hidden = !queda;
        opcion.disabled = !queda;
      });
      if (select.selectedOptions[0]?.disabled) select.value = '';
    };

    const actualizar = () => {
      const nivel = valor('nivel');
      const tipo = valor('tipo');
      limitar(filtros.elements.periodo, { ciclo: valor('ciclo'), nivel });
      limitar(filtros.elements.grado, { nivel });
      limitar(filtros.elements.grupo, { nivel, grado: valor('grado') });
      limitar(filtros.elements.categoria, { nivel, tipo });
      limitar(filtros.elements.motivo, { nivel, tipo, categoria: valor('categoria') });
      limitar(filtros.elements.medida, { nivel });
    };
    filtros.addEventListener('change', (evento) => {
      if (evento.target.matches('select')) actualizar();
    });
    actualizar();
  });

  /* ------------------------------------------------------------------ Varios estudiantes (reportes) */
  document.querySelectorAll('[data-varios-estudiantes]').forEach((caja) => {
    const { liveSearch, alumnoResult } = window.CISAHUAYO || {};
    if (!liveSearch || caja.dataset.listo) return;
    caja.dataset.listo = '1';
    const entrada = caja.querySelector('[data-varios-input]');
    const lista = caja.querySelector('[data-varios-elegidos]');
    const yaElegido = (id) => lista.querySelector(`input[value="${CSS.escape(String(id))}"]`);

    const agregar = (alumno) => {
      if (yaElegido(alumno.id)) return;
      const item = document.createElement('li');
      item.className = 'conducta-elegido';
      const oculto = document.createElement('input');
      oculto.type = 'hidden';
      oculto.name = 'alumnos';
      oculto.value = alumno.id;
      const nombre = document.createElement('span');
      nombre.textContent = alumno.nombre;
      const quitar = document.createElement('button');
      quitar.type = 'button';
      quitar.className = 'conducta-elegido__quitar';
      quitar.setAttribute('aria-label', `Quitar a ${alumno.nombre}`);
      quitar.dataset.variosQuitar = '';
      quitar.append(window.CISAHUAYO.icon('x'));
      item.append(oculto, nombre, quitar);
      lista.append(item);
    };

    liveSearch({
      input: entrada,
      box: caja.querySelector('[data-varios-resultados]'),
      url: caja.dataset.buscarUrl,
      emptyText: 'No hay estudiantes con ese dato.',
      render: alumnoResult,
      isDisabled: (alumno) => Boolean(yaElegido(alumno.id)),
      onPick(alumno) {
        agregar(alumno);
        entrada.value = '';
        entrada.focus();
      },
    });
    /* Enter en la búsqueda elige un resultado, no envía los filtros */
    entrada.addEventListener('keydown', (evento) => {
      if (evento.key === 'Enter') evento.preventDefault();
    });
    lista.addEventListener('click', (evento) => {
      const boton = evento.target.closest('[data-varios-quitar]');
      if (boton) boton.closest('li').remove();
    });
  });

  /* ------------------------------------------------------------------ Confirmar antes de enviar */
  const dialogo = document.querySelector('[data-confirmacion]');
  if (dialogo && !dialogo.dataset.listo) {
    dialogo.dataset.listo = '1';
    const texto = dialogo.querySelector('[data-confirmacion-texto]');
    const aceptar = dialogo.querySelector('[data-confirmacion-aceptar]');
    let pendiente = null;
    document.querySelectorAll('form[data-confirmar]').forEach((formulario) => {
      formulario.addEventListener('submit', (evento) => {
        if (formulario.dataset.confirmado) return;
        evento.preventDefault();
        pendiente = formulario;
        texto.textContent = formulario.dataset.confirmar;
        aceptar.textContent = formulario.dataset.confirmarBoton || 'Confirmar';
        dialogo.showModal();
        document.documentElement.classList.add('is-scroll-locked');
        aceptar.focus();
      });
    });
    aceptar.addEventListener('click', () => {
      if (!pendiente) return;
      pendiente.dataset.confirmado = '1';
      dialogo.close();
      pendiente.requestSubmit();
    });
  }

  /* ------------------------------------------------------------------ Archivos elegidos */
  document.querySelectorAll('[data-evidencias]').forEach((entrada) => {
    if (entrada.dataset.listo) return;
    entrada.dataset.listo = '1';
    const lista = entrada.closest('.field')?.querySelector('[data-evidencias-lista]');
    const formulario = entrada.form;
    const maximo = Number(formulario?.dataset.maximoMb || 5) * MB;
    const porEnvio = Number(formulario?.dataset.porEnvio || 5);
    if (!lista) return;
    entrada.addEventListener('change', () => {
      lista.replaceChildren();
      const archivos = [...entrada.files];
      archivos.forEach((archivo) => {
        const item = document.createElement('li');
        const problema = !TIPOS.includes(archivo.type) ? 'no se acepta este tipo de archivo'
          : (archivo.size > maximo ? `pesa más de ${maximo / MB} MB` : '');
        item.className = problema ? 'conducta-archivos__item is-invalido' : 'conducta-archivos__item';
        item.textContent = `${archivo.name} · ${peso(archivo.size)}${problema ? ` · ${problema}` : ''}`;
        lista.append(item);
      });
      if (archivos.length > porEnvio) {
        const aviso = document.createElement('li');
        aviso.className = 'conducta-archivos__item is-invalido';
        aviso.textContent = `Elige como máximo ${porEnvio} archivo${porEnvio === 1 ? '' : 's'} a la vez.`;
        lista.append(aviso);
      }
      lista.hidden = !archivos.length;
    });
  });

  /* ------------------------------------------------------------------ Contacto: «otra persona» */
  document.querySelectorAll('[data-contacto-form]').forEach((formulario) => {
    const eleccion = formulario.elements.tutor;
    const otra = formulario.querySelector('[data-otra-persona]');
    if (!eleccion || !otra) return;
    const aplicar = () => { otra.hidden = eleccion.value !== 'otra'; };
    eleccion.addEventListener('change', () => {
      aplicar();
      if (!otra.hidden) formulario.elements.persona?.focus();
    });
    aplicar();
  });

  /* ------------------------------------------------------------------ Ajustes: la sección elegida a la vista */
  document.querySelectorAll('.conducta-secciones').forEach((lista) => {
    const actual = lista.querySelector('[aria-current="page"]');
    if (!actual) return;
    const centrar = () => {   // con la letra ya cargada, que cambia el ancho de las pestañas
      const pestana = actual.getBoundingClientRect();
      lista.scrollLeft += pestana.left - lista.getBoundingClientRect().left - (lista.clientWidth - pestana.width) / 2;
    };
    if (document.readyState === 'complete') centrar();
    else window.addEventListener('load', centrar, { once: true });
  });
})();
