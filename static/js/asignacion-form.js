/* CISAHUAYO · nueva asignación académica

   Un solo formulario para materia (del catálogo o nueva), grados y profesores. Reacciona sin volver al servidor con los
   datos que trae la página (<script type="application/json">):
   - plan: {ciclo: {materia: {grado: profesor o 0}}} → los grados que ya tienen la materia se bloquean;
   - habilitados: {materia: [profesores]} → quienes pueden impartirla salen primero en los selectores;
   - profesores: {id: «M. Rangel»} → para mostrar quién la da donde ya está.
   También muestra un profesor por grado si se pide, marca un nivel completo con «Todos» y resume lo que se guardará.
   El servidor valida todo otra vez.
*/
(() => {
  'use strict';

  const form = document.querySelector('[data-asignacion-form]');
  if (!form) return;

  const qs = (selector) => form.querySelector(selector);
  const qsa = (selector) => [...form.querySelectorAll(selector)];
  const datos = JSON.parse(qs('script[type="application/json"]')?.textContent || '{}');
  const plan = datos.plan || {};
  const habilitados = datos.habilitados || {};
  const nombres = datos.profesores || {};

  const ciclo = qs('[name="ciclo"]');
  const materia = qs('[name="materia"]');
  const nuevaNombre = qs('[name="nueva_nombre"]');
  const casillas = qsa('input[name="grados"]');
  const general = qs('select[name="profesor"]');
  const porGrado = qs('[data-por-grado]');
  const panelPorGrado = qs('[data-profesores-por-grado]');
  const pista = qs('[data-pista-habilitados]');
  const resumen = qs('[data-resumen]');

  const origen = () => qs('[data-origenes] input:checked')?.value ?? qs('input[type="hidden"][name="origen"]')?.value ?? 'existente';
  const materiaElegida = () => (origen() === 'existente' && materia ? materia.value : '');

  /* Lo que está oculto no se envía */
  const mostrar = (bloque, visible) => {
    bloque.hidden = !visible;
    bloque.querySelectorAll('input, select, textarea').forEach((control) => { control.disabled = !visible; });
  };

  /* --- Materia del catálogo o nueva --- */
  const sincronizarOrigen = () => {
    qsa('[data-origen-panel]').forEach((panel) => mostrar(panel, panel.dataset.origenPanel === origen()));
  };

  /* --- Grados que ya tienen la materia en el ciclo --- */
  const sincronizarPlan = () => {
    const delPlan = (plan[ciclo?.value] || {})[materiaElegida()] || {};
    casillas.forEach((casilla) => {
      const etiqueta = casilla.closest('[data-grado]');
      const nota = etiqueta?.querySelector('[data-ya]');
      const profesor = delPlan[casilla.value];
      const yaEsta = profesor !== undefined;
      casilla.disabled = yaEsta;
      if (yaEsta) casilla.checked = false;
      etiqueta?.classList.toggle('is-taken', yaEsta);
      if (nota) {
        nota.hidden = !yaEsta;
        nota.textContent = yaEsta ? ` · ${profesor ? nombres[profesor] || 'con profesor' : 'sin profesor'}` : '';
      }
    });
  };

  /* --- Profesores: quienes pueden impartir la materia, primero --- */
  const selectores = qsa('select[name^="profesor"]');
  const originales = new Map(selectores.map((select) => [select, [...select.options]]));
  const grupo = (etiqueta, opciones) => {
    const nodo = document.createElement('optgroup');
    nodo.label = etiqueta;
    opciones.forEach((opcion) => nodo.append(opcion));
    return nodo;
  };
  const agrupar = () => {
    const ids = new Set((habilitados[materiaElegida()] || []).map(String));
    selectores.forEach((select) => {
      const valor = select.value;
      const todas = originales.get(select);
      const vacia = todas.find((opcion) => !opcion.value);
      const propias = todas.filter((opcion) => opcion.value && ids.has(opcion.value));
      const otras = todas.filter((opcion) => opcion.value && !ids.has(opcion.value));
      select.replaceChildren();
      if (vacia) select.append(vacia);
      if (propias.length && otras.length) {
        select.append(grupo('Pueden impartirla', propias), grupo('Otros profesores', otras));
      } else {
        [...propias, ...otras].forEach((opcion) => select.append(opcion));
      }
      select.value = valor;
    });
    if (pista) pista.hidden = !ids.size;
  };

  /* --- Un profesor por grado --- */
  const sincronizarPorGrado = () => {
    if (!panelPorGrado) return;
    const activo = Boolean(porGrado?.checked);
    panelPorGrado.hidden = !activo;
    qsa('[data-fila-grado]').forEach((fila) => {
      const casilla = casillas.find((c) => c.value === fila.dataset.filaGrado);
      mostrar(fila, activo && Boolean(casilla?.checked));
    });
    const etiqueta = qs('[data-profesor-general] .field__label');
    if (etiqueta) etiqueta.textContent = activo ? 'Profesor general (para los grados sin uno propio)' : 'Profesor para los grados elegidos';
  };

  /* --- «Todos» marca o desmarca los grados libres de un nivel --- */
  form.addEventListener('click', (event) => {
    const boton = event.target.closest('[data-nivel-todos]');
    if (!boton) return;
    const libres = [...boton.closest('[data-nivel]').querySelectorAll('input[name="grados"]')].filter((c) => !c.disabled);
    const marcar = libres.some((c) => !c.checked);
    libres.forEach((c) => { c.checked = marcar; });
    actualizar();
  });

  /* --- Resumen de lo que se guardará --- */
  const textoDe = (select) => select?.selectedOptions[0]?.textContent.split(' · ')[0].trim() ?? '';
  const sincronizarResumen = () => {
    if (!resumen) return;
    const nombre = origen() === 'existente' ? textoDe(materia).replace(/\s*\([^)]*\)$/, '') : (nuevaNombre?.value.trim() ?? '');
    const marcadas = casillas.filter((c) => c.checked && !c.disabled);
    if (!nombre || !materiaElegida() && origen() === 'existente' || !marcadas.length) {
      resumen.textContent = '';
      return;
    }
    let texto = `${nombre} se agregará a ${marcadas.length} grado${marcadas.length === 1 ? '' : 's'} del ciclo ${textoDe(ciclo)}`;
    if (general?.value && !porGrado?.checked) texto += `, con ${textoDe(general)}`;
    resumen.textContent = `${texto}.`;
  };

  function actualizar() {
    sincronizarOrigen();
    sincronizarPlan();
    sincronizarPorGrado();
    sincronizarResumen();
  }

  form.addEventListener('change', (event) => {
    if (event.target === materia || event.target.matches('[data-origenes] input')) agrupar();
    actualizar();
  });
  nuevaNombre?.addEventListener('input', sincronizarResumen);

  agrupar();
  actualizar();
})();
