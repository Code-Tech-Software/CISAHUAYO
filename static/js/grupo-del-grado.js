/* CISAHUAYO · el grupo dentro del grado elegido

   Cada selector de grupo ([data-grupo-de="<nombre del selector de grado>"]) trae todos los grupos, cada uno con su grado
   (data-grado). Al elegir el grado se dejan solo los suyos. Si el grado tiene un solo grupo, se elige solo y el campo se
   oculta (no hay nada que decidir); con varios, se muestra para elegirlo. El servidor vuelve a revisarlo al guardar.
*/
(() => {
  'use strict';

  const enlazar = (grupo) => {
    if (grupo.dataset.grupoEnlazado) return;
    grupo.dataset.grupoEnlazado = '1';
    const form = grupo.form || document;
    const grado = form.querySelector(`select[name="${grupo.dataset.grupoDe}"]`);
    if (!grado) return;
    const campo = grupo.closest('.field') || grupo;
    const vacia = grupo.querySelector('option[value=""]');
    const todas = [...grupo.querySelectorAll('option[data-grado]')];

    const actualizar = () => {
      const previo = grupo.value;
      const delGrado = todas.filter((opcion) => opcion.dataset.grado === grado.value);
      grupo.replaceChildren(...[vacia, ...delGrado].filter(Boolean));
      if (delGrado.length === 1) {
        grupo.value = delGrado[0].value;
      } else {
        grupo.value = delGrado.some((opcion) => opcion.value === previo) ? previo : '';
      }
      campo.hidden = delGrado.length < 2;
    };

    grado.addEventListener('change', actualizar);
    actualizar();
  };

  document.querySelectorAll('select[data-grupo-de]').forEach(enlazar);
})();
