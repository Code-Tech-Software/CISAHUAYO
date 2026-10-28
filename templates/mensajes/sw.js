{% load static %}/* CISAHUAYO · service worker de las notificaciones push de la mensajería (Mensajes/push.py; se sirve en /sw.js)

   - Muestra el aviso de un mensaje nuevo aunque la página esté cerrada: quién escribió y una vista previa. Si el sistema
     está a la vista en este equipo, no lo muestra: la página ya lo avisa (la campana, la conversación y su propio aviso).
   - Al tocar el aviso, abre la conversación (o la pestaña del sistema que ya esté abierta).
   No guarda páginas ni datos: solo atiende los avisos.
*/
'use strict';

const ICONO = '{% static "img/logointer.svg" %}';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (evento) => evento.waitUntil(self.clients.claim()));

self.addEventListener('push', (evento) => {
  let datos = {};
  try {
    datos = evento.data ? evento.data.json() : {};
  } catch (error) {
    datos = {};
  }
  evento.waitUntil((async () => {
    const ventanas = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    if (ventanas.some((ventana) => ventana.visibilityState === 'visible')) return;
    await self.registration.showNotification(datos.titulo || 'CISAHUAYO', {
      body: datos.texto || 'Tienes un mensaje nuevo.',
      tag: datos.etiqueta || 'mensajes',
      renotify: Boolean(datos.etiqueta),
      icon: ICONO,
      badge: ICONO,
      lang: 'es',
      data: { url: datos.url || '/' },
    });
  })());
});

self.addEventListener('notificationclick', (evento) => {
  evento.notification.close();
  const destino = new URL(evento.notification.data?.url || '/', self.location.origin).href;
  evento.waitUntil((async () => {
    const ventanas = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    const misma = ventanas.find((ventana) => ventana.url === destino);
    if (misma) return misma.focus();
    const otra = ventanas.find((ventana) => 'navigate' in ventana);
    if (otra) {
      try {
        await otra.focus();
        return await otra.navigate(destino);
      } catch (error) {
        /* una pestaña que este service worker no controla: se abre una nueva */
      }
    }
    return self.clients.openWindow(destino);
  })());
});
