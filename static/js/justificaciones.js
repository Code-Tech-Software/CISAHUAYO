/* CISAHUAYO · formulario de justificaciones

   - Muestra la lista de materias solo cuando se elige «Solo algunas materias».
   - Al crear: elegir al alumno con la búsqueda en vivo (alumnos:buscar) y cargar las materias de su grado
     (asistencias:justificacion_materias) cada vez que cambia el alumno o la fecha. El servidor vuelve a validar todo.
*/
(() => {
  'use strict';

  const form = document.querySelector('[data-justificacion-form]');
  if (!form) return;

  const qs = (selector) => form.querySelector(selector);
  const bloque = qs('[data-materias-bloque]');
  const lista = qs('[data-materias-lista]');

  /* --- Materias: solo se muestran cuando se eligen «algunas» ---------------------------------------------------------- */
  const actualizarVisibilidad = () => {
    const modo = qs('input[name="materias_modo"]:checked')?.value;
    bloque.hidden = modo !== 'ALGUNAS';
  };
  form.addEventListener('change', (evento) => {
    if (evento.target.matches('input[name="materias_modo"]')) actualizarVisibilidad();
  });
  actualizarVisibilidad();

  if (!form.dataset.searchUrl) return; /* edición: el alumno y el día no cambian */

  /* --- Elegir al alumno ----------------------------------------------------------------------------------------------- */
  const { liveSearch, alumnoResult } = window.CISAHUAYO;
  const alumnoInput = qs('input[name="alumno"]');
  const buscador = qs('[data-picker-search]');
  const campoBusqueda = qs('[data-picker-input]');
  const resultados = qs('[data-picker-results]');
  const elegido = qs('[data-picker-chosen]');
  const avatar = qs('[data-picker-avatar]');
  const nombre = qs('[data-picker-name]');
  const gradoElegido = qs('[data-picker-grado]');
  const falta = qs('[data-picker-error]');
  const etiquetaGrado = qs('[data-materias-grado]');
  const fecha = qs('input[name="fecha_desde"]');

  const pintarMaterias = (materias, marcadas = new Set()) => {
    lista.replaceChildren();
    if (!materias.length) {
      const vacio = document.createElement('p');
      vacio.className = 'field__hint';
      vacio.textContent = alumnoInput.value
        ? 'Ese estudiante no tiene materias vigentes en el ciclo.'
        : 'Elige primero al estudiante para ver las materias de su grado.';
      lista.append(vacio);
      return;
    }
    materias.forEach((materia) => {
      const etiqueta = document.createElement('label');
      etiqueta.className = 'choice choice--check';
      const casilla = document.createElement('input');
      casilla.className = 'choice__input';
      casilla.type = 'checkbox';
      casilla.name = 'materias';
      casilla.value = materia.id;
      casilla.checked = marcadas.has(String(materia.id));
      const caja = document.createElement('span');
      caja.className = 'choice__box';
      caja.textContent = materia.nombre;
      etiqueta.append(casilla, caja);
      lista.append(etiqueta);
    });
  };

  const cargarMaterias = async () => {
    if (!alumnoInput.value) {
      pintarMaterias([]);
      etiquetaGrado.textContent = '';
      return;
    }
    const marcadas = new Set([...lista.querySelectorAll('input:checked')].map((casilla) => casilla.value));
    try {
      const parametros = new URLSearchParams({ alumno: alumnoInput.value, fecha: fecha.value });
      const respuesta = await fetch(`${form.dataset.materiasUrl}?${parametros}`, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
      const datos = await respuesta.json();
      pintarMaterias(datos.materias, marcadas);
      etiquetaGrado.textContent = datos.grado ? `de ${datos.grado}` : '';
      gradoElegido.textContent = datos.grado || 'Sin inscripción vigente';
    } catch (error) {
      pintarMaterias([]);
    }
  };

  const elegir = (alumno) => {
    alumnoInput.value = alumno.id;
    nombre.textContent = alumno.nombre;
    gradoElegido.textContent = alumno.grado || 'Estudiante seleccionado';
    avatar.textContent = alumno.iniciales;
    avatar.className = `avatar avatar--tone-${(Number(alumno.id) % 6) + 1}`;
    elegido.hidden = false;
    buscador.hidden = true;
    falta.hidden = true;
    cargarMaterias();
  };

  const limpiar = () => {
    alumnoInput.value = '';
    elegido.hidden = true;
    buscador.hidden = false;
    campoBusqueda.value = '';
    cargarMaterias();
  };

  liveSearch({
    input: campoBusqueda,
    box: resultados,
    url: form.dataset.searchUrl,
    emptyText: 'No hay estudiantes con ese dato.',
    render: alumnoResult,
    onPick(alumno) {
      elegir(alumno);
      fecha?.focus();
    },
  });

  qs('[data-picker-change]').addEventListener('click', () => {
    limpiar();
    campoBusqueda.focus();
  });

  fecha?.addEventListener('change', cargarMaterias);

  form.addEventListener('submit', (evento) => {
    if (!alumnoInput.value) {
      evento.preventDefault();
      falta.hidden = false;
      campoBusqueda.focus();
      return;
    }
    const boton = qs('button[type="submit"]');
    boton.disabled = true; /* evita registrar dos veces con un doble clic */
  });

  if (!alumnoInput.value) campoBusqueda.focus();
})();
