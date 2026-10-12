/* Botones [data-imprimir]: abren el diálogo de impresión del navegador (ahí mismo se puede guardar en PDF). */
document.querySelectorAll('[data-imprimir]').forEach((boton) => {
  boton.addEventListener('click', () => window.print());
});
