/* Asistencia por materia de la administración (templates/asistencias/materias.html): justificar una falta con la foto
   de su comprobante y consultar después la justificación de una J.

   La matriz (asistencia-docente.js) avisa con dos eventos sobre [data-asistencia-docente]: «asistencia:justificar» (se
   eligió «Justificar falta» en una F) y «asistencia:ver-justificacion» (se tocó una J). Su detail trae la celda, el
   estudiante, el día, la versión del registro y cómo repintar la celda con lo que responda el servidor.

   - La foto es obligatoria: se revisa el tipo (JPG, PNG o WEBP), se muestra la vista previa y se puede cambiar o
     quitar antes de guardar; también se puede soltar sobre la zona punteada. «Guardar» se habilita solo cuando hay una
     foto que el navegador pudo abrir. Una foto de más del máximo se reduce aquí mismo (lado mayor de 2400 px, JPEG).
   - Se sube con una barra de progreso. Si la subida falla o el servidor no la acepta, la falta no cambia, se dice por
     qué y la foto se conserva para reintentar. El servidor valida todo de nuevo. */
(() => {
  'use strict';

  const raiz = document.querySelector('[data-asistencia-docente]');
  if (!raiz) return;

  const LADO_MAXIMO = 2400;
  const TIPOS = ['image/jpeg', 'image/png', 'image/webp'];
  const MINIMO_MOTIVO = 3;

  const peso = (bytes) => (bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`);
  /* «Lunes 12 de octubre de 2026» a partir del título de la columna y su fecha */
  const fechaLarga = ({ titulo, fecha }) => {
    const texto = `${titulo} de ${fecha.slice(0, 4)}`;
    return texto.charAt(0).toUpperCase() + texto.slice(1);
  };
  /* Las ventanas se abren desde aquí (no con [data-modal-open]): la página de atrás no se desplaza mientras tanto;
     app.js quita el bloqueo al cerrarse cualquier ventana */
  const bloquearPagina = () => document.documentElement.classList.add('is-scroll-locked');

  /* ======================================================================== Justificar una falta */
  const dialogo = document.querySelector('[data-justificar-dialogo]');
  if (dialogo) {
    const formulario = dialogo.querySelector('[data-justificar-form]');
    const campo = (nombre) => formulario.querySelector(`[data-justificar-campo="${nombre}"]`);
    const motivo = formulario.querySelector('[data-justificar-motivo]');
    const zona = formulario.querySelector('[data-comprobante]');
    const entrada = formulario.querySelector('[data-comprobante-input]');
    const vacio = formulario.querySelector('[data-comprobante-vacio]');
    const vista = formulario.querySelector('[data-comprobante-vista]');
    const imagen = formulario.querySelector('[data-comprobante-img]');
    const nombreFoto = formulario.querySelector('[data-comprobante-nombre]');
    const pesoFoto = formulario.querySelector('[data-comprobante-peso]');
    const guardar = formulario.querySelector('[data-justificar-guardar]');
    const progreso = formulario.querySelector('[data-justificar-progreso]');
    const barra = formulario.querySelector('[data-justificar-barra]');
    const progresoTexto = formulario.querySelector('[data-justificar-progreso-texto]');
    const cajaError = formulario.querySelector('[data-justificar-error]');
    const textoError = formulario.querySelector('[data-justificar-error-texto]');
    const observacion = formulario.querySelector('[data-justificar-observacion]');
    const MAXIMO = Number(dialogo.dataset.maximoMb || 5) * 1024 * 1024;

    let celda = null;      // el detail del evento: la falta que se justifica
    let foto = null;       // lo que se sube: la foto elegida o su versión reducida
    let urlVista = null;
    let subida = null;     // la petición en curso
    let turno = 0;         // descarta lo que termine de una foto que ya se cambió

    const errorDe = (nombre) => formulario.querySelector(`[data-error-de="${nombre}"]`);
    const marcar = (nombre, mensaje = '') => {
      const nodo = errorDe(nombre);
      nodo.textContent = mensaje;
      nodo.hidden = !mensaje;
      const control = nombre === 'motivo' ? motivo : entrada;
      if (mensaje) {
        control.setAttribute('aria-invalid', 'true');
      } else {
        control.removeAttribute('aria-invalid');
      }
      if (nombre === 'comprobante') zona.classList.toggle('is-invalido', Boolean(mensaje));
    };
    const mostrarError = (mensaje = '') => {
      textoError.textContent = mensaje;
      cajaError.hidden = !mensaje;
    };
    const actualizar = () => {
      guardar.disabled = !foto || Boolean(subida);
    };

    const quitarFoto = () => {
      turno += 1;
      foto = null;
      if (urlVista) URL.revokeObjectURL(urlVista);
      urlVista = null;
      entrada.value = '';
      imagen.removeAttribute('src');
      vista.hidden = true;
      vacio.hidden = false;
      actualizar();
    };

    /* Una foto muy pesada (las de los teléfonos) se reduce a JPEG con su lado mayor en LADO_MAXIMO */
    const reducir = (archivo) => new Promise((resolver, rechazar) => {
      const url = URL.createObjectURL(archivo);
      const original = new Image();
      original.onload = () => {
        URL.revokeObjectURL(url);
        const escala = Math.min(1, LADO_MAXIMO / Math.max(original.naturalWidth, original.naturalHeight));
        const lienzo = document.createElement('canvas');
        lienzo.width = Math.round(original.naturalWidth * escala);
        lienzo.height = Math.round(original.naturalHeight * escala);
        const contexto = lienzo.getContext('2d');
        contexto.fillStyle = '#fff';   // una PNG con transparencia no queda con fondo negro
        contexto.fillRect(0, 0, lienzo.width, lienzo.height);
        contexto.drawImage(original, 0, 0, lienzo.width, lienzo.height);
        lienzo.toBlob((blob) => {
          if (!blob || blob.size > MAXIMO) {
            rechazar(new Error('sigue siendo muy pesada'));
            return;
          }
          resolver(new File([blob], `${archivo.name.replace(/\.[^.]+$/, '')}.jpg`, { type: 'image/jpeg' }));
        }, 'image/jpeg', 0.85);
      };
      original.onerror = () => {
        URL.revokeObjectURL(url);
        rechazar(new Error('no se pudo abrir'));
      };
      original.src = url;
    });

    async function elegirFoto(archivo) {
      if (!archivo) return;   // se cerró el selector sin elegir: se queda la foto que había
      const mio = turno + 1;
      quitarFoto();           // (así turno === mio)
      marcar('comprobante');
      mostrarError();
      if (!TIPOS.includes(archivo.type)) {
        marcar('comprobante', 'Elige una fotografía JPG, PNG o WEBP (un PDF u otro archivo no sirve aquí).');
        return;
      }
      let lista = archivo;
      if (archivo.size > MAXIMO) {
        try {
          lista = await reducir(archivo);
        } catch (error) {
          if (mio === turno) marcar('comprobante', `La foto pesa ${peso(archivo.size)} y no se pudo reducir: elige otra.`);
          return;
        }
        if (mio !== turno) return;
      }
      /* Vista previa: solo con una foto que el navegador pudo abrir se puede guardar */
      urlVista = URL.createObjectURL(lista);
      imagen.onload = () => {
        if (mio !== turno) return;
        foto = lista;
        nombreFoto.textContent = archivo.name;
        pesoFoto.textContent = lista === archivo ? `· ${peso(lista.size)}` : `· ${peso(lista.size)} (reducida de ${peso(archivo.size)})`;
        vacio.hidden = true;
        vista.hidden = false;
        actualizar();
      };
      imagen.onerror = () => {
        if (mio !== turno) return;
        quitarFoto();
        marcar('comprobante', 'No se pudo abrir esa foto (puede estar dañada): elige otra.');
      };
      imagen.src = urlVista;
    }

    entrada.addEventListener('change', () => elegirFoto(entrada.files[0]));
    formulario.querySelector('[data-comprobante-cambiar]').addEventListener('click', () => entrada.click());
    formulario.querySelector('[data-comprobante-quitar]').addEventListener('click', () => {
      quitarFoto();
      entrada.focus();
    });

    /* Soltar la foto sobre la zona */
    ['dragenter', 'dragover'].forEach((tipo) => zona.addEventListener(tipo, (evento) => {
      if (subida || !evento.dataTransfer?.types.includes('Files')) return;
      evento.preventDefault();
      zona.classList.add('is-arrastrando');
    }));
    ['dragleave', 'dragend'].forEach((tipo) => zona.addEventListener(tipo, () => zona.classList.remove('is-arrastrando')));
    zona.addEventListener('drop', (evento) => {
      evento.preventDefault();
      zona.classList.remove('is-arrastrando');
      if (!subida) elegirFoto(evento.dataTransfer?.files?.[0]);
    });

    motivo.addEventListener('input', () => {
      if (!errorDe('motivo').hidden && motivo.value.trim().length >= MINIMO_MOTIVO) marcar('motivo');
    });

    const abrir = (detalle) => {
      if (subida) return;
      celda = detalle;
      formulario.reset();
      quitarFoto();
      marcar('motivo');
      marcar('comprobante');
      mostrarError();
      progreso.hidden = true;
      campo('inscripcion').value = detalle.inscripcion;
      campo('fecha').value = detalle.fecha;
      campo('version').value = detalle.version;
      formulario.querySelector('[data-justificar-alumno]').textContent = detalle.alumno;
      formulario.querySelector('[data-justificar-fecha]').textContent = fechaLarga(detalle);
      formulario.querySelector('[data-justificar-observacion-texto]').textContent = detalle.observaciones;
      observacion.hidden = !detalle.observaciones;
      dialogo.showModal();
      bloquearPagina();
      motivo.focus();
    };
    raiz.addEventListener('asistencia:justificar', (evento) => abrir(evento.detail));

    formulario.querySelectorAll('[data-justificar-cerrar]').forEach((boton) => boton.addEventListener('click', () => {
      subida?.abort();
      dialogo.close();
    }));
    /* Escape no corta una subida a medias (para eso está «Cancelar») */
    dialogo.addEventListener('cancel', (evento) => {
      if (subida) evento.preventDefault();
    });
    /* Al cerrarse, el foco vuelve a la celda (después de que el navegador lo devuelva a donde estaba) */
    dialogo.addEventListener('close', () => {
      quitarFoto();
      const boton = celda?.boton;
      celda = null;
      window.setTimeout(() => boton?.focus(), 0);
    });

    /* --- Guardar ------------------------------------------------------------------------------------------------ */
    const enviar = (texto) => {
      const detalle = celda;
      const datos = new FormData(formulario);
      datos.set('motivo', texto);
      datos.set('comprobante', foto, foto.name);

      const peticion = new XMLHttpRequest();
      subida = peticion;
      detalle.ocupada(true);
      guardar.classList.add('is-loading');
      formulario.setAttribute('aria-busy', 'true');
      actualizar();
      progreso.hidden = false;
      barra.style.width = '0%';
      progresoTexto.textContent = 'Subiendo el comprobante…';

      const terminar = () => {
        subida = null;
        detalle.ocupada(false);
        guardar.classList.remove('is-loading');
        formulario.removeAttribute('aria-busy');
        actualizar();
      };
      const fallo = (mensaje) => {
        terminar();
        progreso.hidden = true;
        mostrarError(mensaje);
        guardar.focus();
      };

      peticion.upload.addEventListener('progress', (evento) => {
        if (!evento.lengthComputable) return;
        const avance = Math.round((100 * evento.loaded) / evento.total);
        barra.style.width = `${avance}%`;
        progresoTexto.textContent = avance < 100 ? `Subiendo el comprobante… ${avance} %` : 'Guardando la justificación…';
      });
      peticion.addEventListener('load', () => {
        let json = null;
        try {
          json = JSON.parse(peticion.responseText);
        } catch (error) {
          json = null;
        }
        if (peticion.status === 200 && json?.ok) {
          terminar();
          detalle.pintar(json);
          dialogo.close();
          detalle.avisar(json.mensaje, 'success');
          return;
        }
        if (!json) {
          fallo(peticion.status === 403
            ? 'Tu cuenta no tiene permiso para justificar faltas: la falta sigue sin justificar.'
            : 'El servidor no pudo guardar la justificación (quizá terminó tu sesión). Recarga la página e inténtalo de nuevo: la falta sigue sin justificar.');
          return;
        }
        if (json.letra !== undefined) detalle.pintar(json);   // lo que está guardado
        if (peticion.status === 409) {   // la falta cambió mientras tanto: esta ventana ya no sirve
          terminar();
          dialogo.close();
          detalle.avisar(`No se justificó: ${json.mensaje}`, 'error');
          return;
        }
        if (json.errores) {   // lo que se corrige en un campo
          terminar();
          progreso.hidden = true;
          Object.entries(json.errores).forEach(([nombre, mensajes]) => {
            if (errorDe(nombre)) marcar(nombre, mensajes[0]);
          });
          if (Object.keys(json.errores).some((nombre) => !errorDe(nombre))) mostrarError(json.mensaje);
          (json.errores.motivo ? motivo : entrada).focus();
          return;
        }
        fallo(`No se guardó: ${json.mensaje}`);
      });
      peticion.addEventListener('error', () => fallo('No se pudo subir el comprobante: revisa tu conexión e inténtalo de nuevo. La falta sigue sin justificar.'));
      peticion.addEventListener('timeout', () => fallo('La subida tardó demasiado: revisa tu conexión e inténtalo de nuevo. La falta sigue sin justificar.'));
      peticion.addEventListener('abort', () => {
        terminar();
        progreso.hidden = true;
        detalle.avisar('Se canceló la subida: la falta sigue sin justificar.');
      });

      peticion.open('POST', formulario.action);
      peticion.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
      peticion.timeout = 120000;
      peticion.send(datos);
    };

    formulario.addEventListener('submit', (evento) => {
      evento.preventDefault();
      if (subida || !celda) return;
      mostrarError();
      const texto = motivo.value.trim().replace(/\s+/g, ' ');
      let primero = null;
      if (texto.length < MINIMO_MOTIVO) {
        marcar('motivo', `Escribe el motivo de la justificación (al menos ${MINIMO_MOTIVO} letras).`);
        primero = motivo;
      }
      if (!foto) {
        marcar('comprobante', 'Sube la fotografía del comprobante: sin ella no se puede justificar la falta.');
        primero = primero || entrada;
      }
      if (primero) {
        primero.focus();
        return;
      }
      enviar(texto);
    });
  }

  /* ======================================================================== Consultar la justificación de una J */
  const visor = document.querySelector('[data-ver-justificacion]');
  if (visor) {
    const dato = (nombre) => visor.querySelector(`[data-ver="${nombre}"]`);
    const figura = visor.querySelector('[data-ver-foto]');
    const enlaceFoto = visor.querySelector('[data-ver-foto-enlace]');
    const imagenFoto = visor.querySelector('[data-ver-foto-img]');
    const archivo = visor.querySelector('[data-ver-archivo]');
    const enlaceArchivo = visor.querySelector('[data-ver-archivo-enlace]');
    const sinComprobante = visor.querySelector('[data-ver-sin-comprobante]');
    const lista = visor.querySelector('[data-ver-lista]');
    let celdaVista = null;

    /* Si la foto no carga (sin conexión con el almacenamiento), queda el enlace para abrirla aparte */
    imagenFoto.addEventListener('error', () => {
      if (!imagenFoto.getAttribute('src')) return;
      figura.hidden = true;
      archivo.hidden = false;
    });

    raiz.addEventListener('asistencia:ver-justificacion', ({ detail }) => {
      const justificacion = detail.justificacion;
      if (!justificacion) {
        detail.avisar(detail.boton.dataset.tooltip);
        return;
      }
      celdaVista = detail.boton;
      dato('alumno').textContent = detail.alumno;
      dato('fecha').textContent = fechaLarga(detail);
      dato('motivo').textContent = justificacion.motivo || '—';
      const quien = justificacion.registrada_por ? `Por ${justificacion.registrada_por} el ` : 'El ';
      const donde = justificacion.de_la_falta ? 'desde esta falta' : 'desde Justificaciones';
      dato('registro').textContent = `${quien}${justificacion.registrada_el} (${donde})`;

      const comprobante = justificacion.comprobante;
      figura.hidden = !(comprobante && justificacion.es_imagen);
      archivo.hidden = !(comprobante && !justificacion.es_imagen);
      sinComprobante.hidden = Boolean(comprobante);
      enlaceFoto.href = comprobante || '#';
      enlaceArchivo.href = comprobante || '#';
      if (comprobante && justificacion.es_imagen) {
        /* Si no resulta ser una imagen (p. ej. un PDF guardado sin extensión), se ofrece abrirlo */
        imagenFoto.onerror = () => {
          figura.hidden = true;
          archivo.hidden = false;
        };
        imagenFoto.src = comprobante;
      } else {
        imagenFoto.removeAttribute('src');
      }
      lista.href = justificacion.lista;
      visor.showModal();
      bloquearPagina();
    });
    visor.addEventListener('close', () => {
      const boton = celdaVista;
      celdaVista = null;
      window.setTimeout(() => boton?.focus(), 0);
    });
  }
})();
