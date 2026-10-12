/* Calendario de rango de fechas: reemplaza a la vista los <input type="date"> de un contenedor [data-rango-fechas]
   (uno con [data-rango-desde] y otro con [data-rango-hasta]) por dos campos con la fecha escrita («lun 12 oct 2026») que
   abren un mismo calendario. Se elige el primer día y luego el último; el rango se resalta al pasar el ratón.

   - Los <input> siguen en el formulario (ocultos) y son los que se envían; sin JavaScript se ven los del navegador.
   - Respeta su min y max (días fuera, desactivados); marca hoy y atenúa sábados y domingos.
   - Con [data-rango-enviar] en el contenedor, al terminar de elegir se envía su formulario (y se oculta el botón
     [data-rango-ver], que ya no hace falta).
   - Teclado: flechas (día y semana), Re Pág / Av Pág (mes), Inicio / Fin (semana), Enter para elegir, Escape para cerrar.
   Estilos: .campo-fecha y .calendario en static/css/app.css. */
(() => {
  const contenedores = document.querySelectorAll('[data-rango-fechas]');
  if (!contenedores.length) return;

  const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
  const MESES_CORTOS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
  const DIAS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
  const DIAS_CORTOS = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'];
  const INICIALES = ['L', 'M', 'M', 'J', 'V', 'S', 'D'];
  const icono = (nombre) => window.CISAHUAYO?.icon?.(nombre) || document.createTextNode('');

  /* Fechas sin hora, en la zona local (un «2026-10-12» nunca se corre de día) */
  const leer = (texto) => {
    const partes = /^(\d{4})-(\d{2})-(\d{2})$/.exec(texto || '');
    return partes ? new Date(Number(partes[1]), Number(partes[2]) - 1, Number(partes[3])) : null;
  };
  const iso = (fecha) => `${fecha.getFullYear()}-${String(fecha.getMonth() + 1).padStart(2, '0')}-${String(fecha.getDate()).padStart(2, '0')}`;
  const sumarDias = (fecha, dias) => new Date(fecha.getFullYear(), fecha.getMonth(), fecha.getDate() + dias);
  const mismoDia = (a, b) => Boolean(a && b) && a.getTime() === b.getTime();
  const corta = (fecha) => `${DIAS_CORTOS[fecha.getDay()]} ${fecha.getDate()} ${MESES_CORTOS[fecha.getMonth()]} ${fecha.getFullYear()}`;
  const larga = (fecha) => `${DIAS[fecha.getDay()]} ${fecha.getDate()} de ${MESES[fecha.getMonth()]} de ${fecha.getFullYear()}`;
  const hoy = (() => {
    const ahora = new Date();
    return new Date(ahora.getFullYear(), ahora.getMonth(), ahora.getDate());
  })();

  const diasHabiles = (desde, hasta) => {
    let cuenta = 0;
    for (let dia = desde; dia <= hasta; dia = sumarDias(dia, 1)) {
      if (dia.getDay() !== 0 && dia.getDay() !== 6) cuenta += 1;
    }
    return cuenta;
  };

  contenedores.forEach((contenedor) => {
    const entradas = { desde: contenedor.querySelector('[data-rango-desde]'), hasta: contenedor.querySelector('[data-rango-hasta]') };
    if (!entradas.desde || !entradas.hasta) return;
    const formulario = entradas.desde.form;
    const enviar = contenedor.hasAttribute('data-rango-enviar');
    const minimo = leer(entradas.desde.min);
    const maximo = leer(entradas.desde.max);
    const permitido = (fecha) => (!minimo || fecha >= minimo) && (!maximo || fecha <= maximo);

    /* --- Los dos campos visibles ---------------------------------------------------------------------------- */
    const campos = {};
    Object.entries(entradas).forEach(([cual, entrada]) => {
      const boton = document.createElement('button');
      boton.type = 'button';
      boton.className = 'campo-fecha';
      boton.id = entrada.id;
      entrada.id = `${entrada.id}-valor`;
      boton.setAttribute('aria-haspopup', 'dialog');
      boton.setAttribute('aria-expanded', 'false');
      const texto = document.createElement('span');
      texto.className = 'campo-fecha__texto';
      boton.append(icono('calendar'), texto);
      entrada.hidden = true;
      entrada.after(boton);
      campos[cual] = { boton, texto };
      boton.addEventListener('click', () => abrir(cual));
    });

    const pintarCampos = () => {
      Object.entries(entradas).forEach(([cual, entrada]) => {
        const fecha = leer(entrada.value);
        campos[cual].texto.textContent = fecha ? corta(fecha) : 'Elegir fecha';
        campos[cual].boton.classList.toggle('is-vacio', !fecha);
      });
    };
    pintarCampos();
    if (enviar) formulario?.querySelector('[data-rango-ver]')?.setAttribute('hidden', '');

    /* --- El calendario ------------------------------------------------------------------------------------- */
    const calendario = document.createElement('div');
    calendario.className = 'calendario';
    calendario.hidden = true;
    calendario.setAttribute('role', 'dialog');
    calendario.setAttribute('aria-label', 'Elegir fechas');
    calendario.innerHTML = `
      <div class="calendario__cabecera">
        <button type="button" class="calendario__nav" data-mes="-1" aria-label="Mes anterior"></button>
        <p class="calendario__mes" aria-live="polite"></p>
        <button type="button" class="calendario__nav" data-mes="1" aria-label="Mes siguiente"></button>
      </div>
      <p class="calendario__indicacion" aria-live="polite"></p>
      <table class="calendario__tabla" role="grid">
        <thead><tr>${INICIALES.map((inicial, i) => `<th scope="col" abbr="${DIAS[(i + 1) % 7]}">${inicial}</th>`).join('')}</tr></thead>
        <tbody></tbody>
      </table>
      <div class="calendario__pie">
        <span class="calendario__resumen"></span>
        <button type="button" class="btn btn--ghost btn--sm" data-cancelar>Cancelar</button>
      </div>`;
    const [anterior, siguiente] = calendario.querySelectorAll('.calendario__nav');
    anterior.append(icono('chevron-left'));
    siguiente.append(icono('chevron-right'));
    const titulo = calendario.querySelector('.calendario__mes');
    const indicacion = calendario.querySelector('.calendario__indicacion');
    const cuerpo = calendario.querySelector('tbody');
    const resumen = calendario.querySelector('.calendario__resumen');
    document.body.append(calendario);

    let estado = null;   // { abierto: 'desde'|'hasta', desde, hasta, esperando: 'desde'|'hasta', mes, foco, sobre }

    const dentroDelRango = (fecha) => {
      const fin = estado.esperando === 'hasta' && estado.sobre && estado.desde && estado.sobre >= estado.desde ? estado.sobre : estado.hasta;
      return estado.desde && fin && fecha > estado.desde && fecha < fin;
    };

    const dibujar = () => {
      const { mes } = estado;
      titulo.textContent = `${MESES[mes.getMonth()]} ${mes.getFullYear()}`;
      const primero = new Date(mes.getFullYear(), mes.getMonth(), 1);
      const ultimo = new Date(mes.getFullYear(), mes.getMonth() + 1, 0);
      anterior.disabled = Boolean(minimo && sumarDias(primero, -1) < minimo);
      siguiente.disabled = Boolean(maximo && sumarDias(ultimo, 1) > maximo);
      indicacion.textContent = estado.esperando === 'desde' ? 'Elige el primer día' : 'Ahora elige el último día';

      /* Siempre seis semanas desde el lunes de la primera: el calendario no cambia de alto al pasar de mes */
      const filas = [];
      let dia = sumarDias(primero, -((primero.getDay() + 6) % 7));
      for (let semana = 0; semana < 6; semana += 1) {
        const celdas = [];
        for (let i = 0; i < 7; i += 1) {
          const fecha = dia;
          const clases = ['calendario__dia'];
          if (fecha.getMonth() !== mes.getMonth()) clases.push('is-otro-mes');
          if (fecha.getDay() === 0 || fecha.getDay() === 6) clases.push('is-finde');
          if (mismoDia(fecha, hoy)) clases.push('is-hoy');
          const esInicio = mismoDia(fecha, estado.desde);
          const fin = estado.hasta || (estado.esperando === 'hasta' && estado.sobre && estado.desde && estado.sobre >= estado.desde ? estado.sobre : null);
          const esFin = mismoDia(fecha, fin);
          if (esInicio) clases.push('is-inicio');
          if (esFin) clases.push('is-fin');
          if (dentroDelRango(fecha)) clases.push('is-en-rango');
          const activo = mismoDia(fecha, estado.foco);
          celdas.push(`<td role="gridcell" aria-selected="${esInicio || esFin}"><button type="button" class="${clases.join(' ')}"
            data-fecha="${iso(fecha)}" tabindex="${activo ? 0 : -1}" aria-label="${larga(fecha)}${mismoDia(fecha, hoy) ? ', hoy' : ''}"
            ${permitido(fecha) ? '' : 'disabled'}>${fecha.getDate()}</button></td>`);
          dia = sumarDias(dia, 1);
        }
        filas.push(`<tr>${celdas.join('')}</tr>`);
      }
      cuerpo.innerHTML = filas.join('');

      const fin = estado.hasta || null;
      resumen.textContent = estado.desde && fin
        ? `${estado.desde.getDate()} ${MESES_CORTOS[estado.desde.getMonth()]} – ${fin.getDate()} ${MESES_CORTOS[fin.getMonth()]} · ${diasHabiles(estado.desde, fin)} días de clase`
        : '';
    };

    const enfocar = (fecha) => {
      let destino = fecha;
      if (minimo && destino < minimo) destino = minimo;
      if (maximo && destino > maximo) destino = maximo;
      estado.foco = destino;
      if (destino.getMonth() !== estado.mes.getMonth() || destino.getFullYear() !== estado.mes.getFullYear()) {
        estado.mes = new Date(destino.getFullYear(), destino.getMonth(), 1);
      }
      dibujar();
      cuerpo.querySelector(`[data-fecha="${iso(destino)}"]`)?.focus();
    };

    const colocar = () => {
      const campo = campos[estado.abierto].boton.getBoundingClientRect();
      const caja = calendario.getBoundingClientRect();
      let arriba = campo.bottom + 6;
      if (arriba + caja.height > window.innerHeight - 8) arriba = Math.max(8, campo.top - caja.height - 6);
      const izquierda = Math.max(8, Math.min(campo.left, window.innerWidth - caja.width - 8));
      calendario.style.top = `${arriba}px`;
      calendario.style.left = `${izquierda}px`;
    };

    const cerrar = (devolverFoco = true) => {
      if (!estado) return;
      const { abierto } = estado;
      estado = null;
      calendario.hidden = true;
      Object.values(campos).forEach(({ boton }) => boton.setAttribute('aria-expanded', 'false'));
      if (devolverFoco) campos[abierto].boton.focus();
    };

    function abrir(cual) {
      if (estado?.abierto === cual) {
        cerrar();
        return;
      }
      const desde = leer(entradas.desde.value);
      const hasta = leer(entradas.hasta.value);
      const inicial = (cual === 'hasta' ? hasta : desde) || desde || hoy;
      /* Se abre con el rango actual resaltado; el primer clic empieza uno nuevo (o, desde «Hasta», solo cambia el fin) */
      estado = {
        abierto: cual,
        desde,
        hasta,
        esperando: cual === 'hasta' && desde ? 'hasta' : 'desde',
        mes: new Date(inicial.getFullYear(), inicial.getMonth(), 1),
        foco: inicial,
        sobre: null,
      };
      Object.entries(campos).forEach(([nombre, { boton }]) => boton.setAttribute('aria-expanded', String(nombre === cual)));
      calendario.hidden = false;
      enfocar(inicial);
      colocar();
    }

    const elegir = (fecha) => {
      if (!permitido(fecha)) return;
      if (estado.esperando === 'desde' || (estado.desde && fecha < estado.desde)) {
        estado.desde = fecha;
        estado.hasta = null;
        estado.esperando = 'hasta';
        estado.foco = fecha;
        dibujar();
        cuerpo.querySelector(`[data-fecha="${iso(fecha)}"]`)?.focus();
        return;
      }
      entradas.desde.value = iso(estado.desde);
      entradas.hasta.value = iso(fecha);
      [entradas.desde, entradas.hasta].forEach((entrada) => entrada.dispatchEvent(new Event('change', { bubbles: true })));
      pintarCampos();
      cerrar();
      if (enviar) formulario?.requestSubmit();
    };

    cuerpo.addEventListener('click', (evento) => {
      const dia = evento.target.closest('[data-fecha]');
      if (dia && !dia.disabled) elegir(leer(dia.dataset.fecha));
    });
    cuerpo.addEventListener('pointerover', (evento) => {
      const dia = evento.target.closest('[data-fecha]');
      if (!estado || estado.esperando !== 'hasta' || !dia) return;
      const fecha = leer(dia.dataset.fecha);
      if (mismoDia(fecha, estado.sobre)) return;
      estado.sobre = fecha;
      /* Solo cambian las marcas del rango (sin volver a dibujar: no se pierde el foco) */
      cuerpo.querySelectorAll('[data-fecha]').forEach((boton) => {
        const dia2 = leer(boton.dataset.fecha);
        boton.classList.toggle('is-en-rango', dentroDelRango(dia2));
        boton.classList.toggle('is-fin', fecha >= estado.desde && mismoDia(dia2, fecha));
      });
    });

    calendario.addEventListener('click', (evento) => {
      const nav = evento.target.closest('[data-mes]');
      if (nav && !nav.disabled) {
        const paso = Number(nav.dataset.mes);
        estado.mes = new Date(estado.mes.getFullYear(), estado.mes.getMonth() + paso, 1);
        estado.foco = new Date(estado.mes.getFullYear(), estado.mes.getMonth(), Math.min(estado.foco.getDate(), 28));
        dibujar();
      }
      if (evento.target.closest('[data-cancelar]')) cerrar();
    });

    calendario.addEventListener('keydown', (evento) => {
      if (evento.key === 'Escape') {
        evento.preventDefault();
        cerrar();
        return;
      }
      if (evento.key === 'Tab') {
        /* El foco se queda en el calendario */
        const enfocables = [...calendario.querySelectorAll('button:not([disabled])')].filter((boton) => !boton.dataset.fecha || boton.tabIndex === 0);
        const indice = enfocables.indexOf(document.activeElement);
        evento.preventDefault();
        enfocables[(indice + (evento.shiftKey ? -1 : 1) + enfocables.length) % enfocables.length]?.focus();
        return;
      }
      const dia = evento.target.closest('[data-fecha]');
      if (!dia) return;
      const fecha = leer(dia.dataset.fecha);
      const lunes = sumarDias(fecha, -((fecha.getDay() + 6) % 7));
      const saltos = {
        ArrowLeft: () => sumarDias(fecha, -1),
        ArrowRight: () => sumarDias(fecha, 1),
        ArrowUp: () => sumarDias(fecha, -7),
        ArrowDown: () => sumarDias(fecha, 7),
        Home: () => lunes,
        End: () => sumarDias(lunes, 6),
        PageUp: () => new Date(fecha.getFullYear(), fecha.getMonth() - 1, Math.min(fecha.getDate(), 28)),
        PageDown: () => new Date(fecha.getFullYear(), fecha.getMonth() + 1, Math.min(fecha.getDate(), 28)),
      };
      if (saltos[evento.key]) {
        evento.preventDefault();
        enfocar(saltos[evento.key]());
      } else if (evento.key === 'Enter' || evento.key === ' ') {
        evento.preventDefault();
        if (!dia.disabled) elegir(fecha);
      }
    });

    document.addEventListener('pointerdown', (evento) => {
      if (!estado || calendario.contains(evento.target)) return;
      if (Object.values(campos).some(({ boton }) => boton.contains(evento.target))) return;
      cerrar(false);
    });
    window.addEventListener('resize', () => estado && colocar());
    window.addEventListener('scroll', () => estado && colocar(), { passive: true });
  });
})();
