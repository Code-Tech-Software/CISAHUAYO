"""Inicio de sesión del sistema y de los portales.

Antes se usaba el del admin de Django, que solo deja entrar a personal «staff» y manda siempre a su propio panel. Las
cuentas del sistema (módulo Usuarios) no son de staff: su acceso lo define el rol. Aquí la pantalla es la misma de
siempre (misma ruta, /admin/login/, que los demás módulos usan como `LOGIN_URL`), pero entra cualquier cuenta activa y
se llega a la página que se pidió o, si no hubo ninguna, al inicio del sistema.

Desde el 2026-10-14 la pantalla deja elegir entre tres accesos (la pestaña viaja en ?acceso=… y en el campo `acceso`):
- Sistema: personal y docentes, con el usuario y la contraseña de su cuenta (django.contrib.auth), como siempre.
- Estudiantes: con su correo electrónico y su contraseña.
- Tutores: con su usuario y su contraseña.
Los dos últimos son las cuentas de los portales (CISAHUAYO/portales.py): cada quien llega al inicio de su portal.
"""
from django import forms
from django.conf import settings
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect
from django.urls import reverse

from . import portales

SISTEMA, ESTUDIANTES, TUTORES = 'sistema', 'estudiantes', 'tutores'


class _AccesoAlPortalForm(forms.Form):
    """Credenciales de un portal: las valida CISAHUAYO.portales.autenticar (con sus mensajes claros)."""
    tipo = campo = None
    contrasena = forms.CharField(label='Contraseña', strip=False, widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cuenta = None

    def clean(self):
        datos = super().clean()
        if datos.get(self.campo) and datos.get('contrasena'):
            try:
                self.cuenta = portales.autenticar(self.tipo, datos[self.campo], datos['contrasena'])
            except portales.AccesoRechazado as rechazo:
                raise forms.ValidationError(rechazo.mensaje, code='acceso_rechazado') from None
        return datos


class AccesoEstudianteForm(_AccesoAlPortalForm):
    tipo, campo = portales.ESTUDIANTE, 'correo'
    correo = forms.EmailField(label='Correo electrónico', max_length=254,
                              error_messages={'invalid': 'Escribe un correo electrónico válido, como nombre@dominio.com.'})
    field_order = ['correo', 'contrasena']


class AccesoTutorForm(_AccesoAlPortalForm):
    tipo, campo = portales.TUTOR, 'usuario'
    usuario = forms.CharField(label='Usuario', max_length=40)
    field_order = ['usuario', 'contrasena']


# Pestaña -> (formulario, tipo de cuenta del portal)
PORTALES = {ESTUDIANTES: (AccesoEstudianteForm, portales.ESTUDIANTE), TUTORES: (AccesoTutorForm, portales.TUTOR)}
PESTANAS = (SISTEMA, ESTUDIANTES, TUTORES)


class VistaDeAcceso(LoginView):
    template_name = 'registration/login.html'

    def pestana_pedida(self):
        """La pestaña que se pidió (?acceso=… o el campo del formulario), o '' si no se pidió ninguna válida."""
        valor = (self.request.POST if self.request.method == 'POST' else self.request.GET).get('acceso', '')
        return valor if valor in PESTANAS else ''

    def dispatch(self, request, *args, **kwargs):
        if request.method == 'GET':
            pedida = self.pestana_pedida()
            # Quien ya tiene sesión del sistema y abre esta pantalla pasa directo, salvo que pida el panel de Django sin
            # ser de staff (el admin lo manda aquí: si lo dejáramos pasar, daría vueltas sin fin) o que elija un portal
            # (por ejemplo, en una computadora compartida: al entrar al portal se cierra la sesión del sistema).
            if request.user.is_authenticated and pedida not in PORTALES:
                destino = self.get_redirect_url()
                if not destino:
                    return redirect(settings.LOGIN_REDIRECT_URL)
                if destino != request.path and not (destino.startswith('/admin/') and not request.user.is_staff):
                    return redirect(destino)
            # Con la sesión de un portal abierta y sin pedir nada en particular, se vuelve a ese portal
            tipo, cuenta = portales.sesion(request)
            if cuenta is not None and not pedida and not self.get_redirect_url():
                return redirect(portales.INICIO[tipo])
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        pestana = self.pestana_pedida()
        if pestana not in PORTALES:   # el del sistema (también si no dice cuál: así funcionan los formularios de antes)
            return super().post(request, *args, **kwargs)
        clase, tipo = PORTALES[pestana]
        formulario = clase(request.POST, prefix=pestana)
        if formulario.is_valid():
            portales.iniciar_sesion(request, tipo, formulario.cuenta)
            return redirect(self.destino_en_el_portal(tipo))
        # El formulario del sistema va sin datos: solo se marca el que se envió
        return self.render_to_response(self.get_context_data(form=self.get_form_class()(request=request), **{f'form_{pestana}': formulario}))

    def form_valid(self, form):
        # Entrar al sistema cierra la sesión de un portal que hubiera en este navegador
        self.request.session.pop(portales.CLAVE_DE_SESION, None)
        return super().form_valid(form)

    def destino_en_el_portal(self, tipo):
        """La página del portal que se pidió antes de entrar (si era de ese portal) o su inicio."""
        inicio = reverse(portales.INICIO[tipo])
        pedida = self.get_redirect_url()
        return pedida if pedida.startswith(inicio) else inicio

    def pestana_activa(self):
        pedida = self.pestana_pedida()
        if pedida:
            return pedida
        siguiente = self.get_redirect_url()
        for pestana, (_, tipo) in PORTALES.items():
            if siguiente.startswith(reverse(portales.INICIO[tipo])):
                return pestana
        return SISTEMA

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        for pestana, (clase, _) in PORTALES.items():
            contexto.setdefault(f'form_{pestana}', clase(prefix=pestana))
        tipo, cuenta = portales.sesion(self.request)
        contexto.update({
            'acceso': self.pestana_activa(),
            'acceso_elegido': bool(self.pestana_pedida() or self.get_redirect_url()),
            # Aviso de la sesión de un portal que sigue abierta en este navegador
            'sesion_portal': {'nombre': portales.NOMBRE[tipo], 'cuenta': cuenta, 'url': reverse(portales.INICIO[tipo])} if cuenta else None,
        })
        return contexto


acceso = VistaDeAcceso.as_view()
salir = LogoutView.as_view()
