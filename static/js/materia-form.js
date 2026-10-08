/* CISAHUAYO · alta y edición de una materia

   La clave se propone sola (el servidor da una libre con las iniciales y el grado: «MAT-1P») mientras se escribe el
   nombre y se eligen los grados. En cuanto se escribe en la clave deja de proponerse; si se borra, se vuelve a proponer.
   Al editar se respeta la clave que ya tiene. Es solo una ayuda: el servidor vuelve a revisar todo al guardar.
*/
(() => {
  'use strict';

  const clave = document.querySelector('input[data-clave-url]');
  if (!clave) return;
  const form = clave.closest('form');
  const nombre = form.querySelector('input[name="nombre"]');
  const estado = form.querySelector('[data-clave-estado]');
  let manual = clave.value.trim() !== '';
  let timer;
  let ultima = 0;

  const gradosElegidos = () => [...form.querySelectorAll('input[name="grados"]:checked')].map((casilla) => casilla.value);

  const proponer = () => {
    window.clearTimeout(timer);
    if (manual) return;
    if (!nombre.value.trim()) {
      clave.value = '';
      if (estado) estado.textContent = '';
      return;
    }
    timer = window.setTimeout(async () => {
      const id = ++ultima;
      const url = new URL(clave.dataset.claveUrl, window.location.origin);
      url.searchParams.set('nombre', nombre.value);
      if (clave.dataset.excluir) url.searchParams.set('excluir', clave.dataset.excluir);
      gradosElegidos().forEach((grado) => url.searchParams.append('grado', grado));
      try {
        const respuesta = await fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        if (!respuesta.ok) return;
        const datos = await respuesta.json();
        if (id !== ultima || manual) return;   /* solo cuenta la respuesta más reciente */
        clave.value = datos.sugerida;
        if (estado) estado.textContent = datos.sugerida ? `Clave propuesta: «${datos.sugerida}». Puedes cambiarla.` : '';
      } catch (error) {
        /* sin conexión: se queda como está y el servidor la propone al guardar */
      }
    }, 250);
  };

  nombre?.addEventListener('input', proponer);
  form.addEventListener('change', (event) => {
    if (event.target.matches('input[name="grados"]')) proponer();
  });
  clave.addEventListener('input', () => {
    manual = clave.value.trim() !== '';
    if (estado) estado.textContent = '';
    if (!manual) proponer();
  });
})();
