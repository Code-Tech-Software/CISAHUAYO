/* CISAHUAYO · profesores

   Prepara dos ventanas con los datos de la fila que las abrió:
   - elegir el profesor de una materia ([data-asignar-form], en los perfiles del grado y de la materia);
   - quitar al profesor de una materia ([data-quitar-prof-form], en el perfil del profesor).
*/
(() => {
  'use strict';

  const asignar = document.querySelector('[data-asignar-form]');
  const quitar = document.querySelector('[data-quitar-prof-form]');
  if (!asignar && !quitar) return;

  document.addEventListener('click', (event) => {
    const elegir = asignar && event.target.closest('[data-asignar-profesor]');
    if (elegir) {
      asignar.querySelector('[name="asignacion"]').value = elegir.dataset.asignacion;
      asignar.querySelector('[data-asignar-descripcion]').textContent = elegir.dataset.descripcion;
      asignar.querySelector('select[name="profesor"]').value = elegir.dataset.profesor || '';
      return;
    }

    const retirar = quitar && event.target.closest('[data-quitar-prof]');
    if (retirar) {
      quitar.querySelector('[name="asignacion"]').value = retirar.dataset.asignacion;
      quitar.querySelector('[data-quitar-prof-descripcion]').textContent = retirar.dataset.descripcion;
    }
  });
})();
