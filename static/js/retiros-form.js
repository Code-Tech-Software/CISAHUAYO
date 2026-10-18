/* CISAHUAYO · «Avisar retiro» en el portal de tutores (templates/portales/tutores/retiros/crear.html)

   - Quién recoge: solo se puede elegir a una persona autorizada para todos los estudiantes marcados (data-alumnos de
     cada opción); las demás se desactivan con su aviso, y si la elegida deja de valer se quita.
   - Detalles: si el motivo elegido pide explicación (data-requieren-explicacion del formulario), se marcan como
     obligatorios.
   Es solo ayuda: el servidor vuelve a revisar todo (Retiros/reglas.py).
*/
(() => {
  'use strict';

  const form = document.querySelector('[data-retiros-form]');
  if (!form) return;

  const hijos = [...form.querySelectorAll('[data-retiros-hijo]')];
  const personas = [...form.querySelectorAll('[data-retiros-persona]')];
  const motivo = form.querySelector('select[name="motivo"]');
  const detalles = form.querySelector('textarea[name="detalles"]');
  const etiqueta = form.querySelector('[data-retiros-detalles-etiqueta]');
  const ayuda = form.querySelector('[data-retiros-detalles-ayuda]');
  const requieren = new Set((form.dataset.requierenExplicacion || '').split(',').filter(Boolean));

  const elegidos = () => hijos.filter((casilla) => casilla.checked).map((casilla) => casilla.value);

  const revisarPersonas = () => {
    const ids = elegidos();
    personas.forEach((persona) => {
      const autorizado = new Set((persona.dataset.alumnos || '').split(',').filter(Boolean));
      const vale = ids.every((id) => autorizado.has(id));
      const radio = persona.querySelector('input[type="radio"]');
      radio.disabled = !vale;
      persona.classList.toggle('is-disabled', !vale);
      const aviso = persona.querySelector('[data-retiros-persona-aviso]');
      if (aviso) aviso.hidden = vale || !ids.length;
      if (!vale && radio.checked) radio.checked = false;
    });
    /* Si solo una persona vale, se elige sola */
    const validas = personas.map((p) => p.querySelector('input[type="radio"]')).filter((radio) => !radio.disabled);
    if (ids.length && validas.length === 1 && !validas[0].checked) validas[0].checked = true;
  };

  const revisarMotivo = () => {
    const obligatorio = Boolean(motivo && requieren.has(motivo.value));
    etiqueta?.classList.toggle('field__label--required', obligatorio);
    if (ayuda) ayuda.hidden = !obligatorio;
    if (detalles) detalles.required = obligatorio;
  };

  hijos.forEach((casilla) => casilla.addEventListener('change', revisarPersonas));
  motivo?.addEventListener('change', revisarMotivo);
  revisarPersonas();
  revisarMotivo();
})();
