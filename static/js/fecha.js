/* Selector de fecha: cada <input type="date"> del sitio se ve como un campo con la fecha escrita («lun 12 oct 2026»)
   que abre un calendario; un clic en el día lo elige y lo cierra. El título del mes lleva a los meses del año y de ahí
   a los años: así se llega rápido a fechas lejanas, como la de nacimiento (ese campo, si está vacío, abre en los años).

   - El campo y lo que otros scripts le hagan al <input> los resuelve window.CISAHUAYO.pickers (static/js/app.js);
     sin JavaScript se ve el del navegador. Los campos que llegan después (formularios en ventana) se mejoran solos.
   - Respeta min y max (días, meses y años fuera quedan desactivados); marca hoy y atenúa sábados y domingos.
   - «Hoy» elige la fecha de hoy y «Borrar» la quita (solo si el campo no es obligatorio).
   - Los dos campos de un rango ([data-rango-fechas], en la asistencia del docente) los atiende static/js/calendario.js.
   - Teclado: flechas (día y semana), Re Pág / Av Pág (mes; con Mayús, año), Inicio / Fin (semana), Enter, Escape.
   Estilos: .campo-fecha y .calendario en static/css/app.css. */
(() => {
  const base = window.CISAHUAYO?.pickers;
  if (!base || !HTMLElement.prototype.showPopover) return;   /* sin eso queda el campo del navegador */

  const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
  const MESES_CORTOS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
  const DIAS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
  const DIAS_CORTOS = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'];
  const INICIALES = ['L', 'M', 'M', 'J', 'V', 'S', 'D'];
  const icono = (nombre) => window.CISAHUAYO.icon(nombre);

  /* Fechas sin hora, en la zona local (un «2026-10-12» nunca se corre de día) */
  const leer = (texto) => {
    const partes = /^(\d{4})-(\d{2})-(\d{2})$/.exec(texto || '');
    return partes ? new Date(Number(partes[1]), Number(partes[2]) - 1, Number(partes[3])) : null;
  };
  const iso = (fecha) => `${fecha.getFullYear()}-${String(fecha.getMonth() + 1).padStart(2, '0')}-${String(fecha.getDate()).padStart(2, '0')}`;
  const sumarDias = (fecha, dias) => new Date(fecha.getFullYear(), fecha.getMonth(), fecha.getDate() + dias);
  const mismoDia = (a, b) => Boolean(a && b) && a.getTime() === b.getTime();
  const primeroDelMes = (fecha) => new Date(fecha.getFullYear(), fecha.getMonth(), 1);
  const diasDelMes = (anio, mes) => new Date(anio, mes + 1, 0).getDate();
  /* El mismo día en otro mes (o año); si ese mes es más corto, su último día */
  const moverMeses = (fecha, meses) => {
    const destino = new Date(fecha.getFullYear(), fecha.getMonth() + meses, 1);
    return new Date(destino.getFullYear(), destino.getMonth(), Math.min(fecha.getDate(), diasDelMes(destino.getFullYear(), destino.getMonth())));
  };
  const corta = (fecha) => `${DIAS_CORTOS[fecha.getDay()]} ${fecha.getDate()} ${MESES_CORTOS[fecha.getMonth()]} ${fecha.getFullYear()}`;
  const larga = (fecha) => `${DIAS[fecha.getDay()]} ${fecha.getDate()} de ${MESES[fecha.getMonth()]} de ${fecha.getFullYear()}`;
  const hoyDe = () => {
    const ahora = new Date();
    return new Date(ahora.getFullYear(), ahora.getMonth(), ahora.getDate());
  };

  /* --- El calendario: uno solo, compartido por todos los campos ------------------------------------------- */
  const calendario = document.createElement('div');
  calendario.className = 'calendario calendario--emergente';
  calendario.setAttribute('popover', 'manual');
  calendario.setAttribute('role', 'dialog');
  calendario.innerHTML = `
    <p class="calendario__para" data-calendario-para></p>
    <div class="calendario__cabecera">
      <button type="button" class="calendario__nav" data-paso="-1"></button>
      <button type="button" class="calendario__titulo" data-cambiar-vista><span data-calendario-titulo></span></button>
      <button type="button" class="calendario__nav" data-paso="1"></button>
    </div>
    <table class="calendario__tabla" role="grid" data-vista-dias>
      <thead><tr>${INICIALES.map((inicial, i) => `<th scope="col" abbr="${DIAS[(i + 1) % 7]}">${inicial}</th>`).join('')}</tr></thead>
      <tbody></tbody>
    </table>
    <div class="calendario__rejilla" role="group" data-vista-rejilla hidden></div>
    <div class="calendario__pie">
      <button type="button" class="btn btn--ghost btn--sm" data-hoy>Hoy</button>
      <button type="button" class="btn btn--ghost btn--sm" data-borrar>Borrar</button>
    </div>`;
  document.body.append(calendario);
  const para = calendario.querySelector('[data-calendario-para]');
  const [anterior, siguiente] = calendario.querySelectorAll('[data-paso]');
  anterior.append(icono('chevron-left'));
  siguiente.append(icono('chevron-right'));
  const botonTitulo = calendario.querySelector('[data-cambiar-vista]');
  botonTitulo.append(icono('chevron-down'));
  const titulo = calendario.querySelector('[data-calendario-titulo]');
  const tabla = calendario.querySelector('[data-vista-dias]');
  const cuerpo = tabla.querySelector('tbody');
  const rejilla = calendario.querySelector('[data-vista-rejilla]');
  const botonHoy = calendario.querySelector('[data-hoy]');
  const botonBorrar = calendario.querySelector('[data-borrar]');

  /* { entrada, boton, vista: 'dias'|'meses'|'anios', mes, foco, elegida, minimo, maximo, hoy } mientras está abierto.
     mes: el primer día del mes a la vista; foco: el día (o, en las otras vistas, el mes o el año) que tiene el foco. */
  let estado = null;

  const permitido = (fecha) => (!estado.minimo || fecha >= estado.minimo) && (!estado.maximo || fecha <= estado.maximo);
  const ajustar = (fecha) => {
    if (estado.minimo && fecha < estado.minimo) return estado.minimo;
    if (estado.maximo && fecha > estado.maximo) return estado.maximo;
    return fecha;
  };
  /* Un mes (o un año) se puede elegir si alguno de sus días está permitido */
  const mesPermitido = (anio, mes) => (!estado.minimo || new Date(anio, mes + 1, 0) >= estado.minimo)
    && (!estado.maximo || new Date(anio, mes, 1) <= estado.maximo);
  const anioPermitido = (anio) => (!estado.minimo || anio >= estado.minimo.getFullYear()) && (!estado.maximo || anio <= estado.maximo.getFullYear());

  const celda = (texto, datos, { elegida, actual, activa, desactivada, etiqueta }) => {
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.className = `calendario__celda${elegida ? ' is-elegido' : ''}${actual ? ' is-actual' : ''}`;
    Object.assign(boton.dataset, datos);
    boton.tabIndex = activa ? 0 : -1;
    boton.disabled = desactivada;
    boton.setAttribute('aria-pressed', String(elegida));
    if (etiqueta) boton.setAttribute('aria-label', etiqueta);
    boton.textContent = texto;
    return boton;
  };

  const dibujarDias = () => {
    const { mes, elegida, hoy } = estado;
    /* El día que recibe el foco con Tab: el activo si está en este mes; si no, el primero permitido del mes */
    let foco = estado.foco;
    if (foco.getMonth() !== mes.getMonth() || foco.getFullYear() !== mes.getFullYear()) {
      foco = ajustar(mes);
      if (foco.getMonth() !== mes.getMonth()) foco = mes;
    }
    titulo.textContent = `${MESES[mes.getMonth()]} ${mes.getFullYear()}`;
    botonTitulo.setAttribute('aria-label', `${MESES[mes.getMonth()]} de ${mes.getFullYear()}: elegir otro mes`);
    anterior.setAttribute('aria-label', 'Mes anterior');
    siguiente.setAttribute('aria-label', 'Mes siguiente');
    anterior.disabled = Boolean(estado.minimo && sumarDias(mes, -1) < estado.minimo);
    siguiente.disabled = Boolean(estado.maximo && new Date(mes.getFullYear(), mes.getMonth() + 1, 1) > estado.maximo);

    /* Siempre seis semanas desde el lunes de la primera: el calendario no cambia de alto al pasar de mes */
    const filas = [];
    let dia = sumarDias(mes, -((mes.getDay() + 6) % 7));
    for (let semana = 0; semana < 6; semana += 1) {
      const celdas = [];
      for (let i = 0; i < 7; i += 1) {
        const fecha = dia;
        const clases = ['calendario__dia'];
        if (fecha.getMonth() !== mes.getMonth()) clases.push('is-otro-mes');
        if (fecha.getDay() === 0 || fecha.getDay() === 6) clases.push('is-finde');
        if (mismoDia(fecha, hoy)) clases.push('is-hoy');
        const esElegida = mismoDia(fecha, elegida);
        if (esElegida) clases.push('is-elegido');
        celdas.push(`<td role="gridcell" aria-selected="${esElegida}"><button type="button" class="${clases.join(' ')}"
          data-fecha="${iso(fecha)}" tabindex="${mismoDia(fecha, foco) ? 0 : -1}" aria-label="${larga(fecha)}${mismoDia(fecha, hoy) ? ', hoy' : ''}"
          ${permitido(fecha) ? '' : 'disabled'}>${fecha.getDate()}</button></td>`);
        dia = sumarDias(dia, 1);
      }
      filas.push(`<tr>${celdas.join('')}</tr>`);
    }
    cuerpo.innerHTML = filas.join('');
  };

  const dibujarMeses = () => {
    const { mes, elegida, hoy } = estado;
    const anio = mes.getFullYear();
    titulo.textContent = String(anio);
    botonTitulo.setAttribute('aria-label', `${anio}: elegir otro año`);
    anterior.setAttribute('aria-label', 'Año anterior');
    siguiente.setAttribute('aria-label', 'Año siguiente');
    anterior.disabled = !anioPermitido(anio - 1);
    siguiente.disabled = !anioPermitido(anio + 1);
    rejilla.setAttribute('aria-label', `Meses de ${anio}`);
    rejilla.replaceChildren(...MESES_CORTOS.map((corto, i) => celda(corto, { mesDelAnio: String(i) }, {
      elegida: Boolean(elegida) && elegida.getFullYear() === anio && elegida.getMonth() === i,
      actual: hoy.getFullYear() === anio && hoy.getMonth() === i,
      activa: i === mes.getMonth(),
      desactivada: !mesPermitido(anio, i),
      etiqueta: `${MESES[i]} de ${anio}`,
    })));
  };

  const dibujarAnios = () => {
    const { mes, elegida, hoy } = estado;
    const inicio = Math.floor(mes.getFullYear() / 12) * 12;
    titulo.textContent = `${inicio} – ${inicio + 11}`;
    botonTitulo.setAttribute('aria-label', `De ${inicio} a ${inicio + 11}`);
    anterior.setAttribute('aria-label', 'Años anteriores');
    siguiente.setAttribute('aria-label', 'Años siguientes');
    anterior.disabled = !anioPermitido(inicio - 1);
    siguiente.disabled = !anioPermitido(inicio + 12);
    rejilla.setAttribute('aria-label', 'Años');
    rejilla.replaceChildren(...Array.from({ length: 12 }, (_, i) => {
      const anio = inicio + i;
      return celda(String(anio), { anio: String(anio) }, {
        elegida: Boolean(elegida) && elegida.getFullYear() === anio,
        actual: hoy.getFullYear() === anio,
        activa: anio === mes.getFullYear(),
        desactivada: !anioPermitido(anio),
      });
    }));
  };

  const dibujar = () => {
    const { vista } = estado;
    tabla.hidden = vista !== 'dias';
    rejilla.hidden = vista === 'dias';
    calendario.dataset.vista = vista;
    botonTitulo.setAttribute('aria-disabled', String(vista === 'anios'));
    if (vista === 'dias') dibujarDias();
    else if (vista === 'meses') dibujarMeses();
    else dibujarAnios();
    if (calendario.matches(':popover-open')) base.place(calendario, estado.boton);
  };

  /* Pone el foco en lo que toca de la vista (el día, el mes o el año activo) */
  const enfocarActivo = () => {
    const contenedor = estado.vista === 'dias' ? cuerpo : rejilla;
    (contenedor.querySelector('[tabindex="0"]:not(:disabled)') || contenedor.querySelector('button:not(:disabled)'))?.focus({ preventScroll: true });
  };

  const irADia = (fecha) => {
    const destino = ajustar(fecha);
    estado.foco = destino;
    estado.mes = primeroDelMes(destino);
    dibujar();
    enfocarActivo();
  };

  const cerrar = (devolverFoco = true) => {
    if (!estado) return;
    const { boton } = estado;
    estado = null;
    if (calendario.matches(':popover-open')) calendario.hidePopover();
    boton.setAttribute('aria-expanded', 'false');
    if (devolverFoco && boton.isConnected) boton.focus();
  };

  const poner = (valor) => {
    const { entrada } = estado;
    if (entrada.value !== valor) {
      entrada.value = valor;
      entrada.dispatchEvent(new Event('input', { bubbles: true }));
      entrada.dispatchEvent(new Event('change', { bubbles: true }));
    }
    cerrar();
  };

  const abrir = (entrada, boton) => {
    if (estado?.entrada === entrada) {
      cerrar();
      return;
    }
    cerrar(false);
    const hoy = hoyDe();
    const elegida = leer(entrada.value);
    estado = { entrada, boton, vista: 'dias', elegida, hoy, minimo: leer(entrada.min), maximo: leer(entrada.max) };
    const inicial = ajustar(elegida || hoy);
    estado.foco = inicial;
    estado.mes = primeroDelMes(inicial);
    /* La fecha de nacimiento, si está vacía, empieza por el año */
    if (!elegida && /nacimiento/.test(entrada.name)) estado.vista = 'anios';
    const etiqueta = boton.labels?.[0]?.textContent.replace(/\s+/g, ' ').replace(/\s*\*$/, '').trim() || '';
    para.textContent = etiqueta;
    para.hidden = !etiqueta;
    calendario.setAttribute('aria-label', etiqueta || 'Elegir fecha');
    botonHoy.disabled = !permitido(hoy);
    botonBorrar.hidden = entrada.required || !entrada.value;
    dibujar();
    base.show(calendario, entrada, boton);
    boton.setAttribute('aria-expanded', 'true');
    enfocarActivo();
  };

  /* --- Eventos del calendario ------------------------------------------------------------------------------- */
  calendario.addEventListener('click', (evento) => {
    if (!estado) return;
    const objetivo = evento.target.closest('button');
    if (!objetivo || objetivo.disabled) return;
    const { vista, mes } = estado;
    if (objetivo.dataset.paso) {
      const paso = Number(objetivo.dataset.paso);
      if (vista === 'dias') estado.mes = new Date(mes.getFullYear(), mes.getMonth() + paso, 1);
      else if (vista === 'meses') estado.mes = new Date(mes.getFullYear() + paso, mes.getMonth(), 1);
      else estado.mes = new Date(mes.getFullYear() + paso * 12, mes.getMonth(), 1);
      estado.foco = ajustar(moverMeses(estado.foco, (estado.mes.getFullYear() - mes.getFullYear()) * 12 + estado.mes.getMonth() - mes.getMonth()));
      dibujar();
    } else if (objetivo.hasAttribute('data-cambiar-vista')) {
      if (vista === 'anios') return;
      estado.vista = vista === 'dias' ? 'meses' : 'anios';
      dibujar();
      enfocarActivo();
    } else if (objetivo.dataset.fecha) {
      poner(objetivo.dataset.fecha);
    } else if (objetivo.dataset.mesDelAnio) {
      const destino = new Date(mes.getFullYear(), Number(objetivo.dataset.mesDelAnio), 1);
      estado.vista = 'dias';
      irADia(new Date(destino.getFullYear(), destino.getMonth(), Math.min(estado.foco.getDate(), diasDelMes(destino.getFullYear(), destino.getMonth()))));
    } else if (objetivo.dataset.anio) {
      estado.mes = new Date(Number(objetivo.dataset.anio), mes.getMonth(), 1);
      estado.vista = 'meses';
      dibujar();
      enfocarActivo();
    } else if (objetivo.hasAttribute('data-hoy')) {
      poner(iso(estado.hoy));
    } else if (objetivo.hasAttribute('data-borrar')) {
      poner('');
    }
  });

  calendario.addEventListener('keydown', (evento) => {
    if (!estado) return;
    if (evento.key === 'Escape') {
      evento.preventDefault();
      evento.stopPropagation();                   /* cierra el calendario, no la ventana del formulario */
      cerrar();
      return;
    }
    const dia = evento.target.closest('[data-fecha]');
    if (dia) {
      const fecha = leer(dia.dataset.fecha);
      const lunes = sumarDias(fecha, -((fecha.getDay() + 6) % 7));
      const saltos = {
        ArrowLeft: () => sumarDias(fecha, -1),
        ArrowRight: () => sumarDias(fecha, 1),
        ArrowUp: () => sumarDias(fecha, -7),
        ArrowDown: () => sumarDias(fecha, 7),
        Home: () => lunes,
        End: () => sumarDias(lunes, 6),
        PageUp: () => moverMeses(fecha, evento.shiftKey ? -12 : -1),
        PageDown: () => moverMeses(fecha, evento.shiftKey ? 12 : 1),
      };
      if (saltos[evento.key]) {
        evento.preventDefault();
        irADia(saltos[evento.key]());
      } else if (evento.key === 'Enter' || evento.key === ' ') {
        evento.preventDefault();
        if (!dia.disabled) poner(dia.dataset.fecha);
      }
      return;
    }
    /* Meses y años: una rejilla de tres columnas */
    const actual = evento.target.closest('.calendario__celda');
    if (!actual) return;
    const celdas = [...rejilla.children];
    const saltos = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -3, ArrowDown: 3 };
    let destino;
    if (saltos[evento.key]) destino = celdas[celdas.indexOf(actual) + saltos[evento.key]];
    else if (evento.key === 'Home') destino = celdas[0];
    else if (evento.key === 'End') destino = celdas[celdas.length - 1];
    else return;                                  /* Enter y espacio: el clic del propio botón */
    evento.preventDefault();
    if (destino && !destino.disabled) {
      actual.tabIndex = -1;
      destino.tabIndex = 0;
      destino.focus();
    }
  });

  /* Se cierra al tocar fuera o si el foco sale con Tab */
  document.addEventListener('pointerdown', (evento) => {
    if (!estado || calendario.contains(evento.target) || estado.boton.contains(evento.target)) return;
    cerrar(false);
  });
  calendario.addEventListener('focusout', (evento) => {
    if (estado && evento.relatedTarget && !calendario.contains(evento.relatedTarget)) cerrar(false);
  });
  window.addEventListener('resize', () => estado && base.place(calendario, estado.boton));
  document.addEventListener('scroll', () => estado && base.place(calendario, estado.boton), { capture: true, passive: true });

  /* --- Cada campo de fecha (menos los de un rango) ----------------------------------------------------------- */
  base.watch('input[type="date"]:not([data-fecha-mejorada])', (entrada) => {
    if (entrada.closest('[data-rango-fechas]')) return;
    entrada.dataset.fechaMejorada = '';
    base.field(entrada, {
      icon: 'calendar',
      describe: (valor) => {
        const fecha = leer(valor);
        return fecha ? { text: corta(fecha), empty: false } : { text: 'Elegir fecha', empty: true };
      },
      open: abrir,
      emptyMessage: 'Elige la fecha.',
    });
  });
})();
