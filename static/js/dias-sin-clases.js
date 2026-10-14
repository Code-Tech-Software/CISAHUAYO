/* CISAHUAYO · días sin clases (tarjeta de Ciclos escolares)

   «Todos los niveles» marca o desmarca los cuatro niveles, y marcar los cuatro sueltos marca «Todos»
   ([data-niveles-sin-clases]). El servidor trata «Todos» igual aunque no haya JavaScript.
*/
(() => {
  'use strict';

  document.querySelectorAll('[data-niveles-sin-clases]').forEach((grupo) => {
    const todos = grupo.querySelector('input[value="TODOS"]');
    const niveles = [...grupo.querySelectorAll('input[type="checkbox"]')].filter((casilla) => casilla !== todos);
    if (!todos) return;
    grupo.addEventListener('change', (evento) => {
      if (evento.target === todos) {
        niveles.forEach((casilla) => { casilla.checked = todos.checked; });
      } else {
        todos.checked = niveles.every((casilla) => casilla.checked);
      }
    });
  });
})();
