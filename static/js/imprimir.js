/* Botones [data-imprimir]: abren el diálogo de impresión del navegador (ahí mismo se puede guardar en PDF). */
document.querySelectorAll('[data-imprimir]').forEach((boton) => {
  boton.addEventListener('click', () => window.print());
});

/* Con [data-imprimir-al-abrir] en <body> (el botón «PDF» de los reportes), el diálogo se abre solo al cargar. */
if (document.body.hasAttribute('data-imprimir-al-abrir')) {
  window.addEventListener('load', () => window.print());
}
