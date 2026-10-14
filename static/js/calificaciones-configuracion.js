/* CISAHUAYO · Ajustes › Calificaciones

   - Filtros y asistente de copia ([data-autosubmit], [data-copia-auto]): cambiar una lista recarga la vista.
   - Rubros ([data-config-rubros]): agregar (desde la <template> del formulario vacío), quitar (un rubro guardado se
     marca para eliminar; uno nuevo se borra), subir y bajar (renumera el orden) y la suma en vivo de los rubros
     activos, que debe ser exactamente 100 % para activar. El servidor valida lo mismo.
*/
(() => {
  'use strict';

  document.querySelectorAll('[data-autosubmit] select, [data-copia-auto]').forEach((campo) => {
    campo.addEventListener('change', () => campo.form?.requestSubmit());
  });

  const formulario = document.querySelector('[data-config-rubros]');
  if (!formulario) return;
  const cuerpo = formulario.querySelector('[data-rubros]');
  const plantilla = formulario.querySelector('[data-plantilla-rubro]');
  const total = formulario.querySelector('[name$="-TOTAL_FORMS"]');
  const suma = formulario.querySelector('[data-suma]');

  const visibles = () => [...cuerpo.querySelectorAll('[data-rubro]')].filter((fila) => !fila.hidden);

  const renumerar = () => {
    [...cuerpo.querySelectorAll('[data-rubro]')].forEach((fila, indice) => {
      const orden = fila.querySelector('[data-orden]');
      if (orden) orden.value = indice + 1;
    });
  };

  const calcular = () => {
    let porcentaje = 0;
    visibles().forEach((fila) => {
      const activo = fila.querySelector('[data-activo]');
      const valor = Number(String(fila.querySelector('[data-porcentaje]')?.value || '0').replace(',', '.'));
      if (activo?.checked && Number.isFinite(valor)) porcentaje += valor;
    });
    porcentaje = Math.round(porcentaje * 100) / 100;
    const exacto = porcentaje === 100;
    suma.textContent = exacto
      ? 'Los rubros activos suman 100 %: se puede activar.'
      : `Los rubros activos suman ${porcentaje.toLocaleString('es-MX')} %: ${porcentaje < 100 ? `faltan ${(100 - porcentaje).toLocaleString('es-MX', { maximumFractionDigits: 2 })}` : `sobran ${(porcentaje - 100).toLocaleString('es-MX', { maximumFractionDigits: 2 })}`} % para activarla (sí se puede guardar como borrador).`;
    suma.classList.toggle('is-ok', exacto);
    suma.classList.toggle('is-error', !exacto);
  };

  formulario.querySelector('[data-agregar-rubro]')?.addEventListener('click', () => {
    const indice = Number(total.value);
    const html = plantilla.innerHTML.replace(/__prefix__/g, String(indice));
    cuerpo.insertAdjacentHTML('beforeend', html);
    total.value = indice + 1;
    const nueva = cuerpo.lastElementChild;
    const activo = nueva.querySelector('[data-activo]');
    if (activo) activo.checked = true;
    renumerar();
    calcular();
    nueva.querySelector('input[type="text"]')?.focus();
  });

  cuerpo.addEventListener('click', (evento) => {
    const fila = evento.target.closest('[data-rubro]');
    if (!fila) return;
    if (evento.target.closest('[data-quitar-rubro]')) {
      const pk = fila.querySelector('input[name$="-pk"]');
      if (pk && pk.value) {
        /* Uno guardado: se marca para eliminarlo al guardar */
        fila.querySelector('[data-eliminar]').value = '1';
        fila.hidden = true;
      } else {
        /* Uno nuevo: se quita (un formulario extra sin datos no se valida ni se guarda) */
        fila.remove();
      }
    } else if (evento.target.closest('[data-subir]')) {
      const anterior = fila.previousElementSibling;
      if (anterior) cuerpo.insertBefore(fila, anterior);
    } else if (evento.target.closest('[data-bajar]')) {
      const siguiente = fila.nextElementSibling;
      if (siguiente) cuerpo.insertBefore(siguiente, fila);
    } else {
      return;
    }
    renumerar();
    calcular();
  });

  cuerpo.addEventListener('input', calcular);
  cuerpo.addEventListener('change', calcular);
  renumerar();
  calcular();
})();
