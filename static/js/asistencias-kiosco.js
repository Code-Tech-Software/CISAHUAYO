/* CISAHUAYO · pantalla de la entrada

   El alumno acerca su credencial al lector RFID (que "teclea" el UID y pulsa Enter) o escribe su número de referencia.
   - Un campo oculto mantiene siempre el foco para recibir al lector, aunque nadie toque la pantalla.
   - Cada lectura se envía al servidor (asistencias:registrar_entrada) y el panel muestra el resultado SOLO unos segundos:
     se quita solo, y también al tocarlo, al teclear, al escanear a otro alumno o con Escape, para dejar libre la pantalla
     al siguiente (o a quien quiera intentarlo otra vez).
   - La pantalla nunca muestra a quienes ya entraron: solo el resultado de quien acaba de escanear y cuántos han entrado.
   - Cada 30 s se consulta el estado (contadores) y se detecta si ya cambió el día o terminó la sesión.
   El servidor decide todo (estado, retardo, materias); aquí solo se muestra.
*/
(() => {
  'use strict';

  const kiosco = document.querySelector('[data-kiosk]');
  if (!kiosco) return;

  const qs = (selector, ambito = kiosco) => ambito.querySelector(selector);
  const panel = qs('[data-panel]');
  const tarjeta = qs('[data-descartar]');
  const cuenta = qs('[data-cuenta]');
  const escaner = qs('[data-escaner]');
  const manual = qs('[data-manual]');
  const referencia = qs('[data-referencia]');
  const conexion = qs('[data-conexion]');
  const token = qs('input[name="csrfmiddlewaretoken"]').value;
  const sinClases = Boolean(kiosco.dataset.sinClases);

  /* Cuánto se queda cada aviso (ms). Cortos a propósito: hay una fila de alumnos esperando; el de retardo dura un poco
     más para que se alcance a leer. */
  const MOSTRAR_MS = { success: 2200, late: 3200, info: 2200, error: 2800 };
  const GUARDA_MS = 450;        /* tras mostrar un resultado se ignoran teclas sueltas del propio lector */
  const REPETIDA_MS = 3000;     /* la misma tarjeta, todavía sobre el lector */
  const SONDEO_MS = 30000;

  let temporizador = null;
  let mostradoEn = 0;
  let ocupado = false;
  let ultimo = { codigo: '', momento: 0 };
  const cola = [];

  /* ------------------------------------------------------------------ Reloj */
  /* Muestra la hora del servidor (la que decide los retardos): parte de la que llegó con la página y se
     vuelve a sincronizar con cada respuesta, así no depende del reloj ni de la zona horaria del equipo. */
  const reloj = qs('[data-reloj]');
  let base = Number(kiosco.dataset.ahora);
  let desde = performance.now();
  const sincronizar = (segundos) => {
    if (!Number.isFinite(segundos)) return;
    base = segundos;
    desde = performance.now();
  };
  const dosDigitos = (numero) => String(numero).padStart(2, '0');
  const pintarReloj = () => {
    const segundos = Math.floor(base + (performance.now() - desde) / 1000) % 86400;
    reloj.textContent = `${dosDigitos(Math.floor(segundos / 3600))}:${dosDigitos(Math.floor((segundos % 3600) / 60))}`;
  };
  pintarReloj();
  window.setInterval(pintarReloj, 1000);

  /* ------------------------------------------------------------------ Sonido */
  const botonSonido = qs('[data-sonido]');
  let sonidoActivo = true;
  try {
    sonidoActivo = window.localStorage.getItem('cisahuayo.kiosco-sonido') !== '0';
  } catch (error) {
    /* Sin almacenamiento: el sonido queda activado. */
  }
  const pintarSonido = () => {
    botonSonido.setAttribute('aria-pressed', String(sonidoActivo));
    qs('[data-sonido-texto]', botonSonido).textContent = sonidoActivo ? 'Sonido activado' : 'Sonido apagado';
  };
  pintarSonido();
  botonSonido.addEventListener('click', () => {
    sonidoActivo = !sonidoActivo;
    pintarSonido();
    try {
      window.localStorage.setItem('cisahuayo.kiosco-sonido', sonidoActivo ? '1' : '0');
    } catch (error) {
      /* Se pierde solo la preferencia. */
    }
  });

  let audio = null;
  const SONIDOS = { success: [660, 880], late: [520, 520], info: [600], error: [240, 180] };
  const sonar = (tono) => {
    if (!sonidoActivo) return;
    try {
      audio = audio ?? new (window.AudioContext || window.webkitAudioContext)();
      const inicio = audio.currentTime;
      (SONIDOS[tono] ?? []).forEach((frecuencia, indice) => {
        const oscilador = audio.createOscillator();
        const ganancia = audio.createGain();
        const t = inicio + indice * 0.14;
        oscilador.type = 'sine';
        oscilador.frequency.value = frecuencia;
        ganancia.gain.setValueAtTime(0.0001, t);
        ganancia.gain.exponentialRampToValueAtTime(0.22, t + 0.02);
        ganancia.gain.exponentialRampToValueAtTime(0.0001, t + 0.2);
        oscilador.connect(ganancia).connect(audio.destination);
        oscilador.start(t);
        oscilador.stop(t + 0.24);
      });
    } catch (error) {
      /* Sin audio disponible: la pantalla ya comunica el resultado. */
    }
  };

  /* ------------------------------------------------------------------ Estado de la conexión */
  const pintarConexion = (enLinea) => {
    conexion.textContent = enLinea ? 'En línea' : 'Sin conexión';
    conexion.classList.toggle('is-offline', !enLinea);
  };

  /* ------------------------------------------------------------------ Panel */
  const vistaBase = () => (sinClases ? 'sin-clases' : 'espera');

  /* Quita el resultado y deja la pantalla lista para el siguiente */
  const descartar = () => {
    window.clearTimeout(temporizador);
    if (panel.dataset.vista !== 'resultado') return;
    panel.dataset.vista = vistaBase();
    panel.dataset.tono = '';
    cuenta.classList.remove('is-running');
    enfocar();
  };

  const avatar = (alumno) => {
    const contenedor = qs('[data-avatar]');
    contenedor.replaceChildren();
    contenedor.hidden = !alumno;   /* si no se sabe quién es (código desconocido) no se muestra ninguna foto */
    tarjeta.classList.toggle('kiosk__state--sin-foto', !alumno);
    if (!alumno) return;
    const marca = document.createElement('span');
    if (alumno.foto) {
      marca.className = 'avatar';
      const imagen = document.createElement('img');
      imagen.className = 'avatar__img';
      imagen.alt = '';
      imagen.src = alumno.foto;
      marca.append(imagen);
    } else {
      marca.className = `avatar avatar--soft avatar--tone-${alumno.tono ?? 1}`;
      marca.textContent = alumno.iniciales ?? '?';
    }
    contenedor.append(marca);
  };

  const ETIQUETAS = {
    REGISTRADA: 'Entrada registrada',
    YA_REGISTRADA: 'Ya registrada',
    CON_FALTA: 'Falta registrada',
    NO_ENCONTRADO: 'No encontrada',
    SIN_INSCRIPCION: 'Sin inscripción',
    SIN_CLASES: 'Sin clases',
    VACIO: 'Sin código',
  };

  const tonoDe = (datos) => {
    if (!datos.ok) return 'error';
    if (datos.tipo === 'YA_REGISTRADA') return 'info';
    return datos.estado === 'RETARDO' ? 'late' : 'success';
  };

  const mostrar = (datos) => {
    if (datos.tipo === 'SESION') {
      qs('[data-mensaje-sesion]').textContent = datos.mensaje;
      panel.dataset.vista = 'sesion';
      panel.dataset.tono = '';
      return;
    }
    const tono = tonoDe(datos);
    avatar(datos.alumno);
    qs('[data-etiqueta]').textContent = datos.tipo === 'REGISTRADA' && datos.estado === 'RETARDO'
      ? 'Entrada con retardo'
      : (ETIQUETAS[datos.tipo] ?? (datos.ok ? 'Listo' : 'No registrada'));
    qs('[data-nombre]').textContent = datos.alumno?.nombre ?? '';
    qs('[data-grado]').textContent = datos.alumno?.grado ?? '';
    qs('[data-mensaje]').textContent = datos.mensaje ?? '';
    qs('[data-hora]').textContent = datos.ok && datos.hora ? `Hora de entrada: ${datos.hora}` : '';

    const duracion = MOSTRAR_MS[tono];
    panel.style.setProperty('--duracion', `${duracion}ms`);
    panel.dataset.tono = tono;
    panel.dataset.vista = 'resultado';
    /* La barra de tiempo reinicia aunque un resultado reemplace a otro sin pasar por la pantalla de espera */
    cuenta.classList.remove('is-running');
    void cuenta.offsetWidth;
    cuenta.classList.add('is-running');

    mostradoEn = Date.now();
    sonar(tono);
    window.clearTimeout(temporizador);
    temporizador = window.setTimeout(descartar, duracion);
  };

  /* ------------------------------------------------------------------ Contadores */
  const pintarResumen = (resumen) => {
    if (!resumen) return;
    sincronizar(resumen.ahora);
    qs('[data-entraron]').textContent = resumen.entraron;
    qs('[data-inscritos]').textContent = resumen.inscritos;
    const barra = qs('[data-progreso]');
    barra.max = Math.max(resumen.inscritos, 1);
    barra.value = resumen.entraron;
  };

  /* ------------------------------------------------------------------ Envío al servidor */
  const peticion = async (url, opciones = {}) => {
    const respuesta = await fetch(url, {
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': token, 'X-Requested-With': 'XMLHttpRequest' },
      ...opciones,
    });
    return respuesta.json();
  };

  const enviar = async (codigo, modo) => {
    codigo = codigo.trim();
    if (!codigo) return;
    const ahora = Date.now();
    if (codigo === ultimo.codigo && ahora - ultimo.momento < REPETIDA_MS) return;
    ultimo = { codigo, momento: ahora };
    if (ocupado) {
      cola.push([codigo, modo]);
      return;
    }

    ocupado = true;
    try {
      const datos = await peticion(kiosco.dataset.registrarUrl, { method: 'POST', body: new URLSearchParams({ codigo, modo }) });
      pintarConexion(true);
      mostrar(datos);
      pintarResumen(datos.resumen);
      if (!datos.ok) {
        ultimo = { codigo: '', momento: 0 };   /* quien se equivocó puede intentarlo otra vez de inmediato */
        if (datos.tipo === 'NO_ENCONTRADO' && modo === 'referencia') {
          referencia.value = codigo;           /* y corregir su número sin escribirlo de nuevo */
        }
      }
    } catch (error) {
      pintarConexion(false);
      ultimo = { codigo: '', momento: 0 };
      mostrar({ ok: false, tipo: 'ERROR', mensaje: 'No hay conexión con el servidor. Intenta de nuevo en un momento.' });
    } finally {
      ocupado = false;
      if (cola.length) enviar(...cola.shift());
    }
  };

  const sondear = async () => {
    try {
      const datos = await peticion(kiosco.dataset.estadoUrl);
      pintarConexion(true);
      if (datos.tipo === 'SESION') {
        mostrar(datos);
        return;
      }
      if (datos.fecha && datos.fecha !== kiosco.dataset.fecha) {   /* amaneció: nuevo día, nuevos contadores */
        window.location.reload();
        return;
      }
      pintarResumen(datos);
    } catch (error) {
      pintarConexion(false);
    }
  };
  window.setInterval(sondear, SONDEO_MS);

  /* ------------------------------------------------------------------ Foco y entradas */
  function enfocar() {
    if (document.activeElement === referencia || panel.dataset.vista === 'sesion') return;
    escaner.focus({ preventScroll: true });
  }

  escaner.addEventListener('keydown', (evento) => {
    if (evento.key !== 'Enter') return;
    evento.preventDefault();
    const codigo = escaner.value;
    escaner.value = '';
    enviar(codigo, 'uid');
  });
  escaner.addEventListener('blur', () => window.setTimeout(enfocar, 150));
  referencia.addEventListener('blur', () => window.setTimeout(enfocar, 400));

  /* El resultado se quita en cuanto alguien hace algo: tocarlo, teclear (el lector del siguiente alumno o la referencia),
     enfocar el campo de la referencia o Escape. Las teclas que llegan justo después de mostrarlo se ignoran: algunos
     lectores mandan un salto de línea extra y quitarían el aviso antes de leerse. */
  tarjeta.addEventListener('click', descartar);
  document.addEventListener('keydown', (evento) => {
    if (panel.dataset.vista !== 'resultado') return;
    if (evento.key === 'Escape' || Date.now() - mostradoEn > GUARDA_MS) descartar();
  });
  referencia.addEventListener('focus', descartar);

  document.addEventListener('click', (evento) => {
    if (!evento.target.closest('[data-manual], a, button')) enfocar();
  });

  manual.addEventListener('submit', (evento) => {
    evento.preventDefault();
    const codigo = referencia.value;
    referencia.value = '';
    enviar(codigo, 'referencia');
  });

  /* Teclado en pantalla (para pantallas táctiles sin teclado) */
  const teclado = qs('[data-teclado]');
  const alternarTeclado = qs('[data-teclado-alternar]');
  alternarTeclado.addEventListener('click', () => {
    const mostrarlo = teclado.hidden;
    teclado.hidden = !mostrarlo;
    alternarTeclado.setAttribute('aria-expanded', String(mostrarlo));
    alternarTeclado.textContent = mostrarlo ? 'Ocultar teclado en pantalla' : 'Mostrar teclado en pantalla';
  });
  teclado.addEventListener('click', (evento) => {
    const tecla = evento.target.closest('[data-tecla]');
    if (tecla) {
      referencia.value += tecla.dataset.tecla;
      descartar();
    } else if (evento.target.closest('[data-tecla-borrar]')) {
      referencia.value = referencia.value.slice(0, -1);
    }
  });

  /* Pantalla completa */
  const botonPantalla = qs('[data-pantalla-completa]');
  if (!document.documentElement.requestFullscreen) botonPantalla.hidden = true;
  botonPantalla.addEventListener('click', () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen().catch(() => {});
  });
  document.addEventListener('fullscreenchange', () => {
    qs('[data-pantalla-completa-texto]').textContent = document.fullscreenElement ? 'Salir de pantalla completa' : 'Pantalla completa';
  });

  enfocar();
})();
