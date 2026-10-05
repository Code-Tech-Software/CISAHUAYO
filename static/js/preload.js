/* Se ejecuta en <head>, antes del primer pintado: restaura el tema y el estado
   del sidebar para que la página no parpadee al cargar. Las claves deben
   coincidir con las de app.js. */
(function () {
  var root = document.documentElement;
  try {
    if (localStorage.getItem('cisahuayo.theme') === 'dark') {
      root.setAttribute('data-theme', 'dark');
    }
    if (localStorage.getItem('cisahuayo.sidebar') === 'collapsed') {
      root.classList.add('is-sidebar-collapsed');
    }
  } catch (error) {
    /* Almacenamiento no disponible (modo privado, etc.): se usan los valores por defecto. */
  }
})();
