/* CISAHUAYO · profesores

   Prepara dos ventanas con los datos de la fila que las abrió:
   - elegir el profesor de una materia ([data-asignar-form], en los perfiles del grado y de la materia); si el botón trae
     data-habilitados (ids de quienes pueden impartir esa materia), esos salen primero en su propio grupo, y después los de
     data-del-nivel (quienes dan clases en el nivel del grado, data-nivel);
   - quitar al profesor de una materia ([data-quitar-prof-form], en el perfil del profesor).
*/
(() => {
  'use strict';

  const asignar = document.querySelector('[data-asignar-form]');
  const quitar = document.querySelector('[data-quitar-prof-form]');
  if (!asignar && !quitar) return;

  // Las opciones de profesor tal como llegaron del servidor: se reparten en grupos cada vez que se abre la ventana.
  const selector = asignar && asignar.querySelector('select[name="profesor"]');
  const sinProfesor = selector && selector.querySelector('option[value=""]');
  const profesores = selector ? Array.from(selector.options).filter((opcion) => opcion.value) : [];

  const grupo = (etiqueta, opciones) => {
    const nodo = document.createElement('optgroup');
    nodo.label = etiqueta;
    opciones.forEach((opcion) => nodo.appendChild(opcion));
    return nodo;
  };

  const llenarSelector = (habilitados, delNivel, nivel, elegido) => {
    const ids = new Set((habilitados || '').split(',').filter(Boolean));
    const delMismoNivel = new Set((delNivel || '').split(',').filter(Boolean));
    const propios = profesores.filter((opcion) => ids.has(opcion.value));
    const delNivelOpciones = profesores.filter((opcion) => !ids.has(opcion.value) && delMismoNivel.has(opcion.value));
    const otros = profesores.filter((opcion) => !ids.has(opcion.value) && !delMismoNivel.has(opcion.value));
    const grupos = [
      ['Pueden impartirla', propios],
      [nivel ? `Dan clases en ${nivel.toLowerCase()}` : 'Del mismo nivel', delNivelOpciones],
      ['Otros profesores', otros],
    ].filter(([, opciones]) => opciones.length);
    selector.replaceChildren();
    if (sinProfesor) selector.appendChild(sinProfesor);
    if (grupos.length > 1) {
      grupos.forEach(([etiqueta, opciones]) => selector.appendChild(grupo(etiqueta, opciones)));
    } else {
      profesores.forEach((opcion) => selector.appendChild(opcion));
    }
    selector.value = elegido || '';
    const pista = asignar.querySelector('[data-asignar-pista]');
    if (pista) pista.hidden = !propios.length;
  };

  document.addEventListener('click', (event) => {
    const elegir = asignar && event.target.closest('[data-asignar-profesor]');
    if (elegir) {
      asignar.querySelector('[name="asignacion"]').value = elegir.dataset.asignacion;
      asignar.querySelector('[data-asignar-descripcion]').textContent = elegir.dataset.descripcion;
      llenarSelector(elegir.dataset.habilitados, elegir.dataset.delNivel, elegir.dataset.nivel, elegir.dataset.profesor);
      return;
    }

    const retirar = quitar && event.target.closest('[data-quitar-prof]');
    if (retirar) {
      quitar.querySelector('[name="asignacion"]').value = retirar.dataset.asignacion;
      quitar.querySelector('[data-quitar-prof-descripcion]').textContent = retirar.dataset.descripcion;
    }
  });
})();
