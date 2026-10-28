/* CISAHUAYO · Registrar o editar un evento de la agenda (templates/agenda/evento_form.html)

   - Con «Todo el día» marcado se ocultan las horas; al desmarcarlo aparecen y se lleva el foco a la hora de inicio.
   - «Repetir»: al elegir una repetición aparece «Hasta» (y «Saltar los días sin clases»); las opciones dicen la regla
     con la fecha de inicio elegida («Cada mes, el primer lunes», «Cada mes, el último viernes»…). «El último» solo se
     ofrece si esa fecha es el último de ese día en su mes, y «el quinto» nunca (no todos los meses lo tienen).
   Es solo ayuda: el servidor vuelve a revisar todo (Agenda/forms.py). Este archivo se vuelve a ejecutar cada vez que el
   formulario se abre en una ventana (modal-form.js): cada formulario se prepara una sola vez.
*/
(() => {
  'use strict';

  const DIAS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
  const ORDINALES = ['primer', 'segundo', 'tercer', 'cuarto', 'quinto'];

  document.querySelectorAll('[data-agenda-formulario]').forEach((form) => {
    if (form.dataset.agendaListo) return;
    form.dataset.agendaListo = '1';

    const todoElDia = form.querySelector('[data-agenda-todo-el-dia]');
    const horas = form.querySelector('[data-agenda-horas]');
    if (todoElDia && horas) {
      const revisar = (enfocar = false) => {
        horas.hidden = todoElDia.checked;
        if (enfocar && !todoElDia.checked) horas.querySelector('input')?.focus();
      };
      todoElDia.addEventListener('change', () => revisar(true));
      revisar();
    }

    const repetir = form.querySelector('[data-agenda-repetir]');
    const hasta = form.querySelector('[data-agenda-repetir-hasta]');
    const inicio = form.querySelector('input[name="fecha_inicio"]');
    if (!repetir || !hasta) return;

    /* Las opciones con la fecha de inicio: «Cada lunes», «Cada mes, el día 15», «Cada mes, el primer lunes»… */
    const nombrarOpciones = () => {
      const [anio, mes, dia] = (inicio?.value || '').split('-').map(Number);
      if (!anio) return;
      const fecha = new Date(anio, mes - 1, dia);
      const nombre = DIAS[fecha.getDay()];
      const textos = {
        SEMANAL: `Cada semana (cada ${nombre})`,
        QUINCENAL: `Cada dos semanas (en ${nombre})`,
        MENSUAL_DIA: `Cada mes, el día ${dia}`,
        MENSUAL_ORDINAL: `Cada mes, el ${ORDINALES[Math.floor((dia - 1) / 7)]} ${nombre}`,
        MENSUAL_ULTIMO: `Cada mes, el último ${nombre}`,
      };
      [...repetir.options].forEach((opcion) => { if (textos[opcion.value]) opcion.textContent = textos[opcion.value]; });
      const aplica = { MENSUAL_ORDINAL: dia <= 28, MENSUAL_ULTIMO: dia + 7 > new Date(anio, mes, 0).getDate() };
      Object.entries(aplica).forEach(([valor, si]) => {
        const opcion = repetir.querySelector(`option[value="${valor}"]`);
        if (opcion) opcion.hidden = opcion.disabled = !si;
      });
      if (repetir.selectedOptions[0]?.disabled) {
        repetir.value = '';
        hasta.hidden = true;
      }
    };
    const mostrar = (enfocar = false) => {
      hasta.hidden = !repetir.value;
      if (enfocar && repetir.value) hasta.querySelector('input[type="date"]')?.focus();
    };
    repetir.addEventListener('change', () => mostrar(true));
    inicio?.addEventListener('change', nombrarOpciones);
    nombrarOpciones();
    mostrar();
  });
})();
