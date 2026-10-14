/* CISAHUAYO · prefectura.

   - [data-prefectura-picker]: elegir a un estudiante del alcance con la búsqueda en vivo (window.CISAHUAYO.liveSearch);
     el servidor vuelve a comprobar que esté en el alcance.
   - [data-justificar]: al elegir estudiante, fechas o qué justificar, trae la lista de registros que se justificarán
     (vista previa) y pide confirmarla; las claves confirmadas viajan en el formulario y el servidor las compara con
     lo que hay en ese momento. El comprobante debe ser una foto: se muestra antes de enviarla.
   - [data-alcance-form]: con «Todo el colegio», los niveles y grupos no aplican (se ven apagados).
   - [data-elegir-alumno] (matriz por materia): elegir un estudiante muestra solo su fila.
   Se vuelve a ejecutar cada vez que una de estas páginas se abre en la ventana modal: por eso escucha en los propios
   elementos (nuevos en cada apertura) y no en document. */
(() => {
  'use strict';

  const MB = 1024 * 1024;
  const FOTOS = ['image/jpeg', 'image/png', 'image/webp'];

  /* ------------------------------------------------------------------ Elegir al estudiante */
  const prepararBuscador = (raiz, alElegir) => {
    const { liveSearch, alumnoResult } = window.CISAHUAYO || {};
    const campo = raiz.querySelector('input[type="hidden"]');
    const buscador = raiz.querySelector('[data-picker-search]');
    const entrada = raiz.querySelector('[data-picker-input]');
    const elegido = raiz.querySelector('[data-picker-chosen]');
    if (!campo || !entrada || !liveSearch) return;

    const elegir = (datos) => {
      campo.value = datos.id;
      raiz.querySelector('[data-picker-name]').textContent = datos.nombre;
      raiz.querySelector('[data-picker-meta]').textContent = `${datos.referencia} · ${datos.grado}`;
      const avatar = raiz.querySelector('[data-picker-avatar]');
      avatar.textContent = datos.iniciales;
      avatar.className = `avatar avatar--tone-${(Number(datos.id) % 6) + 1}`;
      elegido.hidden = false;
      buscador.hidden = true;
      alElegir?.();
    };

    liveSearch({
      input: entrada,
      box: raiz.querySelector('[data-picker-results]'),
      url: raiz.dataset.buscarUrl,
      emptyText: 'No hay estudiantes de tu alcance con ese dato.',
      render: alumnoResult,
      onPick: elegir,
    });
    entrada.addEventListener('keydown', (evento) => {
      if (evento.key === 'Enter') evento.preventDefault();
    });
    raiz.querySelector('[data-picker-change]')?.addEventListener('click', () => {
      campo.value = '';
      elegido.hidden = true;
      buscador.hidden = false;
      entrada.value = '';
      entrada.focus();
      alElegir?.();
    });
  };

  /* ------------------------------------------------------------------ Justificar */
  document.querySelectorAll('[data-justificar]').forEach((formulario) => {
    if (formulario.dataset.listo) return;
    formulario.dataset.listo = '1';
    const campos = formulario.elements;
    const estado = formulario.querySelector('[data-previa-estado]');
    const lista = formulario.querySelector('[data-previa-lista]');
    const confirmar = formulario.querySelector('[data-previa-confirmar]');
    const acepto = formulario.querySelector('[data-previa-acepto]');
    const texto = formulario.querySelector('[data-previa-texto]');
    const confirmados = campos.confirmados;
    let pedido;

    const limpiar = (mensaje) => {
      lista.replaceChildren();
      lista.hidden = true;
      confirmar.hidden = true;
      acepto.checked = false;
      confirmados.value = '';
      estado.textContent = mensaje;
    };

    const cargar = async () => {
      const alumno = campos.alumno.value;
      const desde = campos.desde.value;
      const hasta = campos.hasta.value;
      if (!alumno || !desde || !hasta) {
        limpiar('Elige al estudiante y las fechas para ver sus faltas y retardos sin justificar.');
        return;
      }
      const parametros = new URLSearchParams({ alumno, desde, hasta });
      formulario.querySelectorAll('[data-justificar-estado]:checked').forEach((casilla) => parametros.append('estados', casilla.value));
      if (campos.con_entrada?.checked) parametros.set('con_entrada', 'on');
      pedido?.abort();
      pedido = new AbortController();
      estado.textContent = 'Buscando los registros…';
      try {
        const respuesta = await fetch(`${formulario.dataset.previaUrl}?${parametros}`, {
          headers: { 'X-Requested-With': 'XMLHttpRequest' }, signal: pedido.signal,
        });
        const datos = await respuesta.json();
        if (!datos.ok) {
          limpiar(datos.mensaje);
          return;
        }
        if (!datos.registros.length) {
          limpiar('No hay faltas ni retardos sin justificar en esas fechas (los días sin clases no cuentan).');
          return;
        }
        lista.replaceChildren(...datos.registros.map((registro) => {
          const fila = document.createElement('li');
          fila.className = 'prefectura-previa__item';
          const que = document.createElement('span');
          que.textContent = `${registro.fecha_texto} · ${registro.que}`;
          const cual = document.createElement('span');
          cual.className = `tag ${registro.estado === 'Falta' ? 'tag--danger' : 'tag--warning'}`;
          cual.textContent = registro.estado;
          fila.append(que, cual);
          return fila;
        }));
        lista.hidden = false;
        confirmar.hidden = false;
        acepto.checked = false;
        confirmados.value = datos.registros.map((registro) => registro.clave).join(',');
        const total = datos.registros.length;
        estado.textContent = `${total} registro${total === 1 ? '' : 's'} sin justificar.`;
        texto.textContent = `Confirmo que se justifiquen ${total === 1 ? 'este registro' : `estos ${total} registros`}`;
      } catch (error) {
        if (error.name !== 'AbortError') limpiar('No se pudo consultar la lista: revisa tu conexión.');
      }
    };

    const picker = formulario.querySelector('[data-prefectura-picker]');
    if (picker) prepararBuscador(picker, cargar);
    ['desde', 'hasta'].forEach((nombre) => campos[nombre]?.addEventListener('change', cargar));
    formulario.querySelectorAll('[data-justificar-estado]').forEach((casilla) => casilla.addEventListener('change', cargar));
    campos.con_entrada?.addEventListener('change', cargar);

    /* El comprobante: una foto, con su vista previa */
    const archivo = formulario.querySelector('[data-comprobante]');
    const vista = formulario.querySelector('[data-comprobante-vista]');
    const imagen = formulario.querySelector('[data-comprobante-img]');
    const error = formulario.querySelector('[data-comprobante-error]');
    const maximo = Number(formulario.dataset.maximoMb || 5) * MB;
    archivo?.addEventListener('change', () => {
      const elegido = archivo.files[0];
      error.hidden = true;
      vista.hidden = true;
      if (!elegido) return;
      if (!FOTOS.includes(elegido.type)) {
        error.textContent = 'El comprobante debe ser una fotografía (JPG, PNG o WEBP).';
        error.hidden = false;
        return;
      }
      if (elegido.size > maximo) {
        error.textContent = `La foto pesa más de ${formulario.dataset.maximoMb} MB.`;
        error.hidden = false;
        return;
      }
      if (imagen.src) URL.revokeObjectURL(imagen.src);
      imagen.src = URL.createObjectURL(elegido);
      vista.hidden = false;
    });

    formulario.addEventListener('submit', (evento) => {
      if (!confirmados.value || !acepto.checked) {
        evento.preventDefault();
        estado.textContent = confirmados.value
          ? 'Marca la casilla para confirmar los registros que se justificarán.'
          : 'No hay registros por justificar con esos datos.';
        (confirmados.value ? acepto : campos.desde).focus();
        return;
      }
      if (!archivo?.files.length) {
        evento.preventDefault();
        error.textContent = 'Adjunta la foto del comprobante: es obligatoria.';
        error.hidden = false;
        archivo?.focus();
      }
    }, true);

    if (campos.alumno.value) cargar();
  });

  /* ------------------------------------------------------------------ Registrar entrada o salida */
  document.querySelectorAll('form').forEach((formulario) => {
    const picker = formulario.querySelector('[data-prefectura-picker]');
    if (!picker || formulario.hasAttribute('data-justificar') || picker.dataset.listo) return;
    picker.dataset.listo = '1';
    prepararBuscador(picker);
  });

  /* ------------------------------------------------------------------ Alcance de una cuenta */
  document.querySelectorAll('[data-alcance-form]').forEach((formulario) => {
    const todo = formulario.querySelector('[data-alcance-todo]');
    const partes = formulario.querySelector('[data-alcance-partes]');
    if (!todo || !partes) return;
    const aplicar = () => {
      partes.setAttribute('aria-disabled', String(todo.checked));
      partes.querySelectorAll('input').forEach((casilla) => { casilla.disabled = todo.checked; });
    };
    todo.addEventListener('change', aplicar);
    aplicar();
  });

  /* ------------------------------------------------------------------ Matriz: un solo estudiante */
  document.querySelectorAll('[data-elegir-alumno]').forEach((selector) => {
    selector.addEventListener('change', () => selector.form?.requestSubmit());
  });
})();
