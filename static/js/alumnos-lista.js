/* CISAHUAYO · la tabla de estudiantes (templates/alumnos/lista.html)

   - Vista rápida: al tocar el nombre se abre un panel con sus datos clave (Alumnos/views.alumno_vista_rapida), sin salir
     de la lista. Con Ctrl/Cmd+clic, o si algo falla, el enlace abre su expediente como siempre.
   - Acciones en lote: al elegir estudiantes aparece la barra con lo que se puede hacer con ellos; «Elegir a todos» marca
     los de esta página. Generar contraseñas pide confirmación.
   - El menú «Columnas» se cierra al tocar fuera o con Escape.
*/
(() => {
  'use strict';

  const tabla = document.querySelector('[data-alumnos-tabla]');

  /* ------------------------------------------------------------------ vista rápida */
  const panel = document.querySelector('[data-vista-rapida-panel]');
  const cuerpo = panel?.querySelector('[data-vista-rapida-cuerpo]');
  const titulo = panel?.querySelector('#vista-rapida-titulo');
  let origen = null;
  let turno = 0;

  const abrirVistaRapida = async (enlace) => {
    if (typeof panel?.showModal !== 'function' || !cuerpo) return false;
    const mio = ++turno;
    origen = enlace;
    cuerpo.replaceChildren();
    const cargando = document.createElement('p');
    cargando.className = 'text-muted';
    cargando.textContent = 'Cargando…';
    cuerpo.append(cargando);
    if (titulo) titulo.textContent = enlace.querySelector('.person__name')?.textContent || 'Vista rápida';
    panel.showModal();
    try {
      const respuesta = await fetch(enlace.dataset.vistaRapida, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' });
      if (!respuesta.ok) throw new Error(String(respuesta.status));
      const pagina = new DOMParser().parseFromString(await respuesta.text(), 'text/html');
      const contenido = pagina.querySelector('.vista-rapida__contenido');
      if (!contenido) throw new Error('sin contenido');
      if (mio !== turno) return true;
      cuerpo.replaceChildren(document.importNode(contenido, true));
    } catch (error) {
      if (mio !== turno) return true;
      panel.close();
      window.location.href = enlace.href;   /* el expediente, como sin JavaScript */
    }
    return true;
  };

  tabla?.addEventListener('click', (evento) => {
    const enlace = evento.target.closest('a[data-vista-rapida]');
    if (!enlace || evento.button !== 0 || evento.metaKey || evento.ctrlKey || evento.shiftKey || evento.altKey) return;
    if (!window.fetch || !window.DOMParser || typeof panel?.showModal !== 'function') return;
    evento.preventDefault();
    abrirVistaRapida(enlace);
  });

  /* «Editar» abre el formulario en su ventana (modal-form.js): antes se cierra la vista rápida */
  panel?.addEventListener('click', (evento) => {
    if (!evento.target.closest('[data-modal-form]')) return;
    origen = null;
    panel.close();
  });

  panel?.addEventListener('close', () => {
    turno += 1;
    const volver = origen;
    origen = null;
    if (volver?.isConnected) volver.focus({ preventScroll: true });
  });

  /* ------------------------------------------------------------------ acciones en lote */
  const lote = document.querySelector('[data-lote]');
  if (lote && tabla) {
    const casillas = () => [...tabla.querySelectorAll('[data-lote-fila]')];
    const todos = tabla.querySelector('[data-lote-todos]');
    const cuenta = lote.querySelector('[data-lote-cuenta]');
    const plural = lote.querySelector('[data-lote-plural]');

    const actualizar = () => {
      const elegidas = casillas().filter((casilla) => casilla.checked);
      casillas().forEach((casilla) => casilla.closest('tr')?.classList.toggle('is-elegido', casilla.checked));
      lote.hidden = !elegidas.length;
      if (cuenta) cuenta.textContent = String(elegidas.length);
      if (plural) plural.hidden = elegidas.length === 1;
      if (todos) {
        todos.checked = elegidas.length > 0 && elegidas.length === casillas().length;
        todos.indeterminate = elegidas.length > 0 && elegidas.length < casillas().length;
      }
      document.body.classList.toggle('con-lote', elegidas.length > 0);
    };

    tabla.addEventListener('change', (evento) => {
      if (evento.target.matches('[data-lote-todos]')) {
        casillas().forEach((casilla) => { casilla.checked = evento.target.checked; });
      }
      if (evento.target.matches('[data-lote-todos], [data-lote-fila]')) actualizar();
    });

    lote.querySelector('[data-lote-limpiar]')?.addEventListener('click', () => {
      casillas().forEach((casilla) => { casilla.checked = false; });
      actualizar();
    });

    lote.addEventListener('submit', (evento) => {
      const boton = evento.submitter;
      if (!casillas().some((casilla) => casilla.checked)) {
        evento.preventDefault();
        return;
      }
      const pregunta = boton?.dataset.loteConfirmar;
      if (pregunta && !window.confirm(pregunta)) evento.preventDefault();
    });

    actualizar();   /* al volver con «Atrás» el navegador puede conservar las casillas marcadas */
  }

  /* ------------------------------------------------------------------ menú «Columnas» */
  const menu = document.querySelector('[data-columnas]');
  if (menu) {
    document.addEventListener('click', (evento) => {
      if (menu.open && !menu.contains(evento.target)) menu.open = false;
    });
    document.addEventListener('keydown', (evento) => {
      if (evento.key === 'Escape' && menu.open) {
        menu.open = false;
        menu.querySelector('summary')?.focus();
      }
    });
  }
})();
