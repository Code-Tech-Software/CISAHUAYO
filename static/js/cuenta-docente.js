/* CISAHUAYO · cuenta de los docentes

   Una sola cuenta de usuario por profesor. Este script maneja las dos puertas a esa relación:
   - en el formulario del profesor, «Dar acceso al sistema» (crear su cuenta o vincular una existente);
   - en el formulario de usuario, «Es docente» (registrar su ficha de profesor o vincular una existente).

   Comportamientos ([data-cuenta-docente] en el formulario):
   - [data-toggle-card-switch] abre o cierra el [data-toggle-card-body] de su tarjeta;
   - los radios de [data-modos] muestran solo el [data-modo-panel] elegido;
   - lo que queda oculto se deshabilita, así no se envía ni se valida;
   - en usuarios, un rol para docentes ([data-roles-docentes]) enciende «Es docente» y lo deja fijo; con la ficha nueva
     los apellidos se piden por separado y con una ficha ya registrada el nombre sale de ella ([data-campo-*] se ocultan);
   - en profesores, sugiere el usuario de la cuenta a partir del nombre y el apellido paterno.
   El servidor valida todo otra vez.
*/
(() => {
  'use strict';

  const form = document.querySelector('[data-cuenta-docente]');
  if (!form) return;

  const qs = (selector, scope = form) => scope.querySelector(selector);
  const qsa = (selector, scope = form) => [...scope.querySelectorAll(selector)];
  const CONTROLES = 'input, select, textarea';

  /* Muestra u oculta un bloque; lo oculto no se envía (se deshabilita) */
  const mostrar = (bloque, visible) => {
    bloque.hidden = !visible;
    qsa(CONTROLES, bloque).forEach((control) => {
      if (control.dataset.siempreActivo === undefined) control.disabled = !visible;
    });
  };

  /* Dentro de una tarjeta abierta, solo el panel del modo elegido queda activo */
  const sincronizarModos = (tarjeta) => {
    const cuerpo = qs('[data-toggle-card-body]', tarjeta);
    const abierta = cuerpo && !cuerpo.hidden;
    const elegido = qs('[data-modos] input:checked', tarjeta)?.value
      ?? qs('input[type="hidden"][name$="-modo"]', tarjeta)?.value;
    qsa('[data-modo-panel]', tarjeta).forEach((panel) => {
      mostrar(panel, abierta && panel.dataset.modoPanel === elegido);
    });
    sincronizarApellidos();
  };

  const sincronizarTarjeta = (tarjeta) => {
    const interruptor = qs('[data-toggle-card-switch]', tarjeta);
    const cuerpo = qs('[data-toggle-card-body]', tarjeta);
    if (!interruptor || !cuerpo) return;
    mostrar(cuerpo, interruptor.checked);
    sincronizarModos(tarjeta);
  };

  /* Usuarios: con ficha nueva los apellidos van separados en la sección del docente; con una ficha ya registrada, el
     nombre y los apellidos salen de ella */
  const nombreCuenta = qs('[data-campo-nombre]');
  const apellidos = qs('[data-campo-apellidos]');
  function sincronizarApellidos() {
    if (!apellidos) return;
    const panelNuevo = qs('[data-modo-panel="nuevo"]');
    const panelExistente = qs('[data-modo-panel="existente"]');
    const nueva = Boolean(panelNuevo && !panelNuevo.hidden);
    const existente = Boolean(panelExistente && !panelExistente.hidden);
    mostrar(apellidos, !nueva && !existente);
    if (nombreCuenta) mostrar(nombreCuenta, !existente);
  }

  qsa('[data-toggle-card]').forEach((tarjeta) => {
    qs('[data-toggle-card-switch]', tarjeta)?.addEventListener('change', () => {
      sincronizarTarjeta(tarjeta);
      const primero = qs(`[data-toggle-card-body] ${CONTROLES}:not([disabled]):not([type="hidden"])`, tarjeta);
      if (qs('[data-toggle-card-switch]', tarjeta).checked && primero && primero.type !== 'radio') primero.focus();
    });
    qsa('[data-modos] input', tarjeta).forEach((radio) => radio.addEventListener('change', () => sincronizarModos(tarjeta)));
    sincronizarTarjeta(tarjeta);
  });

  /* Usuarios: un rol para docentes exige la ficha de profesor */
  const rol = qs('[data-roles-docentes]');
  const esDocente = qs('[data-es-docente]');
  const nota = qs('[data-nota-rol-docente]');
  if (rol && esDocente) {
    const docentes = (rol.dataset.rolesDocentes || '').split(',').filter(Boolean);
    const tarjeta = esDocente.closest('[data-toggle-card]');
    const alCambiarRol = () => {
      const forzado = docentes.includes(rol.value);
      if (forzado) esDocente.checked = true;
      esDocente.disabled = forzado;
      if (nota) nota.hidden = !forzado;
      sincronizarTarjeta(tarjeta);
    };
    rol.addEventListener('change', alCambiarRol);
    /* Al marcar «Es docente» sin rol elegido, se propone el rol para docentes */
    esDocente.addEventListener('change', () => {
      if (esDocente.checked && !rol.value && esDocente.dataset.rolDocente) {
        rol.value = esDocente.dataset.rolDocente;
        alCambiarRol();
      }
    });
    alCambiarRol();
  }

  /* Profesores: el usuario de la cuenta se sugiere con «nombre.apellido» mientras nadie lo escriba a mano */
  const usuario = qs('[name="acceso-username"]');
  const nombre = qs('[name="nombre"]');
  const paterno = qs('[name="apellido_paterno"]');
  if (usuario && nombre && paterno) {
    const limpiar = (texto) => texto.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '');
    const sugerencia = () => [nombre.value.trim().split(/\s+/)[0] ?? '', paterno.value.trim().split(/\s+/)[0] ?? '']
      .map(limpiar).filter(Boolean).join('.');
    let ultima = usuario.value;
    const sugerir = () => {
      if (usuario.value !== ultima) return;
      ultima = sugerencia();
      usuario.value = ultima;
    };
    if (!usuario.value) {
      sugerir();
      nombre.addEventListener('input', sugerir);
      paterno.addEventListener('input', sugerir);
    }
    usuario.addEventListener('input', () => {
      const limpio = usuario.value.toLowerCase().replace(/[^a-z0-9._-]/g, '');
      if (limpio !== usuario.value) usuario.value = limpio;
    });
  }
})();
