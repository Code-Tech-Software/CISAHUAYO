/* CISAHUAYO · comentarios por periodo (Gestión académica › Comentarios por periodo)

   - Contador de caracteres de cada comentario (se marca al acercarse al límite).
   - El estado de cada uno mientras se escribe: «Sin guardar» si cambió; si no, «Capturado» o «Pendiente» como está
     guardado (el avance del grupo cuenta solo lo guardado).
   - Aviso de cambios sin guardar y, al salir de la página con cambios, la pregunta del navegador.
   Sin JavaScript todo funciona igual: se escribe y se guarda con el botón.
*/
(() => {
  'use strict';

  const formulario = document.querySelector('[data-com-captura]');
  if (!formulario) return;
  const limite = Number(formulario.dataset.limite) || 2000;
  const textos = [...formulario.querySelectorAll('[data-com-texto]')];
  const aviso = formulario.querySelector('[data-com-aviso]');
  const textoAviso = aviso?.textContent || '';
  let enviando = false;

  const cambio = (campo) => campo.value.trim() !== (campo.dataset.original || '').trim();

  const contarCambios = () => {
    const cambiados = textos.filter(cambio).length;
    if (aviso) {
      aviso.textContent = cambiados ? `${cambiados} comentario${cambiados === 1 ? '' : 's'} sin guardar.` : textoAviso;
      aviso.classList.toggle('is-cambios', cambiados > 0);
    }
    return cambiados;
  };

  textos.forEach((campo) => {
    const fila = campo.closest('[data-com-fila]');
    const contador = fila?.querySelector('[data-com-contador]');
    const estado = fila?.querySelector('[data-com-estado]');
    const guardado = (campo.dataset.original || '').trim() !== '';
    const pintar = () => {
      if (contador) {
        contador.textContent = `${campo.value.length} / ${limite}`;
        contador.classList.toggle('is-cerca', campo.value.length > limite * 0.9);
      }
      if (estado) {
        const sinGuardar = cambio(campo);
        estado.textContent = sinGuardar ? 'Sin guardar' : (guardado ? 'Capturado' : 'Pendiente');
        estado.classList.toggle('tag--info', sinGuardar);
        estado.classList.toggle('tag--success', !sinGuardar && guardado);
        estado.classList.toggle('tag--warning', !sinGuardar && !guardado);
      }
    };
    campo.addEventListener('input', () => { pintar(); contarCambios(); });
    pintar();
  });
  contarCambios();

  formulario.addEventListener('submit', () => { enviando = true; });
  window.addEventListener('beforeunload', (evento) => {
    if (!enviando && contarCambios()) {
      evento.preventDefault();
      evento.returnValue = '';
    }
  });
})();
