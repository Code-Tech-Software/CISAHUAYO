/* CISAHUAYO · matriz de permisos de un rol

   Cada casilla (name="permisos") lleva data-accion (ver, crear, editar, baja) y, si necesita otros permisos,
   data-requiere con sus códigos. Marcar una casilla marca lo que necesita; desmarcar «ver» desmarca lo que depende de
   ella. El servidor aplica las mismas dependencias (Usuarios/catalogo.py), esto solo lo hace visible al instante.
   También: contadores por módulo y total, «Todo/Nada» por módulo y las ayudas rápidas de arriba.
*/
(() => {
  'use strict';

  const form = document.querySelector('[data-rol-form]');
  if (!form) return;

  const qsa = (selector, scope = form) => [...scope.querySelectorAll(selector)];
  const cajas = qsa('.perm-cell__input');
  const porPermiso = new Map(cajas.map((caja) => [caja.value, caja]));
  const requisitos = (caja) => (caja.dataset.requiere ? caja.dataset.requiere.split(' ') : []);

  /* Cajas que necesitan (directa o indirectamente) a esta: al quitarla, también se quitan */
  const dependientes = (caja) => {
    const encontradas = new Set();
    const pendientes = [caja.value];
    while (pendientes.length) {
      const actual = pendientes.pop();
      cajas.forEach((otra) => {
        if (!encontradas.has(otra) && requisitos(otra).includes(actual)) {
          encontradas.add(otra);
          pendientes.push(otra.value);
        }
      });
    }
    return encontradas;
  };

  const marcar = (caja, valor) => {
    if (caja.disabled || caja.checked === valor) return;
    caja.checked = valor;
  };

  const aplicar = (caja) => {
    if (caja.checked) {
      /* Lo que necesita se marca solo (las casillas bloqueadas ya están marcadas o no se pueden tocar) */
      const pendientes = [...requisitos(caja)];
      while (pendientes.length) {
        const necesaria = porPermiso.get(pendientes.pop());
        if (necesaria && !necesaria.checked) {
          marcar(necesaria, true);
          pendientes.push(...requisitos(necesaria));
        }
      }
    } else {
      dependientes(caja).forEach((otra) => marcar(otra, false));
    }
  };

  /* ------------------------------------------------------------------------- Contadores */
  const totalMarcados = form.querySelector('[data-total-marcados]');
  const contar = () => {
    qsa('[data-modulo]').forEach((modulo) => {
      const marcadas = qsa('.perm-cell__input:checked', modulo).length;
      const contador = modulo.querySelector('[data-modulo-marcados]');
      if (contador) contador.textContent = marcadas;
    });
    if (totalMarcados) totalMarcados.textContent = cajas.filter((caja) => caja.checked).length;
  };

  form.addEventListener('change', (event) => {
    if (!event.target.matches('.perm-cell__input')) return;
    aplicar(event.target);
    contar();
  });

  /* ------------------------------------------------------------- Todo / Nada por módulo */
  form.addEventListener('click', (event) => {
    const todo = event.target.closest('[data-modulo-todo]');
    const nada = event.target.closest('[data-modulo-nada]');
    if (!todo && !nada) return;
    const modulo = event.target.closest('[data-modulo]');
    qsa('.perm-cell__input', modulo).forEach((caja) => marcar(caja, Boolean(todo)));   /* las dependencias son del mismo módulo */
    contar();
    /* Los cambios hechos por código no avisan solos: así la ventana modal sabe que hay cambios sin guardar */
    form.dispatchEvent(new Event('change', { bubbles: true }));
  });

  /* ------------------------------------------------------------------ Ayudas rápidas */
  const PREAJUSTES = {
    consulta: (caja) => caja.dataset.accion === 'ver',
    todo: () => true,
    nada: () => false,
  };

  form.addEventListener('click', (event) => {
    const boton = event.target.closest('[data-preajuste]');
    if (!boton) return;
    const regla = PREAJUSTES[boton.dataset.preajuste];
    cajas.forEach((caja) => marcar(caja, regla(caja)));
    /* Con «solo consulta» se mantiene todo lo que es obligatorio para poder ver */
    cajas.filter((caja) => caja.checked).forEach(aplicar);
    contar();
    form.dispatchEvent(new Event('change', { bubbles: true }));
  });

  contar();
})();
