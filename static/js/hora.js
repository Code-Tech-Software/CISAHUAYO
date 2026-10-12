/* Selector de hora: cada <input type="time"> del sitio se ve como un campo con la hora escrita («08:00») que abre un
   selector con dos columnas (horas y minutos) y atajos para los minutos más usados. Se elige la hora y después los
   minutos (al elegirlos se cierra); «Listo» cierra con lo que haya.

   - El campo y lo que otros scripts le hagan al <input> los resuelve window.CISAHUAYO.pickers (static/js/app.js);
     sin JavaScript se ve el del navegador. Los campos que llegan después (formularios en ventana) se mejoran solos.
   - Respeta step (en segundos: 300 = de 5 en 5 minutos).
   - Teclado: flechas arriba/abajo en la columna, izquierda/derecha para cambiar de columna, Enter para elegir, Escape.
   Estilos: .campo-fecha (el mismo campo de las fechas) y .reloj en static/css/app.css. */
(() => {
  const base = window.CISAHUAYO?.pickers;
  if (!base || !HTMLElement.prototype.showPopover) return;   /* sin eso queda el campo del navegador */

  const MINUTOS_RAPIDOS = [0, 15, 30, 45];
  const dos = (numero) => String(numero).padStart(2, '0');
  const leer = (texto) => {
    const partes = /^(\d{2}):(\d{2})/.exec(texto || '');
    return partes ? { hora: Number(partes[1]), minuto: Number(partes[2]) } : null;
  };

  /* --- El selector: uno solo, compartido por todos los campos --------------------------------------------- */
  const reloj = document.createElement('div');
  reloj.className = 'reloj';
  reloj.setAttribute('popover', 'manual');
  reloj.setAttribute('role', 'dialog');
  reloj.innerHTML = `
    <p class="reloj__titulo" data-reloj-titulo></p>
    <div class="reloj__columnas">
      <div class="reloj__columna">
        <p class="reloj__encabezado" id="reloj-horas">Hora</p>
        <div class="reloj__lista" role="listbox" aria-labelledby="reloj-horas" data-reloj-horas></div>
      </div>
      <div class="reloj__columna">
        <p class="reloj__encabezado" id="reloj-minutos">Minutos</p>
        <div class="reloj__lista" role="listbox" aria-labelledby="reloj-minutos" data-reloj-minutos></div>
      </div>
    </div>
    <div class="reloj__rapidos" aria-label="Minutos frecuentes" data-reloj-rapidos></div>
    <div class="reloj__pie">
      <span class="reloj__valor" data-reloj-valor></span>
      <button type="button" class="btn btn--primary btn--sm" data-reloj-listo>Listo</button>
    </div>`;
  document.body.append(reloj);
  const titulo = reloj.querySelector('[data-reloj-titulo]');
  const listaHoras = reloj.querySelector('[data-reloj-horas]');
  const listaMinutos = reloj.querySelector('[data-reloj-minutos]');
  const rapidos = reloj.querySelector('[data-reloj-rapidos]');
  const valorVisible = reloj.querySelector('[data-reloj-valor]');

  let estado = null;   /* { entrada, boton, hora, minuto, paso } mientras está abierto */

  const opcion = (texto, valor, elegido, tipo) => {
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.className = 'reloj__opcion';
    boton.setAttribute('role', 'option');
    boton.setAttribute('aria-selected', String(elegido));
    boton.tabIndex = elegido ? 0 : -1;
    boton.dataset[tipo] = String(valor);
    boton.textContent = texto;
    return boton;
  };

  const dibujar = () => {
    const { hora, minuto, paso } = estado;
    listaHoras.replaceChildren(...Array.from({ length: 24 }, (_, h) => opcion(dos(h), h, h === hora, 'hora')));
    const minutos = [];
    for (let m = 0; m < 60; m += paso) minutos.push(m);
    if (minuto !== null && !minutos.includes(minuto)) minutos.push(minuto);   /* el que ya tenía, aunque no siga el paso */
    minutos.sort((a, b) => a - b);
    listaMinutos.replaceChildren(...minutos.map((m) => opcion(dos(m), m, m === minuto, 'minuto')));
    /* Sin hora elegida, el teclado entra por las 07 (ahí se centra la lista) y por el minuto 00 */
    if (hora === null) listaHoras.children[7].tabIndex = 0;
    if (minuto === null) listaMinutos.children[0].tabIndex = 0;
    rapidos.replaceChildren(...MINUTOS_RAPIDOS.filter((m) => m % paso === 0).map((m) => {
      const boton = document.createElement('button');
      boton.type = 'button';
      boton.className = 'reloj__rapido';
      boton.dataset.minuto = String(m);
      boton.setAttribute('aria-pressed', String(m === minuto));
      boton.textContent = `:${dos(m)}`;
      return boton;
    }));
    valorVisible.textContent = hora === null ? 'Sin hora' : `${dos(hora)}:${dos(minuto ?? 0)}`;
  };

  const centrar = () => {
    [listaHoras, listaMinutos].forEach((lista) => {
      const elegido = lista.querySelector('[aria-selected="true"]') || lista.querySelector('[tabindex="0"]');
      if (elegido) lista.scrollTop = elegido.offsetTop - lista.clientHeight / 2 + elegido.offsetHeight / 2;
    });
  };

  const guardar = () => {
    const { entrada, hora, minuto } = estado;
    if (hora === null) return;
    const nuevo = `${dos(hora)}:${dos(minuto ?? 0)}`;
    if (entrada.value === nuevo) return;
    entrada.value = nuevo;
    entrada.dispatchEvent(new Event('input', { bubbles: true }));
    entrada.dispatchEvent(new Event('change', { bubbles: true }));
  };

  const cerrar = (devolverFoco = true) => {
    if (!estado) return;
    const { boton } = estado;
    estado = null;
    if (reloj.matches(':popover-open')) reloj.hidePopover();
    boton.setAttribute('aria-expanded', 'false');
    if (devolverFoco && boton.isConnected) boton.focus();
  };

  const abrir = (entrada, boton) => {
    if (estado?.entrada === entrada) {
      cerrar();
      return;
    }
    cerrar(false);
    const valor = leer(entrada.value);
    const paso = Math.max(1, Math.round((Number(entrada.step) || 60) / 60));
    estado = { entrada, boton, hora: valor ? valor.hora : null, minuto: valor ? valor.minuto : null, paso };
    titulo.textContent = boton.labels?.[0]?.textContent.replace(/\s+/g, ' ').replace(/\s*\*$/, '').trim() || 'Elegir hora';
    reloj.setAttribute('aria-label', titulo.textContent);
    dibujar();
    base.show(reloj, entrada, boton);
    boton.setAttribute('aria-expanded', 'true');
    centrar();
    listaHoras.querySelector('[tabindex="0"]').focus({ preventScroll: true });
  };

  /* --- Eventos del selector --------------------------------------------------------------------------------- */
  reloj.addEventListener('click', (evento) => {
    if (!estado) return;
    const hora = evento.target.closest('[data-hora]');
    const minuto = evento.target.closest('[data-minuto]');
    if (hora) {
      estado.hora = Number(hora.dataset.hora);
      if (estado.minuto === null) estado.minuto = 0;
      guardar();
      dibujar();
      centrar();
      listaMinutos.querySelector('[tabindex="0"]')?.focus({ preventScroll: true });
    } else if (minuto) {
      estado.minuto = Number(minuto.dataset.minuto);
      if (estado.hora === null) {               /* falta la hora: se marca el minuto y se pasa a las horas */
        dibujar();
        listaHoras.children[7]?.focus();
        return;
      }
      guardar();
      cerrar();
    } else if (evento.target.closest('[data-reloj-listo]')) {
      guardar();
      cerrar();
    }
  });

  reloj.addEventListener('keydown', (evento) => {
    if (!estado) return;
    if (evento.key === 'Escape') {
      evento.preventDefault();
      evento.stopPropagation();                   /* cierra el selector, no la ventana del formulario */
      cerrar();
      return;
    }
    const opcionActual = evento.target.closest('.reloj__opcion');
    if (!opcionActual) return;
    const lista = opcionActual.parentElement;
    const opciones = [...lista.children];
    const indice = opciones.indexOf(opcionActual);
    const mover = (destino) => {
      if (!destino) return;
      opcionActual.tabIndex = -1;
      destino.tabIndex = 0;
      destino.focus();
    };
    if (evento.key === 'ArrowDown') {
      evento.preventDefault();
      mover(opciones[Math.min(indice + 1, opciones.length - 1)]);
    } else if (evento.key === 'ArrowUp') {
      evento.preventDefault();
      mover(opciones[Math.max(indice - 1, 0)]);
    } else if (evento.key === 'Home' || evento.key === 'End') {
      evento.preventDefault();
      mover(evento.key === 'Home' ? opciones[0] : opciones[opciones.length - 1]);
    } else if (evento.key === 'ArrowRight' && lista === listaHoras) {
      evento.preventDefault();
      (listaMinutos.querySelector('[tabindex="0"]') || listaMinutos.firstElementChild)?.focus();
    } else if (evento.key === 'ArrowLeft' && lista === listaMinutos) {
      evento.preventDefault();
      (listaHoras.querySelector('[tabindex="0"]') || listaHoras.firstElementChild)?.focus();
    } else if (evento.key === 'Enter' || evento.key === ' ') {
      evento.preventDefault();
      opcionActual.click();
    }
  });

  /* Se cierra al tocar fuera o si el foco sale con Tab */
  document.addEventListener('pointerdown', (evento) => {
    if (!estado || reloj.contains(evento.target) || estado.boton.contains(evento.target)) return;
    cerrar(false);
  });
  reloj.addEventListener('focusout', (evento) => {
    if (estado && evento.relatedTarget && !reloj.contains(evento.relatedTarget)) cerrar(false);
  });
  window.addEventListener('resize', () => estado && base.place(reloj, estado.boton));
  document.addEventListener('scroll', () => estado && base.place(reloj, estado.boton), { capture: true, passive: true });

  /* --- Cada campo de hora ------------------------------------------------------------------------------------ */
  base.watch('input[type="time"]:not([data-hora-mejorada])', (entrada) => {
    entrada.dataset.horaMejorada = '';
    const { button } = base.field(entrada, {
      icon: 'clock',
      describe: (valor) => {
        const hora = leer(valor);
        return hora ? { text: `${dos(hora.hora)}:${dos(hora.minuto)}`, empty: false } : { text: 'Elegir hora', empty: true };
      },
      open: abrir,
      emptyMessage: 'Elige la hora.',
    });
    button.classList.add('campo-hora');
  });
})();
