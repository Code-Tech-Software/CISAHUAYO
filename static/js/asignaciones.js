/* CISAHUAYO · asignaciones

   - Tablero: asignar un profesor a varias materias marcadas ([data-asignacion-masiva]). Las casillas de las filas
     ([data-masiva-fila]) viven fuera del formulario y se unen a él con el atributo form.
   - Carga por profesor: prepara la ventana para pasar las clases de un profesor a otro ([data-transferir-form]) con
     los datos del botón que la abrió.
*/
(() => {
  'use strict';

  const masiva = document.querySelector('[data-asignacion-masiva]');
  if (masiva) {
    const filas = Array.from(document.querySelectorAll('[data-masiva-fila]'));
    const todas = document.querySelector('[data-masiva-todas]');
    const conteo = masiva.querySelector('[data-masiva-conteo]');
    const profesor = masiva.querySelector('[data-masiva-profesor]');
    const enviar = masiva.querySelector('[data-masiva-enviar]');
    const mensajeInicial = conteo.textContent;

    const actualizar = () => {
      const marcadas = filas.filter((casilla) => casilla.checked).length;
      conteo.textContent = marcadas
        ? `${marcadas} materia${marcadas === 1 ? '' : 's'} marcada${marcadas === 1 ? '' : 's'}`
        : mensajeInicial;
      masiva.classList.toggle('is-active', marcadas > 0);
      enviar.disabled = !marcadas || !/^\d+$/.test(profesor.value);
      if (todas) {
        todas.checked = marcadas > 0 && marcadas === filas.length;
        todas.indeterminate = marcadas > 0 && marcadas < filas.length;
      }
    };

    filas.forEach((casilla) => casilla.addEventListener('change', actualizar));
    profesor.addEventListener('change', actualizar);
    if (todas) {
      todas.addEventListener('change', () => {
        filas.forEach((casilla) => { casilla.checked = todas.checked; });
        actualizar();
      });
    }
    actualizar();
  }

  const transferir = document.querySelector('[data-transferir-form]');
  if (transferir) {
    const destino = transferir.querySelector('select[name="destino"]');
    document.addEventListener('click', (event) => {
      const boton = event.target.closest('[data-transferir]');
      if (!boton) return;
      const clases = Number(boton.dataset.clases);
      transferir.querySelector('[name="origen"]').value = boton.dataset.origen;
      transferir.querySelector('[data-transferir-nombre]').textContent = boton.dataset.nombre;
      transferir.querySelector('[data-transferir-clases]').textContent = `${clases} materia${clases === 1 ? '' : 's'}`;
      // Quien se va no puede ser su propio destino
      Array.from(destino.options).forEach((opcion) => {
        const esElMismo = opcion.value === boton.dataset.origen;
        opcion.hidden = esElMismo;
        opcion.disabled = esElMismo;
      });
      destino.value = '-';
    });
  }
})();
