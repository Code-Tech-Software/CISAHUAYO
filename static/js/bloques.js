/* CISAHUAYO · Bloques simultáneos (templates/asignaciones/bloque_form.html, distribuir.html y poblacion.html)

   En el formulario del bloque: solo se ofrecen los grupos del nivel elegido y se avisa si se mezclan grados sin permitirlo.
   En la distribución: elegir todos, contar los elegidos y exigir opción y estudiantes antes de enviar. El servidor vuelve a
   revisar todo (Asignaciones/bloques.py).
*/
(() => {
  'use strict';

  document.querySelectorAll('[data-enviar-al-cambiar]').forEach((campo) => {
    campo.addEventListener('change', () => campo.form.requestSubmit());
  });

  const formulario = document.querySelector('[data-bloque-form]');
  if (formulario) {
    const nivel = formulario.querySelector('[name="nivel"]');
    const mezclar = formulario.querySelector('[name="mezclar_grados"]');
    const aviso = formulario.querySelector('[data-bloque-aviso]');
    const opciones = [...formulario.querySelectorAll('[data-bloque-grupos] [data-nivel]')];
    const revisar = () => {
      opciones.forEach((opcion) => {
        const delNivel = !nivel.value || opcion.dataset.nivel === nivel.value;
        opcion.hidden = !delNivel;
        if (!delNivel) opcion.querySelector('input').checked = false;
      });
      const grados = new Set(opciones.filter((o) => o.querySelector('input').checked).map((o) => o.dataset.grado));
      if (aviso) aviso.hidden = grados.size < 2 || mezclar.checked;
    };
    formulario.addEventListener('change', revisar);
    revisar();
  }

  const tabla = document.querySelector('[data-distribuir]');
  if (tabla) {
    const filas = [...tabla.querySelectorAll('[data-distribuir-fila]')];
    const todos = tabla.querySelector('[data-distribuir-todos]');
    const cuantos = tabla.querySelector('[data-distribuir-cuantos]');
    const opcion = tabla.querySelector('[data-distribuir-opcion]');
    const enviar = tabla.querySelector('[data-distribuir-enviar]');
    const quitar = tabla.querySelector('[data-distribuir-quitar]');
    const actualizar = () => {
      const elegidos = filas.filter((fila) => fila.checked).length;
      if (cuantos) cuantos.textContent = `${elegidos} elegido${elegidos === 1 ? '' : 's'}`;
      if (enviar) enviar.disabled = !elegidos || (opcion && !opcion.value);
      if (quitar) quitar.disabled = !elegidos;
    };
    todos?.addEventListener('change', () => {
      filas.forEach((fila) => { fila.checked = todos.checked; });
      actualizar();
    });
    tabla.addEventListener('change', actualizar);
    actualizar();
  }
})();
