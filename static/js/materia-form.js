/* CISAHUAYO · alta y edición de una materia

   - La clave se propone sola (el servidor da una libre con las iniciales y el grado: «MAT-1P») mientras se escribe el
     nombre y se elige el grado. En cuanto se escribe en la clave deja de proponerse; si se borra, se vuelve a proponer.
     Al editar se respeta la clave que ya tiene.
   - Al registrarla, el selector del profesor muestra solo a quienes dan clases en el nivel del grado elegido (cada
     opción trae sus niveles en data-niveles). Sin grado elegido no se puede elegir profesor.
   - Registrarla sin profesor se puede, pero se confirma: al enviar sin profesor aparece el aviso con «Sí, registrarla
     sin profesor» (que envía sin_profesor=1) o «Elegir un profesor».
   Es solo una ayuda: el servidor vuelve a revisar todo al guardar.
*/
(() => {
  'use strict';

  const clave = document.querySelector('input[data-clave-url]');
  if (!clave) return;
  const form = clave.closest('form');
  const nombre = form.querySelector('input[name="nombre"]');
  const estado = form.querySelector('[data-clave-estado]');
  const selector = form.querySelector('select[name="profesor"]');
  const ayuda = form.querySelector('[data-profesor-ayuda]');
  const aviso = form.querySelector('[data-sin-profesor-aviso]');
  let manual = clave.value.trim() !== '';
  let timer;
  let ultima = 0;

  const gradoElegido = () => form.querySelector('input[name="grado"]:checked');

  /* ------------------------------------------------------------------ Clave propuesta */
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
      const grado = gradoElegido();
      if (grado) url.searchParams.append('grado', grado.value);
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

  /* ------------------------------------------------------------------ Profesores del nivel del grado */
  /* Se guardan todas las opciones y se vuelven a poner solo las del nivel (ocultar <option> no funciona en todos los navegadores) */
  const vacia = selector?.querySelector('option[value=""]');
  const todas = selector ? [...selector.querySelectorAll('option[value]:not([value=""])')] : [];
  const textoDeAyuda = ayuda?.textContent ?? '';

  const nivelDe = (radio) => {
    const grupo = radio?.closest('[data-nivel]');
    return grupo ? { codigo: grupo.dataset.nivel, nombre: grupo.querySelector('.nivel-casillas__titulo')?.textContent.trim() ?? '' } : null;
  };

  const filtrarProfesores = () => {
    if (!selector) return;
    const nivel = nivelDe(gradoElegido());
    const previo = selector.value;
    const delNivel = nivel ? todas.filter((opcion) => (opcion.dataset.niveles || '').split(',').includes(nivel.codigo)) : [];
    selector.replaceChildren(...[vacia, ...delNivel].filter(Boolean));
    selector.value = delNivel.some((opcion) => opcion.value === previo) ? previo : '';
    selector.disabled = !nivel || !delNivel.length;
    if (!ayuda) return;
    if (!nivel) ayuda.textContent = 'Elige primero el grado: solo aparecen quienes dan clases en su nivel.';
    else if (!delNivel.length) ayuda.textContent = `Ningún profesor activo da clases en ${nivel.nombre}. Agrégale ese nivel en su ficha de Profesores, o regístrala sin profesor.`;
    else ayuda.textContent = textoDeAyuda;
  };

  /* ------------------------------------------------------------------ Confirmar «sin profesor» */
  const mostrarAviso = () => {
    aviso.hidden = false;
    aviso.scrollIntoView({ block: 'nearest' });
    aviso.querySelector('[data-sin-profesor-si]')?.focus({ preventScroll: true });
  };

  form.addEventListener('submit', (evento) => {
    if (!selector || !aviso) return;
    if (evento.submitter?.matches('[data-sin-profesor-si]')) return;    /* ya lo confirmó */
    if (!gradoElegido() || selector.value) return;                        /* sin grado, el servidor lo pide */
    evento.preventDefault();
    mostrarAviso();
  });

  aviso?.querySelector('[data-elegir-profesor]')?.addEventListener('click', () => {
    aviso.hidden = true;
    if (!selector.disabled) selector.focus();
    else gradoElegido()?.focus();
  });

  /* ------------------------------------------------------------------ Eventos */
  nombre?.addEventListener('input', proponer);
  form.addEventListener('change', (evento) => {
    if (evento.target.matches('input[name="grado"]')) {
      proponer();
      filtrarProfesores();
    }
    if (evento.target === selector && selector.value && aviso) aviso.hidden = true;
  });
  clave.addEventListener('input', () => {
    manual = clave.value.trim() !== '';
    if (estado) estado.textContent = '';
    if (!manual) proponer();
  });

  filtrarProfesores();
})();
