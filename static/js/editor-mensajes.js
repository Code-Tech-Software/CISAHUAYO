/* CISAHUAYO · editor de mensajes con formato (templates/mensajes/_editor.html, static/css/editor-mensajes.css)

   Un área editable (contenteditable) con su barra de herramientas. No usa librerías: los formatos en línea, las listas,
   la alineación y los títulos usan los comandos de edición del navegador; las tablas, la sangría de párrafos, las
   imágenes y los tamaños de letra se aplican sobre el documento. El HTML que sale de aquí no se da por bueno: el
   servidor lo limpia siempre (Mensajes/enriquecido.py).

   - Historial propio (deshacer y rehacer cubren todo, también tablas e imágenes); Ctrl+Z, Ctrl+Y y Ctrl+Mayús+Z.
   - La selección se guarda al salir del área y se recupera antes de aplicar cualquier herramienta (paneles, listas
     desplegables y ventanas no la pierden).
   - La barra refleja el formato donde está el cursor: negrita, alineación, listas, fuente, tamaño, párrafo y colores.
   - Si no cabe, los grupos de la fila de arriba pasan a la de abajo, que se muestra con «Más herramientas».
   - Imágenes: se suben al servidor (solo las ve la conversación) y se insertan; al tocarlas se cambia su tamaño, su
     texto alternativo o se eliminan.
   Uso (static/js/mensajes.js): new EditorEnriquecido(raiz, { alEnviar, alCambiar }) → .html(), .texto(), .vacio(),
   .subiendo(), .vaciar(), .enfocar(), .poner(html) (un borrador guardado) y .ponerCursorAlFinal().
*/
(() => {
  'use strict';

  const FUENTES = {
    Nunito: '"Nunito", sans-serif', Arial: 'Arial, sans-serif', Georgia: 'Georgia, serif',
    'Times New Roman': '"Times New Roman", serif', 'Courier New': '"Courier New", monospace', Verdana: 'Verdana, sans-serif',
    'Trebuchet MS': '"Trebuchet MS", sans-serif',
  };
  const COLORES_TEXTO = [
    ['#000000', 'Negro'], ['#434343', 'Gris oscuro'], ['#7f7f7f', 'Gris'], ['#ba1346', 'Guinda'],
    ['#c0392b', 'Rojo'], ['#d35400', 'Naranja'], ['#b7950b', 'Mostaza'], ['#1e8449', 'Verde'],
    ['#117a65', 'Verde azulado'], ['#2f737c', 'Turquesa'], ['#1f618d', 'Azul'], ['#283593', 'Azul marino'],
    ['#6c3483', 'Morado'], ['#ad1457', 'Rosa'], ['#795548', 'Café'], ['#cc8118', 'Dorado'],
  ];
  const COLORES_RESALTADO = [
    ['#fff59d', 'Amarillo'], ['#ffe0b2', 'Naranja claro'], ['#ffcdd2', 'Rojo claro'], ['#f8bbd0', 'Rosa claro'],
    ['#e1bee7', 'Lila'], ['#c5cae9', 'Lavanda'], ['#bbdefb', 'Azul claro'], ['#b2ebf2', 'Turquesa claro'],
    ['#c8e6c9', 'Verde claro'], ['#f0f4c3', 'Lima'], ['#eeeeee', 'Gris claro'], ['#d7ccc8', 'Arena'],
  ];
  const EMOJIS = {
    Caras: [['😀', 'Cara sonriente'], ['😃', 'Sonrisa grande'], ['😊', 'Sonrisa con ojos felices'], ['🙂', 'Leve sonrisa'],
      ['😉', 'Guiño'], ['😍', 'Enamorado'], ['🥰', 'Cara con corazones'], ['😂', 'Lágrimas de risa'], ['🤗', 'Abrazo'],
      ['🤔', 'Pensando'], ['😮', 'Sorpresa'], ['😢', 'Lágrima'], ['😴', 'Dormido'], ['😎', 'Con lentes'], ['🥳', 'Fiesta'], ['😷', 'Cubrebocas']],
    Gestos: [['👍', 'Pulgar arriba'], ['👎', 'Pulgar abajo'], ['👏', 'Aplausos'], ['🙌', 'Manos arriba'], ['🙏', 'Gracias'],
      ['👋', 'Saludo'], ['✋', 'Mano levantada'], ['👌', 'De acuerdo'], ['✌️', 'Paz'], ['🤝', 'Apretón de manos'], ['💪', 'Fuerza'],
      ['👀', 'Ojos'], ['❤️', 'Corazón'], ['💙', 'Corazón azul'], ['⭐', 'Estrella'], ['🔥', 'Fuego']],
    Escuela: [['📚', 'Libros'], ['📖', 'Libro abierto'], ['✏️', 'Lápiz'], ['📝', 'Nota'], ['🎒', 'Mochila'], ['🏫', 'Escuela'],
      ['🎓', 'Graduación'], ['🧮', 'Ábaco'], ['🔬', 'Microscopio'], ['🎨', 'Paleta'], ['⚽', 'Balón'], ['🏆', 'Trofeo'],
      ['📅', 'Calendario'], ['⏰', 'Despertador'], ['🚌', 'Autobús'], ['🍎', 'Manzana']],
    Símbolos: [['✅', 'Hecho'], ['❌', 'Equis'], ['⚠️', 'Advertencia'], ['❗', 'Exclamación'], ['❓', 'Pregunta'], ['📌', 'Chincheta'],
      ['📣', 'Megáfono'], ['🔔', 'Campana'], ['💡', 'Idea'], ['🎉', 'Celebración'], ['🎂', 'Pastel'], ['📎', 'Clip'],
      ['📞', 'Teléfono'], ['✉️', 'Sobre'], ['➡️', 'Flecha derecha'], ['🔗', 'Enlace']],
  };
  const TAMANOS = ['8pt', '9pt', '10pt', '11pt', '12pt', '14pt', '16pt', '18pt', '20pt', '24pt', '28pt', '32pt', '36pt'];
  const CENTINELA = 'rgb(1, 2, 3)';           /* color de paso para quitar un color o un resaltado */
  const FUENTE_CENTINELA = 'cisahuayo-sin-fuente';
  const SANGRIA_PASO = 40;
  const SANGRIA_MAXIMA = 200;
  const MAXIMO_HISTORIAL = 100;
  const BLOQUES = 'p,h1,h2,h3,li,blockquote,div,td,th';
  const ESCRITURA = ['bold', 'italic', 'underline', 'strikeThrough'];
  const INVISIBLE = '\u200b';          /* sostiene el formato elegido con el cursor sin selección (ver enCursor) */
  const LLAVE_MAS = 'cisahuayo.editor.mas';
  const GRUPOS_PRIMERO = ['estilo', 'historial'];

  const qs = (selector, ambito = document) => ambito.querySelector(selector);
  const qsa = (selector, ambito = document) => [...ambito.querySelectorAll(selector)];
  const EN_LINEA = 'b,strong,i,em,u,s,strike,del,span,sub,sup';
  const textosCon = (raiz, cadena) => {
    const recorrido = document.createTreeWalker(raiz, NodeFilter.SHOW_TEXT);
    const encontrados = [];
    while (recorrido.nextNode()) if (recorrido.currentNode.data.includes(cadena)) encontrados.push(recorrido.currentNode);
    return encontrados;
  };
  const escapar = (texto) => String(texto).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const rgb = (color) => {
    const prueba = document.createElement('span');
    prueba.style.color = color;
    return prueba.style.color;
  };
  const leerAlmacen = (llave) => { try { return window.localStorage.getItem(llave); } catch (error) { return null; } };
  const guardarAlmacen = (llave, valor) => { try { window.localStorage.setItem(llave, valor); } catch (error) { /* sin almacenamiento */ } };

  class EditorEnriquecido {
    constructor(raiz, opciones = {}) {
      this.raiz = raiz;
      this.opciones = opciones;
      this.area = qs('[data-editor-area]', raiz);
      this.barra = qs('[data-editor-barra]', raiz);
      this.filaPrincipal = qs('[data-editor-fila="principal"]', raiz);
      this.filaExtra = qs('[data-editor-fila="extra"]', raiz);
      this.botonMas = qs('[data-editor-mas]', raiz);
      this.acciones = qs('[data-editor-acciones]', raiz);
      this.botonFormato = qs('[data-editor-formato]', raiz);
      this.archivo = qs('[data-editor-archivo]', raiz);
      this.estado = qs('[data-editor-estado]', raiz);
      this.selects = { fuente: qs('[data-editor-fuente]', raiz), tamano: qs('[data-editor-tamano]', raiz), parrafo: qs('[data-editor-parrafo]', raiz) };
      this.gruposPrincipales = qsa('[data-editor-grupo]', this.filaPrincipal);
      this.gruposExtra = qsa('[data-editor-grupo]', this.filaExtra);
      this.paneles = {};
      qsa('[data-editor-panel]', raiz).forEach((panel) => {
        panel.hidden = false;
        document.body.append(panel);   /* en la capa superior, fuera del recorte de la conversación */
        this.paneles[panel.dataset.editorPanel] = panel;
      });
      this.rango = null;
      this.historial = [];
      this.posicion = -1;
      this.pendiente = null;
      this.subidas = 0;
      this.tamanoPendiente = null;
      this.panelAbierto = null;
      this.imagenElegida = null;

      document.execCommand('defaultParagraphSeparator', false, 'p');
      this.area.innerHTML = '<p><br></p>';
      this.area.classList.add('is-vacio');   /* el texto de ayuda («Escribe un mensaje…») desde que se abre */
      this.guardarEstado();
      this.prepararPaneles();
      this.caracteres = this.prepararCaracteres();
      this.escuchar();
      this.raiz.hidden = false;
      this.reacomodar();
      this.ponerFormato(false);
      this.ponerMas(leerAlmacen(LLAVE_MAS) === null ? window.matchMedia('(min-width: 64rem)').matches : leerAlmacen(LLAVE_MAS) === '1');
      this.actualizarBarra();
    }

    /* ================================================================== API para mensajes.js */
    html() {
      const copia = this.area.cloneNode(true);
      qsa('img', copia).forEach((imagen) => { imagen.removeAttribute('data-elegida'); });
      textosCon(copia, INVISIBLE).forEach((texto) => {
        texto.data = texto.data.split(INVISIBLE).join('');
        if (!texto.data) texto.remove();
      });
      qsa(EN_LINEA, copia).reverse().forEach((nodo) => { if (!nodo.childNodes.length) nodo.remove(); });
      return copia.innerHTML;
    }

    texto() {
      return this.area.innerText.replace(/\u200b/g, '').trim();
    }

    vacio() {
      return !this.texto().replace(/\u00a0/g, ' ').trim() && !qs('img', this.area);
    }

    subiendo() {
      return this.subidas > 0;
    }

    vaciar() {
      this.area.innerHTML = '<p><br></p>';
      this.historial = [];
      this.posicion = -1;
      this.guardarEstado();
      this.ponerCursorAlFinal();
      this.cambio();
    }

    enfocar() {
      this.area.focus({ preventScroll: true });
    }

    /* Pone un contenido guardado (el borrador de la conversación, static/js/mensajes.js) como punto de partida: sin
       historial anterior y con el cursor al final, sin tomar el foco. Salió de este mismo editor; aun así se le quitan
       scripts y atributos de eventos antes de mostrarlo. */
    poner(html) {
      const documento = new DOMParser().parseFromString(html || '', 'text/html');
      qsa('script,style,iframe,object,embed,svg,math,meta,link,form,input,button,textarea,select', documento.body).forEach((nodo) => nodo.remove());
      qsa('*', documento.body).forEach((nodo) => {
        [...nodo.attributes].forEach((atributo) => {
          if (/^on/i.test(atributo.name) || (['href', 'src'].includes(atributo.name) && /^\s*javascript:/i.test(atributo.value))) {
            nodo.removeAttribute(atributo.name);
          }
        });
      });
      this.area.innerHTML = documento.body.innerHTML.trim() || '<p><br></p>';
      this.historial = [];
      this.posicion = -1;
      this.guardarEstado();
      const rango = document.createRange();
      rango.selectNodeContents(this.area.lastElementChild || this.area);
      rango.collapse(false);
      this.rango = rango;
      this.cambio();
      this.actualizarBarra();
    }

    /* ================================================================== selección */
    dentro(nodo) {
      return nodo && (nodo === this.area || this.area.contains(nodo));
    }

    guardarRango() {
      const seleccion = window.getSelection();
      if (seleccion.rangeCount && this.dentro(seleccion.getRangeAt(0).commonAncestorContainer)) {
        this.rango = seleccion.getRangeAt(0).cloneRange();
      }
    }

    restaurarRango() {
      const seleccion = window.getSelection();
      /* Con el foco en el área, manda la selección real (el aviso de cambio de selección puede llegar tarde) */
      if (document.activeElement === this.area && seleccion.rangeCount && this.dentro(seleccion.getRangeAt(0).commonAncestorContainer)) {
        this.rango = seleccion.getRangeAt(0).cloneRange();
        return;
      }
      this.area.focus({ preventScroll: true });
      if (this.rango && this.dentro(this.rango.commonAncestorContainer) && this.rango.startContainer.isConnected) {
        seleccion.removeAllRanges();
        seleccion.addRange(this.rango);
      } else if (!seleccion.rangeCount || !this.dentro(seleccion.getRangeAt(0).commonAncestorContainer)) {
        this.ponerCursorAlFinal();
      }
    }

    ponerCursorAlFinal() {
      const rango = document.createRange();
      rango.selectNodeContents(this.area.lastElementChild || this.area);
      rango.collapse(false);
      const seleccion = window.getSelection();
      seleccion.removeAllRanges();
      seleccion.addRange(rango);
      this.rango = rango.cloneRange();
    }

    rangoActual() {
      const seleccion = window.getSelection();
      if (seleccion.rangeCount && this.dentro(seleccion.getRangeAt(0).commonAncestorContainer)) return seleccion.getRangeAt(0);
      return this.rango;
    }

    elementoActual() {
      const rango = this.rangoActual();
      if (!rango) return this.area.firstElementChild || this.area;
      let nodo = rango.startContainer;
      if (nodo.nodeType === Node.TEXT_NODE) nodo = nodo.parentElement;
      else if (nodo.childNodes[rango.startOffset]?.nodeType === Node.ELEMENT_NODE && nodo !== this.area) nodo = nodo.childNodes[rango.startOffset];
      if (nodo === this.area) nodo = this.area.children[Math.min(rango.startOffset, this.area.children.length - 1)] || this.area;
      return this.dentro(nodo) ? nodo : this.area;
    }

    cercano(selector) {
      const nodo = this.elementoActual()?.closest?.(selector);
      return nodo && this.dentro(nodo) && nodo !== this.area ? nodo : null;
    }

    bloquesSeleccionados() {
      const rango = this.rangoActual();
      const inicio = this.cercano(BLOQUES);
      if (!rango || rango.collapsed) return inicio ? [inicio] : [];
      const bloques = qsa('p,h1,h2,h3,blockquote,div', this.area).filter((bloque) => rango.intersectsNode(bloque) && !bloque.closest('li,td,th'));
      return bloques.length ? bloques : (inicio ? [inicio] : []);
    }

    /* Rutas de la selección (para el historial): índices desde el área hasta el nodo y el desplazamiento */
    ruta(nodo, desplazamiento) {
      const camino = [];
      while (nodo && nodo !== this.area) {
        const padre = nodo.parentNode;
        if (!padre) return null;
        camino.unshift([...padre.childNodes].indexOf(nodo));
        nodo = padre;
      }
      return nodo === this.area ? { camino, desplazamiento } : null;
    }

    nodoDe(ruta) {
      let nodo = this.area;
      for (const indice of ruta.camino) {
        nodo = nodo.childNodes[indice];
        if (!nodo) return null;
      }
      return nodo;
    }

    marcaDeSeleccion() {
      const rango = this.rangoActual();
      if (!rango) return null;
      return { inicio: this.ruta(rango.startContainer, rango.startOffset), fin: this.ruta(rango.endContainer, rango.endOffset) };
    }

    ponerSeleccion(marca) {
      try {
        const inicio = marca?.inicio && this.nodoDe(marca.inicio);
        const fin = marca?.fin && this.nodoDe(marca.fin);
        if (!inicio || !fin) throw new Error('sin selección');
        const rango = document.createRange();
        rango.setStart(inicio, Math.min(marca.inicio.desplazamiento, inicio.length ?? inicio.childNodes.length));
        rango.setEnd(fin, Math.min(marca.fin.desplazamiento, fin.length ?? fin.childNodes.length));
        const seleccion = window.getSelection();
        seleccion.removeAllRanges();
        seleccion.addRange(rango);
        this.rango = rango.cloneRange();
      } catch (error) {
        this.ponerCursorAlFinal();
      }
    }

    /* ================================================================== historial */
    guardarEstado() {
      window.clearTimeout(this.pendiente);
      this.pendiente = null;
      const html = this.area.innerHTML;
      const marca = this.marcaDeSeleccion();
      if (this.historial[this.posicion]?.html === html) {
        this.historial[this.posicion].marca = marca;
        return;
      }
      this.historial.splice(this.posicion + 1);
      this.historial.push({ html, marca });
      if (this.historial.length > MAXIMO_HISTORIAL) this.historial.shift();
      this.posicion = this.historial.length - 1;
      this.actualizarHistorial();
    }

    guardarLuego() {
      window.clearTimeout(this.pendiente);
      this.pendiente = window.setTimeout(() => this.guardarEstado(), 450);
    }

    aplicarEstado(estado) {
      this.area.innerHTML = estado.html;
      this.area.focus({ preventScroll: true });
      this.ponerSeleccion(estado.marca);
      this.soltarImagen();
      this.actualizarHistorial();
      this.cambio();
      this.actualizarBarra();
    }

    deshacer() {
      if (this.pendiente) this.guardarEstado();
      if (this.posicion <= 0) return;
      this.posicion -= 1;
      this.aplicarEstado(this.historial[this.posicion]);
    }

    rehacer() {
      if (this.pendiente) this.guardarEstado();
      if (this.posicion >= this.historial.length - 1) return;
      this.posicion += 1;
      this.aplicarEstado(this.historial[this.posicion]);
    }

    actualizarHistorial() {
      this.boton('deshacer').disabled = this.posicion <= 0 && !this.pendiente;
      this.boton('rehacer').disabled = this.posicion >= this.historial.length - 1;
    }

    /* Aplica un cambio como un paso del historial: recupera la selección, lo ejecuta, ordena y guarda */
    aplicar(funcion) {
      if (this.pendiente) this.guardarEstado();
      this.restaurarRango();
      funcion();
      this.normalizar();
      this.guardarRango();
      this.guardarEstado();
      this.cambio();
      this.actualizarBarra();
    }

    cambio() {
      const vacio = this.vacio();
      this.area.classList.toggle('is-vacio', vacio && !qs('ul,ol,table,h1,h2,h3', this.area));
      this.opciones.alCambiar?.(this);
    }

    /* ================================================================== comandos */
    ejecutar(comando, valor = null, conCss = false) {
      document.execCommand('styleWithCSS', false, conCss);
      document.execCommand(comando, false, valor);
    }

    /* Formato con el cursor sin selección. El navegador lo guarda «para lo que se escriba», pero lo pierde o lo combina
       mal (quitar negrita y luego subrayado deja el subrayado). Por eso se escribe un carácter invisible, se le da el
       formato como a cualquier selección y el cursor queda tras él: lo que se escriba hereda ese formato */
    enCursor(funcion) {
      const rango = this.rangoActual();
      if (!rango?.collapsed) {
        funcion();
        return;
      }
      const seleccion = window.getSelection();
      let texto = rango.startContainer;
      let fin = rango.startOffset;
      if (texto.nodeType !== Node.TEXT_NODE || texto.data[fin - 1] !== INVISIBLE) {
        /* Se escribe como lo haría el usuario: el navegador lo pone donde se ve el cursor (que puede no coincidir con
           su posición en el documento, p. ej. tras un salto de línea) y con el formato que tendría lo escrito */
        document.execCommand('insertText', false, INVISIBLE);
        if (!seleccion.rangeCount) return;
        texto = seleccion.getRangeAt(0).startContainer;
        fin = seleccion.getRangeAt(0).startOffset;
        if (texto.nodeType !== Node.TEXT_NODE || texto.data[fin - 1] !== INVISIBLE) {
          funcion();
          return;
        }
      }
      seleccion.setBaseAndExtent(texto, fin - 1, texto, fin);
      funcion();
      if (seleccion.rangeCount) {
        const final = seleccion.getRangeAt(0);
        seleccion.collapse(final.endContainer, final.endOffset);
      }
    }

    boton(comando) {
      return qs(`[data-comando="${comando}"]`, this.barra) || { disabled: false };
    }

    comando(nombre) {
      const simples = {
        negrita: ['bold'], cursiva: ['italic'], subrayado: ['underline'], tachado: ['strikeThrough'],
        izquierda: ['justifyLeft', true], centro: ['justifyCenter', true], derecha: ['justifyRight', true], justificar: ['justifyFull', true],
        numerada: ['insertOrderedList'], vinetas: ['insertUnorderedList'],
      };
      if (nombre === 'deshacer') return this.deshacer();
      if (nombre === 'rehacer') return this.rehacer();
      if (nombre === 'imagen') return this.elegirImagen();
      if (nombre === 'caracteres') return this.abrirCaracteres();
      if (nombre === 'enlace') {
        /* Con Ctrl+K su botón puede no estar a la vista (barra de formato oculta o en la fila de «Más»): el panel se
           pone junto al cuadro de texto */
        const boton = qs('[data-comando="enlace"]', this.barra);
        return this.abrirPanel('enlace', boton, boton.offsetParent ? boton : this.area);
      }
      if (nombre === 'color' || nombre === 'resaltado') {
        return this.abrirPanel(nombre, qs(`[data-panel="${nombre}"]`, this.barra));
      }
      if (simples[nombre]) {
        const [comando, conCss] = simples[nombre];
        if (ESCRITURA.includes(comando)) return this.aplicar(() => this.enCursor(() => this.ejecutar(comando)));
        return this.aplicar(() => this.ejecutar(comando, null, Boolean(conCss)));
      }
      if (nombre === 'mas-sangria' || nombre === 'menos-sangria') return this.aplicar(() => this.sangria(nombre === 'mas-sangria' ? 1 : -1));
      if (nombre === 'limpiar') return this.aplicar(() => this.enCursor(() => this.limpiarFormato()));
      return undefined;
    }

    sangria(direccion) {
      if (this.cercano('li')) {
        this.ejecutar(direccion > 0 ? 'indent' : 'outdent');
        return;
      }
      this.bloquesSeleccionados().forEach((bloque) => {
        const actual = parseInt(bloque.style.marginLeft, 10) || 0;
        const nueva = Math.max(0, Math.min(SANGRIA_MAXIMA, actual + direccion * SANGRIA_PASO));
        bloque.style.marginLeft = nueva ? `${nueva}px` : '';
        if (!bloque.getAttribute('style')) bloque.removeAttribute('style');
      });
    }

    limpiarFormato() {
      this.ejecutar('removeFormat');
      this.ejecutar('removeFormat', null, true);
    }

    /* Quita un estilo (color, resaltado, fuente) de lo seleccionado: se aplica un valor de paso y luego se borra */
    quitarEstilo(comando, propiedad, centinela) {
      this.ejecutar(comando, centinela, true);
      const buscado = propiedad === 'font-family' ? centinela : rgb(centinela);
      qsa('[style]', this.area).forEach((nodo) => {
        const valor = nodo.style.getPropertyValue(propiedad).replace(/["']/g, '');
        if (valor !== buscado) return;
        nodo.style.removeProperty(propiedad);
        this.sacarDeHerencia(nodo, propiedad);
      });
      qsa('font', this.area).forEach((nodo) => {
        if (nodo.getAttribute('face') === centinela || rgb(nodo.getAttribute('color') || '') === buscado) {
          nodo.removeAttribute(propiedad === 'font-family' ? 'face' : 'color');
        }
      });
    }

    /* Si lo que perdió el estilo sigue dentro de otro elemento que lo tiene (texto rojo dentro de un párrafo rojo), lo
       seguiría heredando: ese elemento se parte en tres (antes, el nodo sin el estilo, después) */
    sacarDeHerencia(nodo, propiedad) {
      let antecesor = nodo.parentElement;
      while (antecesor && antecesor !== this.area && this.dentro(antecesor) && !antecesor.matches(BLOQUES)) {
        const siguiente = antecesor.parentElement;
        if (antecesor.style.getPropertyValue(propiedad)) {
          const partes = [[(rango) => { rango.setStart(antecesor, 0); rango.setEndBefore(nodo); }, 'before'],
            [(rango) => { rango.setStartAfter(nodo); rango.setEnd(antecesor, antecesor.childNodes.length); }, 'after']];
          partes.forEach(([limites, lado]) => {
            const rango = document.createRange();
            limites(rango);
            const parte = antecesor.cloneNode(false);
            parte.append(rango.extractContents());
            if (parte.textContent.replace(/​/g, '') || parte.querySelector('img, br')) antecesor[lado](parte);
          });
          antecesor.style.removeProperty(propiedad);
        }
        antecesor = siguiente;
      }
    }

    ponerColor(tipo, color) {
      this.aplicar(() => this.enCursor(() => {
        if (tipo === 'color') {
          if (color) this.ejecutar('foreColor', color, true);
          else this.quitarEstilo('foreColor', 'color', CENTINELA);
        } else if (color) {
          document.execCommand('styleWithCSS', false, true);
          if (!document.execCommand('hiliteColor', false, color)) document.execCommand('backColor', false, color);
        } else {
          this.quitarEstilo('hiliteColor', 'background-color', CENTINELA);
        }
      }));
    }

    ponerFuente(valor) {
      this.aplicar(() => this.enCursor(() => {
        if (valor) this.ejecutar('fontName', valor, true);
        else this.quitarEstilo('fontName', 'font-family', FUENTE_CENTINELA);
      }));
    }

    /* El navegador solo conoce siete tamaños: se aplica el 7 y se cambia por el tamaño en puntos */
    ponerTamano(valor) {
      this.tamanoPendiente = valor;
      this.aplicar(() => this.enCursor(() => this.ejecutar('fontSize', '7')));
    }

    ponerParrafo(valor) {
      this.aplicar(() => this.ejecutar('formatBlock', `<${valor}>`));
    }

    ponerTipoDeLista(tipo) {
      const ordenada = !['disc', 'circle', 'square'].includes(tipo);
      this.aplicar(() => {
        const etiqueta = ordenada ? 'OL' : 'UL';
        if (this.cercano('ol,ul')?.tagName !== etiqueta) this.ejecutar(ordenada ? 'insertOrderedList' : 'insertUnorderedList');
        this.guardarRango();
        const lista = this.cercano(ordenada ? 'ol' : 'ul');
        if (lista) lista.style.listStyleType = tipo;
      });
    }

    /* ================================================================== orden del documento */
    normalizar(invisibles = true) {
      /* El cursor antes de ordenar: los nodos se mueven (no se recrean), así que al final se vuelve a poner donde estaba */
      const seleccion = window.getSelection();
      const viva = seleccion.rangeCount && this.dentro(seleccion.getRangeAt(0).commonAncestorContainer) ? seleccion.getRangeAt(0) : null;
      const marca = viva ? [viva.startContainer, viva.startOffset, viva.endContainer, viva.endOffset] : null;
      let movido = false;
      /* Tamaños: <font size="7"> (o el equivalente con estilo) → el tamaño en puntos que se eligió */
      qsa('font[size]', this.area).forEach((nodo) => {
        const span = document.createElement('span');
        if (nodo.getAttribute('size') === '7' && this.tamanoPendiente) span.style.fontSize = this.tamanoPendiente;
        if (nodo.getAttribute('color')) span.style.color = nodo.getAttribute('color');
        if (nodo.getAttribute('face')) span.style.fontFamily = nodo.getAttribute('face');
        span.append(...nodo.childNodes);
        nodo.replaceWith(span);
        qsa('span', span).forEach((interior) => { if (span.style.fontSize) interior.style.removeProperty('font-size'); });
      });
      qsa('font', this.area).forEach((nodo) => {
        const span = document.createElement('span');
        if (nodo.getAttribute('color')) span.style.color = nodo.getAttribute('color');
        if (nodo.getAttribute('face')) span.style.fontFamily = nodo.getAttribute('face');
        span.append(...nodo.childNodes);
        nodo.replaceWith(span);
      });
      qsa('[style*="xxx-large"]', this.area).forEach((nodo) => {
        if (this.tamanoPendiente) nodo.style.fontSize = this.tamanoPendiente;
        else nodo.style.removeProperty('font-size');
      });
      /* Spans vacíos de estilo: fuera */
      qsa('span', this.area).forEach((nodo) => {
        if (!nodo.getAttribute('style') && !nodo.attributes.length) nodo.replaceWith(...nodo.childNodes);
        else if (nodo.getAttribute('style') === '') nodo.replaceWith(...nodo.childNodes);
      });
      /* Caracteres invisibles de enCursor: solo sigue el del texto donde está el cursor (no se toca mientras se compone
         una palabra con el teclado del celular) */
      if (invisibles) {
        textosCon(this.area, INVISIBLE).forEach((texto) => {
          if (marca && (texto === marca[0] || texto === marca[2])) return;
          texto.data = texto.data.split(INVISIBLE).join('');
          if (!texto.data) texto.remove();
        });
      }
      /* Atributos de estilo vacíos y elementos de texto vacíos que deja el navegador (de dentro hacia fuera) */
      qsa('[style=""]', this.area).forEach((nodo) => nodo.removeAttribute('style'));
      qsa(EN_LINEA, this.area).reverse().forEach((nodo) => {
        if (!nodo.childNodes.length) nodo.remove();
      });
      /* Un bloque (lista, tabla, título, párrafo) dentro de un párrafo o de un elemento de texto: se saca, partiendo en
         dos lo que lo rodeaba (el navegador lo deja así con algunas combinaciones de formato y listas) */
      const BLOQUE = 'ol, ul, table, h1, h2, h3, p, blockquote, div';
      const CONTENEDOR = 'li, td, th, blockquote';
      const vacio = (nodo) => !nodo.textContent.replace(/\u200b/g, '').trim() && !nodo.querySelector('img, table');
      let pendientes = qsa(BLOQUE, this.area).filter((bloque) => bloque.parentElement !== this.area && !bloque.parentElement.matches(CONTENEDOR));
      let vueltas = 0;
      while (pendientes.length && vueltas < 20) {
        vueltas += 1;
        pendientes.forEach((bloque) => {
          const padre = bloque.parentElement;
          if (!padre || padre === this.area || padre.matches(CONTENEDOR)) return;
          movido = true;
          const resto = padre.cloneNode(false);
          while (bloque.nextSibling) resto.append(bloque.nextSibling);
          padre.after(bloque);
          bloque.after(resto);
          if (vacio(padre)) padre.remove();
          if (vacio(resto)) resto.remove();
        });
        pendientes = qsa(BLOQUE, this.area).filter((bloque) => bloque.parentElement !== this.area && !bloque.parentElement.matches(CONTENEDOR));
      }
      /* Texto suelto directamente en el área: a un párrafo */
      [...this.area.childNodes].forEach((nodo) => {
        if (nodo.nodeType === Node.ELEMENT_NODE && nodo.matches(BLOQUE)) return;
        if (nodo.nodeType === Node.TEXT_NODE && !nodo.textContent.trim()) return;
        movido = true;
        const anterior = nodo.previousSibling;
        if (anterior?.nodeType === Node.ELEMENT_NODE && anterior.tagName === 'P' && anterior.dataset.suelto) anterior.append(nodo);
        else {
          const parrafo = document.createElement('p');
          parrafo.dataset.suelto = '1';
          nodo.before(parrafo);
          parrafo.append(nodo);
        }
      });
      qsa('p[data-suelto]', this.area).forEach((parrafo) => parrafo.removeAttribute('data-suelto'));
      /* También si solo se desenvolvió un elemento: al mover un nodo, el navegador saca la selección de él */
      const distinta = (rango) => !rango || rango.startContainer !== marca[0] || rango.startOffset !== marca[1]
        || rango.endContainer !== marca[2] || rango.endOffset !== marca[3];
      if (marca && (movido || distinta(seleccion.rangeCount ? seleccion.getRangeAt(0) : null))
        && marca[0].isConnected && marca[2].isConnected && this.dentro(marca[0]) && this.dentro(marca[2])) {
        try {
          seleccion.setBaseAndExtent(marca[0], marca[1], marca[2], marca[3]);
        } catch (error) {
          /* la posición ya no existe: el navegador deja el cursor donde pudo */
        }
      }
      if (!this.area.firstChild) this.area.innerHTML = '<p><br></p>';
    }

    /* ================================================================== barra */
    actualizarBarra() {
      if (this.cuadro) return;
      this.cuadro = window.requestAnimationFrame(() => {
        this.cuadro = null;
        this.pintarBarra();
      });
    }

    estadoDe(comando) {
      try {
        return document.queryCommandState(comando);
      } catch (error) {
        return false;
      }
    }

    /* Con el cursor justo tras el carácter invisible de enCursor, el navegador informa el formato de lo que hay antes;
       se lee del documento: es el que tendrá lo que se escriba */
    formatoSostenido() {
      const rango = this.rangoActual();
      const texto = rango?.collapsed ? rango.startContainer : null;
      if (texto?.nodeType !== Node.TEXT_NODE || texto.data[rango.startOffset - 1] !== INVISIBLE || !texto.parentElement) return null;
      const estilo = window.getComputedStyle(texto.parentElement);
      let lineas = '';
      for (let nodo = texto.parentElement; nodo && this.dentro(nodo); nodo = nodo.parentElement) {
        lineas += ` ${window.getComputedStyle(nodo).textDecorationLine}`;
      }
      return {
        bold: parseInt(estilo.fontWeight, 10) >= 600, italic: estilo.fontStyle === 'italic',
        underline: lineas.includes('underline'), strikeThrough: lineas.includes('line-through'),
      };
    }

    pintarBarra() {
      const enArea = this.dentro(document.activeElement) || this.panelAbierto;
      const elemento = this.elementoActual();
      const estilo = window.getComputedStyle(elemento.nodeType === Node.ELEMENT_NODE ? elemento : this.area);
      const marcar = (comando, activo) => {
        const boton = qs(`[data-comando="${comando}"]`, this.barra);
        if (boton) boton.setAttribute('aria-pressed', String(Boolean(activo)));
      };
      if (enArea) {
        const sostenido = this.formatoSostenido();
        const activo = (comando) => (sostenido ? sostenido[comando] : this.estadoDe(comando));
        marcar('negrita', activo('bold'));
        marcar('cursiva', activo('italic'));
        marcar('subrayado', activo('underline'));
        marcar('tachado', activo('strikeThrough'));
      }
      const alineacion = this.cercano(BLOQUES);
      const alinear = alineacion ? window.getComputedStyle(alineacion).textAlign : 'left';
      marcar('izquierda', ['left', 'start'].includes(alinear));
      marcar('centro', alinear === 'center');
      marcar('derecha', ['right', 'end'].includes(alinear));
      marcar('justificar', alinear === 'justify');
      const lista = this.cercano('ol,ul');
      marcar('numerada', lista?.tagName === 'OL');
      marcar('vinetas', lista?.tagName === 'UL');

      /* Fuente, tamaño y párrafo */
      const familia = estilo.fontFamily.split(',')[0].replace(/["']/g, '').trim();
      const base = window.getComputedStyle(this.area).fontFamily.split(',')[0].replace(/["']/g, '').trim();
      this.selects.fuente.value = familia === base || !FUENTES[familia] ? '' : familia;
      const puntos = `${Math.round(parseFloat(estilo.fontSize) * 0.75)}pt`;
      qsa('option[data-temporal]', this.selects.tamano).forEach((opcion) => opcion.remove());
      if (!TAMANOS.includes(puntos)) {
        const opcion = new Option(puntos, puntos);
        opcion.dataset.temporal = '';
        this.selects.tamano.add(opcion);
      }
      this.selects.tamano.value = puntos;
      const bloque = this.cercano('h1,h2,h3');
      this.selects.parrafo.value = bloque ? bloque.tagName.toLowerCase() : 'p';

      /* Colores: el de la selección, o el predeterminado */
      const colorBase = window.getComputedStyle(this.area).color;
      const muestraColor = qs('[data-muestra="color"]', this.barra);
      muestraColor.style.setProperty('--muestra', estilo.color === colorBase ? 'currentColor' : estilo.color);
      const resaltado = this.resaltadoActual(elemento);
      qs('[data-muestra="resaltado"]', this.barra).style.setProperty('--muestra', resaltado || 'transparent');

      /* Disponibles */
      const rango = this.rangoActual();
      this.boton('limpiar').disabled = !rango || rango.collapsed;
      this.boton('menos-sangria').disabled = !lista && !(this.bloquesSeleccionados().some((b) => parseInt(b.style.marginLeft, 10) > 0));
      this.boton('mas-sangria').disabled = !lista && this.bloquesSeleccionados().every((b) => (parseInt(b.style.marginLeft, 10) || 0) >= SANGRIA_MAXIMA);
      this.actualizarHistorial();
    }

    resaltadoActual(elemento) {
      let nodo = elemento;
      while (nodo && nodo !== this.area && this.dentro(nodo)) {
        const fondo = nodo.style?.backgroundColor;
        if (fondo) return fondo;
        nodo = nodo.parentElement;
      }
      return '';
    }

    /* «Mostrar opciones de formato» (como en Teams): la barra empieza oculta; al mostrarla se reparten de nuevo sus
       grupos, porque oculta no tiene ancho que medir */
    ponerFormato(visible) {
      if (!visible) this.cerrarPanel(false);
      this.barra.hidden = !visible;
      if (visible) this.reacomodar();
      if (!this.botonFormato) return;
      const texto = visible ? 'Ocultar opciones de formato' : 'Mostrar opciones de formato';
      this.botonFormato.setAttribute('aria-pressed', String(visible));
      this.botonFormato.setAttribute('aria-label', texto);
      this.botonFormato.dataset.tooltip = `${texto} (Ctrl+Mayús+F)`;
    }

    /* «Más herramientas»: muestra u oculta la fila de abajo */
    ponerMas(abierta) {
      this.filaExtra.hidden = !abierta;
      this.botonMas.setAttribute('aria-expanded', String(abierta));
      this.botonMas.classList.toggle('is-activo', abierta);
    }

    /* Los grupos de arriba que no caben pasan al principio de la fila de abajo */
    reacomodar() {
      const abierta = !this.filaExtra.hidden;
      this.filaExtra.hidden = false;
      this.gruposPrincipales.forEach((grupo) => this.filaPrincipal.append(grupo));
      const espacio = this.barra.clientWidth - this.botonMas.offsetWidth - 24;
      /* Arriba se quedan primero los de más uso (en el celular solo caben negrita, cursiva, subrayado y tachado);
         los que no caben bajan a la fila de «Más», en su orden */
      const orden = [...GRUPOS_PRIMERO.map((nombre) => this.gruposPrincipales.find((grupo) => grupo.dataset.editorGrupo === nombre)),
        ...this.gruposPrincipales.filter((grupo) => !GRUPOS_PRIMERO.includes(grupo.dataset.editorGrupo))].filter(Boolean);
      const arriba = new Set([orden[0]]);   /* al menos uno */
      let ocupado = orden[0].offsetWidth + 8;
      for (const grupo of orden.slice(1)) {
        ocupado += grupo.offsetWidth + 8;
        if (ocupado > espacio) break;
        arriba.add(grupo);
      }
      const sobrantes = this.gruposPrincipales.filter((grupo) => !arriba.has(grupo));
      this.filaExtra.prepend(...sobrantes);
      this.barra.classList.toggle('is-compacta', sobrantes.length > 0);
      this.filaExtra.hidden = !abierta;
    }

    /* ================================================================== paneles */
    prepararPaneles() {
      /* Paletas */
      [['color', COLORES_TEXTO], ['resaltado', COLORES_RESALTADO]].forEach(([tipo, colores]) => {
        const paleta = qs(`[data-paleta="${tipo}"]`, this.paneles[tipo]);
        colores.forEach(([color, nombre]) => {
          const boton = document.createElement('button');
          boton.type = 'button';
          boton.className = 'editor-paleta__color';
          boton.style.setProperty('--muestra', color);
          boton.dataset.color = color;
          boton.setAttribute('aria-label', nombre);
          boton.title = nombre;
          paleta.append(boton);
        });
      });
      /* Cuadrícula de la tabla: 8 columnas × 6 filas */
      const cuadricula = qs('[data-tabla-cuadricula]', this.paneles.tabla);
      for (let fila = 1; fila <= 6; fila += 1) {
        for (let columna = 1; columna <= 8; columna += 1) {
          const celda = document.createElement('button');
          celda.type = 'button';
          celda.className = 'editor-cuadricula__celda';
          celda.dataset.filas = String(fila);
          celda.dataset.columnas = String(columna);
          celda.setAttribute('aria-label', `Tabla de ${fila} fila${fila === 1 ? '' : 's'} y ${columna} columna${columna === 1 ? '' : 's'}`);
          cuadricula.append(celda);
        }
      }
      /* Emojis por categoría */
      const pestanas = qs('[data-emojis-pestanas]', this.paneles.emojis);
      const lista = qs('[data-emojis-lista]', this.paneles.emojis);
      const mostrar = (categoria) => {
        qsa('[role="tab"]', pestanas).forEach((pestana) => pestana.setAttribute('aria-selected', String(pestana.dataset.categoria === categoria)));
        lista.replaceChildren(...EMOJIS[categoria].map(([emoji, nombre]) => {
          const boton = document.createElement('button');
          boton.type = 'button';
          boton.className = 'editor-emojis__emoji';
          boton.textContent = emoji;
          boton.dataset.emoji = emoji;
          boton.setAttribute('aria-label', nombre);
          boton.title = nombre;
          return boton;
        }));
        lista.setAttribute('aria-label', `Emojis: ${categoria}`);
      };
      Object.keys(EMOJIS).forEach((categoria) => {
        const pestana = document.createElement('button');
        pestana.type = 'button';
        pestana.className = 'editor-emojis__pestana';
        pestana.setAttribute('role', 'tab');
        pestana.dataset.categoria = categoria;
        pestana.textContent = EMOJIS[categoria][0][0];
        pestana.setAttribute('aria-label', categoria);
        pestana.title = categoria;
        pestanas.append(pestana);
      });
      pestanas.addEventListener('click', (evento) => {
        const pestana = evento.target.closest('[data-categoria]');
        if (pestana) mostrar(pestana.dataset.categoria);
      });
      mostrar(Object.keys(EMOJIS)[0]);
    }

    abrirPanel(nombre, boton, ancla = boton) {
      const panel = this.paneles[nombre];
      if (!panel) return;
      if (this.panelAbierto?.nombre === nombre) {
        this.cerrarPanel(true);
        return;
      }
      this.cerrarPanel(false);
      this.guardarRango();
      this.prepararPanel(nombre);
      if (!panel.matches(':popover-open')) panel.showPopover();
      if (window.CISAHUAYO?.pickers?.place) window.CISAHUAYO.pickers.place(panel, ancla);
      boton?.setAttribute('aria-expanded', 'true');
      boton?.classList.add('is-abierto');
      this.panelAbierto = { nombre, boton, panel, ancla };
      const visibles = (selector) => qsa(selector, panel).filter((nodo) => nodo.offsetParent !== null);
      const primero = nombre === 'enlace'
        ? qs(qs('[data-enlace-texto]', panel).value ? '[data-enlace-url]' : '[data-enlace-texto]', panel)
        : visibles('[aria-checked="true"], [aria-pressed="true"]')[0] || visibles('button:not([disabled]), input')[0];
      primero?.focus({ preventScroll: true });
    }

    cerrarPanel(devolver) {
      const abierto = this.panelAbierto;
      if (!abierto) return;
      if (abierto.panel.matches(':popover-open')) abierto.panel.hidePopover();
      abierto.boton?.setAttribute('aria-expanded', 'false');
      abierto.boton?.classList.remove('is-abierto');
      this.panelAbierto = null;
      if (abierto.nombre === 'imagen') this.soltarImagen();
      if (devolver) this.restaurarRango();
    }

    prepararPanel(nombre) {
      const panel = this.paneles[nombre];
      if (nombre === 'tabla') {
        const enTabla = Boolean(this.cercano('td,th'));
        qs('[data-tabla-acciones]', panel).hidden = !enTabla;
        qs('[data-tabla-nueva]', panel).hidden = enTabla;
        qs('[data-tabla-medida]', panel).textContent = 'Elige filas y columnas';
        qsa('.editor-cuadricula__celda', panel).forEach((celda) => celda.classList.remove('is-marcada'));
      } else if (nombre === 'numerada' || nombre === 'vinetas') {
        const lista = this.cercano(nombre === 'numerada' ? 'ol' : 'ul');
        const actual = lista ? window.getComputedStyle(lista).listStyleType : '';
        qsa('[data-lista]', panel).forEach((opcion) => opcion.setAttribute('aria-checked', String(opcion.dataset.lista === actual)));
      } else if (nombre === 'color' || nombre === 'resaltado') {
        const elemento = this.elementoActual();
        const actual = nombre === 'color'
          ? (window.getComputedStyle(elemento).color === window.getComputedStyle(this.area).color ? '' : window.getComputedStyle(elemento).color)
          : this.resaltadoActual(elemento);
        qsa('[data-color]', panel).forEach((opcion) => {
          const esta = opcion.dataset.color ? rgb(opcion.dataset.color) === actual : !actual;
          opcion.setAttribute('aria-pressed', String(esta));
        });
      } else if (nombre === 'enlace') {
        const enlace = this.cercano('a');
        const rango = this.rangoActual();
        this.enlaceEditado = enlace;
        qs('[data-enlace-titulo]', panel).textContent = enlace ? 'Editar enlace' : 'Insertar enlace';
        qs('[data-enlace-texto]', panel).value = enlace ? enlace.textContent : (rango ? rango.toString() : '');
        qs('[data-enlace-url]', panel).value = enlace ? enlace.getAttribute('href') || '' : '';
        qs('[data-enlace-quitar]', panel).hidden = !enlace;
        qs('[data-enlace-error]', panel).hidden = true;
      }
    }

    /* --- enlaces ------------------------------------------------------------------------------------------------ */
    static direccion(valor) {
      let direccion = (valor || '').trim();
      if (!direccion) return null;
      if (/^www\./i.test(direccion) || /^[a-z0-9-]+(\.[a-z0-9-]+)+(\/.*)?$/i.test(direccion)) direccion = `https://${direccion}`;
      if (/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(direccion)) direccion = `mailto:${direccion}`;
      return /^(https?:\/\/[^\s]+|mailto:[^\s]+|tel:[+\d][\d\s-]*)$/i.test(direccion) ? direccion : null;
    }

    guardarEnlace() {
      const panel = this.paneles.enlace;
      const texto = qs('[data-enlace-texto]', panel).value.trim();
      const direccion = EditorEnriquecido.direccion(qs('[data-enlace-url]', panel).value);
      const error = qs('[data-enlace-error]', panel);
      if (!direccion) {
        error.textContent = 'Escribe una dirección válida (https://…, un correo o un teléfono).';
        error.hidden = false;
        qs('[data-enlace-url]', panel).focus();
        return;
      }
      const enlace = this.enlaceEditado;
      this.cerrarPanel(false);
      this.aplicar(() => {
        if (enlace && enlace.isConnected) {
          enlace.setAttribute('href', direccion);
          if (texto && texto !== enlace.textContent) enlace.textContent = texto;
          return;
        }
        /* Se crea el enlace directamente (insertHTML le copiaría estilos del texto de alrededor) */
        const visible = texto || direccion.replace(/^mailto:|^tel:/, '');
        const nuevo = document.createElement('a');
        nuevo.href = direccion;
        nuevo.textContent = visible;
        const rango = this.rangoActual();
        rango.deleteContents();
        const espacio = document.createTextNode('\u00a0');
        rango.insertNode(espacio);
        rango.insertNode(nuevo);
        rango.setStartAfter(espacio);
        rango.collapse(true);
        window.getSelection().removeAllRanges();
        window.getSelection().addRange(rango);
      });
    }

    quitarEnlace() {
      const enlace = this.enlaceEditado;
      this.cerrarPanel(false);
      if (!enlace || !enlace.isConnected) return;
      this.aplicar(() => {
        const rango = document.createRange();
        rango.selectNodeContents(enlace);
        const seleccion = window.getSelection();
        seleccion.removeAllRanges();
        seleccion.addRange(rango);
        this.ejecutar('unlink');
      });
    }

    /* --- tablas -------------------------------------------------------------------------------------------------- */
    /* El bloque de primer nivel (hijo directo del área) donde está el cursor */
    bloqueRaiz() {
      let nodo = this.elementoActual();
      while (nodo && nodo !== this.area && nodo.parentElement !== this.area) nodo = nodo.parentElement;
      return nodo && nodo !== this.area ? nodo : null;
    }

    insertarTabla(filas, columnas) {
      this.cerrarPanel(false);
      this.aplicar(() => {
        const tabla = document.createElement('table');
        const cuerpo = tabla.createTBody();
        for (let fila = 0; fila < filas; fila += 1) {
          const renglon = cuerpo.insertRow();
          for (let columna = 0; columna < columnas; columna += 1) renglon.insertCell().innerHTML = '<br>';
        }
        const despues = document.createElement('p');
        despues.innerHTML = '<br>';
        /* Como bloque propio: en lugar de un párrafo vacío, o después del bloque donde está el cursor */
        const bloque = this.bloqueRaiz();
        if (!bloque) this.area.append(tabla);
        else if (bloque.tagName === 'P' && !bloque.textContent.trim() && !bloque.querySelector('img')) bloque.replaceWith(tabla);
        else bloque.after(tabla);
        tabla.after(despues);
        const rango = document.createRange();
        rango.selectNodeContents(tabla.querySelector('td'));
        rango.collapse(true);
        window.getSelection().removeAllRanges();
        window.getSelection().addRange(rango);
      });
    }

    accionDeTabla(accion) {
      const celda = this.cercano('td,th');
      this.cerrarPanel(false);
      if (!celda) return;
      this.aplicar(() => {
        const fila = celda.parentElement;
        const tabla = celda.closest('table');
        const indice = [...fila.children].indexOf(celda);
        const filas = qsa('tr', tabla);
        const nuevaCelda = (etiqueta = 'td') => {
          const nueva = document.createElement(etiqueta);
          nueva.innerHTML = '<br>';
          return nueva;
        };
        const ponerCursor = (nodo) => {
          if (!nodo) return;
          const rango = document.createRange();
          rango.selectNodeContents(nodo);
          rango.collapse(true);
          window.getSelection().removeAllRanges();
          window.getSelection().addRange(rango);
        };
        if (accion === 'fila-arriba' || accion === 'fila-abajo') {
          const nueva = document.createElement('tr');
          [...fila.children].forEach((existente) => nueva.append(nuevaCelda(existente.tagName.toLowerCase() === 'th' ? 'th' : 'td')));
          fila[accion === 'fila-arriba' ? 'before' : 'after'](nueva);
          ponerCursor(nueva.children[Math.min(indice, nueva.children.length - 1)]);
        } else if (accion === 'columna-izquierda' || accion === 'columna-derecha') {
          filas.forEach((otra) => {
            const referencia = otra.children[Math.min(indice, otra.children.length - 1)];
            const nueva = nuevaCelda(referencia?.tagName.toLowerCase() === 'th' ? 'th' : 'td');
            if (!referencia) otra.append(nueva);
            else referencia[accion === 'columna-izquierda' ? 'before' : 'after'](nueva);
          });
          ponerCursor(fila.children[accion === 'columna-izquierda' ? indice : indice + 1]);
        } else if (accion === 'quitar-fila') {
          const siguiente = fila.nextElementSibling || fila.previousElementSibling;
          fila.remove();
          if (!qs('tr', tabla)) this.quitarTabla(tabla);
          else ponerCursor(siguiente?.children[Math.min(indice, siguiente.children.length - 1)]);
        } else if (accion === 'quitar-columna') {
          filas.forEach((otra) => otra.children[Math.min(indice, otra.children.length - 1)]?.remove());
          if (!qs('td,th', tabla)) this.quitarTabla(tabla);
          else ponerCursor(fila.children[Math.max(0, indice - 1)]);
        } else if (accion === 'quitar-tabla') {
          this.quitarTabla(tabla);
        }
      });
    }

    quitarTabla(tabla) {
      const despues = document.createElement('p');
      despues.innerHTML = '<br>';
      tabla.replaceWith(despues);
      const rango = document.createRange();
      rango.selectNodeContents(despues);
      rango.collapse(true);
      window.getSelection().removeAllRanges();
      window.getSelection().addRange(rango);
    }

    /* --- imágenes ------------------------------------------------------------------------------------------------ */
    avisar(texto, error = false) {
      this.estado.textContent = texto;
      this.estado.hidden = !texto;
      this.estado.classList.toggle('is-error', error);
    }

    elegirImagen() {
      this.guardarRango();
      this.archivo.value = '';
      this.archivo.click();
    }

    async subirImagenes(archivos) {
      const aceptadas = (this.raiz.dataset.acepta || '').split(',').map((e) => e.trim().replace('.', '').toLowerCase());
      const maximo = (Number(this.raiz.dataset.maximoMb) || 5) * 1024 * 1024;
      for (const archivo of [...archivos].slice(0, 5)) {
        const extension = archivo.name.includes('.') ? archivo.name.split('.').pop().toLowerCase() : '';
        if (!aceptadas.includes(extension) || !archivo.type.startsWith('image/')) {
          this.avisar(`«${archivo.name}»: solo se pueden insertar imágenes JPG, PNG o WEBP.`, true);
          continue;
        }
        if (archivo.size > maximo) {
          this.avisar(`«${archivo.name}» pesa más de ${this.raiz.dataset.maximoMb || 5} MB.`, true);
          continue;
        }
        this.subidas += 1;
        this.avisar(`Subiendo «${archivo.name}»…`);
        this.opciones.alCambiar?.(this);
        try {
          const datos = new FormData();
          datos.append('imagen', archivo, archivo.name);
          const csrf = document.querySelector('input[name="csrfmiddlewaretoken"]')?.value || '';
          const respuesta = await fetch(this.raiz.dataset.imagenesUrl, {
            method: 'POST', body: datos, credentials: 'same-origin', headers: { 'X-CSRFToken': csrf, Accept: 'application/json' },
          });
          const resultado = await respuesta.json().catch(() => ({}));
          if (!respuesta.ok) throw new Error(resultado.error || 'No se pudo subir la imagen.');
          const alternativo = archivo.name.replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ').trim();
          this.aplicar(() => this.ejecutar('insertHTML',
            `<img data-imagen="${Number(resultado.id)}" src="${escapar(resultado.url)}" alt="${escapar(alternativo)}">`));
          this.avisar('');
        } catch (problema) {
          this.avisar(problema.message || 'No se pudo subir la imagen. Revisa tu conexión e inténtalo de nuevo.', true);
        } finally {
          this.subidas -= 1;
          this.opciones.alCambiar?.(this);
        }
      }
    }

    elegirImagenDelArea(imagen) {
      this.soltarImagen();
      this.imagenElegida = imagen;
      imagen.setAttribute('data-elegida', '');
      const rango = document.createRange();
      rango.selectNode(imagen);
      window.getSelection().removeAllRanges();
      window.getSelection().addRange(rango);
      this.rango = rango.cloneRange();
      const panel = this.paneles.imagen;
      qs('[data-imagen-alt]', panel).value = imagen.getAttribute('alt') || '';
      const ancho = imagen.style.width || '';
      qsa('[data-imagen-ancho]', panel).forEach((chip) => chip.setAttribute('aria-pressed', String(chip.dataset.imagenAncho === ancho)));
      if (this.panelAbierto) this.cerrarPanel(false);
      panel.showPopover();
      if (window.CISAHUAYO?.pickers?.place) window.CISAHUAYO.pickers.place(panel, imagen);
      this.panelAbierto = { nombre: 'imagen', boton: null, panel };
    }

    soltarImagen() {
      this.imagenElegida?.removeAttribute('data-elegida');
      this.imagenElegida = null;
    }

    cambiarImagen(funcion) {
      const imagen = this.imagenElegida;
      if (!imagen || !imagen.isConnected) return;
      if (this.pendiente) this.guardarEstado();
      funcion(imagen);
      this.guardarEstado();
      this.cambio();
    }

    /* --- pegar ---------------------------------------------------------------------------------------------------- */
    static limpiarPegado(html) {
      const documento = new DOMParser().parseFromString(html, 'text/html');
      const permitidas = new Set(['P', 'BR', 'H1', 'H2', 'H3', 'STRONG', 'B', 'EM', 'I', 'U', 'S', 'STRIKE', 'DEL', 'SPAN', 'A', 'UL', 'OL', 'LI',
        'TABLE', 'THEAD', 'TBODY', 'TR', 'TH', 'TD', 'BLOCKQUOTE', 'SUB', 'SUP']);
      const estilos = ['color', 'background-color', 'font-weight', 'font-style', 'text-decoration-line', 'text-align'];
      const limpiar = (nodo) => {
        [...nodo.childNodes].forEach((hijo) => {
          if (hijo.nodeType === Node.COMMENT_NODE) {
            hijo.remove();
            return;
          }
          if (hijo.nodeType !== Node.ELEMENT_NODE) return;
          if (['SCRIPT', 'STYLE', 'IMG', 'IFRAME', 'OBJECT', 'SVG', 'META', 'LINK', 'TITLE'].includes(hijo.tagName)) {
            hijo.remove();
            return;
          }
          limpiar(hijo);
          if (hijo.tagName === 'DIV') {
            const parrafo = documento.createElement('p');
            parrafo.append(...hijo.childNodes);
            hijo.replaceWith(parrafo);
            return;
          }
          if (!permitidas.has(hijo.tagName)) {
            hijo.replaceWith(...hijo.childNodes);
            return;
          }
          const conservar = {};
          estilos.forEach((propiedad) => {
            const valor = hijo.style.getPropertyValue(propiedad);
            if (valor && !/var\(|url\(/i.test(valor)) conservar[propiedad] = valor;
          });
          const href = hijo.tagName === 'A' ? EditorEnriquecido.direccion(hijo.getAttribute('href')) : null;
          [...hijo.attributes].forEach((atributo) => hijo.removeAttribute(atributo.name));
          Object.entries(conservar).forEach(([propiedad, valor]) => hijo.style.setProperty(propiedad, valor));
          if (href) hijo.setAttribute('href', href);
        });
      };
      limpiar(documento.body);
      return documento.body.innerHTML;
    }

    /* ================================================================== caracteres especiales */
    /* La ventana «Carácter especial» (Σ): categorías, búsqueda por nombre o por el propio carácter y una cuadrícula que
       se recorre con las flechas. Sin el catálogo (static/js/caracteres-especiales.js) el botón no se muestra. */
    prepararCaracteres() {
      const dialogo = qs('[data-editor-caracteres]', this.raiz);
      const catalogo = window.CARACTERES_ESPECIALES;
      if (!dialogo || !Array.isArray(catalogo) || typeof dialogo.showModal !== 'function') {
        dialogo?.remove();
        const boton = qs('[data-comando="caracteres"]', this.barra);
        if (boton) boton.hidden = true;
        return null;
      }
      document.body.append(dialogo);   /* fuera del formulario del mensaje: Intro en la búsqueda no lo envía */
      const sinAcentos = (texto) => texto.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
      const categorias = catalogo.map(({ nombre, caracteres }) => ({
        nombre,
        caracteres: caracteres.map(([caracter, descripcion]) => ({ caracter, nombre: descripcion, clave: sinAcentos(descripcion) })),
      }));
      /* «Todo»: todas las categorías, cada carácter una sola vez */
      const vistos = new Set();
      const todo = categorias.flatMap(({ caracteres }) => caracteres).filter(({ caracter }) => !vistos.has(caracter) && vistos.add(caracter));
      categorias.unshift({ nombre: 'Todo', caracteres: todo });

      const c = {
        dialogo, categorias, actual: 0, sinAcentos,
        lista: qs('[data-caracteres-categorias]', dialogo),
        buscar: qs('[data-caracteres-buscar]', dialogo),
        cuadricula: qs('[data-caracteres-cuadricula]', dialogo),
        vacio: qs('[data-caracteres-vacio]', dialogo),
        aviso: qs('[data-caracteres-aviso]', dialogo),
      };
      c.pestanas = categorias.map((categoria, indice) => {
        const pestana = document.createElement('button');
        pestana.type = 'button';
        pestana.className = 'caracteres__categoria';
        pestana.id = `caracteres-categoria-${indice}`;
        pestana.setAttribute('role', 'tab');
        pestana.setAttribute('aria-controls', c.cuadricula.id);
        pestana.dataset.indice = String(indice);
        pestana.textContent = categoria.nombre;
        c.lista.append(pestana);
        return pestana;
      });

      c.lista.addEventListener('click', (evento) => {
        const pestana = evento.target.closest('[role="tab"]');
        if (pestana) this.elegirCategoria(Number(pestana.dataset.indice));
      });
      c.lista.addEventListener('keydown', (evento) => {
        const pasos = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 };
        const total = c.pestanas.length;
        let destino = null;
        if (evento.key in pasos) destino = (c.actual + pasos[evento.key] + total) % total;
        else if (evento.key === 'Home') destino = 0;
        else if (evento.key === 'End') destino = total - 1;
        if (destino === null) return;
        evento.preventDefault();
        this.elegirCategoria(destino, true);
      });
      c.buscar.addEventListener('input', () => this.filtrarCaracteres());
      c.buscar.addEventListener('keydown', (evento) => {
        if (evento.key !== 'ArrowDown' && evento.key !== 'Enter') return;
        evento.preventDefault();
        qs('[data-caracter][tabindex="0"]', c.cuadricula)?.focus();
      });
      c.cuadricula.addEventListener('click', (evento) => {
        const boton = evento.target.closest('[data-caracter]');
        if (boton) this.elegirCaracter(boton);
      });
      c.cuadricula.addEventListener('keydown', (evento) => this.moverEnCaracteres(evento));
      c.cuadricula.addEventListener('focusin', (evento) => {
        const boton = evento.target.closest('[data-caracter]');
        if (!boton) return;
        const anterior = qs('[data-caracter][tabindex="0"]', c.cuadricula);
        if (anterior && anterior !== boton) anterior.tabIndex = -1;
        boton.tabIndex = 0;
      });
      /* Al cerrar, el foco vuelve al mensaje con el cursor tras lo último insertado. Se hace en el momento del cierre
         (X, «Cerrar», Escape —que siempre cierra, también desde la búsqueda—) y no al llegar el evento «close», un
         instante después: lo que se escribiera en ese instante se perdería. El evento cubre el clic fuera de la ventana
         (app.js), y la X y «Cerrar» se atienden aquí antes que en app.js, que ya la encuentra cerrada. */
      const cerrar = () => {
        if (dialogo.open) dialogo.close();
        this.volverDeCaracteres();
      };
      dialogo.addEventListener('keydown', (evento) => {
        if (evento.key !== 'Escape') return;
        evento.preventDefault();
        cerrar();
      });
      dialogo.addEventListener('click', (evento) => {
        if (evento.target.closest('[data-modal-close]')) cerrar();
      });
      dialogo.addEventListener('close', () => this.volverDeCaracteres());
      return c;
    }

    /* Se usa el punto que guarda la ventana: al enfocar la búsqueda, el navegador saca la selección del área y al
       volver la pondría al principio */
    volverDeCaracteres() {
      this.area.focus({ preventScroll: true });
      const rango = this.caracteres.rango;
      if (rango?.startContainer.isConnected && this.dentro(rango.startContainer)) {
        const seleccion = window.getSelection();
        seleccion.removeAllRanges();
        seleccion.addRange(rango);
        this.rango = rango.cloneRange();
      }
      this.actualizarBarra();
    }

    abrirCaracteres() {
      const c = this.caracteres;
      if (!c || c.dialogo.open) return;
      this.cerrarPanel(false);
      this.guardarRango();
      if (!this.rango || !this.rango.startContainer.isConnected || !this.dentro(this.rango.commonAncestorContainer)) this.ponerCursorAlFinal();
      if (this.pendiente) this.guardarEstado();
      c.rango = this.rango.cloneRange();   /* dónde se insertará (o lo que se reemplazará) */
      c.buscar.value = '';
      c.lista.setAttribute('aria-orientation', window.matchMedia('(max-width: 40rem)').matches ? 'horizontal' : 'vertical');
      this.elegirCategoria(c.actual);
      c.aviso.textContent = '';
      c.dialogo.showModal();
      document.documentElement.classList.add('is-scroll-locked');   /* como las ventanas de app.js */
      c.buscar.focus();
    }

    elegirCategoria(indice, enfocar = false) {
      const c = this.caracteres;
      c.actual = indice;
      c.pestanas.forEach((pestana, i) => {
        pestana.setAttribute('aria-selected', String(i === indice));
        pestana.tabIndex = i === indice ? 0 : -1;
      });
      c.cuadricula.setAttribute('aria-labelledby', c.pestanas[indice].id);
      if (enfocar) c.pestanas[indice].focus();
      c.pestanas[indice].scrollIntoView({ block: 'nearest', inline: 'nearest' });
      this.filtrarCaracteres();
    }

    /* Los de la categoría elegida que coinciden con la búsqueda: un solo símbolo (€, é, ñ…) busca ese carácter; si no,
       cada palabra debe estar en el nombre (sin importar acentos ni mayúsculas) */
    filtrarCaracteres() {
      const c = this.caracteres;
      const consulta = c.buscar.value.trim();
      let entradas = c.categorias[c.actual].caracteres;
      if (consulta) {
        const caracter = [...consulta].length === 1 && !/^[a-z0-9]$/i.test(consulta);
        const palabras = c.sinAcentos(consulta).split(/\s+/);
        entradas = entradas.filter((entrada) => (caracter
          ? entrada.caracter === consulta || entrada.caracter.toLowerCase() === consulta.toLowerCase()
          : entrada.caracter === consulta || palabras.every((palabra) => entrada.clave.includes(palabra))));
        /* Primero los que tienen palabras que empiezan así («raya» antes que «semirraya»), cada grupo en su orden */
        const alInicio = (entrada) => palabras.every((palabra) => entrada.clave.split(/[^a-z0-9ñ]+/).some((parte) => parte.startsWith(palabra)));
        entradas = [...entradas.filter(alInicio), ...entradas.filter((entrada) => !alInicio(entrada))];
      }
      c.cuadricula.replaceChildren(...entradas.map((entrada, indice) => {
        const boton = document.createElement('button');
        boton.type = 'button';
        boton.className = 'caracteres__caracter';
        boton.textContent = entrada.caracter;
        boton.dataset.caracter = entrada.caracter;
        boton.dataset.tooltip = entrada.nombre;
        boton.setAttribute('aria-label', entrada.nombre);
        boton.tabIndex = indice === 0 ? 0 : -1;
        return boton;
      }));
      c.cuadricula.hidden = !entradas.length;
      c.vacio.hidden = Boolean(entradas.length);
      c.cuadricula.scrollTop = 0;
    }

    moverEnCaracteres(evento) {
      const c = this.caracteres;
      const botones = qsa('[data-caracter]', c.cuadricula);
      const actual = botones.indexOf(document.activeElement);
      if (actual < 0) return;
      const primeraFila = botones.findIndex((boton) => boton.offsetTop !== botones[0].offsetTop);
      const columnas = primeraFila < 0 ? botones.length : primeraFila;
      const pasos = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: columnas, ArrowUp: -columnas, PageDown: columnas * 5, PageUp: -columnas * 5 };
      let destino;
      if (evento.key === 'ArrowUp' && actual < columnas) {
        evento.preventDefault();
        c.buscar.focus();   /* de la primera fila, a la búsqueda */
        return;
      }
      if (evento.key in pasos) destino = actual + pasos[evento.key];
      else if (evento.key === 'Home') destino = evento.ctrlKey ? 0 : actual - (actual % columnas);
      else if (evento.key === 'End') destino = evento.ctrlKey ? botones.length - 1 : actual - (actual % columnas) + columnas - 1;
      else return;
      evento.preventDefault();
      botones[Math.min(botones.length - 1, Math.max(0, destino))].focus();
    }

    elegirCaracter(boton) {
      const c = this.caracteres;
      this.rango = c.rango;
      this.insertarTexto(boton.dataset.caracter);
      c.rango = this.rango.cloneRange();   /* el siguiente va después de este */
      /* Para lectores de pantalla (el estado del editor queda fuera de la ventana, inerte) */
      c.aviso.textContent = '';
      window.requestAnimationFrame(() => { c.aviso.textContent = `Insertado: ${boton.getAttribute('aria-label')}`; });
      boton.classList.remove('is-insertado');
      void boton.offsetWidth;   /* reinicia la animación si se elige el mismo dos veces */
      boton.classList.add('is-insertado');
    }

    /* Inserta texto donde estaba el cursor (en lugar de lo seleccionado, si había algo) como un paso del historial y
       deja el cursor después, para que lo siguiente quede en orden. Trabaja sobre el documento y no con los comandos del
       navegador: mientras la ventana modal está abierta el área está inerte y esos comandos no hacen nada. El texto se
       pone en el nodo de texto donde estaba el cursor, así conserva su formato (negrita, color…). */
    insertarTexto(texto) {
      if (this.pendiente) this.guardarEstado();
      if (!this.rango || !this.rango.startContainer.isConnected || !this.dentro(this.rango.commonAncestorContainer)) this.ponerCursorAlFinal();
      const rango = this.rango.cloneRange();
      if (!rango.collapsed) this.borrarSeleccion(rango);
      let contenedor = rango.startContainer;
      let posicion = rango.startOffset;
      if (contenedor === this.area) {   /* entre bloques (o todo se borró): a un párrafo nuevo */
        const parrafo = document.createElement('p');
        this.area.insertBefore(parrafo, this.area.childNodes[posicion] || null);
        contenedor = parrafo;
        posicion = 0;
      }
      let nodo;
      if (contenedor.nodeType === Node.TEXT_NODE) {
        contenedor.insertData(posicion, texto);
        nodo = contenedor;
        posicion += texto.length;
      } else {
        let siguiente = contenedor.childNodes[posicion] || null;
        /* Tras el salto de línea final (que no se ve) el cursor está, a la vista, antes de él */
        if (!siguiente && contenedor.lastChild?.nodeName === 'BR') siguiente = contenedor.lastChild;
        const previo = siguiente ? siguiente.previousSibling : contenedor.lastChild;
        if (previo?.nodeType === Node.TEXT_NODE) {
          posicion = previo.length + texto.length;
          previo.appendData(texto);
          nodo = previo;
        } else {
          nodo = document.createTextNode(texto);
          contenedor.insertBefore(nodo, siguiente);
          posicion = texto.length;
        }
        /* El salto que solo sostenía la línea vacía sobra ahora que tiene texto */
        if (siguiente?.nodeName === 'BR' && !siguiente.nextSibling && siguiente.previousSibling === nodo) siguiente.remove();
      }
      window.getSelection().setBaseAndExtent(nodo, posicion, nodo, posicion);
      this.rango = document.createRange();
      this.rango.setStart(nodo, posicion);
      this.normalizar();
      this.guardarRango();
      this.guardarEstado();
      this.cambio();
    }

    /* Quita lo seleccionado; si abarcaba dos bloques (fin de un párrafo y principio de otro), los une como al teclear */
    borrarSeleccion(rango) {
      const bloque = (nodo) => {
        const elemento = (nodo.nodeType === Node.ELEMENT_NODE ? nodo : nodo.parentElement)?.closest('p,h1,h2,h3,li,blockquote,div');
        return elemento && elemento !== this.area && this.dentro(elemento) ? elemento : null;
      };
      const inicio = bloque(rango.startContainer);
      const fin = bloque(rango.endContainer);
      rango.deleteContents();
      if (inicio && fin && inicio !== fin && inicio.isConnected && fin.isConnected && !inicio.contains(fin) && !fin.contains(inicio)) {
        inicio.append(...fin.childNodes);
        fin.remove();
      }
    }

    /* ================================================================== eventos */
    escuchar() {
      const area = this.area;

      document.addEventListener('selectionchange', () => {
        const seleccion = window.getSelection();
        if (seleccion.rangeCount && this.dentro(seleccion.getRangeAt(0).commonAncestorContainer)) {
          this.guardarRango();
          this.actualizarBarra();
        }
      });

      area.addEventListener('input', (evento) => {
        this.guardarRango();
        this.normalizar(!evento.isComposing);
        this.guardarLuego();
        this.actualizarHistorial();
        this.cambio();
        this.actualizarBarra();
      });

      area.addEventListener('beforeinput', (evento) => {
        if (evento.inputType === 'historyUndo') {
          evento.preventDefault();
          this.deshacer();
        } else if (evento.inputType === 'historyRedo') {
          evento.preventDefault();
          this.rehacer();
        }
      });

      area.addEventListener('keydown', (evento) => this.teclado(evento));

      area.addEventListener('click', (evento) => {
        const imagen = evento.target.closest('img');
        if (imagen && this.dentro(imagen)) this.elegirImagenDelArea(imagen);
        else if (this.panelAbierto?.nombre === 'imagen') this.cerrarPanel(false);
      });

      area.addEventListener('paste', (evento) => {
        const datos = evento.clipboardData;
        if (!datos) return;
        const imagenes = [...datos.files].filter((archivo) => archivo.type.startsWith('image/'));
        evento.preventDefault();
        if (imagenes.length) {
          this.guardarRango();
          this.subirImagenes(imagenes);
          return;
        }
        const html = datos.getData('text/html');
        if (html) {
          const limpio = EditorEnriquecido.limpiarPegado(html);
          this.aplicar(() => this.ejecutar('insertHTML', limpio));
          if (/<img/i.test(html)) this.avisar('Las imágenes copiadas de otra página no se pegan: usa «Insertar imagen».');
          return;
        }
        const texto = datos.getData('text/plain');
        if (texto) this.aplicar(() => this.ejecutar('insertText', texto));
      });

      area.addEventListener('drop', (evento) => {
        const imagenes = [...(evento.dataTransfer?.files || [])].filter((archivo) => archivo.type.startsWith('image/'));
        if (!imagenes.length) return;
        evento.preventDefault();
        const rango = document.caretRangeFromPoint?.(evento.clientX, evento.clientY);
        if (rango && this.dentro(rango.startContainer)) this.rango = rango;
        this.subirImagenes(imagenes);
      });

      this.archivo.addEventListener('change', () => {
        if (this.archivo.files.length) this.subirImagenes(this.archivo.files);
      });

      /* La barra y los botones de abajo (formato, emojis, adjuntar): no le quitan el foco al área (la selección no se
         pierde). Adjuntar lo maneja static/js/mensajes.js */
      const alPulsar = (evento) => {
        const boton = evento.target.closest('button');
        if (!boton || boton.disabled) return;
        if (boton === this.botonFormato) {
          this.ponerFormato(this.barra.hidden);
          return;
        }
        if (boton === this.botonMas) {
          const abrir = this.filaExtra.hidden;
          this.ponerMas(abrir);
          guardarAlmacen(LLAVE_MAS, abrir ? '1' : '0');
          return;
        }
        if (boton.dataset.panel && !boton.dataset.comando) {
          this.abrirPanel(boton.dataset.panel, boton);
          return;
        }
        if (boton.dataset.comando) this.comando(boton.dataset.comando);
      };
      [this.barra, this.acciones].filter(Boolean).forEach((zona) => {
        zona.addEventListener('mousedown', (evento) => {
          if (evento.target.closest('button')) evento.preventDefault();
        });
        zona.addEventListener('click', alPulsar);
      });
      this.selects.fuente.addEventListener('change', () => this.ponerFuente(this.selects.fuente.value));
      this.selects.tamano.addEventListener('change', () => this.ponerTamano(this.selects.tamano.value));
      this.selects.parrafo.addEventListener('change', () => this.ponerParrafo(this.selects.parrafo.value));
      Object.values(this.selects).forEach((select) => select.addEventListener('mousedown', () => this.guardarRango()));

      /* Paneles */
      Object.values(this.paneles).forEach((panel) => {
        panel.addEventListener('mousedown', (evento) => {
          if (evento.target.closest('button')) evento.preventDefault();
        });
        panel.addEventListener('keydown', (evento) => {
          if (evento.key === 'Escape') {
            evento.preventDefault();
            /* Vuelve a su botón; si no está a la vista (Ctrl+K con la barra oculta), al texto */
            const boton = this.panelAbierto?.boton?.offsetParent ? this.panelAbierto.boton : null;
            this.cerrarPanel(!boton);
            boton?.focus();
          }
        });
      });
      const tabla = this.paneles.tabla;
      tabla.addEventListener('mouseover', (evento) => this.marcarCuadricula(evento.target.closest('.editor-cuadricula__celda')));
      tabla.addEventListener('focusin', (evento) => this.marcarCuadricula(evento.target.closest('.editor-cuadricula__celda')));
      tabla.addEventListener('click', (evento) => {
        const celda = evento.target.closest('.editor-cuadricula__celda');
        if (celda) this.insertarTabla(Number(celda.dataset.filas), Number(celda.dataset.columnas));
        const accion = evento.target.closest('[data-tabla]');
        if (accion) this.accionDeTabla(accion.dataset.tabla);
      });
      qs('[data-tabla-cuadricula]', tabla).addEventListener('keydown', (evento) => this.moverEnCuadricula(evento));
      ['numerada', 'vinetas'].forEach((nombre) => this.paneles[nombre].addEventListener('click', (evento) => {
        const opcion = evento.target.closest('[data-lista]');
        if (!opcion) return;
        this.cerrarPanel(false);
        this.ponerTipoDeLista(opcion.dataset.lista);
      }));
      ['color', 'resaltado'].forEach((nombre) => this.paneles[nombre].addEventListener('click', (evento) => {
        const opcion = evento.target.closest('[data-color]');
        if (!opcion) return;
        this.cerrarPanel(false);
        this.ponerColor(nombre, opcion.dataset.color);
      }));
      this.paneles.emojis.addEventListener('click', (evento) => {
        const opcion = evento.target.closest('[data-emoji]');
        if (!opcion) return;
        this.cerrarPanel(false);
        this.aplicar(() => this.ejecutar('insertText', opcion.dataset.emoji));
      });
      const enlace = this.paneles.enlace;
      qs('[data-enlace-guardar]', enlace).addEventListener('click', () => this.guardarEnlace());
      enlace.addEventListener('keydown', (evento) => {
        if (evento.key === 'Enter' && evento.target.matches('input')) {
          evento.preventDefault();   /* no envía el mensaje: guarda el enlace */
          this.guardarEnlace();
        }
      });
      qs('[data-enlace-cancelar]', enlace).addEventListener('click', () => this.cerrarPanel(true));
      qs('[data-enlace-quitar]', enlace).addEventListener('click', () => this.quitarEnlace());
      const imagen = this.paneles.imagen;
      imagen.addEventListener('click', (evento) => {
        const chip = evento.target.closest('[data-imagen-ancho]');
        if (chip) {
          this.cambiarImagen((elegida) => { elegida.style.width = chip.dataset.imagenAncho === '100%' ? '' : chip.dataset.imagenAncho; });
          qsa('[data-imagen-ancho]', imagen).forEach((otro) => otro.setAttribute('aria-pressed', String(otro === chip)));
        }
        if (evento.target.closest('[data-imagen-quitar]')) {
          this.cambiarImagen((elegida) => elegida.remove());
          this.cerrarPanel(true);
        }
        if (evento.target.closest('[data-imagen-listo]')) this.cerrarPanel(true);
      });
      qs('[data-imagen-alt]', imagen).addEventListener('input', (evento) => {
        this.cambiarImagen((elegida) => elegida.setAttribute('alt', evento.target.value));
      });

      /* Cerrar paneles al tocar fuera */
      document.addEventListener('pointerdown', (evento) => {
        const abierto = this.panelAbierto;
        if (!abierto || abierto.panel.contains(evento.target) || abierto.boton?.contains(evento.target)) return;
        if (abierto.nombre === 'imagen' && evento.target === this.imagenElegida) return;
        this.cerrarPanel(false);
      });
      window.addEventListener('resize', () => {
        this.reacomodar();
        const abierto = this.panelAbierto;
        if (abierto && window.CISAHUAYO?.pickers?.place) window.CISAHUAYO.pickers.place(abierto.panel, abierto.ancla || abierto.boton || this.imagenElegida);
      });
      if ('ResizeObserver' in window) {
        let ancho = 0;
        new ResizeObserver(([entrada]) => {
          if (Math.round(entrada.contentRect.width) === ancho) return;   /* solo al cambiar el ancho */
          ancho = Math.round(entrada.contentRect.width);
          this.reacomodar();
        }).observe(this.barra);
      }
    }

    marcarCuadricula(celda) {
      if (!celda) return;
      const filas = Number(celda.dataset.filas);
      const columnas = Number(celda.dataset.columnas);
      qsa('.editor-cuadricula__celda', this.paneles.tabla).forEach((otra) => {
        otra.classList.toggle('is-marcada', Number(otra.dataset.filas) <= filas && Number(otra.dataset.columnas) <= columnas);
      });
      qs('[data-tabla-medida]', this.paneles.tabla).textContent = `${filas} × ${columnas}`;
    }

    moverEnCuadricula(evento) {
      const pasos = { ArrowRight: [0, 1], ArrowLeft: [0, -1], ArrowDown: [1, 0], ArrowUp: [-1, 0] };
      const paso = pasos[evento.key];
      const actual = evento.target.closest('.editor-cuadricula__celda');
      if (!paso || !actual) return;
      evento.preventDefault();
      const fila = Math.min(6, Math.max(1, Number(actual.dataset.filas) + paso[0]));
      const columna = Math.min(8, Math.max(1, Number(actual.dataset.columnas) + paso[1]));
      qs(`.editor-cuadricula__celda[data-filas="${fila}"][data-columnas="${columna}"]`, this.paneles.tabla)?.focus();
    }

    teclado(evento) {
      const mod = evento.ctrlKey || evento.metaKey;
      const tecla = evento.key.toLowerCase();
      /* En el teclado latinoamericano «\» se escribe con AltGr, que Windows informa como Ctrl+Alt */
      if (mod && (!evento.altKey || tecla === '\\')) {
        let atajo = null;
        if (tecla === 'z' && !evento.shiftKey) atajo = () => this.deshacer();
        else if (tecla === 'y' || (tecla === 'z' && evento.shiftKey)) atajo = () => this.rehacer();
        else if (tecla === 'b') atajo = () => this.comando('negrita');
        else if (tecla === 'i') atajo = () => this.comando('cursiva');
        else if (tecla === 'u') atajo = () => this.comando('subrayado');
        else if (tecla === 'x' && evento.shiftKey) atajo = () => this.comando('tachado');
        else if (tecla === 'k') atajo = () => this.comando('enlace');
        else if (tecla === 'f' && evento.shiftKey) atajo = () => this.ponerFormato(this.barra.hidden);
        else if (tecla === '\\') atajo = () => this.comando('limpiar');
        else if (evento.shiftKey && evento.code === 'Digit7') atajo = () => this.comando('numerada');
        else if (evento.shiftKey && evento.code === 'Digit8') atajo = () => this.comando('vinetas');
        else if (tecla === 'enter') atajo = () => this.opciones.alEnviar?.();
        if (atajo) {
          evento.preventDefault();
          evento.stopPropagation();   /* dentro del editor, Ctrl+K es «enlace» y no el buscador de comandos */
          atajo();
          return;
        }
      }
      if (evento.key === 'Tab' && this.cercano('li')) {
        evento.preventDefault();
        this.comando(evento.shiftKey ? 'menos-sangria' : 'mas-sangria');
        return;
      }
      if ((evento.key === 'Delete' || evento.key === 'Backspace') && this.imagenElegida) {
        evento.preventDefault();
        this.cambiarImagen((elegida) => elegida.remove());
        this.cerrarPanel(true);
        return;
      }
      if (evento.key === 'Backspace' && !evento.isComposing) {
        /* El carácter invisible de enCursor no cuenta: se quita y el retroceso borra lo que se ve antes */
        const rango = this.rangoActual();
        const texto = rango?.collapsed ? rango.startContainer : null;
        if (texto?.nodeType === Node.TEXT_NODE && texto.data[rango.startOffset - 1] === INVISIBLE) texto.deleteData(rango.startOffset - 1, 1);
      }
      if (evento.key === 'Enter' && !evento.shiftKey && !mod && !evento.isComposing && !this.cercano('li,td,th')) {
        evento.preventDefault();
        this.opciones.alEnviar?.();
      }
    }
  }

  window.EditorEnriquecido = EditorEnriquecido;
})();
