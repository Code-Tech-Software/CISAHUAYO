/* CISAHUAYO · captura de una entrada de bitácora (templates/bitacoras/form.html)

   - Al elegir el grupo trae sus materias (con sus bloques) y sus estudiantes (Bitacoras/views.opciones).
   - El bloque solo ofrece los de la materia elegida en el día de la semana de la fecha.
   - «Observación general del grupo» oculta la lista de estudiantes (no se atribuye a nadie).
   - Búsqueda en la lista de estudiantes (sin importar acentos ni mayúsculas) y conteo de elegidos.
   El servidor vuelve a validar todo: esto solo hace la captura más rápida.
*/
(() => {
  'use strict';

  const form = document.querySelector('[data-bitacora-form]');
  if (!form) return;

  const grupo = form.querySelector('[data-bitacora-grupo]');
  const materia = form.querySelector('[data-bitacora-materia]');
  const fecha = form.querySelector('input[name="fecha"]');
  const bloque = form.querySelector('[data-bitacora-bloque]');
  const general = form.querySelector('[data-bitacora-general]');
  const caja = form.querySelector('[data-bitacora-alumnos]');
  const lista = form.querySelector('[data-bitacora-lista]');
  const buscar = form.querySelector('[data-bitacora-buscar]');
  const conteo = form.querySelector('[data-bitacora-conteo]');
  const vacio = form.querySelector('[data-bitacora-vacio]');
  const nada = form.querySelector('[data-bitacora-nada]');
  const url = form.dataset.opcionesUrl;

  const normal = (texto) => texto.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();
  const diaDe = (valor) => {
    if (!valor) return null;
    const [a, m, d] = valor.split('-').map(Number);
    return (new Date(a, m - 1, d).getDay() + 6) % 7;   /* lunes = 0, como el horario */
  };

  /* ------------------------------------------------------------------ bloques de la materia en ese día */
  const filtrarBloques = () => {
    if (!bloque) return;
    const dia = diaDe(fecha?.value);
    let elegidoVisible = false;
    [...bloque.options].forEach((opcion) => {
      if (!opcion.value) return;
      const visible = opcion.dataset.materia === materia.value && (dia === null || Number(opcion.dataset.dia) === dia);
      opcion.hidden = !visible;
      opcion.disabled = !visible;
      if (visible && opcion.selected) elegidoVisible = true;
    });
    if (!elegidoVisible) {
      const disponibles = [...bloque.options].filter((o) => o.value && !o.disabled);
      bloque.value = disponibles.length === 1 ? disponibles[0].value : '';
    }
  };

  /* ------------------------------------------------------------------ materias del grupo elegido */
  /* Al abrir la página la lista trae las materias de todos sus grupos: solo se ofrecen las del grupo elegido */
  const filtrarMaterias = () => {
    if (!grupo || !materia) return;
    [...materia.options].forEach((opcion) => {
      if (!opcion.value) return;
      const visible = opcion.dataset.grupo === grupo.value;
      opcion.hidden = !visible;
      opcion.disabled = !visible;
    });
    if (materia.selectedOptions[0]?.disabled) materia.value = '';
  };

  /* ------------------------------------------------------------------ lista de estudiantes */
  const actualizarConteo = () => {
    if (!conteo || !lista) return;
    const total = lista.querySelectorAll('input[type="checkbox"]').length;
    const elegidos = lista.querySelectorAll('input[type="checkbox"]:checked').length;
    conteo.textContent = total ? `${elegidos} de ${total} elegido${total === 1 ? '' : 's'}` : '';
  };

  const aplicarBusqueda = () => {
    if (!lista) return;
    const consulta = normal(buscar?.value || '');
    let visibles = 0;
    lista.querySelectorAll('li').forEach((fila) => {
      const coincide = !consulta || normal(fila.dataset.texto || '').includes(consulta);
      fila.hidden = !coincide;
      if (coincide) visibles += 1;
    });
    if (nada) nada.hidden = !(consulta && visibles === 0 && lista.children.length);
  };

  const pintarAlumnos = (alumnos) => {
    const elegidos = new Set([...lista.querySelectorAll('input:checked')].map((c) => c.value));
    lista.replaceChildren(...alumnos.map((alumno) => {
      const fila = document.createElement('li');
      fila.dataset.texto = `${alumno.nombre} ${alumno.referencia}`.toLowerCase();
      const etiqueta = document.createElement('label');
      etiqueta.className = 'bitacora-alumno';
      etiqueta.htmlFor = `alumno-${alumno.id}`;
      const casilla = document.createElement('input');
      Object.assign(casilla, { type: 'checkbox', name: 'alumnos', value: String(alumno.id), id: `alumno-${alumno.id}`, checked: elegidos.has(String(alumno.id)) });
      const avatar = document.createElement('span');
      avatar.className = `avatar avatar--tone-${alumno.tono} avatar--sm`;
      avatar.setAttribute('aria-hidden', 'true');
      avatar.textContent = alumno.iniciales;
      const texto = document.createElement('span');
      texto.className = 'bitacora-alumno__texto';
      const nombre = document.createElement('span');
      nombre.className = 'bitacora-alumno__nombre';
      nombre.textContent = alumno.nombre;
      const referencia = document.createElement('span');
      referencia.className = 'bitacora-alumno__ref';
      referencia.textContent = alumno.referencia;
      texto.append(nombre, referencia);
      etiqueta.append(casilla, avatar, texto);
      fila.append(etiqueta);
      return fila;
    }));
    if (vacio) {
      vacio.hidden = alumnos.length > 0;
      vacio.textContent = grupo?.value ? 'El grupo no tiene estudiantes inscritos en el ciclo.' : 'Elige el grupo para ver a sus estudiantes.';
    }
    aplicarBusqueda();
    actualizarConteo();
  };

  /* ------------------------------------------------------------------ al cambiar de grupo */
  const pintarMaterias = (materias) => {
    const anterior = materia.value;
    const opciones = [new Option('Elige la materia…', '')];
    materias.forEach((m) => {
      const opcion = new Option(m.nombre, String(m.id));
      opcion.dataset.grupo = grupo.value;
      opciones.push(opcion);
    });
    materia.replaceChildren(...opciones);
    materia.value = materias.some((m) => String(m.id) === anterior) ? anterior : (materias.length === 1 ? String(materias[0].id) : '');

    if (bloque) {
      const bloques = [new Option('Sin bloque', '')];
      materias.forEach((m) => m.bloques.forEach((b) => {
        const opcion = new Option(b.texto, String(b.id));
        opcion.dataset.materia = String(m.id);
        opcion.dataset.dia = String(b.dia);
        bloques.push(opcion);
      }));
      bloque.replaceChildren(...bloques);
    }
    filtrarBloques();
  };

  let pedido = null;
  const cargarGrupo = async () => {
    if (!grupo || !url) return;
    if (!grupo.value) {
      pintarMaterias([]);
      pintarAlumnos([]);
      return;
    }
    pedido?.abort();
    pedido = new AbortController();
    form.setAttribute('aria-busy', 'true');
    try {
      const respuesta = await fetch(`${url}?grupo=${encodeURIComponent(grupo.value)}`, {
        headers: { Accept: 'application/json' }, credentials: 'same-origin', signal: pedido.signal,
      });
      if (!respuesta.ok) throw new Error(String(respuesta.status));
      const datos = await respuesta.json();
      pintarMaterias(datos.materias);
      lista.querySelectorAll('input:checked').forEach((c) => { c.checked = false; });   /* otro grupo: otros estudiantes */
      pintarAlumnos(datos.alumnos);
    } catch (error) {
      if (error.name !== 'AbortError') window.alert('No se pudieron cargar las materias y los estudiantes del grupo. Revisa tu conexión e inténtalo de nuevo.');
    } finally {
      form.removeAttribute('aria-busy');
    }
  };

  /* ------------------------------------------------------------------ observación general */
  const sincronizarGeneral = () => {
    if (!general || !caja) return;
    caja.hidden = general.checked;
    caja.querySelectorAll('input[type="checkbox"]').forEach((c) => { c.disabled = general.checked; });
  };

  grupo?.addEventListener('change', cargarGrupo);
  materia?.addEventListener('change', filtrarBloques);
  fecha?.addEventListener('change', filtrarBloques);
  general?.addEventListener('change', sincronizarGeneral);
  buscar?.addEventListener('input', aplicarBusqueda);
  buscar?.addEventListener('keydown', (event) => { if (event.key === 'Enter') event.preventDefault(); });   /* no envía el formulario */
  lista?.addEventListener('change', actualizarConteo);

  filtrarMaterias();
  filtrarBloques();
  sincronizarGeneral();
  actualizarConteo();
})();
