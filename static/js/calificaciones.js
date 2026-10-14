/* CISAHUAYO · calificaciones (Gestión académica › Calificaciones)

   - Selector: cambiar ciclo, grupo, materia o periodo recarga la página (sin JavaScript, con «Ver»).
   - Captura en la tabla [data-captura]: cada celda se valida al salir de ella (0 a 10 con dos decimales; las faltas,
     enteros) y se guarda sola, en lotes, en el servidor, que vuelve a validar todo y responde celda por celda y con lo
     recalculado de cada estudiante (promedios, aportaciones, final y estado).
   - Si la conexión falla, los cambios se conservan (también en sessionStorage, por si se recarga) y se reintentan sin
     duplicarse: el servidor sabe que una celda que ya tiene el valor nuevo no cambia, y rechaza la que alguien más
     cambió mientras tanto (data-anterior).
   - Teclado: flechas, Enter (baja), Escape (deshace la celda). Pegar un rango copiado de Excel lo reparte desde la
     celda elegida, revisando cada valor antes de guardarlo.
*/
(() => {
  'use strict';

  /* --- Selector ------------------------------------------------------------------------------------------------ */
  const selector = document.querySelector('[data-cal-selector]');
  if (selector) {
    selector.querySelector('[data-cal-ver]')?.closest('.filters__actions')?.setAttribute('hidden', '');
    selector.addEventListener('change', (evento) => {
      const campo = evento.target;
      if (campo.matches('[data-cal-reinicia]')) {
        /* Otro ciclo u otro grupo: abre su primera materia y su periodo sugerido */
        selector.querySelectorAll('[data-cal-materia], [data-cal-periodo]').forEach((otro) => { otro.disabled = true; });
      }
      if (campo.matches('select')) selector.requestSubmit();
    });
  }

  /* --- Captura -------------------------------------------------------------------------------------------------- */
  const tabla = document.querySelector('[data-captura]');
  if (!tabla) return;
  const urlGuardar = tabla.dataset.urlGuardar;
  const claveLocal = `cisahuayo.calificaciones.pendientes.${tabla.dataset.acta}`;
  const barra = document.querySelector('[data-guardado]');
  const textoBarra = barra?.querySelector('[data-guardado-texto]');
  const botonReintentar = barra?.querySelector('[data-reintentar]');
  const botonDescartar = barra?.querySelector('[data-descartar]');
  const celdas = [...tabla.querySelectorAll('[data-celda]')];
  const porClave = new Map(celdas.map((celda) => [celda.dataset.clave, celda]));
  const filas = [...tabla.querySelectorAll('tbody tr[data-fila]')];
  const rejilla = filas.map((fila) => [...fila.querySelectorAll('input.cal-entrada[data-celda]')]);

  const pendientes = new Map();   // clave -> cambio por enviar
  let enviando = null;            // Map de lo que va en la petición actual
  let temporizador = null;
  let errores = 0;

  const csrf = () => {
    const galleta = document.cookie.split('; ').find((parte) => parte.startsWith('csrftoken='));
    return galleta ? decodeURIComponent(galleta.split('=')[1]) : (document.querySelector('[name=csrfmiddlewaretoken]')?.value || '');
  };

  const avisar = (texto, tono = '', conReintento = false, conDescarte = false) => {
    if (!barra) return;
    barra.hidden = !texto;
    barra.dataset.tono = tono;
    textoBarra.textContent = texto;
    if (botonReintentar) botonReintentar.hidden = !conReintento;
    if (botonDescartar) botonDescartar.hidden = !conDescarte;
  };

  const guardarLocal = () => {
    try {
      const todos = [...pendientes.values(), ...(enviando ? enviando.values() : [])];
      if (todos.length) sessionStorage.setItem(claveLocal, JSON.stringify(todos));
      else sessionStorage.removeItem(claveLocal);
    } catch (error) { /* sin almacenamiento: los cambios siguen en memoria */ }
  };

  const marcar = (celda, estado, mensaje = '') => {
    const td = celda.closest('td');
    td?.classList.remove('is-pendiente', 'is-guardada', 'is-error');
    celda.removeAttribute('aria-invalid');
    celda.removeAttribute('title');
    if (estado === 'pendiente') td?.classList.add('is-pendiente');
    if (estado === 'guardada') {
      td?.classList.add('is-guardada');
      window.setTimeout(() => td?.classList.remove('is-guardada'), 1200);
    }
    if (estado === 'error') {
      td?.classList.add('is-error');
      celda.setAttribute('aria-invalid', 'true');
      celda.title = mensaje;
    }
  };

  /* Revisa el texto como el servidor (para avisar antes); el servidor decide */
  const revisar = (celda, texto) => {
    const limpio = String(texto).trim().replace(',', '.');
    if (limpio === '') return { ok: true, valor: '' };
    if (celda.hasAttribute('data-entero')) {
      if (!/^\d{1,3}$/.test(limpio)) return { ok: false, error: 'Las faltas son un número entero de 0 en adelante.' };
      return { ok: true, valor: String(Number(limpio)) };
    }
    if (!/^(\d{1,2}(\.\d{0,2})?|\.\d{1,2})$/.test(limpio)) return { ok: false, error: 'Escribe un número de 0 a 10, con máximo dos decimales.' };
    const numero = Number(limpio);
    if (numero < 0 || numero > 10) return { ok: false, error: 'La calificación va de 0 a 10.' };
    return { ok: true, valor: limpio };
  };

  const mismoValor = (celda, a, b) => {
    if (celda.type === 'checkbox' || celda.hasAttribute('data-entero')) return String(a) === String(b);
    if (a === '' || b === '') return a === b;
    return Number(a) === Number(b);
  };

  const programar = (espera = 400) => {
    window.clearTimeout(temporizador);
    temporizador = window.setTimeout(enviar, espera);
  };

  const encolar = (celda, valor) => {
    const clave = celda.dataset.clave;
    const previo = pendientes.get(clave);
    pendientes.set(clave, {
      clave, tipo: celda.dataset.tipo, id: celda.dataset.id, inscripcion: celda.dataset.inscripcion,
      valor, anterior: previo ? previo.anterior : celda.dataset.anterior,
    });
    marcar(celda, 'pendiente');
    guardarLocal();
    programar();
  };

  const procesar = (celda) => {
    if (celda.type === 'checkbox') {
      const valor = celda.checked ? '1' : '0';
      if (valor === celda.dataset.anterior) { pendientes.delete(celda.dataset.clave); marcar(celda, ''); return true; }
      encolar(celda, valor);
      return true;
    }
    const revision = revisar(celda, celda.value);
    if (!revision.ok) {
      pendientes.delete(celda.dataset.clave);
      marcar(celda, 'error', revision.error);
      guardarLocal();
      return false;
    }
    if (mismoValor(celda, revision.valor, celda.dataset.anterior)) {
      pendientes.delete(celda.dataset.clave);
      marcar(celda, '');
      guardarLocal();
      return true;
    }
    encolar(celda, revision.valor);
    return true;
  };

  const actualizarFila = (inscripcion, datos) => {
    const fila = tabla.querySelector(`tr[data-inscripcion="${inscripcion}"]`);
    if (!fila) return;
    fila.querySelectorAll('[data-calc]').forEach((elemento) => {
      const nombre = elemento.dataset.calc;
      if (!(nombre in datos)) return;
      const valor = datos[nombre];
      if (nombre === 'estado') {
        elemento.textContent = valor;
        elemento.className = `cal-estado-fila cal-estado-fila--${datos.estado_clave}`;
        return;
      }
      elemento.textContent = valor || (elemento.classList.contains('cal-promedio') ? 'Sin calificar' : '—');
    });
  };

  const resumenDeErrores = () => {
    errores = tabla.querySelectorAll('td.is-error').length;
    return errores ? ` ${errores} celda${errores === 1 ? '' : 's'} con error: pasa el cursor sobre ella${errores === 1 ? '' : 's'} para ver por qué.` : '';
  };

  async function enviar() {
    if (enviando || !pendientes.size) return;
    enviando = new Map(pendientes);
    pendientes.clear();
    avisar(`Guardando ${enviando.size} calificaci${enviando.size === 1 ? 'ón' : 'ones'}…`, 'info');
    let respuesta;
    let datos = null;
    try {
      respuesta = await fetch(urlGuardar, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' },
        body: JSON.stringify({ cambios: [...enviando.values()] }),
        credentials: 'same-origin',
      });
      datos = await respuesta.json().catch(() => null);
    } catch (error) {
      respuesta = null;
    }

    if (!respuesta || respuesta.status >= 500 || (!datos && respuesta.ok)) {
      /* Sin conexión o falla del servidor: lo enviado vuelve a la cola (sin pisar algo más nuevo) */
      enviando.forEach((cambio, clave) => { if (!pendientes.has(clave)) pendientes.set(clave, cambio); });
      enviando = null;
      guardarLocal();
      avisar(`No se pudo guardar (sin conexión o error del servidor). ${pendientes.size} cambio${pendientes.size === 1 ? '' : 's'} se conserva${pendientes.size === 1 ? '' : 'n'} para reintentar.`, 'error', true);
      return;
    }
    if (!datos || !datos.resultados) {
      /* El acta ya no admite capturas (se cerró, cambió el periodo…) o la sesión terminó */
      enviando.forEach((cambio, clave) => { const celda = porClave.get(clave); if (celda) marcar(celda, 'error', datos?.mensaje || 'No se guardó.'); });
      enviando = null;
      guardarLocal();
      avisar(datos?.mensaje || 'No se guardó. Recarga la página.', 'error');
      return;
    }

    datos.resultados.forEach((resultado) => {
      const celda = porClave.get(resultado.clave);
      enviando.delete(resultado.clave);
      if (!celda) return;
      if (resultado.ok) {
        celda.dataset.anterior = resultado.valor;
        const nuevo = pendientes.get(resultado.clave);
        if (nuevo) nuevo.anterior = celda.dataset.anterior;
        else {
          if (celda.type !== 'checkbox' && document.activeElement !== celda) celda.value = resultado.valor;
          marcar(celda, 'guardada');
        }
      } else {
        marcar(celda, 'error', resultado.error);
      }
    });
    Object.entries(datos.filas || {}).forEach(([inscripcion, fila]) => actualizarFila(inscripcion, fila));
    enviando = null;
    guardarLocal();
    const conError = resumenDeErrores();
    avisar(conError ? `Se guardó lo demás.${conError}` : 'Guardado.', conError ? 'error' : 'ok');
    if (!conError) window.setTimeout(() => { if (!pendientes.size && !enviando && !resumenDeErrores()) avisar(''); }, 2500);
    if (pendientes.size) programar(100);
  }

  /* Cambios de antes que no se guardaron (p. ej., se perdió la conexión y se recargó la página) */
  try {
    const guardados = JSON.parse(sessionStorage.getItem(claveLocal) || '[]');
    let restaurados = 0;
    guardados.forEach((cambio) => {
      const celda = porClave.get(cambio.clave);
      if (!celda || celda.disabled) return;
      if (celda.type === 'checkbox') celda.checked = cambio.valor === '1';
      else celda.value = cambio.valor;
      pendientes.set(cambio.clave, cambio);
      marcar(celda, 'pendiente');
      restaurados += 1;
    });
    if (restaurados) {
      avisar(`Hay ${restaurados} cambio${restaurados === 1 ? '' : 's'} sin guardar de la última vez.`, 'error', true, true);
    }
  } catch (error) { /* sin almacenamiento */ }

  botonReintentar?.addEventListener('click', () => enviar());
  botonDescartar?.addEventListener('click', () => {
    pendientes.forEach((cambio, clave) => {
      const celda = porClave.get(clave);
      if (!celda) return;
      if (celda.type === 'checkbox') celda.checked = celda.dataset.anterior === '1';
      else celda.value = celda.dataset.anterior;
      marcar(celda, '');
    });
    pendientes.clear();
    guardarLocal();
    avisar('');
  });
  window.addEventListener('online', () => { if (pendientes.size) enviar(); });
  window.addEventListener('beforeunload', (evento) => {
    if (pendientes.size || enviando) {
      guardarLocal();
      evento.preventDefault();
      evento.returnValue = '';
    }
  });

  tabla.addEventListener('change', (evento) => {
    if (evento.target.matches('[data-celda]')) procesar(evento.target);
  });

  /* --- Teclado ---------------------------------------------------------------------------------------------------- */
  const posicion = (celda) => {
    for (let fila = 0; fila < rejilla.length; fila += 1) {
      const columna = rejilla[fila].indexOf(celda);
      if (columna !== -1) return [fila, columna];
    }
    return null;
  };
  const ir = (fila, columna) => {
    const destino = rejilla[fila]?.[columna];
    if (destino) {
      destino.focus();
      destino.select();
    }
  };

  tabla.addEventListener('focusin', (evento) => {
    if (evento.target.matches('input.cal-entrada')) evento.target.select();
  });

  tabla.addEventListener('keydown', (evento) => {
    const celda = evento.target;
    if (!celda.matches('input.cal-entrada')) return;
    const lugar = posicion(celda);
    if (!lugar) return;
    const [fila, columna] = lugar;
    const todoSeleccionado = celda.selectionStart === 0 && celda.selectionEnd === celda.value.length;
    if (evento.key === 'ArrowDown' || evento.key === 'Enter') {
      evento.preventDefault();
      if (evento.key === 'Enter' && evento.shiftKey) ir(fila - 1, columna);
      else ir(fila + 1, columna);
    } else if (evento.key === 'ArrowUp') {
      evento.preventDefault();
      ir(fila - 1, columna);
    } else if (evento.key === 'ArrowLeft' && (todoSeleccionado || celda.selectionStart === 0)) {
      evento.preventDefault();
      ir(fila, columna - 1);
    } else if (evento.key === 'ArrowRight' && (todoSeleccionado || celda.selectionEnd === celda.value.length)) {
      evento.preventDefault();
      ir(fila, columna + 1);
    } else if (evento.key === 'Escape') {
      celda.value = celda.dataset.anterior;
      pendientes.delete(celda.dataset.clave);
      marcar(celda, '');
      guardarLocal();
    }
  });

  /* --- Pegar un rango desde Excel ----------------------------------------------------------------------------------- */
  tabla.addEventListener('paste', (evento) => {
    const celda = evento.target;
    if (!celda.matches('input.cal-entrada')) return;
    const texto = (evento.clipboardData || window.clipboardData)?.getData('text') || '';
    if (!/[\t\n\r]/.test(texto.trim())) return;   // un solo valor: se pega normal
    evento.preventDefault();
    const lugar = posicion(celda);
    if (!lugar) return;
    const renglones = texto.replace(/\r/g, '').split('\n');
    if (renglones[renglones.length - 1] === '') renglones.pop();
    let pegados = 0;
    let conError = 0;
    let fuera = 0;
    renglones.forEach((renglon, i) => {
      renglon.split('\t').forEach((valor, j) => {
        const destino = rejilla[lugar[0] + i]?.[lugar[1] + j];
        if (!destino || destino.disabled) { fuera += 1; return; }
        destino.value = valor.trim();
        if (procesar(destino)) pegados += 1;
        else conError += 1;
      });
    });
    const partes = [`Se pegaron ${pegados} valor${pegados === 1 ? '' : 'es'}`];
    if (conError) partes.push(`${conError} con error (no se guardan hasta corregirlos)`);
    if (fuera) partes.push(`${fuera} quedaron fuera de la tabla`);
    avisar(`${partes.join(', ')}.`, conError ? 'error' : 'info');
  });
})();
