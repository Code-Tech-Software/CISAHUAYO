from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, POR_PAGINA_DEFECTO, paginar
from CISAHUAYO.permisos import requiere_permisos

from . import catalogo, contrasenas
from .forms import CambioContrasenaForm, FiltroUsuariosForm, MiCuentaForm, UsuarioForm, validar_contrasena_inicial
from .docentes import profesor_de
from .models import PerfilUsuario
from .seguridad import (
    ACCION_ALTA,
    ACCION_BAJA,
    ACCION_CAMBIO,
    contrasena_temporal,
    es_ultimo_administrador,
    historial,
    nombre_de,
    permisos_de_cuenta,
    permisos_efectivos,
    puede_gestionar,
    registrar,
    rol_de,
)
from .signals import SESION_CAMBIO_DE_CONTRASENA

Usuario = get_user_model()
SESION_CREDENCIALES = 'credenciales_usuario'


def _consulta():
    """Usuarios con su perfil, su ficha de profesor y su rol ya cargados (sin una consulta por fila)."""
    return Usuario.objects.select_related('perfil', 'profesor').prefetch_related(
        Prefetch('groups', queryset=Group.objects.select_related('rol').prefetch_related('permissions')),
        'user_permissions',
    )


def _gestionable(request, usuario):
    """Si quien pide puede actuar sobre este usuario, o 403: no se puede tocar a quien tiene más poder que uno mismo."""
    if not puede_gestionar(request.user, usuario):
        raise PermissionDenied('No puedes administrar a un usuario con más permisos que tú.')
    return usuario


def guardar_credenciales(request, usuario, contrasena, titulo, url=None, escrita=False, pedir_cambio=False, etiqueta=None):
    """Deja en la sesión las credenciales de una cuenta para mostrarlas una vez al terminar (después, solo un administrador
    puede consultar la contraseña en el perfil: Usuarios/contrasenas.py)."""
    request.session[SESION_CREDENCIALES] = {
        'pk': usuario.pk,
        'nombre': nombre_de(usuario),
        'url': url or reverse('usuarios:detalle', args=[usuario.pk]),
        'usuario': usuario.username,
        'contrasena': contrasena,
        'titulo': titulo,
        'etiqueta': etiqueta or ('Contraseña inicial' if escrita else 'Contraseña generada'),
        'pedir_cambio': pedir_cambio,
    }


def _texto_de_la_ficha(form):
    """« Se registró su ficha de profesor.» o « Quedó vinculada con el profesor X.» (o nada)."""
    profesor = getattr(form, 'profesor_vinculado', None)
    if profesor is None:
        return ''
    if form.docente.profesor_creado:
        return f' Se registró su ficha de profesor ({profesor}).'
    return f' Quedó vinculada con la ficha del profesor {profesor}.'


def _anotar_en_la_ficha(request, form, usuario):
    profesor = getattr(form, 'profesor_vinculado', None)
    if profesor is not None:
        accion = 'Ficha registrada junto con' if form.docente.profesor_creado else 'Se vinculó con'
        registrar(request.user, profesor, ACCION_CAMBIO, f'{accion} la cuenta de acceso «{usuario.username}».')


def _cambios_de(form):
    """Texto con qué cambió en un formulario (para la bitácora)."""
    etiquetas = {nombre: str(campo.label) for nombre, campo in form.fields.items()}
    cambios = [etiquetas[n] for n in form.changed_data if n in etiquetas and n != 'rol']
    return ', '.join(cambios)


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
@requiere_permisos('auth.view_user')
def usuario_lista(request):
    filtro = FiltroUsuariosForm(request.GET)
    pagina, rango_paginas, por_pagina = paginar(request, filtro.filtrar(_consulta()))

    puede_actuar = request.user.has_perm('auth.change_user') or request.user.has_perm('auth.delete_user')
    propios = permisos_efectivos(request.user) if puede_actuar else set()
    for usuario in pagina:
        usuario.rol_actual = rol_de(usuario)
        usuario.gestionable = puede_actuar and puede_gestionar(request.user, usuario, propios)
        usuario.es_yo = usuario.pk == request.user.pk

    conteos = Usuario.objects.aggregate(
        activos=Count('pk', filter=Q(is_active=True)), inactivos=Count('pk', filter=Q(is_active=False)),
    )
    return render(request, 'usuarios/lista.html', {
        'filtro': filtro,
        'pagina': pagina,
        'rango_paginas': rango_paginas,
        'por_pagina': por_pagina,
        'por_pagina_defecto': POR_PAGINA_DEFECTO,
        'opciones_por_pagina': OPCIONES_POR_PAGINA,
        'total_activos': conteos['activos'],
        'total_inactivos': conteos['inactivos'],
        'viendo_inactivos': filtro.activos.get('estado') == 'INACTIVO',
        'filtros_activos': {k: v for k, v in filtro.activos.items() if k not in ('orden', 'estado')},
        # Tras crear una cuenta se muestran, una sola vez, sus credenciales temporales
        'credenciales': request.session.pop(SESION_CREDENCIALES, None),
    })


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
def _formulario(request, form, usuario=None):
    return render(request, 'usuarios/form.html', {'form': form, 'usuario': usuario, 'es_edicion': usuario is not None})


@requiere_permisos('auth.add_user')
def usuario_crear(request):
    form = UsuarioForm(request.POST if request.method == 'POST' else None, actor=request.user)
    if request.method == 'POST':
        if form.is_valid():
            usuario = form.save()
            rol = rol_de(usuario)
            registrar(request.user, usuario, ACCION_ALTA, f'Cuenta creada con el rol «{rol}».{_texto_de_la_ficha(form)}')
            _anotar_en_la_ficha(request, form, usuario)
            guardar_credenciales(request, usuario, form.contrasena_en_claro, 'Cuenta creada', escrita=form.contrasena_escrita,
                                 pedir_cambio=form.pedir_cambio)
            messages.success(request, f'La cuenta de {nombre_de(usuario)} fue creada con el rol «{rol}».{_texto_de_la_ficha(form)}')
            return redirect('usuarios:lista')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return _formulario(request, form)


@requiere_permisos('auth.change_user')
def usuario_editar(request, pk):
    usuario = _gestionable(request, get_object_or_404(Usuario, pk=pk))
    form = UsuarioForm(request.POST if request.method == 'POST' else None, instance=usuario, actor=request.user)
    if request.method == 'POST':
        if form.is_valid():
            usuario = form.save()
            partes = []
            if form.rol_cambio:
                partes.append(f'Rol: {form.rol_anterior or "sin rol"} → {rol_de(usuario)}.')
            cambios = _cambios_de(form)
            if cambios:
                partes.append(f'Datos modificados: {cambios}.')
            if form.profesor_vinculado:
                partes.append(_texto_de_la_ficha(form).strip())
                _anotar_en_la_ficha(request, form, usuario)
            if partes:
                registrar(request.user, usuario, ACCION_CAMBIO, ' '.join(partes))
            messages.success(request, f'Los datos de {nombre_de(usuario)} se actualizaron.{_texto_de_la_ficha(form)}')
            return redirect('usuarios:lista')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return _formulario(request, form, usuario)


# ---------------------------------------------------------------------------
# Perfil
# ---------------------------------------------------------------------------
@requiere_permisos('auth.view_user')
def usuario_detalle(request, pk):
    usuario = get_object_or_404(_consulta(), pk=pk)
    rol = rol_de(usuario)
    es_yo = usuario.pk == request.user.pk
    gestionable = puede_gestionar(request.user, usuario)
    # Una cuenta desactivada no tiene permisos en Django: se muestra lo que tendría al reactivarla
    permisos = permisos_efectivos(usuario) if usuario.is_active else permisos_de_cuenta(usuario)
    resumen = catalogo.resumen(permisos)
    ultimo_administrador = es_ultimo_administrador(usuario)

    return render(request, 'usuarios/detalle.html', {
        'usuario': usuario,
        'perfil': getattr(usuario, 'perfil', None) or PerfilUsuario(usuario=usuario),
        'profesor': profesor_de(usuario),
        'rol': rol,
        'es_yo': es_yo,
        'resumen': resumen,
        'total_permisos': sum(m['concedidos'] for m in resumen),
        'historial': historial(usuario),
        'puede_editar': request.user.has_perm('auth.change_user') and gestionable,
        'puede_desactivar': (
            request.user.has_perm('auth.delete_user') and gestionable and usuario.is_active
            and not es_yo and not ultimo_administrador
        ),
        'motivo_no_desactivar': (
            'Es tu propia cuenta.' if es_yo else 'Es el único administrador activo.' if ultimo_administrador else ''
        ),
        'puede_restablecer': request.user.has_perm('auth.change_user') and gestionable and usuario.is_active and not es_yo,
        # Solo un administrador consulta la contraseña (como en estudiantes y tutores); los demás ven si está vigente
        'consulta_contrasena': {
            'contrasena': usuario.has_usable_password(), 'contrasena_visible': contrasenas.consultable(usuario),
        } if request.user.is_superuser else None,
        'credenciales': request.session.pop(SESION_CREDENCIALES, None),
        'alcance': alcance_de_cuenta(usuario) if rol and rol.es_prefectura else None,
        'direccion': direccion_de_cuenta(usuario, permisos),
        'coordinacion': coordinacion_de_cuenta(usuario, permisos, rol),
    })


BITACORAS_AMPLIAS = ('Bitacoras.consultar_todas', 'Bitacoras.registrar_todas', 'Bitacoras.gestionar')


def coordinacion_de_cuenta(usuario, permisos, rol):
    """Los niveles a los que llegan sus bitácoras de todos los grupos ([(clave, nombre)]; vacío = todo el colegio), o
    None si no aplica: el administrador, las cuentas de prefectura (usan su alcance) y quien no tiene esos permisos."""
    if usuario.is_superuser or (rol is not None and (rol.es_prefectura or rol.acceso_total)) or not any(p in permisos for p in BITACORAS_AMPLIAS):
        return None
    from Alumnos.models import Grado
    elegidos = set(PerfilUsuario.de(usuario).niveles_bitacora)
    return [(clave, nombre) for clave, nombre in Grado.NIVEL_CHOICES if clave in elegidos]


@requiere_permisos('auth.change_user')
def usuario_coordinacion(request, pk):
    """Los niveles que coordina una cuenta con las bitácoras de todos los grupos: solo consulta y registra en esos."""
    from django import forms as formularios

    from Alumnos.models import Grado

    usuario = _gestionable(request, get_object_or_404(_consulta(), pk=pk))
    perfil = PerfilUsuario.de(usuario)
    permisos = permisos_efectivos(usuario) if usuario.is_active else permisos_de_cuenta(usuario)
    if coordinacion_de_cuenta(usuario, permisos, rol_de(usuario)) is None:
        messages.info(request, 'Solo las cuentas que consultan o registran en las bitácoras de todos los grupos coordinan niveles '
                               '(prefectura usa su alcance y el administrador ve todo).')
        return redirect('usuarios:detalle', usuario.pk)
    campo = formularios.MultipleChoiceField(choices=Grado.NIVEL_CHOICES, required=False)
    elegidos = perfil.niveles_bitacora
    if request.method == 'POST':
        try:
            elegidos = campo.clean(request.POST.getlist('niveles'))
        except ValidationError:
            messages.error(request, 'Elige niveles de la lista.')
        else:
            perfil.niveles_bitacora = list(elegidos)
            perfil.save(update_fields=['niveles_bitacora', 'modificado'])
            nombres = ', '.join(nombre for clave, nombre in Grado.NIVEL_CHOICES if clave in elegidos) or 'todo el colegio'
            registrar(request.user, usuario, ACCION_CAMBIO, f'Niveles que coordina (bitácoras): {nombres}.')
            messages.success(request, f'Las bitácoras de {nombre_de(usuario)} llegan a: {nombres}.')
            return redirect('usuarios:detalle', usuario.pk)
    return render(request, 'usuarios/coordinacion.html', {
        'usuario': usuario, 'niveles': [(clave, nombre, clave in elegidos) for clave, nombre in Grado.NIVEL_CHOICES],
    })


def direccion_de_cuenta(usuario, permisos):
    """Los niveles cuyas suspensiones y medidas autoriza (si su rol tiene el permiso de aprobar y no es administrador):
    [(clave, nombre)], o None si no aplica."""
    if usuario.is_superuser or 'Conducta.aprobar_suspension' not in permisos:
        return None
    from Alumnos.models import Grado
    elegidos = set(PerfilUsuario.de(usuario).niveles_direccion)
    return [(clave, nombre) for clave, nombre in Grado.NIVEL_CHOICES if clave in elegidos]


@requiere_permisos('auth.change_user')
def usuario_direccion(request, pk):
    """Los niveles que dirige una cuenta con el permiso de aprobar: solo autoriza las suspensiones y medidas de ellos."""
    from django import forms as formularios

    from Alumnos.models import Grado

    usuario = _gestionable(request, get_object_or_404(_consulta(), pk=pk))
    perfil = PerfilUsuario.de(usuario)
    permisos = permisos_efectivos(usuario) if usuario.is_active else permisos_de_cuenta(usuario)
    if usuario.is_superuser or 'Conducta.aprobar_suspension' not in permisos:
        messages.info(request, 'Solo las cuentas cuyo rol puede aprobar suspensiones dirigen un nivel (el administrador las autoriza todas).')
        return redirect('usuarios:detalle', usuario.pk)
    campo = formularios.MultipleChoiceField(choices=Grado.NIVEL_CHOICES, required=False)
    elegidos = perfil.niveles_direccion
    if request.method == 'POST':
        try:
            elegidos = campo.clean(request.POST.getlist('niveles'))
        except ValidationError:
            messages.error(request, 'Elige niveles de la lista.')
        else:
            perfil.niveles_direccion = list(elegidos)
            perfil.save(update_fields=['niveles_direccion', 'modificado'])
            nombres = ', '.join(nombre for clave, nombre in Grado.NIVEL_CHOICES if clave in elegidos) or 'ninguno'
            registrar(request.user, usuario, ACCION_CAMBIO, f'Niveles que dirige: {nombres}.')
            messages.success(request, f'{nombre_de(usuario)} autoriza las suspensiones y medidas de: {nombres}.')
            return redirect('usuarios:detalle', usuario.pk)
    return render(request, 'usuarios/direccion.html', {
        'usuario': usuario, 'niveles': [(clave, nombre, clave in elegidos) for clave, nombre in Grado.NIVEL_CHOICES],
    })


# ---------------------------------------------------------------------------
# Alcance de una cuenta de prefectura
# ---------------------------------------------------------------------------
def alcance_de_cuenta(usuario):
    """El alcance que tendría la cuenta (aunque esté desactivada), para mostrarlo en su ficha."""
    from Prefectura.alcance import NINGUNO, Alcance
    from Prefectura.models import AlcancePrefectura

    fila = AlcancePrefectura.objects.filter(usuario=usuario).prefetch_related('grupos').first()
    if fila is None:
        return NINGUNO
    return Alcance(restringido=True, todo=fila.todo_el_colegio, niveles=frozenset(fila.niveles),
                   grupos=frozenset(g.pk for g in fila.grupos.all()))


@requiere_permisos('auth.change_user')
def usuario_alcance(request, pk):
    """Los niveles completos y/o grupos que puede consultar una cuenta de prefectura (todo el colegio, expresamente)."""
    from Prefectura.forms import AlcanceForm
    from Prefectura.models import AlcancePrefectura

    usuario = _gestionable(request, get_object_or_404(_consulta(), pk=pk))
    rol = rol_de(usuario)
    if not (rol and rol.es_prefectura):
        messages.info(request, 'Solo las cuentas con un rol de prefectura tienen alcance: las demás ven lo que sus permisos les dejan ver.')
        return redirect('usuarios:detalle', usuario.pk)
    fila = AlcancePrefectura.objects.filter(usuario=usuario).first()
    inicial = {'todo_el_colegio': fila.todo_el_colegio, 'niveles': fila.niveles, 'grupos': list(fila.grupos.values_list('pk', flat=True))} if fila else {}
    form = AlcanceForm(request.POST or None, initial=inicial)
    if request.method == 'POST':
        if form.is_valid():
            datos = form.cleaned_data
            fila, _ = AlcancePrefectura.objects.update_or_create(usuario=usuario, defaults={
                'todo_el_colegio': datos['todo_el_colegio'], 'niveles': list(datos['niveles']), 'modificado_por': request.user,
            })
            fila.grupos.set(datos['grupos'])
            descripcion = alcance_de_cuenta(usuario).descripcion()
            registrar(request.user, usuario, ACCION_CAMBIO, f'Alcance de prefectura: {descripcion}.')
            messages.success(request, f'Alcance de {nombre_de(usuario)}: {descripcion}.')
            return redirect('usuarios:detalle', usuario.pk)
        messages.error(request, 'Revisa los datos: el alcance no se guardó.')
    return render(request, 'usuarios/alcance.html', {'usuario': usuario, 'form': form})


# ---------------------------------------------------------------------------
# Desactivar, reactivar y restablecer la contraseña
# ---------------------------------------------------------------------------
@require_POST
@requiere_permisos('auth.delete_user')
def usuario_baja(request, pk):
    """Desactiva la cuenta (no se borra): deja de poder entrar, pero conserva su historial y su rol."""
    usuario = _gestionable(request, get_object_or_404(Usuario, pk=pk))
    if usuario.pk == request.user.pk:
        messages.error(request, 'No puedes desactivar tu propia cuenta.')
    elif es_ultimo_administrador(usuario):
        messages.error(request, 'Es el único administrador activo: si lo desactivas, nadie podría administrar el sistema.')
    elif not usuario.is_active:
        messages.info(request, f'La cuenta de {nombre_de(usuario)} ya estaba desactivada.')
    else:
        usuario.is_active = False
        usuario.save(update_fields=['is_active'])
        registrar(request.user, usuario, ACCION_BAJA, 'Cuenta desactivada.')
        messages.success(
            request,
            f'La cuenta de {nombre_de(usuario)} fue desactivada: ya no puede entrar. Se conserva y puedes reactivarla desde el filtro «Desactivados».',
        )
    if request.POST.get('volver') == 'detalle':
        return redirect('usuarios:detalle', usuario.pk)
    return redirect('usuarios:lista')


@require_POST
@requiere_permisos('auth.change_user')
def usuario_reactivar(request, pk):
    usuario = _gestionable(request, get_object_or_404(Usuario, pk=pk))
    if not usuario.is_active:
        usuario.is_active = True
        usuario.save(update_fields=['is_active'])
        registrar(request.user, usuario, ACCION_CAMBIO, 'Cuenta reactivada.')
        messages.success(request, f'La cuenta de {nombre_de(usuario)} fue reactivada.')
    return redirect('usuarios:lista')


@require_POST
@requiere_permisos('auth.change_user')
def usuario_restablecer(request, pk):
    """Restablece la contraseña de otra cuenta: la que se escriba (debe cumplir las reglas de seguridad) o, si se deja
    vacía, una generada. Se muestra al terminar y un administrador puede consultarla después en el perfil. Si se marca,
    la persona deberá cambiarla al entrar (y la suya ya no se podrá consultar)."""
    usuario = _gestionable(request, get_object_or_404(Usuario, pk=pk))
    if usuario.pk == request.user.pk:
        messages.error(request, 'Para cambiar tu propia contraseña usa «Mi cuenta».')
        return redirect('usuarios:detalle', usuario.pk)
    if not usuario.is_active:
        messages.error(request, 'Reactiva la cuenta antes de cambiar su contraseña.')
        return redirect('usuarios:detalle', usuario.pk)

    escrita = request.POST.get('contrasena', '')
    try:
        validar_contrasena_inicial(
            escrita, username=usuario.username, email=usuario.email, first_name=usuario.first_name, last_name=usuario.last_name,
        )
    except ValidationError as error:
        messages.error(request, f'No se cambió la contraseña de {nombre_de(usuario)}: {" ".join(error.messages)}')
        return redirect('usuarios:detalle', usuario.pk)

    contrasena = escrita or contrasena_temporal()
    usuario.set_password(contrasena)   # además cierra sus sesiones abiertas: el hash de la sesión deja de coincidir
    usuario.save(update_fields=['password'])
    pedir_cambio = bool(request.POST.get('pedir_cambio'))
    perfil = PerfilUsuario.de(usuario)
    perfil.debe_cambiar_contrasena = pedir_cambio
    perfil.contrasena_visible = contrasena   # un administrador la puede consultar en el perfil
    perfil.save(update_fields=['debe_cambiar_contrasena', 'contrasena_visible', 'modificado'])
    registrar(request.user, usuario, ACCION_CAMBIO, 'Contraseña cambiada' + (' (deberá cambiarla al entrar).' if pedir_cambio else '.'))
    guardar_credenciales(request, usuario, contrasena, 'Contraseña cambiada', pedir_cambio=pedir_cambio,
                         etiqueta='Contraseña nueva' if escrita else 'Contraseña generada')
    if escrita:
        messages.success(request, f'Se cambió la contraseña de {nombre_de(usuario)}.')
    else:
        despues = 'podrás consultarla en su perfil' if request.user.is_superuser else 'no se volverá a mostrar'
        messages.success(request, f'Se generó una contraseña nueva para {nombre_de(usuario)}. Entrégasela: {despues}.')
    return redirect('usuarios:detalle', usuario.pk)


# ---------------------------------------------------------------------------
# Mi cuenta (cualquier usuario con sesión)
# ---------------------------------------------------------------------------
@login_required
def cuenta_perfil(request):
    form = MiCuentaForm(request.POST if request.method == 'POST' else None, instance=request.user)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, 'Tus datos se actualizaron.')
            return redirect('cuenta:perfil')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')

    permisos = permisos_efectivos(request.user)
    resumen = catalogo.resumen(permisos)
    return render(request, 'usuarios/cuenta.html', {
        'form': form,
        'perfil': PerfilUsuario.de(request.user),
        'rol': rol_de(request.user),
        'resumen': resumen,
        'total_permisos': sum(m['concedidos'] for m in resumen),
    })


@login_required
def cuenta_contrasena(request):
    perfil = PerfilUsuario.de(request.user)
    obligatorio = perfil.debe_cambiar_contrasena
    form = CambioContrasenaForm(request.user, request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, request.user)   # sigue con la sesión abierta
            perfil.debe_cambiar_contrasena = False
            perfil.save(update_fields=['debe_cambiar_contrasena', 'modificado'])
            request.session[SESION_CAMBIO_DE_CONTRASENA] = False
            registrar(request.user, request.user, ACCION_CAMBIO, 'Cambió su propia contraseña.')
            messages.success(request, 'Tu contraseña se actualizó.')
            return redirect('inicio' if obligatorio else 'cuenta:perfil')
        messages.error(request, 'No se pudo cambiar la contraseña: revisa los campos marcados.')
    return render(request, 'usuarios/contrasena.html', {'form': form, 'obligatorio': obligatorio})
