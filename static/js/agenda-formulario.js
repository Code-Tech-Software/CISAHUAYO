/* CISAHUAYO · Registrar o editar un evento de la agenda (templates/agenda/evento_form.html)

   - Con «Todo el día» marcado se ocultan las horas; al desmarcarlo aparecen y se lleva el foco a la hora de inicio.
   - «Repetir»: al elegir una repetición aparece «Hasta» (y «Saltar los días sin clases»); las opciones dicen la regla
     con la fecha de inicio elegida («Cada mes, el primer lunes», «Cada mes, el último viernes»…). «El último» solo se
     ofrece si esa fecha es el último de ese día en su mes, y «el quinto» nunca (no todos los meses lo tienen).
   - Para quién: «Todos los niveles» y los niveles sueltos se excluyen; los grados y grupos que se ofrecen son solo los
     de los niveles elegidos (los demás se desmarcan). Debajo, el resumen: «Lo verán el personal y las familias de…».
   - «Recordar antes del evento»: al marcarlo aparece con cuánta anticipación.
   Es solo ayuda: el servidor vuelve a revisar todo (Agenda/forms.py). Este archivo se vuelve a ejecutar cada vez que el
   formulario se abre en una ventana (modal-form.js): cada formulario se prepara una sola vez.
*/
(() => {
  'use strict';

  const DIAS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
  const ORDINALES = ['primer', 'segundo', 'tercer', 'cuarto', 'quinto'];
  const TODOS = 'COLEGIO';

  const enLista = (partes) => (partes.length > 1 ? `${partes.slice(0, -1).join(', ')} y ${partes[partes.length - 1]}` : partes[0] || '');

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

    /* --- Recordar antes del evento ------------------------------------------------------------------------- */
    const importante = form.querySelector('[data-agenda-importante]');
    const recordar = form.querySelector('[data-agenda-recordar]');
    if (importante && recordar) {
      importante.addEventListener('change', () => { recordar.hidden = !importante.checked; resumir(); });
    }

    /* --- Para quién --------------------------------------------------------------------------------------- */
    const niveles = [...form.querySelectorAll('[data-agenda-niveles] input[type="checkbox"]')];
    const cursos = [...form.querySelectorAll('[data-agenda-cursos] input[type="checkbox"]')];
    const familias = form.querySelector('[data-agenda-familias]');
    const estudiantes = form.querySelector('[data-agenda-estudiantes]');
    const resumen = form.querySelector('[data-agenda-resumen]');
    const nombreDe = (casilla) => casilla.closest('label')?.querySelector('.choice__box')?.textContent.trim() || '';

    function elegidos() {
      return niveles.filter((casilla) => casilla.checked).map((casilla) => casilla.value);
    }

    function filtrarCursos() {
      const todos = elegidos();
      cursos.forEach((casilla) => {
        const visible = todos.includes(TODOS) || todos.includes(casilla.dataset.nivel);
        const etiqueta = casilla.closest('label');
        if (etiqueta) etiqueta.hidden = !visible;
        if (!visible) casilla.checked = false;
      });
    }

    function resumir() {
      if (!resumen) return;
      const todos = elegidos();
      if (!todos.length) {
        resumen.hidden = true;
        return;
      }
      const quienes = ['el personal'];
      if (familias?.checked) quienes.push('las familias');
      if (estudiantes?.checked) quienes.push('los estudiantes');
      const deDonde = todos.includes(TODOS) ? 'de todo el colegio'
        : `de ${enLista(niveles.filter((casilla) => casilla.checked).map(nombreDe))}`;
      const solo = cursos.filter((casilla) => casilla.checked).map(nombreDe);
      let texto = `Lo verá${quienes.length > 1 ? 'n' : ''} ${enLista(quienes)} ${deDonde}`;
      if (solo.length && quienes.length > 1) texto += ` (las familias y los estudiantes, solo de ${enLista(solo)})`;
      texto += '.';
      if (quienes.length === 1) texto += ' Es un evento interno.';
      if (importante?.checked) {
        const cuando = form.querySelector('select[name="recordar_dias"]');
        texto += ` Se recordará ${(cuando?.selectedOptions[0]?.textContent || 'un día antes').toLowerCase()}.`;
      }
      resumen.textContent = texto;
      resumen.hidden = false;
    }

    niveles.forEach((casilla) => casilla.addEventListener('change', () => {
      /* «Todos los niveles» y los niveles sueltos no van juntos */
      if (casilla.checked && casilla.value === TODOS) niveles.forEach((otra) => { if (otra !== casilla) otra.checked = false; });
      if (casilla.checked && casilla.value !== TODOS) niveles.forEach((otra) => { if (otra.value === TODOS) otra.checked = false; });
      filtrarCursos();
      resumir();
    }));
    [...cursos, familias, estudiantes].forEach((casilla) => casilla?.addEventListener('change', resumir));
    form.querySelector('select[name="recordar_dias"]')?.addEventListener('change', resumir);
    filtrarCursos();
    resumir();

    /* --- Repetir ------------------------------------------------------------------------------------------- */
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
