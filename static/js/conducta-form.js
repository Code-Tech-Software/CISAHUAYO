/* CISAHUAYO · formulario de registro de conducta (templates/conducta/form.html).

   - Al registrar: el estudiante se busca en todo el colegio (conducta:buscar); al elegirlo, o al cambiar la fecha, se
     piden su grupo en esa fecha y las opciones activas de su nivel (conducta:opciones).
   - El tipo filtra las categorías; la categoría, los motivos (al cambiarla se limpia el motivo para no mezclar); el
     motivo propone su gravedad. Una conducta positiva no lleva gravedad ni medidas.
   - Si alguna medida implica suspensión, aparecen sus datos; si requiere seguimiento, se avisa que hacen falta el
     responsable y la fecha de revisión.
   El servidor valida todo de nuevo (nivel, tipo, motivos de la categoría, fechas, archivos). */
(() => {
  'use strict';

  const form = document.querySelector('[data-conducta-form]');
  if (!form || form.dataset.listo) return;
  form.dataset.listo = '1';

  const qs = (selector) => form.querySelector(selector);
  const qsa = (selector) => [...form.querySelectorAll(selector)];
  const edicion = form.hasAttribute('data-edicion');

  const categoria = qs('[data-conducta-categoria]');
  const motivo = qs('[data-conducta-motivo]');
  const gravedad = form.elements.gravedad;
  const estado = form.elements.estado;
  const medidas = qs('[data-conducta-medidas]');
  const suspension = qs('[data-suspension-bloque]');
  const avisoSeguimiento = qs('[data-aviso-seguimiento]');
  const sinOpciones = qs('[data-sin-opciones]');

  const tipo = () => qs('input[name="tipo"]:checked')?.value || 'INCIDENCIA';
  const hayOpciones = () => [...categoria.options].some((opcion) => opcion.value);

  const mostrar = (select, prueba) => {
    let visibles = 0;
    [...select.options].forEach((opcion) => {
      if (!opcion.value) return;
      const queda = prueba(opcion);
      opcion.hidden = !queda;
      opcion.disabled = !queda;
      visibles += queda;
    });
    if (select.selectedOptions[0]?.disabled) select.value = '';
    return visibles;
  };

  const filtrarCategorias = () => {
    const visibles = mostrar(categoria, (opcion) => opcion.dataset.tipo === tipo());
    sinOpciones.hidden = visibles > 0 || !hayOpciones();
  };

  const filtrarMotivos = () => {
    mostrar(motivo, (opcion) => opcion.dataset.categoria === categoria.value);
  };

  const aplicarMedidas = () => {
    const marcadas = qsa('input[name="medidas"]:checked');
    suspension.hidden = !marcadas.some((casilla) => casilla.hasAttribute('data-suspension'));
    avisoSeguimiento.hidden = !marcadas.some((casilla) => casilla.hasAttribute('data-seguimiento'));
  };

  /* Positiva: sin gravedad ni medidas; su seguimiento suele quedar cerrado (al registrar se propone) */
  const aplicarTipo = (cambio) => {
    const positiva = tipo() === 'POSITIVA';
    qsa('[data-solo-incidencia]').forEach((elemento) => { elemento.hidden = positiva; });
    if (positiva) {
      qsa('input[name="medidas"]').forEach((casilla) => { casilla.checked = false; });
      gravedad.value = '';
    }
    if (cambio && !edicion) {
      if (positiva && estado.value === 'PENDIENTE') estado.value = 'CERRADO';
      else if (!positiva && estado.value === 'CERRADO') estado.value = 'PENDIENTE';
    }
    filtrarCategorias();
    filtrarMotivos();
    aplicarMedidas();
  };

  form.addEventListener('change', (evento) => {
    if (evento.target.name === 'tipo') aplicarTipo(true);
  });
  categoria.addEventListener('change', () => {
    motivo.value = '';
    gravedad.value = '';
    filtrarMotivos();
  });
  motivo.addEventListener('change', () => {
    const propuesta = motivo.selectedOptions[0]?.dataset.gravedad;
    if (propuesta !== undefined && tipo() === 'INCIDENCIA') gravedad.value = propuesta;
  });
  medidas.addEventListener('change', aplicarMedidas);

  aplicarTipo(false);

  if (edicion) return;

  /* ------------------------------------------------------------------ Elegir al estudiante (solo al registrar) */
  const { liveSearch, alumnoResult } = window.CISAHUAYO || {};
  const alumno = form.elements.alumno;
  const buscador = qs('[data-picker-search]');
  const entrada = qs('[data-picker-input]');
  const elegido = qs('[data-picker-chosen]');
  const contexto = qs('[data-contexto]');
  const errorContexto = qs('[data-contexto-error]');
  const fecha = form.elements.fecha;
  let nivel = form.dataset.nivel || null;   // el de las opciones que ya trae la página

  const opcion = (valor, texto, datos = {}) => {
    const elemento = document.createElement('option');
    elemento.value = valor;
    elemento.textContent = texto;
    Object.entries(datos).forEach(([clave, dato]) => { elemento.dataset[clave] = dato; });
    return elemento;
  };

  /* Las opciones de otro nivel: se rehacen las listas conservando lo que siga existiendo */
  const reconstruir = (opciones) => {
    const antes = {
      categoria: categoria.value, motivo: motivo.value, suspension: form.elements.suspension_motivo.value,
      medidas: new Set(qsa('input[name="medidas"]:checked').map((c) => c.value)),
    };
    categoria.replaceChildren(opcion('', 'Elige la categoría…'), ...(opciones?.categorias || []).map((c) => opcion(c.id, c.nombre, { tipo: c.tipo })));
    motivo.replaceChildren(opcion('', 'Elige el motivo…'), ...(opciones?.motivos || []).map((m) => opcion(m.id, m.nombre, { categoria: m.categoria, gravedad: m.gravedad })));
    const motivoSuspension = form.elements.suspension_motivo;
    motivoSuspension.replaceChildren(opcion('', 'Elige el motivo…'), ...(opciones?.motivos_suspension || []).map((m) => opcion(m.id, m.nombre)));
    categoria.value = antes.categoria;
    motivo.value = antes.motivo;
    motivoSuspension.value = antes.suspension;

    medidas.replaceChildren();
    (opciones?.medidas || []).forEach((medida) => {
      const etiqueta = document.createElement('label');
      etiqueta.className = 'choice choice--check';
      etiqueta.htmlFor = `medida-${medida.id}`;
      const casilla = document.createElement('input');
      Object.assign(casilla, { className: 'choice__input', type: 'checkbox', name: 'medidas', value: medida.id, id: `medida-${medida.id}` });
      casilla.checked = antes.medidas.has(String(medida.id));
      if (medida.implica_suspension) casilla.dataset.suspension = '';
      if (medida.requiere_seguimiento) casilla.dataset.seguimiento = '';
      const caja = document.createElement('span');
      caja.className = 'choice__box';
      const porAprobar = (medida.requiere_aprobacion || medida.implica_suspension) && !('aprueba' in form.dataset);
      caja.textContent = medida.nombre + (medida.implica_suspension ? ' · suspensión' : '') + (porAprobar ? ' · requiere aprobación' : '');
      etiqueta.append(casilla, caja);
      medidas.append(etiqueta);
    });
    if (!opciones?.medidas?.length) {
      const vacio = document.createElement('p');
      vacio.className = 'field__hint';
      vacio.textContent = opciones ? 'Este nivel no tiene medidas activas que puedas aplicar: el administrador debe completar el catálogo en Ajustes › Conducta.' : 'Elige primero al estudiante para ver las medidas de su nivel.';
      medidas.append(vacio);
    }
    aplicarTipo(false);
  };

  const pintarContexto = (datos) => {
    qs('[data-contexto-ciclo]').textContent = datos.ciclo;
    qs('[data-contexto-nivel]').textContent = datos.nivel_nombre;
    qs('[data-contexto-grupo]').textContent = datos.grupo;
    qs('[data-contexto-periodo]').textContent = datos.periodo;
    contexto.hidden = false;
  };

  const cargarOpciones = async () => {
    errorContexto.hidden = true;
    if (!alumno.value) {
      contexto.hidden = true;
      return;
    }
    try {
      const parametros = new URLSearchParams({ alumno: alumno.value, fecha: fecha.value || '' });
      const respuesta = await fetch(`${form.dataset.opcionesUrl}?${parametros}`, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
      const datos = await respuesta.json();
      if (!datos.ok) {
        contexto.hidden = true;
        errorContexto.textContent = datos.mensaje;
        errorContexto.hidden = false;
        return;
      }
      pintarContexto(datos.contexto);
      if (datos.opciones.nivel !== nivel || !hayOpciones()) reconstruir(datos.opciones);
      nivel = datos.opciones.nivel;
    } catch (error) {
      errorContexto.textContent = 'No se pudieron cargar las opciones de su nivel: revisa tu conexión.';
      errorContexto.hidden = false;
    }
  };

  const elegir = (datos) => {
    alumno.value = datos.id;
    qs('[data-picker-name]').textContent = datos.nombre;
    qs('[data-picker-meta]').textContent = `${datos.referencia} · ${datos.grado}`;
    const avatar = qs('[data-picker-avatar]');
    avatar.textContent = datos.iniciales;
    avatar.className = `avatar avatar--tone-${(Number(datos.id) % 6) + 1}`;
    elegido.hidden = false;
    buscador.hidden = true;
    qs('[data-picker-error]').hidden = true;
    cargarOpciones();
  };

  if (liveSearch && entrada) {
    liveSearch({
      input: entrada,
      box: qs('[data-picker-results]'),
      url: form.dataset.buscarUrl,
      emptyText: 'No hay estudiantes con ese dato.',
      render: alumnoResult,
      onPick(datos) {
        elegir(datos);
        fecha.focus();
      },
    });
    entrada.addEventListener('keydown', (evento) => {
      if (evento.key === 'Enter') evento.preventDefault();
    });
  }

  qs('[data-picker-change]')?.addEventListener('click', () => {
    alumno.value = '';
    elegido.hidden = true;
    buscador.hidden = false;
    contexto.hidden = true;
    entrada.value = '';
    entrada.focus();
  });

  fecha.addEventListener('change', cargarOpciones);
  /* Con el estudiante ya elegido (desde su expediente o tras un error), se toma su nivel actual */
  if (alumno.value) {
    cargarOpciones();
  } else {
    entrada?.focus();
  }
})();
