/* CISAHUAYO · Panel de control (templates/panel/inicio.html y seguimiento.html)

   - Filtros: grado y periodo dependen del nivel, y grupo del grado (solo se ofrecen los que corresponden). Se aplican al
     cambiarlos; mientras se recarga, el panel conserva lo anterior atenuado. Sin JavaScript, con «Aplicar».
   - Motivo y prioridad de las alertas también se aplican al cambiarlos.
   - Buscar estudiante: sugiere mientras se escribe (Alumnos · buscar) y abre su Vista 360. Flechas para moverse, Intro
     para abrir, Escape para cerrar.
   El servidor vuelve a validar todo (Panel/filtros.py).
*/
(() => {
  'use strict';

  const raiz = document.querySelector('[data-panel]');
  if (!raiz) return;

  const cuerpo = raiz.querySelector('[data-panel-cuerpo]');
  const aviso = raiz.querySelector('[data-panel-cargando]');

  const cargando = () => {
    cuerpo?.classList.add('is-cargando');
    cuerpo?.setAttribute('aria-busy', 'true');
    if (aviso) aviso.hidden = false;
  };
  window.addEventListener('pageshow', () => {
    cuerpo?.classList.remove('is-cargando');
    cuerpo?.removeAttribute('aria-busy');
    if (aviso) aviso.hidden = true;
  });

  // --- Filtros globales ----------------------------------------------------------------------------------------
  const filtros = raiz.querySelector('[data-panel-filtros]');
  if (filtros) {
    const nivel = filtros.querySelector('[data-panel-nivel]');
    const grado = filtros.querySelector('[data-panel-grado]');
    const grupo = filtros.querySelector('[data-panel-grupo]');
    const periodo = filtros.querySelector('[data-panel-periodo]');
    const desde = filtros.querySelector('[name="desde"]');
    const hasta = filtros.querySelector('[name="hasta"]');
    filtros.querySelector('[data-panel-aplicar]')?.setAttribute('hidden', '');

    // Solo las opciones que corresponden (la primera, «Todos…», siempre)
    const limitar = (select, atributo, valor, vacio, lleno) => {
      if (!select) return;
      [...select.options].slice(1).forEach((opcion) => {
        const vale = Boolean(valor) && opcion.dataset[atributo] === valor;
        opcion.hidden = !vale;
        opcion.disabled = !vale;
      });
      if (select.selectedOptions[0]?.disabled) select.value = '';
      select.disabled = !valor;
      select.options[0].textContent = valor ? lleno : vacio;
    };
    const ajustar = () => {
      limitar(grado, 'nivel', nivel.value, 'Elige un nivel', 'Todos los grados');
      limitar(periodo, 'nivel', nivel.value, 'Actual por nivel', 'Periodo actual');
      limitar(grupo, 'grado', grado.value, 'Elige un grado', 'Todos los grupos');
    };
    ajustar();

    filtros.addEventListener('change', (evento) => {
      if (evento.target === nivel) {
        grado.value = '';
        grupo.value = '';
        periodo.value = '';
      }
      if (evento.target === grado) grupo.value = '';
      ajustar();
      if ((evento.target === desde || evento.target === hasta) && !(desde.value && hasta.value && desde.value <= hasta.value)) return;
      cargando();
      filtros.requestSubmit();
    });
    filtros.addEventListener('submit', cargando);
  }

  raiz.querySelectorAll('[data-panel-auto]').forEach((select) => {
    select.addEventListener('change', () => {
      cargando();
      select.form.requestSubmit();
    });
  });
  raiz.querySelector('[data-panel-actualizar]')?.addEventListener('click', cargando);

  // --- Buscar estudiante y abrir su Vista 360 -------------------------------------------------------------------
  const buscador = raiz.querySelector('[data-panel-buscar]');
  if (buscador) {
    const campo = buscador.querySelector('[data-panel-buscar-campo]');
    const lista = buscador.querySelector('[data-panel-buscar-resultados]');
    let espera = 0;
    let ultima = '';

    const cerrar = () => {
      lista.hidden = true;
      campo.setAttribute('aria-expanded', 'false');
      campo.removeAttribute('aria-activedescendant');
    };
    const opciones = () => [...lista.querySelectorAll('[role="option"]')];
    const marcar = (indice) => {
      const todas = opciones();
      todas.forEach((o, i) => o.setAttribute('aria-selected', String(i === indice)));
      if (todas[indice]) {
        campo.setAttribute('aria-activedescendant', todas[indice].id);
        todas[indice].scrollIntoView({ block: 'nearest' });
      }
    };
    const mostrar = (resultados) => {
      lista.replaceChildren();
      if (!resultados.length) {
        const vacio = document.createElement('li');
        vacio.className = 'panel-buscar__opcion';
        vacio.textContent = 'Sin coincidencias';
        lista.append(vacio);
      }
      resultados.forEach((r, i) => {
        const li = document.createElement('li');
        const a = document.createElement('a');
        a.className = 'panel-buscar__opcion';
        a.id = `panel-buscar-${i}`;
        a.setAttribute('role', 'option');
        a.setAttribute('aria-selected', 'false');
        a.href = buscador.dataset.vista360.replace('/0/', `/${r.id}/`);
        a.textContent = `${r.nombre}${r.grado ? ` · ${r.grado}` : ''} · ${r.referencia}`;
        li.append(a);
        lista.append(li);
      });
      lista.hidden = false;
      campo.setAttribute('aria-expanded', 'true');
    };

    campo.addEventListener('input', () => {
      window.clearTimeout(espera);
      const texto = campo.value.trim();
      if (texto.length < 2) {
        cerrar();
        return;
      }
      espera = window.setTimeout(async () => {
        ultima = texto;
        try {
          const respuesta = await fetch(`${buscador.dataset.url}?q=${encodeURIComponent(texto)}`, { headers: { Accept: 'application/json' } });
          const datos = await respuesta.json();
          if (texto === ultima) mostrar(datos.resultados || []);
        } catch {
          cerrar();
        }
      }, 250);
    });
    campo.addEventListener('keydown', (evento) => {
      const todas = opciones();
      const actual = todas.findIndex((o) => o.getAttribute('aria-selected') === 'true');
      if (evento.key === 'ArrowDown' && todas.length) {
        evento.preventDefault();
        marcar((actual + 1) % todas.length);
      } else if (evento.key === 'ArrowUp' && todas.length) {
        evento.preventDefault();
        marcar((actual - 1 + todas.length) % todas.length);
      } else if (evento.key === 'Enter' && todas.length) {
        evento.preventDefault();
        window.location.href = todas[Math.max(actual, 0)].href;
      } else if (evento.key === 'Escape') {
        cerrar();
      }
    });
    document.addEventListener('click', (evento) => {
      if (!buscador.contains(evento.target)) cerrar();
    });
  }
})();
