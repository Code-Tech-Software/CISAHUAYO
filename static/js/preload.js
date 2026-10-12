/* Se ejecuta en <head>, antes del primer pintado: restaura el modo (claro, oscuro
   o el del dispositivo) y el estado del sidebar para que la página no parpadee al
   cargar. Las claves deben coincidir con las de app.js. El tema de color no va
   aquí: lo pone el servidor en <html data-tema>. */
(function () {
  var root = document.documentElement;
  try {
    var modo = localStorage.getItem('cisahuayo.theme');
    var oscuroDelDispositivo = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (modo === 'dark' || (modo === 'auto' && oscuroDelDispositivo)) {
      root.setAttribute('data-theme', 'dark');
    }
    if (localStorage.getItem('cisahuayo.sidebar') === 'collapsed') {
      root.classList.add('is-sidebar-collapsed');
    }
  } catch (error) {
    /* Almacenamiento no disponible (modo privado, etc.): se usan los valores por defecto. */
  }
})();
