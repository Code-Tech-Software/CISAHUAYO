/* CISAHUAYO · asignaciones

   - Tablero: asignar un profesor a varias materias marcadas ([data-asignacion-masiva]). Las casillas de las filas
     ([data-masiva-fila]) viven fuera del formulario y se unen a él con el atributo form. Solo se ofrecen los profesores
     que dan clases en el nivel de todas las marcadas (data-nivel de la fila, data-niveles de cada profesor).
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

    // Un profesor solo imparte materias de sus niveles: quedan a la vista los que cubren los de todas las marcadas
    const filtrarProfesores = () => {
      const niveles = new Set(filas.filter((casilla) => casilla.checked).map((casilla) => casilla.dataset.nivel).filter(Boolean));
      Array.from(profesor.options).forEach((opcion) => {
        if (opcion.dataset.niveles === undefined) return;
        const suyos = opcion.dataset.niveles.split(',');
        const fuera = [...niveles].some((nivel) => !suyos.includes(nivel));
        opcion.hidden = fuera;
        opcion.disabled = fuera;
      });
      if (profesor.selectedOptions[0]?.disabled) profesor.value = '-';
    };

    const actualizar = () => {
      filtrarProfesores();
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
      // Quien se va no puede ser su propio destino, y solo se ofrecen profesores de alguno de los niveles de sus materias
      const niveles = (boton.dataset.niveles || '').split(',').filter(Boolean);
      Array.from(destino.options).forEach((opcion) => {
        if (opcion.dataset.niveles === undefined) return;   /* «Elige…» y «Dejarlas sin profesor» */
        const suyos = opcion.dataset.niveles.split(',');
        const fuera = opcion.value === boton.dataset.origen || !niveles.some((nivel) => suyos.includes(nivel));
        opcion.hidden = fuera;
        opcion.disabled = fuera;
      });
      destino.value = '-';
    });
  }
})();
